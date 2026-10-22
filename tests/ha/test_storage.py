"""Reading log persistence, de-duplication and time handling."""

from datetime import UTC, datetime

from homeassistant.util import dt as dt_util

from custom_components.ihealth_bp.kn550bt.protocol import Reading
from custom_components.ihealth_bp.storage import CuffStore, ReadingStatus, reading_uid

R1 = Reading(datetime(2026, 10, 21, 14, 52, 31), 125, 64, 69, arrhythmia=False, body_movement=False)
R2 = Reading(datetime(2026, 10, 21, 15, 9, 2), 121, 71, 68, arrhythmia=True, body_movement=False)


async def new_store(hass) -> CuffStore:
    store = CuffStore(hass, "entry1")
    await store.async_load()
    return store


def test_reading_uid():
    assert reading_uid(R1) == "20261021145231-125-64-69"


async def test_add_returns_new_oldest_first_and_converts_time(hass):
    await hass.config.async_set_time_zone("America/Chicago")
    store = await new_store(hass)
    added = await store.async_add([R2, R1], review=False)
    assert [r.uid for r in added] == [reading_uid(R1), reading_uid(R2)]
    assert added[0].measured_at == datetime(2026, 10, 21, 19, 52, 31, tzinfo=UTC)
    assert added[1].irregular_pulse is True
    assert all(r.status is ReadingStatus.IMPORTED for r in added)


async def test_add_dedupes_including_deleted(hass):
    store = await new_store(hass)
    await store.async_add([R1], review=False)
    await store.async_set_status(reading_uid(R1), ReadingStatus.DELETED)
    assert await store.async_add([R1, R2], review=False) == [store.find(reading_uid(R2))]


async def test_review_mode_adds_pending(hass):
    store = await new_store(hass)
    (added,) = await store.async_add([R1], review=True)
    assert added.status is ReadingStatus.PENDING


async def test_latest_imported_ignores_pending_and_deleted(hass):
    store = await new_store(hass)
    await store.async_add([R1], review=False)
    await store.async_add([R2], review=True)
    assert store.latest_imported().uid == reading_uid(R1)
    await store.async_set_status(reading_uid(R1), ReadingStatus.DELETED)
    assert store.latest_imported() is None
    assert [r.uid for r in store.visible()] == [reading_uid(R2)]


async def test_store_round_trip_after_reload(hass):
    store = await new_store(hass)
    await store.async_add([R1, R2], review=False)
    await store.async_set_pending_display("backlight", False)
    reloaded = await new_store(hass)
    assert [r.uid for r in reloaded.visible()] == [reading_uid(R2), reading_uid(R1)]
    assert reloaded.pending_display == {"backlight": False}
    assert reloaded.find_by_time(store.find(reading_uid(R1)).measured_at).uid == reading_uid(R1)


async def test_dst_ambiguous_time_round_trip(hass):
    await hass.config.async_set_time_zone("America/Chicago")
    store = await new_store(hass)
    ambiguous = Reading(datetime(2026, 11, 1, 1, 30, 0), 120, 80, 60, False, False)
    (added,) = await store.async_add([ambiguous], review=False)
    assert added.measured_at.tzinfo is not None
    # 01:30 happens twice that night; the first (CDT, UTC-5) occurrence is used (fold=0).
    assert added.measured_at == datetime(2026, 11, 1, 6, 30, 0, tzinfo=UTC)
    assert dt_util.as_local(added.measured_at).replace(tzinfo=None) == ambiguous.time
    reloaded = await new_store(hass)
    assert reloaded.find(added.uid).measured_at == added.measured_at


async def test_clearing_pending_keeps_newer_changes(hass):
    store = await new_store(hass)
    await store.async_set_pending_display("backlight", False)
    applied = dict(store.pending_display)
    await store.async_set_pending_display("backlight", True)  # changed while applying
    await store.async_set_pending_display("clock", False)
    await store.async_clear_pending_display(applied)
    assert store.pending_display == {"backlight": True, "clock": False}
