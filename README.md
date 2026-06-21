# Image Proxy for Home Assistant

A Home Assistant custom integration that provides a server-side image cache and proxy for media-card album art. It serves art from a stable, integration-owned endpoint keyed by a cache key, fetches it through from source hosts under an SSRF guard, and locks the serving endpoint down with a client-IP allowlist.

## Status

Phase 1 (the art cache) is implemented. The integration installs, serves cached blobs over an HTTP endpoint, fetches art through on a miss, and exposes WebSocket commands to warm and inspect the cache. It is still young, and it is designed to run on a trusted LAN or tailnet only (see the security model below).

## Why

Media cards often reference image URLs that are short-lived, host-specific, or only reachable from inside the local network. Image Proxy gives the frontend a single, stable URL per piece of art, served by Home Assistant, backed by a small server-side cache.

## How it works

1. A card (the client) computes a cache key for a piece of art and calls the `image_proxy/register` WebSocket command to map that key to the art's source URL. The server is key-scheme agnostic: it just stores `key -> src` and, later, the bytes.
2. The card points its `<img>` at `GET /api/image_proxy/img/<key>`. On the first request for a known key, the integration fetches the source through the SSRF guard, stores the blob, and serves it. Subsequent requests are served straight from the on-disk cache with long-lived caching headers.

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

## Configuration

Open **Settings, Devices and Services, Image Proxy, Configure**. All list fields accept comma-separated values.

- **Allowed client CIDRs**: the IP allowlist for the img endpoint. Only clients whose address falls inside one of these ranges may pull blobs. Defaults to RFC1918 private space, the Tailscale CGNAT range (`100.64.0.0/10`), loopback, and IPv6 ULA + loopback. This is the main access control on the endpoint, so keep it tight.
- **Sonos coordinator IPs**: private IP addresses that are allowed as fetch-through targets even though they are private. Add your Sonos coordinators here so their album art can be fetched. Empty by default.
- **Upstream host allowlist**: fnmatch patterns (for example `*.sndcdn.com`) that restrict which public hosts may be fetched. Empty means any public host that passes the private-IP check is allowed.
- **Trusted reverse proxies**: CIDRs of proxies you run in front of Home Assistant. Only when the request's peer is one of these is the `X-Forwarded-For` header consulted to find the real client IP. Empty by default, which means `X-Forwarded-For` is never trusted.
- **Maximum cache size (MB)**: an upper bound on total cached bytes (default 200). When the cache exceeds the cap after a store, least-recently-used blobs are evicted until it is back under the cap.

## API

### `GET /api/image_proxy/img/<key>`

Serves a cached blob by key. This endpoint does not require a Home Assistant token (media cards cannot easily attach one); access is gated by the client-IP allowlist instead.

- Cache hit: returns the bytes with `Content-Type` from the index, `Cache-Control: public, max-age=31536000, immutable`, and an `ETag`. A matching `If-None-Match` yields `304`.
- Known key, no blob yet: fetches the source through the SSRF guard, stores it, and serves it. A fetch failure returns `502`.
- Unknown key: `404`.
- Client not on the allowlist: `403`.

### `image_proxy/register` (WebSocket, authenticated)

Records one or more `key -> src` mappings and warms the cache with bounded-concurrency background fetches.

```json
{
  "type": "image_proxy/register",
  "items": [{ "key": "sc:12345", "src": "https://cf-media.sndcdn.com/abc.jpg" }]
}
```

Returns `{ "registered": <n>, "warming": <m> }`, where `m` is the number of items that were not already cached and so were scheduled for a background fetch.

### `image_proxy/stats` (WebSocket, authenticated)

Returns `{ "entries": <count>, "total_bytes": <bytes> }`.

## Security model

Image Proxy is built for a trusted LAN or tailnet, and it must stay there. Two controls work together:

- **Client-IP allowlist** on the img endpoint. The endpoint is token-less, so the only thing standing between a caller and the cache is its source IP. `X-Forwarded-For` is honored only when the immediate peer is a configured trusted proxy, and even then only the right-most non-proxy address is used. Never expose this endpoint directly to the public internet.
- **SSRF-guarded fetch-through.** Before fetching a source, the host is resolved and every resolved IP is checked. Private, loopback, link-local, reserved, and multicast addresses are rejected unless the host or IP is explicitly listed as a Sonos coordinator. An optional host allowlist further restricts which public hosts may be fetched. Redirects are followed only after re-validating each hop, so an allowed host cannot redirect the fetcher into your internal network.

Known limitation: the SSRF guard validates resolved IPs and then connects by hostname, leaving a narrow DNS-rebinding TOCTOU window. This is acceptable for a LAN-only MVP and is documented in `custom_components/image_proxy/fetch.py`.

## Try it

With the dev server running (`scripts/develop`) and the integration added:

1. Create a long-lived access token in Home Assistant: **Profile, Security, Long-lived access tokens**.
2. Run the demo:

   ```bash
   HA_TOKEN="<your token>" ./scripts/demo
   ```

The demo registers a key mapped to a public test image, prints the ready-to-open `http://localhost:8123/api/image_proxy/img/<key>` URL, and fetches it, showing the served bytes and headers. Override the source or key with `DEMO_SRC` and `DEMO_KEY`, or the base URL with `HA_URL`.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full data flow.

## License

[MIT](./LICENSE)
