"""Shared fixtures for Home Assistant tests."""

from __future__ import annotations

import pytest

ADDRESS = "00:4D:32:65:0E:89"


@pytest.fixture(autouse=True)
def mock_recorder_before_hass(async_test_recorder):
    """Prepare the recorder before the hass fixture is created."""
    return


@pytest.fixture(autouse=True)
def auto_recorder(recorder_mock):
    """The integration depends on recorder (long-term statistics)."""
    return


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    return


@pytest.fixture(autouse=True)
def auto_enable_bluetooth(enable_bluetooth):
    """Run every test with a mocked Bluetooth stack."""
    return
