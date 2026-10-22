"""The reading log: every reading the cuff has handed over, and what became of it."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .kn550bt.protocol import Reading

STORAGE_VERSION = 1


class ReadingStatus(StrEnum):
    IMPORTED = "imported"
    PENDING = "pending"
    DELETED = "deleted"


@dataclass(frozen=True)
class LoggedReading:
    uid: str
    measured_at: datetime  # aware, UTC
    systolic: int
    diastolic: int
    pulse: int
    irregular_pulse: bool
    body_movement: bool
    status: ReadingStatus

    def as_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "measured_at": self.measured_at.isoformat(),
            "systolic": self.systolic,
            "diastolic": self.diastolic,
            "pulse": self.pulse,
            "irregular_pulse": self.irregular_pulse,
            "body_movement": self.body_movement,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoggedReading:
        return cls(
            uid=data["uid"],
            measured_at=datetime.fromisoformat(data["measured_at"]),
            systolic=data["systolic"],
            diastolic=data["diastolic"],
            pulse=data["pulse"],
            irregular_pulse=data["irregular_pulse"],
            body_movement=data["body_movement"],
            status=ReadingStatus(data["status"]),
        )


def reading_uid(reading: Reading) -> str:
    return f"{reading.time:%Y%m%d%H%M%S}-{reading.systolic}-{reading.diastolic}-{reading.pulse}"


def cuff_time_to_utc(naive: datetime) -> datetime:
    """The cuff keeps naive local time; interpret it in Home Assistant's time zone."""
    return dt_util.as_utc(naive.replace(tzinfo=dt_util.get_default_time_zone()))


class CuffStore:
    """Keyed by the cuff's address, so the log survives removing and re-adding the entry."""

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        key = f"{DOMAIN}.{address.replace(':', '').lower()}"
        # Atomic (fsynced) writes: the cuff wipes its memory once a save returns.
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, key, atomic_writes=True
        )
        self._readings: dict[str, LoggedReading] = {}
        self._pending_display: dict[str, bool] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._readings = {
            r["uid"]: LoggedReading.from_dict(r) for r in data.get("readings", [])
        }
        self._pending_display = dict(data.get("pending_display") or {})

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "readings": [r.as_dict() for r in self._readings.values()],
                "pending_display": dict(self._pending_display),
            }
        )

    async def async_add(self, readings: list[Reading], *, review: bool) -> list[LoggedReading]:
        """Log readings not seen before; returns the new ones, oldest first, once saved."""
        status = ReadingStatus.PENDING if review else ReadingStatus.IMPORTED
        added: list[LoggedReading] = []
        for reading in sorted(readings, key=lambda r: r.time):
            uid = reading_uid(reading)
            if uid in self._readings:
                continue
            logged = LoggedReading(
                uid=uid,
                measured_at=cuff_time_to_utc(reading.time),
                systolic=reading.systolic,
                diastolic=reading.diastolic,
                pulse=reading.pulse,
                irregular_pulse=reading.arrhythmia,
                body_movement=bool(reading.body_movement),
                status=status,
            )
            self._readings[uid] = logged
            added.append(logged)
        if added:
            await self._async_save()
        return added

    async def async_set_status(self, uid: str, status: ReadingStatus) -> LoggedReading:
        updated = replace(self._readings[uid], status=status)
        self._readings[uid] = updated
        await self._async_save()
        return updated

    def find(self, uid: str) -> LoggedReading | None:
        return self._readings.get(uid)

    def find_by_time(self, measured_at: datetime) -> LoggedReading | None:
        target = dt_util.as_utc(measured_at).replace(microsecond=0)
        for reading in self.visible():
            if reading.measured_at == target:
                return reading
        return None

    def visible(self) -> list[LoggedReading]:
        """Imported and pending readings, newest first."""
        return sorted(
            (r for r in self._readings.values() if r.status is not ReadingStatus.DELETED),
            key=lambda r: r.measured_at,
            reverse=True,
        )

    def imported(self) -> list[LoggedReading]:
        return [r for r in self.visible() if r.status is ReadingStatus.IMPORTED]

    def latest_imported(self) -> LoggedReading | None:
        imported = self.imported()
        return imported[0] if imported else None

    @property
    def pending_display(self) -> dict[str, bool]:
        """Display fields ("backlight", "clock") changed in HA but not yet sent to the cuff."""
        return self._pending_display

    async def async_set_pending_display(self, field: str, value: bool) -> None:
        self._pending_display = {**self._pending_display, field: value}
        await self._async_save()

    async def async_clear_pending_display(self, applied: dict[str, bool]) -> None:
        """Forget applied changes, keeping any made while they were being applied."""
        self._pending_display = {
            k: v for k, v in self._pending_display.items() if applied.get(k) != v
        }
        await self._async_save()
