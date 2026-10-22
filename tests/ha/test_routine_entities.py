"""Routine sensors, session flag switches, note and discard button."""

from datetime import datetime, timedelta

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.ihealth_bp.diagnostics import async_get_config_entry_diagnostics

from ..kn550bt.fake_cuff import FakeCuff, StoredReading
from .helpers import async_setup_cuff, async_sync

P = "kn_550bt"
# 10:00 on 2026-10-21 in America/Chicago (UTC-5)
NOW = datetime(2026, 10, 21, 15, 0, 0, tzinfo=dt_util.UTC)


def morning_cuff() -> FakeCuff:
    return FakeCuff(readings=[
        StoredReading(datetime(2026, 10, 21, 9, 50), 120, 80, 70),
        StoredReading(datetime(2026, 10, 21, 9, 51), 124, 82, 72),
    ])


def state(hass, entity_id):
    return hass.states.get(entity_id)


async def setup_synced(hass, freezer):
    freezer.move_to(NOW)
    entry, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, morning_cuff())
    return entry, coordinator


async def test_routine_sensors_after_sync(hass, freezer):
    await setup_synced(hass, freezer)
    assert state(hass, f"sensor.{P}_baseline_systolic_7_days").state == "122.0"
    assert state(hass, f"sensor.{P}_baseline_diastolic_7_days").state == "81.0"
    assert state(hass, f"sensor.{P}_baseline_systolic_7_days").attributes["unit_of_measurement"] == "mmHg"
    assert state(hass, f"sensor.{P}_baseline_category_7_days").state == "hypertension_stage_1"
    assert state(hass, f"sensor.{P}_routine_slots_filled_7_days").state == "1"
    assert state(hass, f"sensor.{P}_irregular_pulse_readings_7_days").state == "0"
    assert state(hass, f"sensor.{P}_morning_systolic_7_days").state == "122.0"
    assert state(hass, f"sensor.{P}_evening_systolic_7_days").state == "unknown"
    morning = state(hass, f"sensor.{P}_morning_slot")
    assert morning.state == "filled"
    assert morning.attributes["reading_count"] == 2
    assert morning.attributes["mean_systolic"] == 122.0
    assert morning.attributes["first_reading_at"].startswith("2026-10-21T09:50:00")
    assert "window_start" in morning.attributes and "window_end" in morning.attributes
    assert state(hass, f"sensor.{P}_evening_slot").state == "upcoming"
    for key in ("baseline_systolic_7_days", "routine_slots_filled_7_days"):
        assert "state_class" not in state(hass, f"sensor.{P}_{key}").attributes


async def test_flag_switch_excludes_from_baseline(hass, freezer):
    _, coordinator = await setup_synced(hass, freezer)
    assert state(hass, f"switch.{P}_had_caffeine").state == "off"
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": f"switch.{P}_had_caffeine"}, blocking=True
    )
    assert all(r.flags == ("caffeine",) for r in coordinator.store.imported())
    assert state(hass, f"switch.{P}_had_caffeine").state == "on"
    assert state(hass, f"sensor.{P}_baseline_systolic_7_days").state == "unknown"
    assert state(hass, f"sensor.{P}_baseline_category_7_days").state == "unknown"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": f"switch.{P}_had_caffeine"}, blocking=True
    )
    assert state(hass, f"switch.{P}_had_caffeine").state == "off"
    assert state(hass, f"sensor.{P}_baseline_systolic_7_days").state == "122.0"


async def test_flag_switch_unknown_without_session(hass, freezer):
    freezer.move_to(NOW)
    await async_setup_cuff(hass)
    assert state(hass, f"switch.{P}_sick").state == "unknown"
    assert state(hass, f"text.{P}_session_note").state == ""


async def test_session_note_roundtrip(hass, freezer):
    _, coordinator = await setup_synced(hass, freezer)
    entity = f"text.{P}_session_note"
    await hass.services.async_call(
        "text", "set_value", {"entity_id": entity, "value": "walked upstairs"}, blocking=True
    )
    assert all(r.note == "walked upstairs" for r in coordinator.store.imported())
    assert state(hass, entity).state == "walked upstairs"
    await hass.services.async_call(
        "text", "set_value", {"entity_id": entity, "value": ""}, blocking=True
    )
    assert all(r.note is None for r in coordinator.store.imported())
    assert state(hass, entity).state == ""


async def test_discard_button(hass, freezer):
    _, coordinator = await setup_synced(hass, freezer)
    button = {"entity_id": f"button.{P}_discard_latest_session"}
    await hass.services.async_call("button", "press", button, blocking=True)
    assert not list(coordinator.store.imported())
    assert state(hass, f"sensor.{P}_morning_slot").state == "open"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("button", "press", button, blocking=True)


async def test_deleting_only_reading_reopens_slot(hass, freezer):
    freezer.move_to(NOW)
    _, coordinator = await async_setup_cuff(hass)
    cuff = FakeCuff(readings=[StoredReading(datetime(2026, 10, 21, 9, 50), 120, 80, 70)])
    await async_sync(hass, coordinator, cuff)
    assert state(hass, f"sensor.{P}_morning_slot").state == "filled"
    uid = coordinator.store.imported()[0].uid
    await hass.services.async_call(
        "todo", "remove_item", {"entity_id": f"todo.{P}_readings", "item": [uid]}, blocking=True
    )
    assert state(hass, f"sensor.{P}_morning_slot").state == "open"
    assert state(hass, f"sensor.{P}_baseline_systolic_7_days").state == "unknown"


async def test_slot_sensor_refreshes_at_boundary(hass, freezer):
    freezer.move_to(datetime(2026, 10, 21, 9, 59, 59, tzinfo=dt_util.UTC))  # 04:59:59 local
    await async_setup_cuff(hass)
    assert state(hass, f"sensor.{P}_morning_slot").state == "closed"
    freezer.move_to(datetime(2026, 10, 21, 10, 0, 0, tzinfo=dt_util.UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert state(hass, f"sensor.{P}_morning_slot").state == "open"


async def test_diagnostics_has_no_context(hass, freezer):
    entry, _ = await setup_synced(hass, freezer)
    await hass.services.async_call(
        "text", "set_value",
        {"entity_id": f"text.{P}_session_note", "value": "secret note"}, blocking=True,
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": f"switch.{P}_missed_meds"}, blocking=True
    )
    dump = str(await async_get_config_entry_diagnostics(hass, entry))
    assert "secret note" not in dump
    assert "missed_meds" not in dump
