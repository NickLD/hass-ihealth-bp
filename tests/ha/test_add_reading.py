"""The add_reading action: readings entered by hand."""

from __future__ import annotations

from datetime import datetime

import pytest
import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.ihealth_bp.const import DOMAIN, EVENT_MEASUREMENT
from custom_components.ihealth_bp.storage import CuffStore, ReadingStatus
from ..kn550bt.fake_cuff import FakeCuff, StoredReading

from .conftest import ADDRESS
from .helpers import async_setup_cuff, async_sync


def call(coordinator, measured_at="2026-10-21 22:05:00", **extra):
    return {
        "device_id": coordinator.device_id,
        "measured_at": measured_at,
        "systolic": 131,
        "diastolic": 82,
        "pulse": 71,
        **extra,
    }


def local(*args) -> datetime:
    return datetime(*args, tzinfo=dt_util.get_default_time_zone())


async def test_add_reading(hass):
    events = async_capture_events(hass, EVENT_MEASUREMENT)
    _, coordinator = await async_setup_cuff(hass)
    await hass.services.async_call(DOMAIN, "add_reading", call(coordinator), blocking=True)
    [reading] = coordinator.store.imported()
    assert reading.measured_at == dt_util.as_utc(local(2026, 10, 21, 22, 5))
    assert (reading.systolic, reading.diastolic, reading.pulse) == (131, 82, 71)
    assert not reading.irregular_pulse and not reading.body_movement
    assert reading.manual
    assert len(events) == 1
    assert events[0].data["period"] == "evening"
    assert events[0].data["measured_at"].startswith("2026-10-21T22:05:00")


async def test_add_reading_joins_cuff_session(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, FakeCuff(readings=[
        StoredReading(datetime(2026, 10, 21, 22, 30, 12), 118, 76, 68),
    ]))
    await hass.services.async_call(
        DOMAIN, "add_reading",
        call(coordinator, "2026-10-21 22:24:00", systolic=124, diastolic=80), blocking=True,
    )
    [session] = coordinator.sessions()
    assert len(session.readings) == 2
    assert session.readings[0].manual and not session.readings[1].manual


async def test_add_reading_options(hass):
    _, coordinator = await async_setup_cuff(hass)
    await hass.services.async_call(
        DOMAIN, "add_reading",
        call(coordinator, irregular_pulse=True, body_movement=True), blocking=True,
    )
    [reading] = coordinator.store.imported()
    assert reading.irregular_pulse and reading.body_movement


async def test_add_reading_ignores_review_mode(hass):
    _, coordinator = await async_setup_cuff(hass, review=True)
    await hass.services.async_call(DOMAIN, "add_reading", call(coordinator), blocking=True)
    assert coordinator.store.find_by_time(local(2026, 10, 21, 22, 5)).status is (
        ReadingStatus.IMPORTED
    )


async def test_add_reading_existing_time(hass):
    _, coordinator = await async_setup_cuff(hass)
    await hass.services.async_call(DOMAIN, "add_reading", call(coordinator), blocking=True)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "add_reading", call(coordinator, systolic=140), blocking=True
        )
    assert err.value.translation_key == "reading_exists"


async def test_add_reading_after_delete(hass):
    _, coordinator = await async_setup_cuff(hass)
    await hass.services.async_call(DOMAIN, "add_reading", call(coordinator), blocking=True)
    await hass.services.async_call(
        DOMAIN, "delete_reading",
        {"device_id": coordinator.device_id, "measured_at": "2026-10-21 22:05:00"}, blocking=True,
    )
    await hass.services.async_call(DOMAIN, "add_reading", call(coordinator), blocking=True)
    assert len(coordinator.store.imported()) == 1


async def test_add_reading_in_future(hass):
    _, coordinator = await async_setup_cuff(hass)
    later = dt_util.as_local(dt_util.utcnow()).replace(tzinfo=None, microsecond=0)
    later = later.replace(year=later.year + 1)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "add_reading", call(coordinator, later.isoformat(" ")), blocking=True
        )
    assert err.value.translation_key == "reading_in_future"


async def test_add_reading_systolic_not_above_diastolic(hass):
    _, coordinator = await async_setup_cuff(hass)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "add_reading", call(coordinator, systolic=80, diastolic=80), blocking=True
        )
    assert err.value.translation_key == "invalid_reading"


async def test_add_reading_out_of_range(hass):
    _, coordinator = await async_setup_cuff(hass)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "add_reading", call(coordinator, pulse=0), blocking=True
        )


async def test_manual_survives_reload(hass):
    _, coordinator = await async_setup_cuff(hass)
    await hass.services.async_call(DOMAIN, "add_reading", call(coordinator), blocking=True)
    store = CuffStore(hass, ADDRESS)
    await store.async_load()
    [reading] = store.imported()
    assert reading.manual
