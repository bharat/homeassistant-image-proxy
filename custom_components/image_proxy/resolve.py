"""
Resolve indirect image sources to a directly fetchable artwork URL.

Media browsers sometimes hand out a thumbnail that points back at Home
Assistant's own ``media_player_proxy`` endpoint rather than at the artwork. For
streaming-service *tracks* those URLs are not usable as a cache source:

* The Sonos integration only serves browse images for albums and artists, so a
  track URL returns an empty 404 (fixed upstream by home-assistant/core#177510).
* They embed a ``token`` taken from the media player's ``access_token``, which
  is regenerated on every restart, so a stored URL later 403s.

A track's artwork URI cannot be rebuilt from its content id by the media player,
but the *service* track id is embedded in that content id, and both services we
care about expose a public, unauthenticated oEmbed endpoint that returns the
artwork. So we recover the track id and ask the service directly instead of
round-tripping Home Assistant's own HTTP endpoint.

Resolution is best-effort: anything unrecognised or unreachable falls back to
the original source, so behaviour is never worse than not resolving at all.
"""

from __future__ import annotations

import json
import logging
import re
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import FETCH_TIMEOUT_S, OEMBED_MAX_BYTES

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Only browse-media *track* URLs need this. Album and artist URLs are served
# correctly by the media player today, so they are left alone.
_PROXY_TRACK = re.compile(r"/api/media_player_proxy/[^/]+/browse_media/track/")

# The content id is percent-encoded twice (once by the media source, again by
# get_browse_image_url) and the service id sits inside one of several
# ``x-sonos*`` container schemes. Matching the service id itself is more robust
# than trying to parse the container. The captured ids are alphanumeric, which
# is what makes them safe to interpolate into the oEmbed URLs below.
_TRACK_PATTERNS = (
    ("spotify", re.compile(r"spotify:track:([A-Za-z0-9]+)")),
    ("soundcloud", re.compile(r"soundcloud:tracks:([0-9]+)")),
)

_UNQUOTE_PASSES = 3


def _fully_unquoted(value: str) -> str:
    """Percent-decode until stable, since the content id is doubly encoded."""
    for _ in range(_UNQUOTE_PASSES):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return value


def _track_ref(src: str) -> tuple[str, str] | None:
    """Return ``(provider, track_id)`` if src is a proxied service track."""
    if not _PROXY_TRACK.search(src):
        return None
    decoded = _fully_unquoted(src)
    for provider, pattern in _TRACK_PATTERNS:
        match = pattern.search(decoded)
        if match:
            return provider, match.group(1)
    return None


def _oembed_url(provider: str, track_id: str) -> str:
    """Build a provider's public oEmbed URL for a track id."""
    if provider == "spotify":
        return f"https://open.spotify.com/oembed?url=spotify:track:{track_id}"
    track_url = quote(f"https://api.soundcloud.com/tracks/{track_id}", safe="")
    return f"https://soundcloud.com/oembed?format=json&url={track_url}"


def _thumbnail_from_payload(raw: bytes) -> str | None:
    """Extract a non-empty ``thumbnail_url`` from an oEmbed JSON body."""
    try:
        payload = json.loads(raw)
    except ValueError as err:
        _LOGGER.debug("oEmbed response is not valid JSON: %s", err)
        return None
    if not isinstance(payload, dict):
        return None
    thumbnail = payload.get("thumbnail_url")
    if not isinstance(thumbnail, str) or not thumbnail:
        return None
    return thumbnail


async def _async_oembed_thumbnail(hass: HomeAssistant, url: str) -> str | None:
    """Return the ``thumbnail_url`` from an oEmbed endpoint, or None."""
    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT_S)
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status != HTTPStatus.OK:
                _LOGGER.debug("oEmbed %s returned status %s", url, resp.status)
                return None
            # Bound the body: these payloads are a few hundred bytes, and the
            # provider is third-party.
            raw = await resp.content.read(OEMBED_MAX_BYTES + 1)
    except (TimeoutError, aiohttp.ClientError) as err:
        _LOGGER.debug("oEmbed request to %s failed: %s", url, err)
        return None

    if len(raw) > OEMBED_MAX_BYTES:
        _LOGGER.debug("oEmbed response from %s exceeds the size cap", url)
        return None
    return _thumbnail_from_payload(raw)


async def async_resolve_src(hass: HomeAssistant, src: str) -> str:
    """
    Return a directly fetchable artwork URL for ``src``.

    Sources that are not recognised as an indirect reference are returned
    unchanged. A resolved URL comes from a third party and is still subject to
    the SSRF guard in ``fetch.py``; nothing here is trusted.
    """
    ref = _track_ref(src)
    if ref is None:
        return src
    provider, track_id = ref

    thumbnail = await _async_oembed_thumbnail(hass, _oembed_url(provider, track_id))
    if thumbnail is None:
        return src

    _LOGGER.debug("Resolved %s track %s to %s", provider, track_id, thumbnail)
    return thumbnail
