"""
SSRF-guarded fetch-through for the Image Proxy integration.

This is the security-critical part of the integration. ``fetch_image`` resolves
the source host, rejects any host that resolves to a private, loopback,
link-local, reserved, or multicast address (unless explicitly allowlisted as a
Sonos coordinator), optionally enforces an upstream host allowlist, follows a
bounded number of redirects revalidating each hop, and caps the response size.

Known limitation (DNS-rebinding TOCTOU): we validate the IP addresses returned
by ``getaddrinfo`` and then let aiohttp connect by hostname, so a hostile
resolver could in principle return a public IP for validation and a private IP
for the actual connection. Closing that window means pinning the connection to
the validated IP, which aiohttp does not make easy. For a LAN/tailnet-only MVP
this residual risk is accepted rather than solved here.
"""

from __future__ import annotations

import ipaddress
from fnmatch import fnmatch
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import FETCH_MAX_BYTES, FETCH_MAX_REDIRECTS, FETCH_TIMEOUT_S

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.core import HomeAssistant

_ALLOWED_SCHEMES = ("http", "https")
_CHUNK = 64 * 1024


class FetchError(Exception):
    """Base error for fetch-through failures."""


class FetchRejectedError(FetchError):
    """The source was rejected by the SSRF guard (host/scheme/IP/allowlist)."""


class FetchFailedError(FetchError):
    """The upstream request failed, timed out, or returned an unusable body."""


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if an IP must not be reached without explicit allowlisting."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _resolve_ips(
    hass: HomeAssistant, host: str
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname to the set of IP addresses it maps to."""
    loop = hass.loop
    try:
        infos = await loop.getaddrinfo(host, None)
    except OSError as err:
        msg = f"DNS resolution failed for {host}: {err}"
        raise FetchFailedError(msg) from err
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        try:
            ips.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    return ips


def _host_in_allowlist(host: str, host_allowlist: Iterable[str]) -> bool:
    """Return True if host matches any fnmatch pattern in the allowlist."""
    host = host.lower()
    return any(fnmatch(host, pattern.lower()) for pattern in host_allowlist)


async def _validate_target(
    hass: HomeAssistant,
    url: str,
    *,
    allow_private_hosts: set[str],
    host_allowlist: list[str],
) -> None:
    """
    Validate a single URL's scheme, host allowlist, and resolved IPs.

    Raises ``FetchRejectedError`` if the target is not permitted.
    """
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        msg = f"scheme {parts.scheme!r} is not allowed"
        raise FetchRejectedError(msg)
    host = parts.hostname
    if not host:
        msg = "missing host in URL"
        raise FetchRejectedError(msg)

    host_allowed = host in allow_private_hosts
    if (
        host_allowlist
        and not host_allowed
        and not _host_in_allowlist(host, host_allowlist)
    ):
        msg = f"host {host!r} is not on the upstream allowlist"
        raise FetchRejectedError(msg)

    ips = await _resolve_ips(hass, host)
    if not ips:
        msg = f"host {host!r} did not resolve to any address"
        raise FetchRejectedError(msg)

    for ip in ips:
        if _is_disallowed_ip(ip) and not (
            host in allow_private_hosts or str(ip) in allow_private_hosts
        ):
            msg = f"host {host!r} resolves to disallowed address {ip}"
            raise FetchRejectedError(msg)


async def fetch_image(  # noqa: PLR0913
    hass: HomeAssistant,
    src: str,
    *,
    allow_private_hosts: Iterable[str] | None = None,
    host_allowlist: list[str] | None = None,
    timeout_s: int = FETCH_TIMEOUT_S,
    max_bytes: int = FETCH_MAX_BYTES,
    max_redirects: int = FETCH_MAX_REDIRECTS,
) -> tuple[str, bytes]:
    """
    Fetch an image through the SSRF guard.

    Returns ``(content_type, data)`` on success. Raises ``FetchRejectedError`` if the
    SSRF guard refuses the target, or ``FetchFailedError`` on any upstream failure.
    """
    allow_private = set(allow_private_hosts or [])
    allowlist = host_allowlist or []
    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=timeout_s)

    url = src
    try:
        for _ in range(max_redirects + 1):
            await _validate_target(
                hass,
                url,
                allow_private_hosts=allow_private,
                host_allowlist=allowlist,
            )
            async with session.get(url, allow_redirects=False, timeout=timeout) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if not location:
                        msg = "redirect response without a Location header"
                        raise FetchFailedError(msg)
                    url = urljoin(url, location)
                    continue
                if resp.status != 200:  # noqa: PLR2004
                    msg = f"upstream returned status {resp.status}"
                    raise FetchFailedError(msg)
                content_type = resp.headers.get("Content-Type", "")
                if not content_type.lower().startswith("image/"):
                    msg = f"upstream content-type {content_type!r} is not an image"
                    raise FetchFailedError(msg)
                data = await _read_capped(resp, max_bytes)
                return content_type, data
    except TimeoutError as err:
        msg = f"fetch timed out after {timeout_s}s"
        raise FetchFailedError(msg) from err
    except aiohttp.ClientError as err:
        msg = f"upstream request failed: {err}"
        raise FetchFailedError(msg) from err

    msg = f"too many redirects (>{max_redirects})"
    raise FetchFailedError(msg)


async def _read_capped(resp: aiohttp.ClientResponse, max_bytes: int) -> bytes:
    """Read a response body in chunks, aborting if it exceeds max_bytes."""
    buf = bytearray()
    async for chunk in resp.content.iter_chunked(_CHUNK):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            msg = f"body exceeds max_bytes ({max_bytes})"
            raise FetchFailedError(msg)
    return bytes(buf)
