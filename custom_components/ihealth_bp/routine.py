"""Measurement periods, BP days and sessions: the pure logic of the routine."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_EVENING_END,
    CONF_EVENING_START,
    CONF_MORNING_END,
    CONF_MORNING_START,
)
from .storage import LoggedReading

SESSION_GAP = timedelta(minutes=10)
_DAY = timedelta(hours=24)


class Period(StrEnum):
    MORNING = "morning"
    EVENING = "evening"
    EXTRA = "extra"


ROUTINE_PERIODS = (Period.MORNING, Period.EVENING)


def _since_midnight(t: time) -> timedelta:
    return timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)


@dataclass(frozen=True)
class Windows:
    morning_start: time = time(5)
    morning_end: time = time(12, 30)
    evening_start: time = time(21)
    evening_end: time = time(3)

    def offset(self, t: time) -> timedelta:
        """Time of day measured from morning_start, modulo 24 h."""
        return (_since_midnight(t) - _since_midnight(self.morning_start)) % _DAY

    def offsets(self) -> tuple[timedelta, timedelta, timedelta]:
        """Offsets of morning end, evening start and evening end (0 means 24 h)."""
        evening_end = self.offset(self.evening_end) or _DAY
        return self.offset(self.morning_end), self.offset(self.evening_start), evening_end

    def valid(self) -> bool:
        me, es, ee = self.offsets()
        return timedelta(0) < me <= es < ee

    def slot_bounds(self, day: date, period: Period) -> tuple[datetime, datetime]:
        """Start and end (aware, local) of a routine period of the given BP day."""
        me, es, ee = self.offsets()
        begin, end = (timedelta(0), me) if period is Period.MORNING else (es, ee)
        origin = datetime.combine(
            day, self.morning_start, tzinfo=dt_util.get_default_time_zone()
        )
        return origin + begin, origin + end


def _parse(value: str | None, default: time) -> time:
    return time.fromisoformat(value) if value else default


def windows_from_options(options: Mapping[str, Any]) -> Windows:
    defaults = Windows()
    return Windows(
        morning_start=_parse(options.get(CONF_MORNING_START), defaults.morning_start),
        morning_end=_parse(options.get(CONF_MORNING_END), defaults.morning_end),
        evening_start=_parse(options.get(CONF_EVENING_START), defaults.evening_start),
        evening_end=_parse(options.get(CONF_EVENING_END), defaults.evening_end),
    )


def bp_day(moment: datetime, windows: Windows) -> date:
    """The BP day a moment belongs to; it starts at the morning window start."""
    local = dt_util.as_local(moment)
    return (local - _since_midnight(windows.morning_start)).date()


def period_of(moment: datetime, windows: Windows) -> Period:
    offset = windows.offset(dt_util.as_local(moment).time())
    me, es, ee = windows.offsets()
    if offset < me:
        return Period.MORNING
    if es <= offset < ee:
        return Period.EVENING
    return Period.EXTRA


@dataclass(frozen=True)
class Session:
    readings: tuple[LoggedReading, ...]  # oldest first
    period: Period
    day: date

    @property
    def start(self) -> datetime:
        return self.readings[0].measured_at

    @property
    def mean_systolic(self) -> float:
        return round(sum(r.systolic for r in self.readings) / len(self.readings), 1)

    @property
    def mean_diastolic(self) -> float:
        return round(sum(r.diastolic for r in self.readings) / len(self.readings), 1)

    @property
    def mean_pulse(self) -> float:
        return round(sum(r.pulse for r in self.readings) / len(self.readings), 1)

    def index_of(self, uid: str) -> int:
        """1-based position of a reading in the session."""
        for i, reading in enumerate(self.readings, start=1):
            if reading.uid == uid:
                return i
        raise KeyError(uid)

    @property
    def measured_at(self) -> list[datetime]:
        return [r.measured_at for r in self.readings]


def group_sessions(readings: Iterable[LoggedReading], windows: Windows) -> list[Session]:
    """Chain readings no more than SESSION_GAP apart; the first reading sets period and day."""
    groups: list[list[LoggedReading]] = []
    for reading in sorted(readings, key=lambda r: r.measured_at):
        if groups and reading.measured_at - groups[-1][-1].measured_at <= SESSION_GAP:
            groups[-1].append(reading)
        else:
            groups.append([reading])
    return [
        Session(
            readings=tuple(g),
            period=period_of(g[0].measured_at, windows),
            day=bp_day(g[0].measured_at, windows),
        )
        for g in groups
    ]
