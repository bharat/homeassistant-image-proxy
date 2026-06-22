"""Tests for the register/stats WebSocket commands."""

from __future__ import annotations

import socket

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.image_proxy.const import DOMAIN

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_register_records_and_warms(
    hass, hass_ws_client, aioclient_mock, monkeypatch
):
    async def _getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(hass.loop, "getaddrinfo", _getaddrinfo)
    aioclient_mock.get(
        "https://cdn.example/art.png",
        content=PNG,
        headers={"Content-Type": "image/png"},
    )

    entry = await _setup(hass)
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": "image_proxy/register",
            "items": [{"key": "k1", "src": "https://cdn.example/art.png"}],
        }
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] == {"registered": 1, "warming": 1}

    # Let the background warm task finish, then the blob is cached.
    await hass.async_block_till_done()
    store = hass.data[DOMAIN][entry.entry_id]["store"]
    assert store.has_blob("k1")
    assert await store.async_read_blob("k1") == PNG


async def test_stats_returns_counts(hass, hass_ws_client):
    entry = await _setup(hass)
    store = hass.data[DOMAIN][entry.entry_id]["store"]
    await store.async_store_blob("k1", "http://src/1", "image/png", PNG)

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "image_proxy/stats"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["entries"] == 1
    assert msg["result"]["total_bytes"] == len(PNG)
