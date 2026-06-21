"""
Blob store and key index for the Image Proxy integration.

Blob bytes live as files under ``.storage/image_proxy/blobs``, named by a safe
hash of the cache key so any key string is filesystem-safe. The metadata index
(one entry per key) is persisted via Home Assistant's ``Store`` helper and held
in memory, guarded by an ``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class IndexEntry(TypedDict):
    """Metadata stored per cache key."""

    blob: str | None
    content_type: str | None
    src: str
    size: int
    etag: str | None
    ts: float
    last_access: float


def _blob_name(key: str) -> str:
    """Return a filesystem-safe blob filename for an arbitrary key string."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class ImageStore:
    """In-memory key index backed by ``Store``, plus an on-disk blob directory."""

    def __init__(self, hass: HomeAssistant, max_cache_bytes: int) -> None:
        """Initialize the store with a maximum total blob-byte cap."""
        self._hass = hass
        self._store: Store[dict[str, IndexEntry]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._index: dict[str, IndexEntry] = {}
        self._lock = asyncio.Lock()
        self._max_cache_bytes = max_cache_bytes
        self._blob_dir = Path(hass.config.path(".storage", "image_proxy", "blobs"))

    def set_max_cache_bytes(self, max_cache_bytes: int) -> None:
        """Update the cache cap (used when options change)."""
        self._max_cache_bytes = max_cache_bytes

    async def async_load(self) -> None:
        """Load the persisted index into memory and ensure the blob dir exists."""
        data = await self._store.async_load()
        if data:
            self._index = data
        await self._hass.async_add_executor_job(self._ensure_blob_dir)

    def _ensure_blob_dir(self) -> None:
        self._blob_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> IndexEntry | None:
        """Return the index entry for a key, or None if unknown."""
        return self._index.get(key)

    def has_blob(self, key: str) -> bool:
        """Return True if a key has a stored blob (not just a src mapping)."""
        entry = self._index.get(key)
        return bool(entry and entry["blob"])

    async def async_register(self, key: str, src: str) -> None:
        """Record (or update) a key -> src mapping without fetching anything."""
        async with self._lock:
            existing = self._index.get(key)
            now = time.time()
            if existing is not None:
                # Keep any existing blob; only refresh the source mapping.
                existing["src"] = src
            else:
                self._index[key] = IndexEntry(
                    blob=None,
                    content_type=None,
                    src=src,
                    size=0,
                    etag=None,
                    ts=now,
                    last_access=now,
                )
            self._store.async_delay_save(self._data_to_save, 1)

    async def async_read_blob(self, key: str) -> bytes | None:
        """Read a stored blob's bytes, or None if missing on disk."""
        entry = self._index.get(key)
        if not entry or not entry["blob"]:
            return None
        path = self._blob_dir / entry["blob"]
        return await self._hass.async_add_executor_job(self._read_file, path)

    @staticmethod
    def _read_file(path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except OSError:
            return None

    async def async_store_blob(
        self, key: str, src: str, content_type: str, data: bytes
    ) -> IndexEntry:
        """Write bytes for a key, update the index, and evict LRU if over cap."""
        blob = _blob_name(key)
        etag = hashlib.sha256(data).hexdigest()
        path = self._blob_dir / blob
        await self._hass.async_add_executor_job(self._write_file, path, data)
        async with self._lock:
            now = time.time()
            entry = IndexEntry(
                blob=blob,
                content_type=content_type,
                src=src,
                size=len(data),
                etag=etag,
                ts=now,
                last_access=now,
            )
            self._index[key] = entry
            await self._async_evict_locked()
            self._store.async_delay_save(self._data_to_save, 1)
            return entry

    @staticmethod
    def _write_file(path: Path, data: bytes) -> None:
        path.write_bytes(data)

    async def async_touch(self, key: str) -> None:
        """Update last_access for a key (LRU bookkeeping on a cache hit)."""
        async with self._lock:
            entry = self._index.get(key)
            if entry is not None:
                entry["last_access"] = time.time()
                self._store.async_delay_save(self._data_to_save, 1)

    def total_bytes(self) -> int:
        """Return the total bytes across all stored blobs."""
        return sum(e["size"] for e in self._index.values())

    def entry_count(self) -> int:
        """Return the number of index entries."""
        return len(self._index)

    async def _async_evict_locked(self) -> None:
        """
        Evict least-recently-used blobs until total bytes are under the cap.

        Caller must hold ``self._lock``.
        """
        while self.total_bytes() > self._max_cache_bytes:
            # Only entries that actually hold a blob count toward the cap and
            # are eligible for eviction.
            candidates = [
                (k, e) for k, e in self._index.items() if e["blob"] and e["size"]
            ]
            if not candidates:
                break
            victim_key, victim = min(candidates, key=lambda kv: kv[1]["last_access"])
            blob = victim["blob"]
            if blob:
                path = self._blob_dir / blob
                await self._hass.async_add_executor_job(self._unlink_file, path)
            # Drop the whole entry; the src mapping can be re-registered later.
            self._index.pop(victim_key, None)

    @staticmethod
    def _unlink_file(path: Path) -> None:
        with contextlib.suppress(OSError):
            path.unlink()

    def _data_to_save(self) -> dict[str, IndexEntry]:
        return self._index
