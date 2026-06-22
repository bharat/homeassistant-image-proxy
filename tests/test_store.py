"""Tests for the Image Proxy blob store and index."""

from __future__ import annotations

import hashlib

from custom_components.image_proxy.store import ImageStore


async def test_store_and_read_blob(hass):
    store = ImageStore(hass, max_cache_bytes=10 * 1024 * 1024)
    await store.async_load()

    data = b"hello-image-bytes"
    entry = await store.async_store_blob("k1", "http://src/1", "image/png", data)

    assert entry["content_type"] == "image/png"
    assert entry["size"] == len(data)
    assert entry["etag"] == hashlib.sha256(data).hexdigest()
    assert store.has_blob("k1")
    assert await store.async_read_blob("k1") == data


async def test_last_access_touch(hass):
    store = ImageStore(hass, max_cache_bytes=10 * 1024 * 1024)
    await store.async_load()
    await store.async_store_blob("k1", "http://src/1", "image/png", b"abc")

    before = store.get("k1")["last_access"]
    # Force a distinct timestamp without relying on wall-clock resolution.
    store.get("k1")["last_access"] = before - 100
    await store.async_touch("k1")
    assert store.get("k1")["last_access"] > before - 100


async def test_register_then_warm_keeps_blob(hass):
    store = ImageStore(hass, max_cache_bytes=10 * 1024 * 1024)
    await store.async_load()
    await store.async_register("k1", "http://src/1")
    assert not store.has_blob("k1")
    assert store.get("k1")["src"] == "http://src/1"

    await store.async_store_blob("k1", "http://src/1", "image/png", b"abc")
    # Re-registering must not wipe an existing blob.
    await store.async_register("k1", "http://src/2")
    assert store.has_blob("k1")
    assert store.get("k1")["src"] == "http://src/2"


async def test_lru_eviction_over_cap(hass):
    # Cap at 10 bytes; each blob is 6 bytes, so only one fits at a time.
    store = ImageStore(hass, max_cache_bytes=10)
    await store.async_load()

    await store.async_store_blob("old", "http://src/old", "image/png", b"aaaaaa")
    # Make "old" clearly the least recently used.
    store.get("old")["last_access"] = store.get("old")["last_access"] - 100

    await store.async_store_blob("new", "http://src/new", "image/png", b"bbbbbb")

    assert not store.has_blob("old")
    assert store.get("old") is None
    assert store.has_blob("new")
    assert store.total_bytes() <= 10
    assert await store.async_read_blob("new") == b"bbbbbb"
