# Architecture

This document describes the planned architecture of the Image Proxy integration. It is a design skeleton. As of Phase 0, none of the data flow below is implemented in code; the integration only sets up and tears down a config entry. Treat everything here as Phase 1 intent.

## Goal

Media cards (album art for now-playing tiles) often reference image URLs that are short-lived, host-specific, or only reachable from inside the local network. Image Proxy gives the frontend a single, stable URL per piece of art, served by Home Assistant itself, backed by a small server-side cache.

## Planned data flow

### Warming a key (register)

```
client ──register(key, src)──▶ WebSocket command
                                    │
                                    ▼
                          index[key] = src  (Store-backed)
```

A `register` WebSocket command associates a cache key with a source URL. This warms the index so the img endpoint knows where to fetch from on a miss. It does not (necessarily) download the blob immediately; that can happen lazily on first request.

### Serving art (img)

```
client ──GET /api/image_proxy/img/<key>──▶ HTTP view
                                                │
                              client-IP allowlist check (CIDRs)
                                                │
                                  ┌─────────────┴─────────────┐
                              cache hit                   cache miss
                                  │                            │
                          serve blob from              look up index[key] = src
                          config/.storage/                     │
                          image_proxy/blobs              SSRF guard on src host
                                                               │
                                                        fetch-through (GET src)
                                                               │
                                                     store blob (size-capped)
                                                               │
                                                          serve blob
```

## Planned components

- **HTTP view**: `GET /api/image_proxy/img/<key>`. Unauthenticated in the HA-token sense (media cards cannot easily attach a token), gated instead by a client-IP allowlist of configured CIDRs. Serves a cached blob, or fetches it through on a miss for a known key.
- **WebSocket command**: `register`, maps a cache key to a source URL ahead of time.
- **Blob store**: files under `config/.storage/image_proxy/blobs`, with a `Store`-backed index mapping key to source URL and blob metadata.
- **SSRF guard**: fetch-through only proceeds if the source host is on the configured whitelist and the resolved address is not private or link-local, so the proxy cannot be turned into a request forwarder for internal services.
- **Cache key**: `sc:<track_id>` plus `h:<sha1(src)>`, stable for a given track and source URL.

## Planned configuration (options flow)

- Client CIDRs (the IP allowlist for the img endpoint).
- Sonos coordinator IPs (a common source of media art on the local network).
- Blob size cap (an upper bound on what gets cached, to keep storage bounded).

## Status

Phase 0: scaffold only. The img endpoint, the register command, the blob store, and the SSRF guard are not implemented yet. This document is the target for Phase 1.
