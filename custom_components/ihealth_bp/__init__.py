"""The iHealth Blood Pressure integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .connection import MODEL
from .const import CONF_ROUTINE_START, DOMAIN
from .coordinator import IHealthBPCoordinator
from .services import async_setup_services
from .storage import CuffStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TODO,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type IHealthBPConfigEntry = ConfigEntry[IHealthBPCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IHealthBPConfigEntry) -> bool:
    """Set up iHealth Blood Pressure from a config entry."""
    if CONF_ROUTINE_START not in entry.options:
        # Before the update listener is registered below, so this does not reload.
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_ROUTINE_START: dt_util.now().date().isoformat()},
        )
    address = entry.data[CONF_ADDRESS]
    store = CuffStore(hass, address)
    await store.async_load()
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, address)},
        identifiers={(DOMAIN, address)},
        manufacturer="iHealth",
        model=MODEL,
        name=entry.title,
    )
    coordinator = IHealthBPCoordinator(hass, entry, store, device.id)
    entry.runtime_data = coordinator
    if coordinator.variant.untested:
        _LOGGER.warning(
            "%s uses older firmware (%s). Support for it is UNTESTED - please report how it "
            "works, with debug logs, at https://github.com/NickLD/hass-ihealth-bp/issues",
            address,
            coordinator.variant.value,
        )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_start())
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: IHealthBPConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: IHealthBPConfigEntry) -> bool:
    """Unload a config entry, after any running session has finished."""
    await entry.runtime_data.async_close()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
