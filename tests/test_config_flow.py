"""Tests for the Image Proxy config and options flows."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.image_proxy.const import (
    CONF_ALLOWED_CIDRS,
    CONF_MAX_CACHE_MB,
    CONF_SONOS_IPS,
    DOMAIN,
)


async def test_user_flow_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Image Proxy"


async def test_second_instance_aborts(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_round_trip(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ALLOWED_CIDRS: "192.168.1.0/24, 127.0.0.0/8",
            CONF_SONOS_IPS: "192.168.1.50",
            CONF_MAX_CACHE_MB: 50,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ALLOWED_CIDRS] == ["192.168.1.0/24", "127.0.0.0/8"]
    assert entry.options[CONF_SONOS_IPS] == ["192.168.1.50"]
    assert entry.options[CONF_MAX_CACHE_MB] == 50


async def test_options_flow_rejects_bad_cidr(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_ALLOWED_CIDRS: "not-a-cidr", CONF_MAX_CACHE_MB: 100},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_ALLOWED_CIDRS: "invalid_cidr"}
