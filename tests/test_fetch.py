"""
Tests for the SSRF-guarded fetch-through.

These are the security-critical tests. We monkeypatch ``getaddrinfo`` so we can
control exactly which IP each hostname resolves to, and drive the HTTP layer
with the ``aioclient_mock`` fixture.
"""

from __future__ import annotations

import socket

import pytest

from custom_components.image_proxy.fetch import (
    FetchFailedError,
    FetchRejectedError,
    fetch_image,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def fake_dns(hass, monkeypatch):
    """Patch hass.loop.getaddrinfo to resolve hosts from a controllable map."""
    mapping: dict[str, str] = {}

    async def _getaddrinfo(host, port, *args, **kwargs):
        ip = mapping.get(host)
        if ip is None:
            msg = f"no fake DNS entry for {host}"
            raise OSError(msg)
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        sockaddr = (ip, 0, 0, 0) if ":" in ip else (ip, 0)
        return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]

    monkeypatch.setattr(hass.loop, "getaddrinfo", _getaddrinfo)
    return mapping


async def test_rejects_private_resolved_ip(hass, fake_dns):
    fake_dns["evil.example"] = "192.168.1.10"
    with pytest.raises(FetchRejectedError):
        await fetch_image(hass, "http://evil.example/art.png")


async def test_allows_configured_sonos_private_ip(hass, fake_dns, aioclient_mock):
    fake_dns["sonos.local"] = "192.168.1.50"
    aioclient_mock.get(
        "http://sonos.local/art.png",
        content=PNG,
        headers={"Content-Type": "image/png"},
    )
    content_type, data = await fetch_image(
        hass,
        "http://sonos.local/art.png",
        allow_private_hosts=["sonos.local"],
    )
    assert content_type == "image/png"
    assert data == PNG


async def test_allows_sonos_by_ip_literal(hass, fake_dns, aioclient_mock):
    fake_dns["192.168.1.50"] = "192.168.1.50"
    aioclient_mock.get(
        "http://192.168.1.50/art.png",
        content=PNG,
        headers={"Content-Type": "image/png"},
    )
    content_type, _ = await fetch_image(
        hass,
        "http://192.168.1.50/art.png",
        allow_private_hosts=["192.168.1.50"],
    )
    assert content_type == "image/png"


async def test_allows_public_ip(hass, fake_dns, aioclient_mock):
    fake_dns["cdn.example"] = "93.184.216.34"
    aioclient_mock.get(
        "https://cdn.example/art.png",
        content=PNG,
        headers={"Content-Type": "image/png"},
    )
    content_type, data = await fetch_image(hass, "https://cdn.example/art.png")
    assert content_type == "image/png"
    assert data == PNG


async def test_rejects_non_http_scheme(hass, fake_dns):
    with pytest.raises(FetchRejectedError):
        await fetch_image(hass, "ftp://cdn.example/art.png")


async def test_rejects_non_image_content_type(hass, fake_dns, aioclient_mock):
    fake_dns["cdn.example"] = "93.184.216.34"
    aioclient_mock.get(
        "https://cdn.example/art.png",
        content=b"<html>",
        headers={"Content-Type": "text/html"},
    )
    with pytest.raises(FetchFailedError):
        await fetch_image(hass, "https://cdn.example/art.png")


async def test_enforces_max_bytes(hass, fake_dns, aioclient_mock):
    fake_dns["cdn.example"] = "93.184.216.34"
    aioclient_mock.get(
        "https://cdn.example/big.png",
        content=b"x" * 5000,
        headers={"Content-Type": "image/png"},
    )
    with pytest.raises(FetchFailedError):
        await fetch_image(hass, "https://cdn.example/big.png", max_bytes=1000)


async def test_host_allowlist_blocks_unlisted_host(hass, fake_dns, aioclient_mock):
    fake_dns["cdn.example"] = "93.184.216.34"
    aioclient_mock.get(
        "https://cdn.example/art.png",
        content=PNG,
        headers={"Content-Type": "image/png"},
    )
    with pytest.raises(FetchRejectedError):
        await fetch_image(
            hass,
            "https://cdn.example/art.png",
            host_allowlist=["*.sndcdn.com"],
        )


async def test_host_allowlist_allows_glob_match(hass, fake_dns, aioclient_mock):
    fake_dns["cf-media.sndcdn.com"] = "93.184.216.34"
    aioclient_mock.get(
        "https://cf-media.sndcdn.com/art.png",
        content=PNG,
        headers={"Content-Type": "image/png"},
    )
    content_type, _ = await fetch_image(
        hass,
        "https://cf-media.sndcdn.com/art.png",
        host_allowlist=["*.sndcdn.com"],
    )
    assert content_type == "image/png"


async def test_redirect_to_good_host_followed(hass, fake_dns, aioclient_mock):
    fake_dns["cdn.example"] = "93.184.216.34"
    fake_dns["img.sndcdn.com"] = "93.184.216.35"
    aioclient_mock.get(
        "https://cdn.example/art.png",
        status=302,
        headers={"Location": "https://img.sndcdn.com/real.png"},
    )
    aioclient_mock.get(
        "https://img.sndcdn.com/real.png",
        content=PNG,
        headers={"Content-Type": "image/png"},
    )
    content_type, data = await fetch_image(hass, "https://cdn.example/art.png")
    assert content_type == "image/png"
    assert data == PNG


async def test_redirect_to_private_host_rejected(hass, fake_dns, aioclient_mock):
    fake_dns["cdn.example"] = "93.184.216.34"
    fake_dns["internal.local"] = "10.0.0.5"
    aioclient_mock.get(
        "https://cdn.example/art.png",
        status=302,
        headers={"Location": "http://internal.local/secret"},
    )
    with pytest.raises(FetchRejectedError):
        await fetch_image(hass, "https://cdn.example/art.png")
