# AGENTS.md, Image Proxy HA Integration

This is the canonical agent guide for `bharat/homeassistant-image-proxy`. New Claude/Codex/Cursor sessions should read this before making changes. Pair it with `ARCHITECTURE.md` for the implemented data flow.

## What this is

A Home Assistant custom integration that provides a server-side image cache and proxy for media-card album art. The idea is to serve art from a stable, integration-owned endpoint keyed by a cache key, so the frontend always hits a predictable URL instead of whatever short-lived URL a media source happens to expose. Art is fetched through from a small set of whitelisted source hosts (a fetch-through cache), and the serving endpoint is locked down by a client-IP allowlist so only known clients can pull blobs. A key-to-source metadata index plus the on-disk blob store is a later phase; Phase 0 is just the loadable skeleton.

## Layout

```
.
├── AGENTS.md                   # This guide
├── ARCHITECTURE.md             # Implemented data flow (Phase 1), read for design intent
├── CONTRIBUTING.md             # Standard fork/PR flow
├── README.md                   # User-facing install + status
│
├── custom_components/image_proxy/
│   ├── __init__.py             # async_setup_entry: wires store + view + WS commands
│   ├── manifest.json           # version is "0.0.0" sentinel, see Releases section
│   ├── config_flow.py          # User flow + options flow (allowlists, proxies, cap)
│   ├── options.py              # Option parsing/validation shared by flow + setup
│   ├── store.py                # Blob store + Store-backed index, LRU eviction
│   ├── fetch.py                # SSRF-guarded fetch-through (security-critical part)
│   ├── resolve.py              # Indirect-source resolution (oEmbed artwork lookup)
│   ├── view.py                 # img HTTP view + client_ip_allowed() pure function
│   ├── websocket.py            # image_proxy/register + image_proxy/stats commands
│   ├── const.py                # DOMAIN, CONF_* keys, defaults, timeouts
│   ├── strings.json            # Config + options flow strings
│   └── translations/en.json    # English translations
│
├── config/
│   └── configuration.yaml      # Minimal dev HA config (no default_config)
│
├── scripts/
│   ├── setup                   # Container post-create: pip + pre-commit + claude CLI
│   ├── develop                 # Foreground HA launcher (hass --config config --debug)
│   ├── demo / demo.py          # End-to-end demo: register a key, then fetch the img URL
│   └── lint                    # ruff check --fix && ruff format --check
│
├── .ruff.toml                  # select = ["ALL"] with a handful disabled; max-complexity 25
├── .pre-commit-config.yaml     # ruff + EOF/whitespace + check-yaml + local pytest hook
└── pyproject.toml              # Pytest config only (asyncio_mode = "auto", testpaths = ["tests"])
```

## Dev workflow

```bash
# First time inside the devcontainer (auto-runs scripts/setup on create):
scripts/setup                                       # pip install + pre-commit install + claude CLI

# Run Home Assistant in debug against the dev config:
scripts/develop                                     # HA at http://localhost:8123

# Add the integration via Settings, Devices and Services, Add Integration, Image Proxy.

# Tests
python -m pytest tests/                             # HA component tests

# Lint
scripts/lint                                        # ruff check --fix + format --check
pre-commit run --all-files                          # Same hooks CI runs
```

## Conventions and gotchas

- **Manifest version is `"0.0.0"` on purpose.** It is a sentinel. HACS reads the released version from git tags, not `manifest.json`, so do not bump it manually. See the Releases section.
- **Tags use CalVer** (`v<YYYY>.<M>.<DD>`), matching the fleet-wide HA-integration convention.
- **Ruff runs with `select = ["ALL"]`** (a handful disabled in `.ruff.toml`). New code is expected to pass cleanly; keep full type hints and docstrings.
- **The img view and WS commands are process-wide.** `__init__.py` registers the view once and reads the per-entry runtime dict (`hass.data[DOMAIN][entry_id]`) at request time. An options update triggers an entry reload so new config takes effect.
- **Keys are computed by the card, not the server.** The server is key-scheme agnostic: it stores `key -> src` and bytes by key. Blob filenames are `sha256(key)` so any key string is filesystem-safe.

## Status

Phase 1 implemented (art cache). The integration serves cached blobs over `GET /api/image_proxy/img/<key>` (client-IP allowlisted), fetches art through under an SSRF guard on a miss, exposes `image_proxy/register` and `image_proxy/stats` WebSocket commands, persists a `Store`-backed index alongside on-disk blobs, and enforces an LRU-evicted size cap. The full pytest suite covers the store, the SSRF guard, the IP gate, the endpoint, and the WS commands. A key-to-metadata KV API is the remaining Phase 2 work (see below).

## Implemented architecture (Phase 1)

- **`GET /api/image_proxy/img/<key>`** (`view.py`): serves a cached blob by key. Token-less, guarded by a client-IP allowlist. The IP decision lives in the pure, unit-tested `client_ip_allowed()`. On a miss for a known key, it fetches through; unknown key is `404`, fetch failure is `502`, blocked client is `403`.
- **`image_proxy/register`** (`websocket.py`): records `key -> src` mappings and warms the cache with bounded-concurrency background fetches. `image_proxy/stats` returns entry count + total bytes.
- **Blob store** (`store.py`): bytes under `config/.storage/image_proxy/blobs/<sha256(key)>`, plus a `Store`-backed in-memory index (`{blob, content_type, src, size, etag, ts, last_access}`) under an `asyncio.Lock`, with LRU eviction past the size cap.
- **Source resolution** (`resolve.py`): rewrites media-browser thumbnail URLs that point back at Home Assistant into direct artwork URLs via the services' public oEmbed endpoints. Best-effort, with pass-through on anything unrecognised. See `ARCHITECTURE.md`.
- **SSRF guard** (`fetch.py`): scheme + host-allowlist + resolved-IP checks, per-hop revalidation on redirects, `image/` content-type enforcement, and a body-size cap. Residual DNS-rebinding TOCTOU window is documented there as a LAN-only limitation.
- **Config-flow options** (`config_flow.py`, `options.py`): client CIDRs, Sonos coordinator IPs, upstream host allowlist, trusted proxies, and the cache cap (MB). List fields accept comma-separated text and are validated with `ipaddress`.

See `ARCHITECTURE.md` for the data-flow diagrams.

## Phase 2 (not built)

A key-to-metadata KV API (structured per-key metadata beyond the source URL) is the planned next phase and is intentionally out of scope for the Phase 1 art cache.

## Releases

Tags use **CalVer**: `v<YYYY>.<M>.<DD>` (e.g. `v2026.6.21`). Release titles use `Image Proxy v<YYYY>.<M>.<DD>`. No releases have been cut for this repo yet, so the first one establishes the on-disk history under the CalVer convention.

The release workflow (`.github/workflows/release.yml`) auto-creates the GitHub release on `v*` tag push. HACS reads the version from the git tag, not `manifest.json`, so do not bump `manifest.json`'s `"0.0.0"`.

Build the GitHub release body in three parts:

1. **Lead paragraph** (no header): 1 to 3 sentences of plain-English summary of what this release means for users.
2. **`## What's Changed`**: bullet list of non-dependabot merged PRs since the previous tag, one per line: `* <commit subject> by @<author> in <PR url>`. Skip dependabot PRs.
3. **`N dependabot updates:`** (rollup at the bottom): one line per dependency: `* <package>: <oldest version in window> -> <newest version>`. Collapse all bumps for the same dep into one line.

End with `**Full Changelog**: <compare link>` (GitHub auto-generates).
