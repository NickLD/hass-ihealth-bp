"""The ihealth_bp reading and session actions."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    FLAGS,
    SERVICE_DELETE_READING,
    SERVICE_DELETE_SESSION,
    SERVICE_SET_READING_CONTEXT,
)
from .coordinator import IHealthBPCoordinator

DELETE_READING_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("measured_at"): cv.datetime,
    }
)

DELETE_SESSION_SCHEMA = DELETE_READING_SCHEMA

SET_READING_CONTEXT_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("measured_at"): cv.datetime,
        vol.Optional("session", default=False): cv.boolean,
        vol.Optional("flags"): vol.All(cv.ensure_list, [vol.In(FLAGS)]),
        vol.Optional("add_flags"): vol.All(cv.ensure_list, [vol.In(FLAGS)]),
        vol.Optional("note"): vol.All(cv.string, vol.Length(max=255)),
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


def _not_found() -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key="reading_not_found")


def _find_uid(call: ServiceCall) -> tuple[IHealthBPCoordinator, str]:
    coordinator = _coordinator_for_device(call.hass, call.data["device_id"])
    measured_at = call.data["measured_at"]
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=dt_util.get_default_time_zone())
    reading = coordinator.store.find_by_time(measured_at)
    if reading is None:
        raise _not_found()
    return coordinator, reading.uid


async def _async_delete_reading(call: ServiceCall) -> None:
    coordinator, uid = _find_uid(call)
    await coordinator.async_delete_reading(uid)


async def _async_delete_session(call: ServiceCall) -> None:
    coordinator, uid = _find_uid(call)
    try:
        await coordinator.async_delete_session(uid)
    except KeyError:
        raise _not_found() from None


async def _async_set_reading_context(call: ServiceCall) -> None:
    data = call.data
    if not any(k in data for k in ("flags", "add_flags", "note")):
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="nothing_to_set")
    coordinator, uid = _find_uid(call)
    try:
        await coordinator.async_set_context(
            uid,
            session=data["session"],
            flags=data.get("flags"),
            add_flags=data.get("add_flags", ()),
            note=data.get("note"),
        )
    except KeyError:
        raise _not_found() from None


def async_setup_services(hass: HomeAssistant) -> None:
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_READING, _async_delete_reading, schema=DELETE_READING_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_SESSION, _async_delete_session, schema=DELETE_SESSION_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_READING_CONTEXT,
        _async_set_reading_context,
        schema=SET_READING_CONTEXT_SCHEMA,
    )
