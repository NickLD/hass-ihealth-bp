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


class SlotStatus(StrEnum):
    FILLED = "filled"
    OPEN = "open"
    UPCOMING = "upcoming"
    CLOSED = "closed"


@dataclass(frozen=True)
class Mean:
    systolic: float
    diastolic: float


@dataclass(frozen=True)
class SlotInfo:
    status: SlotStatus
    window_start: datetime
    window_end: datetime
    first_reading_at: datetime | None
    mean: Mean | None  # every reading in the slot, clean or not, for display
    reading_count: int


@dataclass(frozen=True)
class RoutineSummary:
    baseline_7d: Mean | None
    baseline_30d: Mean | None
    morning_7d: Mean | None
    evening_7d: Mean | None
    slots_filled_7d: int
    irregular_pulse_7d: int
    morning: SlotInfo
    evening: SlotInfo


def is_clean(reading: LoggedReading, routine_start: date, windows: Windows) -> bool:
    """No flags, no body movement and not before the routine started.

    The period check belongs to the session, not the reading.
    """
    return (
        not reading.flags
        and not reading.body_movement
        and bp_day(reading.measured_at, windows) >= routine_start
    )


def _mean(values: list[tuple[float, float]]) -> Mean | None:
    if not values:
        return None
    n = len(values)
    return Mean(
        round(sum(v[0] for v in values) / n, 1),
        round(sum(v[1] for v in values) / n, 1),
    )


def _avg(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    n = len(pairs)
    return sum(p[0] for p in pairs) / n, sum(p[1] for p in pairs) / n


def _slot_info(
    sessions: list[Session], day: date, period: Period, windows: Windows, now: datetime
) -> SlotInfo:
    start, end = windows.slot_bounds(day, period)
    readings = sorted(
        (r for s in sessions if s.day == day and s.period is period for r in s.readings),
        key=lambda r: r.measured_at,
    )
    if readings:
        status = SlotStatus.FILLED
    elif now < start:
        status = SlotStatus.UPCOMING
    elif now < end:
        status = SlotStatus.OPEN
    else:
        status = SlotStatus.CLOSED
    return SlotInfo(
        status=status,
        window_start=start,
        window_end=end,
        first_reading_at=dt_util.as_local(readings[0].measured_at) if readings else None,
        mean=_mean([(r.systolic, r.diastolic) for r in readings]),
        reading_count=len(readings),
    )


def summarize(
    readings: Iterable[LoggedReading],
    windows: Windows,
    routine_start: date,
    now: datetime,
) -> RoutineSummary:
    """Baselines and today's slot state; the caller passes imported readings only."""
    readings = list(readings)
    now = dt_util.as_local(now)
    today = bp_day(now, windows)
    sessions = group_sessions(readings, windows)

    # slot value: mean of the slot's clean session means (a session mean uses its clean readings)
    slots: dict[tuple[date, Period], list[tuple[float, float]]] = {}
    filled: set[tuple[date, Period]] = set()
    for session in sessions:
        if session.period not in ROUTINE_PERIODS:
            continue
        key = (session.day, session.period)
        filled.add(key)
        clean = [
            (r.systolic, r.diastolic)
            for r in session.readings
            if is_clean(r, routine_start, windows)
        ]
        if clean:
            slots.setdefault(key, []).append(_avg(clean))

    def baseline(days: int, period: Period | None = None) -> Mean | None:
        return _mean(
            [
                _avg(sessions_means)
                for (day, p), sessions_means in slots.items()
                if today - timedelta(days=days) < day <= today
                and (period is None or p is period)
            ]
        )

    in_7d = lambda d: today - timedelta(days=7) < d <= today  # noqa: E731
    return RoutineSummary(
        baseline_7d=baseline(7),
        baseline_30d=baseline(30),
        morning_7d=baseline(7, Period.MORNING),
        evening_7d=baseline(7, Period.EVENING),
        slots_filled_7d=sum(1 for day, _ in filled if in_7d(day)),
        irregular_pulse_7d=sum(
            1 for r in readings if r.irregular_pulse and in_7d(bp_day(r.measured_at, windows))
        ),
        morning=_slot_info(sessions, today, Period.MORNING, windows, now),
        evening=_slot_info(sessions, today, Period.EVENING, windows, now),
    )
