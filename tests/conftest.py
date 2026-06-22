"""Shared fixtures for the Image Proxy test suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the image_proxy custom integration in every test."""
    return enable_custom_integrations
