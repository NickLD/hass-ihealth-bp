"""The measurement routine option: off leaves only the base reading entities."""

from __future__ import annotations

from datetime import datetime

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.ihealth_bp.const import CONF_MEASUREMENT_ROUTINE, DOMAIN, EVENT_MEASUREMENT
from ..kn550bt.fake_cuff import FakeCuff, StoredReading

from .helpers import async_setup_cuff, async_sync

P = "kn_550bt"
ROUTINE_ENTITIES = (
    f"sensor.{P}_baseline_systolic_7_days",
    f"sensor.{P}_morning_slot",
    f"sensor.{P}_routine_slots_filled_7_days",
    f"switch.{P}_had_caffeine",
    f"text.{P}_session_note",
    f"button.{P}_discard_latest_session",
)
BASE_ENTITIES = (
    f"sensor.{P}_systolic",
    f"sensor.{P}_measured_at",
    f"binary_sensor.{P}_irregular_pulse",
    f"switch.{P}_backlight",
    f"todo.{P}_readings",
)


def routine_entities(hass, entry) -> list[str]:
    registry = er.async_get(hass)
    return [
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.entity_id in ROUTINE_ENTITIES
    ]


async def test_routine_entities_by_default(hass):
    entry, _ = await async_setup_cuff(hass)
    assert sorted(routine_entities(hass, entry)) == sorted(ROUTINE_ENTITIES)


async def test_routine_off_creates_only_base_entities(hass):
    entry, _ = await async_setup_cuff(hass, routine=False)
    assert routine_entities(hass, entry) == []
    for entity_id in ROUTINE_ENTITIES:
        assert hass.states.get(entity_id) is None
    for entity_id in BASE_ENTITIES:
        assert hass.states.get(entity_id) is not None


async def test_turning_routine_off_removes_its_entities(hass):
    entry, _ = await async_setup_cuff(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_MEASUREMENT_ROUTINE: False}
    )
    await hass.async_block_till_done()
    assert routine_entities(hass, entry) == []
    for entity_id in BASE_ENTITIES:
        assert hass.states.get(entity_id) is not None


async def test_routine_off_still_imports(hass):
    events = async_capture_events(hass, EVENT_MEASUREMENT)
    _, coordinator = await async_setup_cuff(hass, routine=False)
    await async_sync(hass, coordinator, FakeCuff(readings=[
        StoredReading(datetime(2026, 10, 21, 9, 50), 120, 80, 70),
    ]))
    assert hass.states.get(f"sensor.{P}_systolic").state == "120"
    assert len(events) == 1
    assert hass.services.has_service(DOMAIN, "add_reading")
