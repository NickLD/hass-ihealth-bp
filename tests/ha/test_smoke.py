"""The integration loads at all."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ihealth_bp.const import DOMAIN

from .conftest import ADDRESS


async def test_setup_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={"address": ADDRESS})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
