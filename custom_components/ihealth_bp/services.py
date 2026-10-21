"""The ihealth_bp.delete_reading action."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SERVICE_DELETE_READING
from .coordinator import IHealthBPCoordinator

DELETE_READING_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("measured_at"): cv.datetime,
    }
)


def _coordinator_for_device(hass: HomeAssistant, device_id: str) -> IHealthBPCoordinator:
    device = dr.async_get(hass).async_get(device_id)
    if device is not None:
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry and entry.domain == DOMAIN and entry.state is ConfigEntryState.LOADED:
                return entry.runtime_data
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="device_not_found")


async def _async_delete_reading(call: ServiceCall) -> None:
    coordinator = _coordinator_for_device(call.hass, call.data["device_id"])
    measured_at = call.data["measured_at"]
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=dt_util.get_default_time_zone())
    reading = coordinator.store.find_by_time(measured_at)
    if reading is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="reading_not_found",
        )
    await coordinator.async_delete_reading(reading.uid)


def async_setup_services(hass: HomeAssistant) -> None:
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_READING, _async_delete_reading, schema=DELETE_READING_SCHEMA
    )
