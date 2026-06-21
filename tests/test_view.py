"""Tests for the img endpoint and the client-IP gate."""

from __future__ import annotations

import ipaddress
import socket

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.image_proxy.const import DOMAIN
from custom_components.image_proxy.view import client_ip_allowed

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _nets(*cidrs):
    return [ipaddress.ip_network(c) for c in cidrs]


DEFAULTS = _nets("10.0.0.0/8", "192.168.0.0/16", "100.64.0.0/10", "127.0.0.0/8")


def test_rfc1918_allowed():
    assert client_ip_allowed("192.168.1.5", None, DEFAULTS, [])


def test_tailscale_cgnat_allowed():
    assert client_ip_allowed("100.101.102.103", None, DEFAULTS, [])


def test_public_ip_blocked():
    assert not client_ip_allowed("93.184.216.34", None, DEFAULTS, [])


def test_xff_ignored_from_untrusted_peer():
    # Peer is public (not a trusted proxy), so its XFF claim is ignored and the
    # public peer itself is judged: blocked.
    assert not client_ip_allowed(
        "93.184.216.34", "192.168.1.5", DEFAULTS, _nets("10.0.0.0/8")
    )


def test_xff_honored_from_trusted_proxy():
    # Peer is a trusted proxy; the right-most non-proxy XFF entry is the client.
    assert client_ip_allowed(
        "10.0.0.2",
        "192.168.1.5, 10.0.0.2",
        DEFAULTS,
        _nets("10.0.0.0/8"),
    )


def test_xff_skips_chained_trusted_proxies():
    # Two trusted proxies at the tail; the client is the first non-proxy hop.
    assert client_ip_allowed(
        "10.0.0.3",
        "192.168.1.5, 10.0.0.2, 10.0.0.3",
        DEFAULTS,
        _nets("10.0.0.0/8"),
    )


def test_missing_peer_blocked():
    assert not client_ip_allowed(None, None, DEFAULTS, [])


@pytest.fixture
async def setup_entry(hass):
    """Set up the integration with loopback allowed (test client is 127.0.0.1)."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_unknown_key_404(hass, setup_entry, hass_client_no_auth):
    client = await hass_client_no_auth()
    resp = await client.get("/api/image_proxy/img/nope")
    assert resp.status == 404


async def test_prestored_blob_served_with_headers(
    hass, setup_entry, hass_client_no_auth
):
    runtime = hass.data[DOMAIN][setup_entry.entry_id]
    store = runtime["store"]
    entry = await store.async_store_blob("k1", "http://src/1", "image/png", PNG)

    client = await hass_client_no_auth()
    resp = await client.get("/api/image_proxy/img/k1")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert resp.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert resp.headers["ETag"] == f'"{entry["etag"]}"'
    assert await resp.read() == PNG

    # If-None-Match matching the etag yields a 304.
    resp = await client.get(
        "/api/image_proxy/img/k1",
        headers={"If-None-Match": f'"{entry["etag"]}"'},
    )
    assert resp.status == 304


async def test_known_mapping_fetches_through(
    hass, setup_entry, hass_client_no_auth, aioclient_mock, monkeypatch
):
    async def _getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(hass.loop, "getaddrinfo", _getaddrinfo)
    aioclient_mock.get(
        "https://cdn.example/art.png",
        content=PNG,
        headers={"Content-Type": "image/png"},
    )

    runtime = hass.data[DOMAIN][setup_entry.entry_id]
    store = runtime["store"]
    await store.async_register("k2", "https://cdn.example/art.png")

    client = await hass_client_no_auth()
    resp = await client.get("/api/image_proxy/img/k2")
    assert resp.status == 200
    assert await resp.read() == PNG
    # The blob is now cached.
    assert store.has_blob("k2")


async def test_fetch_failure_returns_502(
    hass, setup_entry, hass_client_no_auth, monkeypatch
):
    async def _getaddrinfo(host, port, *args, **kwargs):
        # Resolves to a private IP that is not allowlisted: SSRF guard rejects.
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0))]

    monkeypatch.setattr(hass.loop, "getaddrinfo", _getaddrinfo)
    runtime = hass.data[DOMAIN][setup_entry.entry_id]
    store = runtime["store"]
    await store.async_register("k3", "http://internal.local/secret.png")

    client = await hass_client_no_auth()
    resp = await client.get("/api/image_proxy/img/k3")
    assert resp.status == 502
