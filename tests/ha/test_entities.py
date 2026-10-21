"""Sensors, binary sensors, switches and diagnostics."""

from datetime import datetime, timedelta

from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON

from custom_components.ihealth_bp.diagnostics import async_get_config_entry_diagnostics
from custom_components.ihealth_bp.kn550bt.session import DisplaySettings

from ..kn550bt.fake_cuff import FakeCuff, StoredReading
from .helpers import async_setup_cuff, async_sync

T0 = datetime(2026, 10, 21, 14, 52, 31)
P = "kn_550bt"


def cuff_with_two() -> FakeCuff:
    return FakeCuff(readings=[
        StoredReading(T0, 125, 64, 69),
        StoredReading(T0 + timedelta(minutes=16, seconds=31), 121, 71, 68, arrhythmia=True),
    ])


def state(hass, entity_id):
    return hass.states.get(entity_id)


async def test_sensors_after_sync(hass):
    _, coordinator = await async_setup_cuff(hass)
    assert state(hass, f"sensor.{P}_systolic").state == "unknown"
    await async_sync(hass, coordinator, cuff_with_two())
    assert state(hass, f"sensor.{P}_systolic").state == "121"
    assert state(hass, f"sensor.{P}_diastolic").state == "71"
    assert state(hass, f"sensor.{P}_pulse").state == "68"
    assert state(hass, f"sensor.{P}_pulse_pressure").state == "50"
    assert state(hass, f"sensor.{P}_mean_arterial_pressure").state == "87.7"
    assert state(hass, f"sensor.{P}_blood_pressure_category").state == "elevated"
    assert state(hass, f"sensor.{P}_measured_at").state == "2026-10-21T20:09:02+00:00"
    assert state(hass, f"sensor.{P}_battery").state == "100"
    assert state(hass, f"binary_sensor.{P}_irregular_pulse").state == STATE_ON
    assert state(hass, f"binary_sensor.{P}_body_movement").state == STATE_OFF
    assert state(hass, f"sensor.{P}_last_sync").state != "unknown"
    assert state(hass, f"sensor.{P}_protocol").state == "com.jiuan.dev (BPAV21)"
    assert state(hass, f"sensor.{P}_systolic").attributes["unit_of_measurement"] == "mmHg"


async def test_measurement_sensors_have_no_state_class(hass):
    await async_setup_cuff(hass)
    for key in ("systolic", "diastolic", "pulse", "pulse_pressure", "mean_arterial_pressure"):
        assert "state_class" not in state(hass, f"sensor.{P}_{key}").attributes, key
    assert state(hass, f"sensor.{P}_battery").attributes["state_class"] == "measurement"


async def test_values_restore_after_restart(hass):
    entry, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, cuff_with_two())
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, f"sensor.{P}_systolic").state == "121"
    assert state(hass, f"sensor.{P}_battery").state == "100"


async def test_last_failure_sensor_reports_stage(hass):
    _, coordinator = await async_setup_cuff(hass)
    cuff = cuff_with_two()
    cuff.disconnect_on = {0x40}
    await async_sync(hass, coordinator, cuff)
    failure = state(hass, f"sensor.{P}_last_failure")
    assert failure.state != "unknown"
    assert failure.attributes["stage"] == "readings"


async def test_switch_toggle_sets_pending_then_reflects_device_after_sync(hass):
    _, coordinator = await async_setup_cuff(hass)
    cuff = FakeCuff(display_mask=0x03)
    await async_sync(hass, coordinator, cuff)
    switch = f"switch.{P}_backlight"
    assert state(hass, switch).state == STATE_ON
    await hass.services.async_call("switch", "turn_off", {ATTR_ENTITY_ID: switch}, blocking=True)
    assert state(hass, switch).state == STATE_OFF
    assert state(hass, switch).attributes["pending"] is True
    assert coordinator.store.pending_display == DisplaySettings(backlight=False, clock=True)
    await async_sync(hass, coordinator, cuff)
    assert cuff.display_mask == 0x02
    assert state(hass, switch).state == STATE_OFF
    assert state(hass, switch).attributes["pending"] is False
    assert state(hass, f"switch.{P}_clock_display").state == STATE_ON


async def test_display_change_from_app_shows_after_sync(hass):
    _, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, FakeCuff(display_mask=0x01))
    assert state(hass, f"switch.{P}_backlight").state == STATE_ON
    assert state(hass, f"switch.{P}_clock_display").state == STATE_OFF


async def test_protocol_sensor_untested_attribute_for_legacy(hass):
    await async_setup_cuff(hass, variant="com.jiuan.BPAV21")
    protocol = state(hass, f"sensor.{P}_protocol")
    assert protocol.state == "com.jiuan.BPAV21"
    assert protocol.attributes["untested"] is True


async def test_diagnostics_redacts_address(hass):
    entry, coordinator = await async_setup_cuff(hass)
    await async_sync(hass, coordinator, cuff_with_two())
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    assert "00:4D:32:65:0E:89" not in text and "004D32650E89" not in text
    assert diag["readings"]["imported"] == 2
    assert len(diag["recent_readings"]) == 2
    assert diag["variant"] == "com.jiuan.dev"
