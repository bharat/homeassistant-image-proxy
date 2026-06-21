"""
Option parsing and validation shared by the config flow and setup.

Options are stored as the raw user input (comma-separated strings for the
list-y fields). These helpers turn them into the validated, typed runtime
values the view and fetcher consume.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Any

from .const import (
    CONF_ALLOWED_CIDRS,
    CONF_HOST_ALLOWLIST,
    CONF_MAX_CACHE_MB,
    CONF_SONOS_IPS,
    CONF_TRUSTED_PROXIES,
    DEFAULT_ALLOWED_CIDRS,
    DEFAULT_HOST_ALLOWLIST,
    DEFAULT_MAX_CACHE_MB,
    DEFAULT_SONOS_IPS,
    DEFAULT_TRUSTED_PROXIES,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.config_entries import ConfigEntry

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def split_list(value: Any) -> list[str]:
    """
    Normalize a list field to a list of non-empty trimmed strings.

    Accepts either an actual list or a comma-separated string.
    """
    if value is None:
        return []
    parts = value.split(",") if isinstance(value, str) else list(value)
    return [p.strip() for p in parts if str(p).strip()]


def parse_networks(values: Iterable[str]) -> list[Network]:
    """
    Parse CIDR/IP strings into networks, raising ValueError on bad input.

    ``ip_network`` with ``strict=False`` accepts both "10.0.0.0/8" and a bare IP.
    """
    return [ipaddress.ip_network(raw, strict=False) for raw in values]


def parse_ips(values: Iterable[str]) -> list[str]:
    """Validate bare IP strings, returning them normalized; raises ValueError."""
    return [str(ipaddress.ip_address(raw)) for raw in values]


def _opt(entry: ConfigEntry, key: str, default: Any) -> Any:
    return entry.options.get(key, default)


def effective_config(entry: ConfigEntry) -> dict[str, Any]:
    """
    Compute the validated runtime config from an entry's options.

    Falls back to the const defaults for any unset option. Invalid stored values
    fall back to defaults defensively (the config flow validates on input).
    """
    allowed_raw = split_list(_opt(entry, CONF_ALLOWED_CIDRS, DEFAULT_ALLOWED_CIDRS))
    sonos_raw = split_list(_opt(entry, CONF_SONOS_IPS, DEFAULT_SONOS_IPS))
    host_allowlist = split_list(
        _opt(entry, CONF_HOST_ALLOWLIST, DEFAULT_HOST_ALLOWLIST)
    )
    proxies_raw = split_list(_opt(entry, CONF_TRUSTED_PROXIES, DEFAULT_TRUSTED_PROXIES))
    max_mb = _opt(entry, CONF_MAX_CACHE_MB, DEFAULT_MAX_CACHE_MB)

    try:
        allowed_networks = parse_networks(allowed_raw)
    except ValueError:
        allowed_networks = parse_networks(DEFAULT_ALLOWED_CIDRS)
    try:
        sonos_ips = parse_ips(sonos_raw)
    except ValueError:
        sonos_ips = []
    try:
        trusted_proxies = parse_networks(proxies_raw)
    except ValueError:
        trusted_proxies = []
    try:
        max_cache_bytes = int(max_mb) * 1024 * 1024
    except (TypeError, ValueError):
        max_cache_bytes = DEFAULT_MAX_CACHE_MB * 1024 * 1024

    return {
        "allowed_networks": allowed_networks,
        "sonos_ips": sonos_ips,
        "host_allowlist": host_allowlist,
        "trusted_proxies": trusted_proxies,
        "max_cache_bytes": max_cache_bytes,
    }
