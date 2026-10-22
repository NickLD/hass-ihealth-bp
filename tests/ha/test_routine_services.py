"""Context and session actions, and session info in the measurement event."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.ihealth_bp.const import DOMAIN, EVENT_MEASUREMENT
from ..kn550bt.fake_cuff import FakeCuff, StoredReading

from .helpers import async_setup_cuff, async_sync


def dt(day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, second)


def two_readings() -> FakeCuff:
    return FakeCuff(readings=[
        StoredReading(dt(21, 9, 50), 130, 80, 70),
        StoredReading(dt(21, 9, 51, 10), 120, 76, 66),
    ])


def call(coordinator, minute=51, second=10, **extra):
    return {
        "device_id": coordinator.device_id,
        "measured_at": f"2026-10-21 09:{minute:02d}:{second:02d}",
        **extra,
    }


async def test_event_includes_session_fields(hass):
    events = async_capture_events(hass, EVENT_MEASUREMENT)
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, two_readings())
    assert len(events) == 2
    second = events[1].data
    assert second["session_index"] == 2
    assert second["period"] == "morning"
    assert second["session_mean_systolic"] == 125.0
    assert second["session_mean_diastolic"] == 78.0
    assert len(second["session_measured_at"]) == 2
    assert second["session_start"].startswith("2026-10-21T09:50:00")
    assert second["bp_category"] == "elevated"
    assert second["uid"]


async def test_backlog_events_have_correct_sessions(hass):
    events = async_capture_events(hass, EVENT_MEASUREMENT)
    _, coordinator = await async_setup_cuff(hass)
    cuff = FakeCuff(readings=[
        StoredReading(dt(19, 9, 50), 130, 80, 70),
        StoredReading(dt(19, 22, 30), 128, 80, 70),
        StoredReading(dt(20, 9, 50), 126, 78, 68),
        StoredReading(dt(20, 9, 51), 124, 76, 66),
    ])
    await async_sync(hass, coordinator, cuff)
    assert [e.data["period"] for e in events] == ["morning", "evening", "morning", "morning"]
    assert [e.data["session_index"] for e in events] == [1, 1, 1, 2]
    now = datetime(2026, 10, 20, 13, 0, tzinfo=dt_util.get_default_time_zone())
    assert coordinator.routine_summary(now=now).slots_filled_7d == 3


async def test_set_reading_context_session(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, two_readings())
    await hass.services.async_call(
        DOMAIN, "set_reading_context",
        call(coordinator, session=True, add_flags=["caffeine"], note="x"), blocking=True,
    )
    readings = coordinator.store.imported()
    assert len(readings) == 2
    assert all(r.flags == ("caffeine",) and r.note == "x" for r in readings)


async def test_set_reading_context_single_reading(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, two_readings())
    await hass.services.async_call(
        DOMAIN, "set_reading_context", call(coordinator, add_flags=["ate"]), blocking=True
    )
    flagged = [r for r in coordinator.store.imported() if r.flags]
    assert len(flagged) == 1 and flagged[0].flags == ("ate",)


async def test_set_reading_context_requires_something(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, two_readings())
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "set_reading_context", call(coordinator), blocking=True
        )
    assert err.value.translation_key == "nothing_to_set"


async def test_set_reading_context_rejects_unknown_flag(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, two_readings())
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "set_reading_context", call(coordinator, flags=["coffee"]), blocking=True
        )


async def test_set_reading_context_unknown_time(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, two_readings())
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "set_reading_context", call(coordinator, minute=3, note="x"), blocking=True
        )
    assert err.value.translation_key == "reading_not_found"


async def test_delete_session(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, FakeCuff(readings=[
        StoredReading(dt(20, 9, 50), 140, 90, 80),
        StoredReading(dt(21, 9, 50), 130, 80, 70),
        StoredReading(dt(21, 9, 51, 10), 120, 76, 66),
    ]))
    assert hass.states.get("sensor.kn_550bt_systolic").state == "120"
    with patch.object(
        coordinator, "async_refresh_statistics", wraps=coordinator.async_refresh_statistics
    ) as refresh:
        await hass.services.async_call(DOMAIN, "delete_session", call(coordinator), blocking=True)
    await hass.async_block_till_done()
    refresh.assert_called_once()
    assert len(refresh.call_args.args[0]) == 2  # one refresh, both readings
    assert len(coordinator.store.imported()) == 1
    assert hass.states.get("sensor.kn_550bt_systolic").state == "140"
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "delete_session", call(coordinator), blocking=True)
    assert err.value.translation_key == "reading_not_found"


async def test_delete_session_refreshes_all_hours(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, FakeCuff(readings=[
        StoredReading(dt(21, 9, 55), 130, 80, 70),
        StoredReading(dt(21, 10, 3), 120, 76, 66),
    ]))
    with patch.object(
        coordinator, "async_refresh_statistics", wraps=coordinator.async_refresh_statistics
    ) as refresh:
        await hass.services.async_call(
            DOMAIN, "delete_session", call(coordinator, minute=55, second=0), blocking=True
        )
    refresh.assert_called_once()
    assert len(refresh.call_args.args[0]) == 2


async def test_concurrent_delete_session(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, two_readings())
    original_save = coordinator.store._async_save

    async def yielding_save(*args, **kwargs):
        await asyncio.sleep(0)  # let the other call interleave, as a real disk write would
        return await original_save(*args, **kwargs)

    coordinator.store._async_save = yielding_save
    with patch.object(
        coordinator, "async_refresh_statistics", wraps=coordinator.async_refresh_statistics
    ) as refresh:
        results = await asyncio.gather(
            hass.services.async_call(DOMAIN, "delete_session", call(coordinator), blocking=True),
            hass.services.async_call(DOMAIN, "delete_session", call(coordinator), blocking=True),
            return_exceptions=True,
        )
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], ServiceValidationError)
    assert errors[0].translation_key == "reading_not_found"
    refresh.assert_called_once()
    assert coordinator.store.imported() == []
