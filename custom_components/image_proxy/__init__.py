"""The Image Proxy integration.

Phase 0 scaffold: this sets up a single config entry and tears it down again.
The actual image cache, the HTTP view, and the WebSocket command land in Phase 1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Image Proxy from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    # Phase 1 will register the img HTTP view and register WS command here.
    domain_data[entry.entry_id] = {}
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Image Proxy config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    domain_data.pop(entry.entry_id, None)
    return True
