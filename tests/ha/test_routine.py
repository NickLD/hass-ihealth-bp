"""Measurement periods, BP days and sessions."""

from datetime import date, datetime, time

from homeassistant.util import dt as dt_util

from custom_components.ihealth_bp.routine import (
    Period,
    Windows,
    bp_day,
    group_sessions,
    period_of,
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
