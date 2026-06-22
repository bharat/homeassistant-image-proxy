"""
HTTP view that serves cached image blobs by key.

The endpoint is unauthenticated in the HA-token sense (media cards cannot easily
attach a token), so access is gated by a client-IP allowlist evaluated before
anything else. On a cache miss for a known key, it fetches through under the
SSRF guard, stores the result, and serves it.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN
from .fetch import FetchError, fetch_image

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.core import HomeAssistant

    from .store import ImageStore

_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse an IP string, returning None if it is not a valid address."""
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def client_ip_allowed(
    peer: str | None,
    xff_header: str | None,
    allowed_networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network],
    trusted_proxies: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """
    Decide whether a request's real client IP is on the allowlist.

    ``peer`` is the socket peer address (aiohttp's ``request.remote``). If the
    peer is itself a trusted proxy and an ``X-Forwarded-For`` header is present,
    the real client is taken as the right-most XFF entry that is not itself a
    trusted proxy. ``X-Forwarded-For`` from a non-trusted peer is never trusted.

    This is a pure function so the IP-decision logic is unit-testable without a
    live request.
    """
    allowed = list(allowed_networks)
    trusted = list(trusted_proxies)

    peer_ip = _parse_ip(peer) if peer else None
    if peer_ip is None:
        return False

    client_ip = peer_ip
    peer_is_trusted = any(peer_ip in net for net in trusted)
    if peer_is_trusted and xff_header:
        # Walk right to left and pick the first address that is not a trusted
        # proxy: that is the closest non-proxy hop, i.e. the real client.
        for raw in reversed(xff_header.split(",")):
            candidate = _parse_ip(raw)
            if candidate is None:
                continue
            if any(candidate in net for net in trusted):
                continue
            client_ip = candidate
            break

    return any(client_ip in net for net in allowed)


class ImageProxyView(HomeAssistantView):
    """Serve cached image blobs at ``/api/image_proxy/img/{key}``."""

    url = "/api/image_proxy/img/{key}"
    name = "api:image_proxy:img"
    requires_auth = False

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the view bound to a config entry's runtime data."""
        self._hass = hass
        self._entry_id = entry_id

    def _runtime(self) -> dict:
        return self._hass.data[DOMAIN][self._entry_id]

    async def get(self, request: web.Request, key: str) -> web.StreamResponse:
        """Handle a GET for a single cache key."""
        runtime = self._runtime()

        if not client_ip_allowed(
            request.remote,
            request.headers.get("X-Forwarded-For"),
            runtime["allowed_networks"],
            runtime["trusted_proxies"],
        ):
            return web.Response(status=403, text="Forbidden")

        store: ImageStore = runtime["store"]
        entry = store.get(key)

        if entry is not None and entry["blob"]:
            return await self._serve_cached(request, store, key, entry)

        if entry is not None and entry["src"]:
            return await self._fetch_and_serve(runtime, store, key, entry["src"])

        return web.Response(status=404, text="Unknown key")

    async def _serve_cached(
        self,
        request: web.Request,
        store: ImageStore,
        key: str,
        entry: dict,
    ) -> web.StreamResponse:
        """Serve a blob that is already on disk, honoring If-None-Match."""
        etag = f'"{entry["etag"]}"'
        if request.headers.get("If-None-Match") == etag:
            await store.async_touch(key)
            return web.Response(status=304, headers={"ETag": etag})

        data = await store.async_read_blob(key)
        if data is None:
            # Index says we have a blob but the file is gone; treat as a miss
            # and re-fetch if we still know the source.
            if entry["src"]:
                runtime = self._runtime()
                return await self._fetch_and_serve(runtime, store, key, entry["src"])
            return web.Response(status=404, text="Unknown key")

        await store.async_touch(key)
        return web.Response(
            body=data,
            content_type=entry["content_type"] or "application/octet-stream",
            headers={"Cache-Control": _IMMUTABLE_CACHE, "ETag": etag},
        )

    async def _fetch_and_serve(
        self,
        runtime: dict,
        store: ImageStore,
        key: str,
        src: str,
    ) -> web.StreamResponse:
        """Fetch a known key's source through the SSRF guard, store, and serve."""
        try:
            content_type, data = await fetch_image(
                self._hass,
                src,
                allow_private_hosts=runtime["sonos_ips"],
                host_allowlist=runtime["host_allowlist"],
            )
        except FetchError:
            return web.Response(status=502, text="Upstream fetch failed")

        stored = await store.async_store_blob(key, src, content_type, data)
        etag = f'"{stored["etag"]}"'
        return web.Response(
            body=data,
            content_type=content_type,
            headers={"Cache-Control": _IMMUTABLE_CACHE, "ETag": etag},
        )
