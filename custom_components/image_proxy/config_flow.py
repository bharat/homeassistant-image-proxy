"""
Config flow for the Image Proxy integration.

A single-step user flow creates one entry and guards against a second instance.
The options flow exposes the client-IP allowlist, the Sonos coordinator IPs, the
upstream host allowlist, the trusted proxies, and the cache size cap.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_ALLOWED_CIDRS,
    CONF_HOST_ALLOWLIST,
    CONF_MAX_CACHE_MB,
    CONF_SONOS_IPS,
    CONF_TRUSTED_PROXIES,
    DEFAULT_ALLOWED_CIDRS,
    DEFAULT_HOST_ALLOWLIST,
    DEFAULT_MAX_CACHE_MB,
    DEFAULT_SONOS_IPS,
    DEFAULT_TRUSTED_PROXIES,
    DOMAIN,
)
from .options import parse_ips, parse_networks, split_list


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
        config_entry: config_entries.ConfigEntry,  # noqa: ARG004
    ) -> ImageProxyOptionsFlow:
        """Return the options flow handler."""
        return ImageProxyOptionsFlow()


def _as_text(value: Any) -> str:
    """Render a stored option (list or string) as comma-separated text."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


class ImageProxyOptionsFlow(config_entries.OptionsFlow):
    """Handle Image Proxy options (allowlists, proxies, and cache cap)."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        options = self.config_entry.options
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_ALLOWED_CIDRS: split_list(
                            user_input.get(CONF_ALLOWED_CIDRS)
                        ),
                        CONF_SONOS_IPS: split_list(user_input.get(CONF_SONOS_IPS)),
                        CONF_HOST_ALLOWLIST: split_list(
                            user_input.get(CONF_HOST_ALLOWLIST)
                        ),
                        CONF_TRUSTED_PROXIES: split_list(
                            user_input.get(CONF_TRUSTED_PROXIES)
                        ),
                        CONF_MAX_CACHE_MB: int(user_input[CONF_MAX_CACHE_MB]),
                    },
                )

        def _default(key: str, fallback: Any) -> str:
            if user_input is not None and key in user_input:
                return _as_text(user_input[key])
            return _as_text(options.get(key, fallback))

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ALLOWED_CIDRS,
                    default=_default(CONF_ALLOWED_CIDRS, DEFAULT_ALLOWED_CIDRS),
                ): str,
                vol.Optional(
                    CONF_SONOS_IPS,
                    default=_default(CONF_SONOS_IPS, DEFAULT_SONOS_IPS),
                ): str,
                vol.Optional(
                    CONF_HOST_ALLOWLIST,
                    default=_default(CONF_HOST_ALLOWLIST, DEFAULT_HOST_ALLOWLIST),
                ): str,
                vol.Optional(
                    CONF_TRUSTED_PROXIES,
                    default=_default(CONF_TRUSTED_PROXIES, DEFAULT_TRUSTED_PROXIES),
                ): str,
                vol.Optional(
                    CONF_MAX_CACHE_MB,
                    default=int(
                        options.get(CONF_MAX_CACHE_MB, DEFAULT_MAX_CACHE_MB)
                        if user_input is None
                        else user_input.get(CONF_MAX_CACHE_MB, DEFAULT_MAX_CACHE_MB)
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate the list-y fields, returning a field -> error-key map."""
    errors: dict[str, str] = {}
    try:
        parse_networks(split_list(user_input.get(CONF_ALLOWED_CIDRS)))
    except ValueError:
        errors[CONF_ALLOWED_CIDRS] = "invalid_cidr"
    try:
        parse_networks(split_list(user_input.get(CONF_TRUSTED_PROXIES)))
    except ValueError:
        errors[CONF_TRUSTED_PROXIES] = "invalid_cidr"
    try:
        parse_ips(split_list(user_input.get(CONF_SONOS_IPS)))
    except ValueError:
        errors[CONF_SONOS_IPS] = "invalid_ip"
    return errors
