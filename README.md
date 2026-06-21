# Image Proxy for Home Assistant

A Home Assistant custom integration that provides a server-side image cache and proxy for media-card album art. It serves art from a stable, integration-owned endpoint keyed by a cache key, fetches it through from a small set of whitelisted source hosts, and locks the serving endpoint down with a client-IP allowlist.

## Status

Early and experimental. Phase 1 (the art cache itself) is in progress. The current build is a loadable scaffold: it installs, sets up a config entry, and unloads cleanly, but it does not cache or serve images yet. Do not rely on it for anything real today.

## Why

Media cards often reference image URLs that are short-lived, host-specific, or only reachable from inside the local network. Image Proxy gives the frontend a single, stable URL per piece of art, served by Home Assistant, backed by a small server-side cache.

## Install

### HACS (custom repository)

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/bharat/homeassistant-image-proxy` with category **Integration**.
3. Install **Image Proxy** from HACS.
4. Restart Home Assistant.
5. Go to **Settings, Devices and Services, Add Integration** and add **Image Proxy**.

### Manual

1. Copy `custom_components/image_proxy` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings, Devices and Services, Add Integration** and add **Image Proxy**.

## Planned configuration

These options are planned for Phase 1 and are not configurable yet:

- **Client CIDRs**: the IP allowlist that may pull blobs from the serving endpoint.
- **Sonos coordinator IPs**: a common source of media art on the local network.
- **Blob size cap**: an upper bound on what gets cached, to keep storage bounded.

## Planned API surface

These endpoints are part of the design and are not implemented yet:

- `GET /api/image_proxy/img/<key>`: serve a cached blob by key. Guarded by the client-IP allowlist. On a cache miss for a known key, fetches the art through from its source URL.
- `register` (WebSocket command): warm the cache by mapping a cache key to a source URL ahead of time.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full planned data flow.

## Not feature-complete

This integration is under active development and is not feature-complete. The image cache, the serving endpoint, the WebSocket command, and the SSRF guard are planned for Phase 1 and are not in the current build.

## License

[MIT](./LICENSE)
