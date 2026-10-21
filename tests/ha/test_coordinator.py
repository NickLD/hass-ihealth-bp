"""One sync per cuff wake: import, events, statistics, deletion and failure handling."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.components.bluetooth import async_get_advertisement_callback
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.ihealth_bp.const import DOMAIN, EVENT_MEASUREMENT
from custom_components.ihealth_bp.kn550bt.session import DisplaySettings
from custom_components.ihealth_bp.storage import ReadingStatus

from ..kn550bt.fake_cuff import FakeCuff, StoredReading
from .helpers import async_setup_cuff as setup
from .helpers import async_sync as sync
from .helpers import make_service_info

CONNECT = "custom_components.ihealth_bp.coordinator.async_connect"
T0 = datetime(2026, 10, 21, 14, 52, 31)


def cuff_with_two() -> FakeCuff:
    return FakeCuff(readings=[
        StoredReading(T0, 125, 64, 69),
        StoredReading(T0 + timedelta(minutes=16, seconds=31), 121, 71, 68, arrhythmia=True),
    ])


async def test_sync_imports_events_and_deletes(hass):
    entry, coordinator = await setup(hass)
    events = async_capture_events(hass, EVENT_MEASUREMENT)
    cuff = cuff_with_two()
    await sync(hass, coordinator, cuff)
    assert [(e.data["systolic"], e.data["diastolic"], e.data["pulse"]) for e in events] == [
        (125, 64, 69), (121, 71, 68)]
    assert events[0].data["measured_at"] == "2026-10-21T14:52:31-05:00"
    assert events[1].data["irregular_pulse"] is True
    assert events[0].data["device_id"] == coordinator.device_id
    assert cuff.readings == []
    assert cuff.clock is not None
    state = coordinator.state
    assert state.battery == 100 and state.last_sync is not None and state.last_failure is None
    assert state.info.firmware == "303"
    assert coordinator.store.latest_imported().systolic == 121


async def test_coexist_mode_does_not_delete_and_second_sync_adds_nothing(hass):
    _, coordinator = await setup(hass, delete=False)
    events = async_capture_events(hass, EVENT_MEASUREMENT)
    cuff = cuff_with_two()
    await sync(hass, coordinator, cuff)
    await sync(hass, coordinator, cuff)
    assert len(cuff.readings) == 2
    assert len(events) == 2


async def test_failure_on_delete_keeps_readings_and_next_sync_does_not_duplicate(hass):
    _, coordinator = await setup(hass)
    events = async_capture_events(hass, EVENT_MEASUREMENT)
    cuff = cuff_with_two()
    cuff.disconnect_on = {0x47}
    await sync(hass, coordinator, cuff)
    assert len(cuff.readings) == 2 and len(events) == 2
    assert coordinator.state.failure_stage == "delete"
    cuff.disconnect_on = set()
    cuff.is_connected = True
    await sync(hass, coordinator, cuff)
    assert cuff.readings == [] and len(events) == 2
    assert coordinator.state.last_sync is not None


async def test_failure_before_download_persists_nothing(hass):
    _, coordinator = await setup(hass)
    cuff = cuff_with_two()
    cuff.disconnect_on = {0x40}
    await sync(hass, coordinator, cuff)
    assert coordinator.store.visible() == []
    assert len(cuff.readings) == 2
    assert coordinator.state.failure_stage == "readings"
    assert coordinator.state.last_failure is not None


async def test_connect_failure_is_recorded(hass):
    _, coordinator = await setup(hass)
    with patch(CONNECT, side_effect=TimeoutError("no slot")):
        await coordinator.async_sync(make_service_info())
    assert coordinator.state.failure_stage == "connect"
    assert "no slot" in coordinator.state.failure_reason


async def test_review_mode_logs_pending_without_events_and_still_deletes(hass):
    _, coordinator = await setup(hass, review=True)
    events = async_capture_events(hass, EVENT_MEASUREMENT)
    cuff = cuff_with_two()
    await sync(hass, coordinator, cuff)
    assert events == []
    assert {r.status for r in coordinator.store.visible()} == {ReadingStatus.PENDING}
    assert cuff.readings == []


async def test_pending_display_applied_and_cleared(hass):
    _, coordinator = await setup(hass)
    await coordinator.async_request_display("backlight", False)
    assert coordinator.store.pending_display == {"backlight": False}
    cuff = FakeCuff()
    await sync(hass, coordinator, cuff)
    assert cuff.display_mask == 0x02
    assert coordinator.store.pending_display == {}
    assert coordinator.state.display == DisplaySettings(backlight=False, clock=True)


async def test_wrong_model_raises_repair_issue(hass):
    entry, coordinator = await setup(hass)
    cuff = FakeCuff(model=b"BG5S\x00")
    await sync(hass, coordinator, cuff)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"unsupported_device_{entry.entry_id}")
    assert issue is not None
    assert cuff.received == []  # never authenticated or asked for anything


@pytest.mark.parametrize(("age", "expected"), [(None, True), (5.0, False), (31.0, True)])
async def test_needs_poll_threshold(hass, age, expected):
    _, coordinator = await setup(hass)
    assert coordinator.needs_poll_for(make_service_info(), age) is expected


async def test_advertisement_triggers_sync(hass):
    _, coordinator = await setup(hass)
    cuff = cuff_with_two()
    with patch(CONNECT, return_value=cuff):
        async_get_advertisement_callback(hass)(make_service_info())
        await hass.async_block_till_done()
    assert coordinator.state.last_sync is not None
    assert cuff.readings == []


async def test_incomplete_download_keeps_cuff_readings(hass):
    _, coordinator = await setup(hass)
    stored = [StoredReading(T0 + timedelta(minutes=i), 120, 80, 60) for i in range(10)]
    cuff = FakeCuff(readings=list(stored), page_size=3, truncate_after_pages=2)
    await sync(hass, coordinator, cuff)
    assert len(coordinator.store.visible()) == 6  # what arrived is kept
    assert len(cuff.readings) == 10  # but nothing was deleted
    assert coordinator.state.failure_stage == "readings"
    assert "incomplete" in coordinator.state.failure_reason


async def test_reload_during_sync_does_not_lose_readings(hass):
    import asyncio

    from custom_components.ihealth_bp.storage import CuffStore

    entry, coordinator = await setup(hass)
    cuff = cuff_with_two()
    cuff.gate_cmd, cuff.gate, cuff.gate_reached = 0x40, asyncio.Event(), asyncio.Event()
    with patch(CONNECT, return_value=cuff):
        sync_task = hass.async_create_task(coordinator.async_sync(make_service_info()))
        await cuff.gate_reached.wait()
        reload_task = hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
        for _ in range(5):
            await asyncio.sleep(0)
        cuff.gate.set()
        await sync_task
        await reload_task
    await hass.async_block_till_done()
    new = entry.runtime_data
    assert new is not coordinator
    await new.async_request_display("backlight", False)  # forces the new store to save
    assert len(new.store.visible()) == 2
    reread = CuffStore(hass, entry.unique_id)
    await reread.async_load()
    assert len(reread.visible()) == 2
