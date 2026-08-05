"""Constants for the Image Proxy integration."""

from __future__ import annotations

DOMAIN = "image_proxy"

# Config-entry options keys.
CONF_ALLOWED_CIDRS = "allowed_cidrs"
CONF_SONOS_IPS = "sonos_ips"
CONF_HOST_ALLOWLIST = "host_allowlist"
CONF_TRUSTED_PROXIES = "trusted_proxies"
CONF_MAX_CACHE_MB = "max_cache_mb"

# Default client-IP allowlist for the img endpoint. These are the address
# ranges a LAN or tailnet client legitimately appears from: RFC1918 private
# space, the Tailscale CGNAT range, loopback, and IPv6 ULA + loopback.
DEFAULT_ALLOWED_CIDRS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "::1/128",
    "fc00::/7",
]

# Default upstream host allowlist. Empty means "allow any public host that
# passes the private-IP check".
DEFAULT_HOST_ALLOWLIST: list[str] = []

# Default Sonos coordinator IPs allowed as fetch targets even though they are
# private. Empty by default; the owner adds their coordinators here.
DEFAULT_SONOS_IPS: list[str] = []

# Default trusted reverse proxies. Empty means "never trust X-Forwarded-For".
DEFAULT_TRUSTED_PROXIES: list[str] = []

# Default cache size cap in megabytes.
DEFAULT_MAX_CACHE_MB = 200

# Store key + version for the key -> source/blob index.
STORAGE_KEY = "image_proxy_index"
STORAGE_VERSION = 1

# Fetch-through defaults.
FETCH_TIMEOUT_S = 10
FETCH_MAX_BYTES = 15 * 1024 * 1024
FETCH_MAX_REDIRECTS = 3

# Cap on an oEmbed metadata response body. Real payloads are a few hundred
# bytes; the cap only bounds a hostile or broken provider.
OEMBED_MAX_BYTES = 64 * 1024

# Bounded concurrency for cache-warming fetches.
WARM_CONCURRENCY = 4
