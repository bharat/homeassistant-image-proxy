"""Config flow for the Image Proxy integration.

Phase 0 scaffold: a single-step user flow that creates one entry and guards
against a second instance. The allowlist and size-cap options arrive in Phase 1
via the options flow stubbed here.
"""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN


class ImageProxyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Image Proxy."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, object] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step initiated by the user."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Image Proxy", data={})

        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ImageProxyOptionsFlow:
        """Return the options flow handler."""
        return ImageProxyOptionsFlow(config_entry)


class ImageProxyOptionsFlow(config_entries.OptionsFlow):
    """Handle Image Proxy options.

    Phase 1 will add the client CIDR allowlist, the Sonos coordinator IPs, and
    the blob size cap here. For now this is an empty single-step stub.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, object] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(step_id="init")
