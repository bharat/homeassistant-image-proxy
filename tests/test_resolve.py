"""
Tests for indirect-source resolution.

The proxy URLs here are real shapes taken from a live index: the service id
inside the content id is percent-encoded twice, and the content id's own query
string has been flattened into the URL's query string.
"""

from __future__ import annotations

import pytest

from custom_components.image_proxy.resolve import async_resolve_src

BASE = "http://ha.example/api/media_player_proxy/media_player.main/browse_media"
PROXY_QUERY = "?token=a52e26bd5fee67a476fd6bdbc4ce45407e6ae3361de052789be239075e1493a8"

SPOTIFY_SRC = (
    f"{BASE}/track/x-sonos-spotify:spotify%253atrack%253a0JhKJg5ejeQ8jq89UQtnw8"
    f"%3Fsid=12&flags=8224&sn=3{PROXY_QUERY}"
)
SPOTIFY_OEMBED = (
    "https://open.spotify.com/oembed?url=spotify:track:0JhKJg5ejeQ8jq89UQtnw8"
)
SPOTIFY_ART = "https://image-cdn-ak.spotifycdn.com/image/ab67616d00001e02e0a8be"

SOUNDCLOUD_SRC = (
    f"{BASE}/track/x-sonosapi-hls-static:track-%253esoundcloud%253atracks"
    f"%253a1233498328%3Fsid=160&flags=8232&sn=26{PROXY_QUERY}"
)
SOUNDCLOUD_OEMBED = (
    "https://soundcloud.com/oembed?format=json"
    "&url=https%3A%2F%2Fapi.soundcloud.com%2Ftracks%2F1233498328"
)
SOUNDCLOUD_ART = "https://i1.sndcdn.com/artworks-000074272625-0pwdr9-t500x500.jpg"


async def test_spotify_track_resolves_to_artwork(hass, aioclient_mock):
    aioclient_mock.get(SPOTIFY_OEMBED, json={"thumbnail_url": SPOTIFY_ART})
    assert await async_resolve_src(hass, SPOTIFY_SRC) == SPOTIFY_ART


async def test_soundcloud_track_resolves_to_artwork(hass, aioclient_mock):
    aioclient_mock.get(SOUNDCLOUD_OEMBED, json={"thumbnail_url": SOUNDCLOUD_ART})
    assert await async_resolve_src(hass, SOUNDCLOUD_SRC) == SOUNDCLOUD_ART


@pytest.mark.parametrize(
    "src",
    [
        # A direct Sonos coordinator URL, the common case.
        "http://192.168.0.33:1400/getaa?u=x&v=1",
        # A plain CDN URL.
        "https://i.scdn.co/image/abc123",
        # Albums and artists are served correctly by the media player already.
        f"{BASE}/album/A%3Aalbum%3A123{PROXY_QUERY}",
        # A track with no recognisable service id in its content id.
        f"{BASE}/track/x-sonos-http:A0DvPDnowsLnj0OKyk74.mp3%3Fsid=151{PROXY_QUERY}",
    ],
)
async def test_unrecognised_sources_pass_through(hass, src):
    assert await async_resolve_src(hass, src) == src


@pytest.mark.parametrize(
    "response",
    [
        {"status": 404},
        {"text": "not json"},
        {"json": {"title": "no thumbnail here"}},
        {"json": {"thumbnail_url": ""}},
        {"json": ["not", "a", "dict"]},
    ],
)
async def test_bad_oembed_response_falls_back_to_original(
    hass, aioclient_mock, response
):
    aioclient_mock.get(SPOTIFY_OEMBED, **response)
    assert await async_resolve_src(hass, SPOTIFY_SRC) == SPOTIFY_SRC


async def test_oversized_oembed_response_falls_back(hass, aioclient_mock):
    aioclient_mock.get(SPOTIFY_OEMBED, text="x" * (64 * 1024 + 10))
    assert await async_resolve_src(hass, SPOTIFY_SRC) == SPOTIFY_SRC


async def test_unreachable_oembed_falls_back(hass, aioclient_mock):
    aioclient_mock.get(SPOTIFY_OEMBED, exc=TimeoutError)
    assert await async_resolve_src(hass, SPOTIFY_SRC) == SPOTIFY_SRC
