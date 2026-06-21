# AGENTS.md, Image Proxy HA Integration

This is the canonical agent guide for `bharat/homeassistant-image-proxy`. New Claude/Codex/Cursor sessions should read this before making changes. Pair it with `ARCHITECTURE.md` for the planned data flow.

## What this is

A Home Assistant custom integration that provides a server-side image cache and proxy for media-card album art. The idea is to serve art from a stable, integration-owned endpoint keyed by a cache key, so the frontend always hits a predictable URL instead of whatever short-lived URL a media source happens to expose. Art is fetched through from a small set of whitelisted source hosts (a fetch-through cache), and the serving endpoint is locked down by a client-IP allowlist so only known clients can pull blobs. A key-to-source metadata index plus the on-disk blob store is a later phase; Phase 0 is just the loadable skeleton.

## Layout

```
.
├── AGENTS.md                   # This guide
├── ARCHITECTURE.md             # Planned data flow (Phase 1), read for design intent
├── CONTRIBUTING.md             # Standard fork/PR flow
├── README.md                   # User-facing install + status
│
├── custom_components/image_proxy/
│   ├── __init__.py             # async_setup_entry / async_unload_entry (no platforms yet)
│   ├── manifest.json           # version is "0.0.0" sentinel, see Releases section
│   ├── config_flow.py          # Single-step user flow + empty options-flow stub
│   ├── const.py                # DOMAIN
│   ├── strings.json            # Config-flow strings
│   └── translations/en.json    # English translations
│
├── config/
│   └── configuration.yaml      # Minimal dev HA config (no default_config)
│
├── scripts/
│   ├── setup                   # Container post-create: pip + pre-commit + claude CLI
│   ├── develop                 # Foreground HA launcher (hass --config config --debug)
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
- **No platforms are registered yet.** `__init__.py` only sets up and tears down a config entry. Phase 1 adds the HTTP view and the WebSocket command.

## Status

Phase 0, scaffold only. The integration loads cleanly (config entry set up and unloaded), but the actual image cache is not implemented yet. There is no img endpoint, no register WebSocket command, no blob store, and no SSRF guard in the code today. All of that is Phase 1. Do not document or advertise those features as working; they are planned.

## Planned architecture

The locked design for Phase 1 (not yet built):

- **`GET /api/image_proxy/img/<key>`**, an HTTP view that serves a cached blob by key. It is unauthenticated in the HA-token sense (media cards cannot easily attach a token), but it is guarded by a client-IP allowlist (configured CIDRs). On a cache miss for a known key, it fetches through from the source URL associated with that key.
- **`register` WebSocket command**, which warms the cache: it maps a cache key to a source URL (`key -> src`) ahead of time so the img endpoint can serve or fetch-through.
- **Blob store** under `config/.storage/image_proxy/blobs`, with a `Store`-backed index mapping keys to source URLs and blob metadata.
- **SSRF guard** on fetch-through: the source host must be on the configured whitelist, and resolved addresses must not be private or link-local, so the proxy cannot be used to reach internal services.
- **Cache key** shape: `sc:<track_id>` plus `h:<sha1(src)>`, so a key is stable for a given track and source.
- **Config-flow options** (Phase 1): client CIDRs for the IP allowlist, Sonos coordinator IPs (a common source of media art), and a blob size cap.

See `ARCHITECTURE.md` for the data-flow diagram.

## Releases

Tags use **CalVer**: `v<YYYY>.<M>.<DD>` (e.g. `v2026.6.21`). Release titles use `Image Proxy v<YYYY>.<M>.<DD>`. No releases have been cut for this repo yet, so the first one establishes the on-disk history under the CalVer convention.

The release workflow (`.github/workflows/release.yml`) auto-creates the GitHub release on `v*` tag push. HACS reads the version from the git tag, not `manifest.json`, so do not bump `manifest.json`'s `"0.0.0"`.

Build the GitHub release body in three parts:

1. **Lead paragraph** (no header): 1 to 3 sentences of plain-English summary of what this release means for users.
2. **`## What's Changed`**: bullet list of non-dependabot merged PRs since the previous tag, one per line: `* <commit subject> by @<author> in <PR url>`. Skip dependabot PRs.
3. **`N dependabot updates:`** (rollup at the bottom): one line per dependency: `* <package>: <oldest version in window> -> <newest version>`. Collapse all bumps for the same dep into one line.

End with `**Full Changelog**: <compare link>` (GitHub auto-generates).
