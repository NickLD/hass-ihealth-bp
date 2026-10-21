"""Readings list, deleting readings and review mode."""

from datetime import datetime, timedelta

import pytest
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.ihealth_bp.const import DOMAIN, EVENT_MEASUREMENT
from custom_components.ihealth_bp.storage import ReadingStatus

from ..kn550bt.fake_cuff import FakeCuff, StoredReading
from .helpers import async_setup_cuff, async_sync

T0 = datetime(2026, 10, 21, 14, 52, 31)
TODO = "todo.kn_550bt_readings"
LATEST = "Oct 21 15:09 — 121/71, pulse 68"
OLDEST = "Oct 21 14:52 — 125/64, pulse 69"


def cuff_with_two() -> FakeCuff:
    return FakeCuff(readings=[
        StoredReading(T0, 125, 64, 69),
        StoredReading(T0 + timedelta(minutes=16, seconds=31), 121, 71, 68, arrhythmia=True),
    ])


async def items(hass) -> list[dict]:
    result = await hass.services.async_call(
        "todo", "get_items", {ATTR_ENTITY_ID: TODO}, blocking=True, return_response=True
    )
    return result[TODO]["items"]


async def test_todo_lists_readings_newest_first_completed(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, cuff_with_two())
    listed = await items(hass)
    assert [i["summary"] for i in listed] == [LATEST, OLDEST]
    assert {i["status"] for i in listed} == {"completed"}
    assert listed[0]["description"] == "Irregular pulse"
    assert hass.states.get(TODO).state == "0"


async def test_delete_latest_rolls_sensors_back(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, cuff_with_two())
    await hass.services.async_call(
        "todo", "remove_item", {ATTR_ENTITY_ID: TODO, "item": LATEST}, blocking=True
    )
    assert [i["summary"] for i in await items(hass)] == [OLDEST]
    assert hass.states.get("sensor.kn_550bt_systolic").state == "125"
    assert hass.states.get("binary_sensor.kn_550bt_irregular_pulse").state == "off"
    assert coordinator.store.latest_imported().systolic == 125


async def test_deleted_reading_does_not_return_on_next_sync(hass):
    _, coordinator = await async_setup_cuff(hass, delete=False)
    cuff = cuff_with_two()
    await async_sync(hass, coordinator, cuff)
    await hass.services.async_call(
        "todo", "remove_item", {ATTR_ENTITY_ID: TODO, "item": LATEST}, blocking=True
    )
    await async_sync(hass, coordinator, cuff)
    assert [i["summary"] for i in await items(hass)] == [OLDEST]


async def test_delete_action_by_time(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, cuff_with_two())
    await hass.services.async_call(
        DOMAIN, "delete_reading",
        {"device_id": coordinator.device_id, "measured_at": "2026-10-21 14:52:31"},
        blocking=True,
    )
    assert [i["summary"] for i in await items(hass)] == [LATEST]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "delete_reading",
            {"device_id": coordinator.device_id, "measured_at": "2026-10-21 14:52:31"},
            blocking=True,
        )


async def test_review_mode_pending_then_approve_fires_event(hass):
    _, coordinator = await async_setup_cuff(hass, review=True)
    events = async_capture_events(hass, EVENT_MEASUREMENT)
    await async_sync(hass, coordinator, cuff_with_two())
    assert hass.states.get(TODO).state == "2"
    assert hass.states.get("sensor.kn_550bt_systolic").state == "unknown"
    await hass.services.async_call(
        "todo", "update_item", {ATTR_ENTITY_ID: TODO, "item": OLDEST, "status": "completed"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert [e.data["systolic"] for e in events] == [125]
    assert hass.states.get("sensor.kn_550bt_systolic").state == "125"
    assert hass.states.get(TODO).state == "1"


async def test_review_mode_delete_pending_never_imports(hass):
    _, coordinator = await async_setup_cuff(hass, review=True)
    events = async_capture_events(hass, EVENT_MEASUREMENT)
    await async_sync(hass, coordinator, cuff_with_two())
    await hass.services.async_call(
        "todo", "remove_item", {ATTR_ENTITY_ID: TODO, "item": [LATEST, OLDEST]}, blocking=True
    )
    assert events == []
    assert await items(hass) == []
    assert {r.status for r in coordinator.store._readings.values()} == {ReadingStatus.DELETED}


async def test_cannot_create_or_rename_items(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, cuff_with_two())
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "todo", "add_item", {ATTR_ENTITY_ID: TODO, "item": "new"}, blocking=True
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "todo", "update_item", {ATTR_ENTITY_ID: TODO, "item": LATEST, "rename": "x"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "todo", "update_item",
            {ATTR_ENTITY_ID: TODO, "item": LATEST, "status": "needs_action"}, blocking=True,
        )
