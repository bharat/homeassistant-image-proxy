# Architecture

This document describes the Phase 1 architecture of the Image Proxy integration: the art cache as implemented today. A later phase (a key-to-metadata KV API) is noted at the end as future work.

## Goal

Media cards (album art for now-playing tiles) often reference image URLs that are short-lived, host-specific, or only reachable from inside the local network. Image Proxy gives the frontend a single, stable URL per piece of art, served by Home Assistant itself, backed by a small server-side cache.

## Components

- **HTTP view** (`view.py`): `GET /api/image_proxy/img/{key}`, token-less but gated by a client-IP allowlist. Serves cached blobs, or fetches through on a miss for a known key.
- **WebSocket commands** (`websocket.py`): `image_proxy/register` (map keys to sources and warm the cache) and `image_proxy/stats` (entry count and total bytes).
- **Source resolution** (`resolve.py`): turns an indirect source (a media-browser thumbnail that points back at Home Assistant rather than at the artwork) into a directly fetchable URL. Best-effort; unrecognised sources pass through unchanged.
- **Fetch-through with SSRF guard** (`fetch.py`): resolves and validates the source host before fetching, follows redirects with per-hop revalidation, and caps the body size.
- **Blob store + index** (`store.py`): bytes on disk plus a `Store`-backed in-memory index, with LRU eviction.
- **Options** (`config_flow.py`, `options.py`): allowlists, trusted proxies, and the cache cap.

## Data flow

### Warming a key (register)

```
client ──register(items=[{key, src}])──▶ image_proxy/register (WS, authenticated)
                                              │
                                index[key] = {src, ...}   (Store-backed, in memory)
                                              │
                                  schedule background warm (Semaphore, bounded)
                                              │
                                  fetch-through(src) ──▶ store blob (size-capped)
```

`register` records each `key -> src` mapping immediately, then schedules bounded-concurrency background fetches for any item that is not already cached, so the command returns promptly. The response is `{registered, warming}`.

### Serving art (img)

```
client ──GET /api/image_proxy/img/<key>──▶ HTTP view (token-less)
                                                │
                              client-IP allowlist check (CIDRs, XFF via trusted proxies)
                                          not allowed ──▶ 403
                                                │ allowed
                                  ┌─────────────┼──────────────────────────┐
                              blob present              key known, no blob            key unknown
                                  │                            │                          │
                         If-None-Match match? ──▶ 304    resolve src (best-effort)        404
                                  │ else                       │
                         serve bytes + ETag +          SSRF guard + fetch-through
                         immutable Cache-Control               │ ok            │ fail
                         (touch last_access)            store + serve         502
```

### Source resolution

Some media browsers publish a thumbnail URL that points back at Home Assistant's own `media_player_proxy` endpoint instead of at the artwork. For streaming-service *tracks* those URLs are unusable as a cache source: the Sonos integration only serves browse images for albums and artists, so a track URL returns an empty 404, and the embedded `token` is regenerated on every restart, so a stored URL eventually 403s.

home-assistant/core#173330 addresses the 404, but not in a way that makes this redundant. It captures the speaker's advertised art URI at browse time into a per-speaker dict that is bounded (4096 entries, FIFO) and never persisted, so it only answers for tracks browsed in the current process. A source recorded in this index outlives that cache, so after a restart a track nobody has re-browsed still resolves to nothing.

A track's artwork URI cannot be rebuilt from its content id, but the *service* track id is embedded in it. `resolve.py` recovers that id and asks the service's public, unauthenticated oEmbed endpoint for the artwork, rather than round-tripping Home Assistant's own HTTP endpoint. Spotify and SoundCloud are recognised today.

The content id is percent-encoded twice and wrapped in one of several `x-sonos*` container schemes, so resolution decodes until stable and then matches the service id itself. The captured ids are alphanumeric, which is what makes them safe to interpolate into an oEmbed URL.

Resolution is best-effort in both directions: an unrecognised source, an unreachable provider, or a malformed response all fall back to the original source, so behaviour is never worse than not resolving. A resolved URL comes from a third party and still goes through the full SSRF guard.

The index keeps the *original* source, not the resolved one. The original is the stable identity of the artwork and stays re-resolvable if the blob is later evicted.

### Client-IP gate

`client_ip_allowed(peer, xff_header, allowed_networks, trusted_proxies)` is a pure function. It starts from the socket peer. If the peer is itself a trusted proxy and an `X-Forwarded-For` header is present, it walks the header right to left and takes the first address that is not a trusted proxy as the real client. It never trusts `X-Forwarded-For` from a non-trusted peer. The chosen client IP must fall within one of the allowed networks.

### SSRF guard

For the initial source and for each redirect hop:

1. Scheme must be `http` or `https`.
2. If a host allowlist is configured, the host must match one of its fnmatch patterns (or be an allowlisted Sonos host).
3. The host is resolved via the event loop's `getaddrinfo`. If any resolved IP is private, loopback, link-local, reserved, multicast, or unspecified, the target is rejected unless the host or IP is explicitly listed as a Sonos coordinator.

On a 2xx the `Content-Type` must start with `image/`, and the body is read in chunks up to `max_bytes`. Redirects (up to `max_redirects`) are followed only after re-running the full validation on the new target.

Known limitation: validation happens on the resolved IPs, then aiohttp connects by hostname, leaving a narrow DNS-rebinding TOCTOU window. Accepted for a LAN-only MVP and documented in `fetch.py`.

## Store layout

```
config/.storage/
├── image_proxy_index            # Store-backed JSON index (key -> entry)
└── image_proxy/
    └── blobs/
        └── <sha256(key)>        # one file per cached blob
```

Each index entry is `{blob, content_type, src, size, etag, ts, last_access}`, where `blob` is the on-disk filename (the sha256 hex of the key, so any key string is filesystem-safe) and `etag` is the sha256 hex of the bytes. The index is held in memory under an `asyncio.Lock` and persisted with `Store.async_delay_save`.

## Eviction

After storing a blob, if the total bytes across all entries exceed the configured cap, the store evicts entries with the oldest `last_access` first (deleting both the index entry and the blob file) until the total is back under the cap. A cache hit updates `last_access`, so frequently-served art survives eviction.

## Future work (Phase 2)

A key-to-metadata KV API (storing structured metadata per key alongside the blob, beyond the source URL) is planned but not implemented. It is intentionally out of scope for the Phase 1 art cache.
