"""
WebSocket commands for the Image Proxy integration.

``image_proxy/register`` records key -> src mappings and warms the cache with
bounded-concurrency background fetches. ``image_proxy/stats`` reports the entry
count and total cached bytes (handy for the demo).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.components import websocket_api

from .const import DOMAIN, WARM_CONCURRENCY
from .fetch import FetchError, fetch_image

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .store import ImageStore

_LOGGER = logging.getLogger(__name__)


def async_register_commands(hass: HomeAssistant) -> None:
    """Register the integration's WebSocket commands (idempotent)."""
    if hass.data[DOMAIN].get("_ws_registered"):
        return
    websocket_api.async_register_command(hass, ws_register)
    websocket_api.async_register_command(hass, ws_stats)
    hass.data[DOMAIN]["_ws_registered"] = True


def _first_runtime(hass: HomeAssistant) -> dict | None:
    """Return the single config entry's runtime data, if set up."""
    for key, value in hass.data.get(DOMAIN, {}).items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and "store" in value:
            return value
    return None


@websocket_api.websocket_command(
    {
        vol.Required("type"): "image_proxy/register",
        vol.Required("items"): [
            {vol.Required("key"): str, vol.Required("src"): str},
        ],
    }
)
@websocket_api.async_response
async def ws_register(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Record key -> src mappings and warm the cache in the background."""
    runtime = _first_runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_ready", "Image Proxy is not set up")
        return

    store: ImageStore = runtime["store"]
    items = msg["items"]

    to_warm: list[tuple[str, str]] = []
    for item in items:
        key = item["key"]
        src = item["src"]
        await store.async_register(key, src)
        if not store.has_blob(key):
            to_warm.append((key, src))

    if to_warm:
        hass.async_create_background_task(
            _warm(hass, runtime, store, to_warm),
            name="image_proxy_warm",
        )

    connection.send_result(
        msg["id"],
        {"registered": len(items), "warming": len(to_warm)},
    )


async def _warm(
    hass: HomeAssistant,
    runtime: dict,
    store: ImageStore,
    items: list[tuple[str, str]],
) -> None:
    """Fetch-through each item with bounded concurrency, ignoring failures."""
    sem = asyncio.Semaphore(WARM_CONCURRENCY)

    async def _one(key: str, src: str) -> None:
        async with sem:
            if store.has_blob(key):
                return
            try:
                content_type, data = await fetch_image(
                    hass,
                    src,
                    allow_private_hosts=runtime["sonos_ips"],
                    host_allowlist=runtime["host_allowlist"],
                )
            except FetchError as err:
                _LOGGER.debug("Warm fetch failed for %s (%s): %s", key, src, err)
                return
            await store.async_store_blob(key, src, content_type, data)

    await asyncio.gather(*(_one(key, src) for key, src in items))


@websocket_api.websocket_command({vol.Required("type"): "image_proxy/stats"})
@websocket_api.async_response
async def ws_stats(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return the cache entry count and total bytes."""
    runtime = _first_runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_ready", "Image Proxy is not set up")
        return
    store: ImageStore = runtime["store"]
    connection.send_result(
        msg["id"],
        {"entries": store.entry_count(), "total_bytes": store.total_bytes()},
    )
