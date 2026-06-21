"""
The Image Proxy integration.

Phase 1 (art cache): sets up the blob store, registers the img HTTP view and the
register/stats WebSocket commands, and exposes the allowlist + cache-cap options.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import DOMAIN
from .options import effective_config
from .store import ImageStore
from .view import ImageProxyView
from .websocket import async_register_commands

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_VIEW_REGISTERED = "_view_registered"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Image Proxy from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    config = effective_config(entry)
    store = ImageStore(hass, config["max_cache_bytes"])
    await store.async_load()

    domain_data[entry.entry_id] = {"store": store, **config}

    # The view and WS commands are process-wide; register them once. Both read
    # the per-entry runtime dict at request time, so option changes take effect
    # after the reload triggered by the update listener below.
    if not domain_data.get(_VIEW_REGISTERED):
        hass.http.register_view(ImageProxyView(hass, entry.entry_id))
        domain_data[_VIEW_REGISTERED] = True
    async_register_commands(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Image Proxy config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    domain_data.pop(entry.entry_id, None)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry so updated options take effect."""
    await hass.config_entries.async_reload(entry.entry_id)
