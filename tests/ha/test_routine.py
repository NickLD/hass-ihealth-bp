"""Measurement periods, BP days and sessions."""

from datetime import date, datetime, time

from homeassistant.util import dt as dt_util

from custom_components.ihealth_bp.routine import (
    Mean,
    Period,
    SlotStatus,
    Windows,
    bp_day,
    group_sessions,
    period_of,
    summarize,
    windows_from_options,
)
from custom_components.ihealth_bp.storage import (
    LoggedReading,
    ReadingStatus,
    cuff_time_to_utc,
)

W = Windows()


def local(*args) -> datetime:
    return dt_util.as_local(cuff_time_to_utc(datetime(*args)))


def reading(local_naive, sys, dia, pulse=70, **kw) -> LoggedReading:
    fields = {
        "uid": f"{local_naive:%Y%m%d%H%M%S}-{sys}-{dia}-{pulse}",
        "measured_at": cuff_time_to_utc(local_naive),
        "systolic": sys,
        "diastolic": dia,
        "pulse": pulse,
        "irregular_pulse": False,
        "body_movement": False,
        "status": ReadingStatus.IMPORTED,
    }
    fields.update(kw)
    return LoggedReading(**fields)


async def test_period_of_defaults(hass):
    await hass.config.async_set_time_zone("America/Chicago")
    cases = [
        ((2026, 10, 21, 5, 0), Period.MORNING),
        ((2026, 10, 21, 12, 29, 59), Period.MORNING),
        ((2026, 10, 21, 12, 30), Period.EXTRA),
        ((2026, 10, 21, 20, 59), Period.EXTRA),
        ((2026, 10, 21, 21, 0), Period.EVENING),
        ((2026, 10, 22, 0, 30), Period.EVENING),
        ((2026, 10, 22, 2, 59, 59), Period.EVENING),
        ((2026, 10, 22, 3, 0), Period.EXTRA),
        ((2026, 10, 22, 4, 59), Period.EXTRA),
    ]
    for args, expected in cases:
        assert period_of(local(*args), W) is expected, args


async def test_bp_day_shifts_at_morning_start(hass):
    await hass.config.async_set_time_zone("America/Chicago")
    assert bp_day(local(2026, 10, 22, 0, 30), W) == date(2026, 10, 21)
    assert bp_day(local(2026, 10, 22, 5, 0), W) == date(2026, 10, 22)


def test_windows_valid():
    assert W.valid()
    assert not Windows(morning_end=time(4)).valid()
    assert not Windows(evening_start=time(12)).valid()
    assert not Windows(evening_end=time(6)).valid()
    assert Windows(evening_start=time(18), evening_end=time(23)).valid()


async def test_slot_bounds(hass):
    await hass.config.async_set_time_zone("America/Chicago")
    assert W.slot_bounds(date(2026, 10, 21), Period.EVENING) == (
        local(2026, 10, 21, 21, 0),
        local(2026, 10, 22, 3, 0),
    )
    assert W.slot_bounds(date(2026, 10, 21), Period.MORNING) == (
        local(2026, 10, 21, 5, 0),
        local(2026, 10, 21, 12, 30),
    )


def test_windows_from_options():
    assert windows_from_options({"morning_end": "11:00:00"}) == Windows(morning_end=time(11))
    assert windows_from_options({}) == Windows()


async def test_group_sessions_chains_within_10_min(hass):
    await hass.config.async_set_time_zone("America/Chicago")
    r1 = reading(datetime(2026, 10, 21, 9, 50, 0), 120, 80, 60)
    r2 = reading(datetime(2026, 10, 21, 9, 51, 10), 124, 82, 64)
    r3 = reading(datetime(2026, 10, 21, 9, 59, 0), 122, 78, 62)
    r4 = reading(datetime(2026, 10, 21, 10, 12, 0), 118, 76)
    sessions = group_sessions([r4, r2, r1, r3], W)
    assert [len(s.readings) for s in sessions] == [3, 1]
    first = sessions[0]
    assert first.period is Period.MORNING
    assert first.day == date(2026, 10, 21)
    assert first.start == r1.measured_at
    assert first.index_of(r3.uid) == 3
    assert first.mean_systolic == 122.0
    assert first.mean_diastolic == 80.0
    assert first.mean_pulse == 62.0
    assert first.measured_at == [r1.measured_at, r2.measured_at, r3.measured_at]


async def test_session_period_from_first_reading(hass):
    await hass.config.async_set_time_zone("America/Chicago")
    a = reading(datetime(2026, 10, 21, 12, 25), 120, 80)
    b = reading(datetime(2026, 10, 21, 12, 31), 121, 81)
    (session,) = group_sessions([a, b], W)
    assert session.period is Period.MORNING


START = date(2026, 10, 1)
NOW = (2026, 10, 21, 14, 0)


async def _tz(hass):
    await hass.config.async_set_time_zone("America/Chicago")


async def test_baseline_mean_of_slot_means(hass):
    await _tz(hass)
    rs = [
        reading(datetime(2026, 10, 20, 7, 0), 130, 85),
        reading(datetime(2026, 10, 20, 7, 3), 126, 81),
        reading(datetime(2026, 10, 20, 21, 30), 120, 80),
        reading(datetime(2026, 10, 21, 7, 0), 124, 80),
    ]
    s = summarize(rs, W, START, local(*NOW))
    assert s.baseline_7d == Mean(124.0, 81.0)
    assert s.morning_7d == Mean(126.0, 81.5)
    assert s.evening_7d == Mean(120.0, 80.0)
    assert s.slots_filled_7d == 3


async def test_baseline_excludes_unclean(hass):
    await _tz(hass)
    good = reading(datetime(2026, 10, 21, 7, 0), 120, 80)
    bad = [
        reading(datetime(2026, 10, 20, 7, 0), 200, 100, flags=("caffeine",)),
        reading(datetime(2026, 10, 19, 7, 0), 200, 100, body_movement=True),
        reading(datetime(2026, 10, 18, 15, 0), 200, 100),
        reading(datetime(2026, 9, 30, 7, 0), 200, 100),
    ]
    assert summarize([good, *bad], W, START, local(*NOW)).baseline_7d == Mean(120.0, 80.0)
    mixed = [
        reading(datetime(2026, 10, 21, 7, 0), 200, 100, body_movement=True),
        reading(datetime(2026, 10, 21, 7, 2), 110, 70),
    ]
    assert summarize(mixed, W, START, local(*NOW)).baseline_7d == Mean(110.0, 70.0)


async def test_baseline_none_without_clean_readings(hass):
    await _tz(hass)
    rs = [reading(datetime(2026, 10, 21, 7, 0), 130, 85, flags=("ate",))]
    s = summarize(rs, W, START, local(*NOW))
    assert s.baseline_7d is None
    assert s.slots_filled_7d == 1


async def test_7_day_window_edges(hass):
    await _tz(hass)
    now = local(*NOW)
    six = reading(datetime(2026, 10, 15, 7, 0), 120, 80)
    seven = reading(datetime(2026, 10, 14, 7, 0), 140, 90)
    s = summarize([six, seven], W, START, now)
    assert s.baseline_7d == Mean(120.0, 80.0)
    assert s.baseline_30d == Mean(130.0, 85.0)
    assert s.slots_filled_7d == 1
    old = reading(datetime(2026, 9, 22, 7, 0), 100, 60)
    s = summarize([old], W, date(2026, 9, 1), now)
    assert s.baseline_30d == Mean(100.0, 60.0)
    assert s.baseline_7d is None


async def test_irregular_pulse_7d_counts_all_periods(hass):
    await _tz(hass)
    rs = [
        reading(datetime(2026, 10, 21, 7, 0), 120, 80, irregular_pulse=True),
        reading(datetime(2026, 10, 20, 15, 0), 120, 80, irregular_pulse=True),
        reading(datetime(2026, 10, 10, 7, 0), 120, 80, irregular_pulse=True),
    ]
    assert summarize(rs, W, START, local(*NOW)).irregular_pulse_7d == 2


async def test_slot_status_progression(hass):
    await _tz(hass)
    s = summarize([], W, START, local(2026, 10, 21, 2, 0))
    assert (s.morning.status, s.evening.status) == (SlotStatus.CLOSED, SlotStatus.OPEN)
    s = summarize([], W, START, local(2026, 10, 21, 4, 0))
    assert (s.morning.status, s.evening.status) == (SlotStatus.CLOSED, SlotStatus.CLOSED)
    s = summarize([], W, START, local(2026, 10, 21, 6, 0))
    assert (s.morning.status, s.evening.status) == (SlotStatus.OPEN, SlotStatus.UPCOMING)
    s = summarize([], W, START, local(2026, 10, 21, 13, 0))
    assert s.morning.status is SlotStatus.CLOSED
    assert s.morning.mean is None and s.morning.reading_count == 0
    s = summarize(
        [reading(datetime(2026, 10, 21, 9, 50), 120, 80)], W, START, local(2026, 10, 21, 13, 0)
    )
    assert s.morning.status is SlotStatus.FILLED
    assert s.morning.first_reading_at == local(2026, 10, 21, 9, 50)
    assert s.morning.reading_count == 1
    assert s.morning.mean == Mean(120.0, 80.0)


async def test_after_midnight_reading_fills_previous_evening(hass):
    await _tz(hass)
    r = reading(datetime(2026, 10, 22, 0, 30), 120, 80)
    s = summarize([r], W, START, local(2026, 10, 22, 0, 31))
    assert s.evening.status is SlotStatus.FILLED
    assert s.evening.window_start == local(2026, 10, 21, 21, 0)
    s = summarize([r], W, START, local(2026, 10, 22, 5, 0))
    assert (s.morning.status, s.evening.status) == (SlotStatus.OPEN, SlotStatus.UPCOMING)
