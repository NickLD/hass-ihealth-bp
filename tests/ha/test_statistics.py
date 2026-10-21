"""Long-term statistics are keyed by measurement time and rebuilt from the log."""

from datetime import UTC, datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.ihealth_bp.statistics import (
    async_update_statistics,
    hourly_buckets,
    statistic_id,
)
from custom_components.ihealth_bp.storage import LoggedReading, ReadingStatus

from .conftest import ADDRESS

H14 = datetime(2026, 10, 21, 14, 0, tzinfo=UTC)
SYS = statistic_id(ADDRESS, "systolic")


def reading(minute: int, sys: int, dia: int, pulse: int, hour: datetime = H14) -> LoggedReading:
    at = hour + timedelta(minutes=minute)
    return LoggedReading(f"{at:%H%M}-{sys}", at, sys, dia, pulse, False, False, ReadingStatus.IMPORTED)


async def rows(hass, metric: str = "systolic") -> list[dict]:
    await async_wait_recording_done(hass)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, H14 - timedelta(days=1), H14 + timedelta(days=1),
        {statistic_id(ADDRESS, metric)}, "hour", None, {"mean", "min", "max", "state"},
    )
    return stats.get(statistic_id(ADDRESS, metric), [])


def test_statistic_id():
    assert statistic_id(ADDRESS, "systolic") == "ihealth_bp:004d32650e89_systolic"


def test_two_readings_same_hour_mean_min_max():
    buckets = hourly_buckets([reading(5, 120, 80, 60), reading(40, 130, 70, 70)])
    (row,) = buckets["systolic"]
    assert row["start"] == H14
    assert (row["mean"], row["min"], row["max"], row["state"]) == (125, 120, 130, 130)
    assert buckets["pulse"][0]["mean"] == 65


async def test_reading_lands_in_its_measurement_hour_not_sync_hour(hass):
    readings = [reading(52, 125, 64, 69)]
    await async_update_statistics(hass, ADDRESS, "KN-550BT", readings, {H14})
    (row,) = await rows(hass)
    assert datetime.fromtimestamp(row["start"], UTC) == H14
    assert row["mean"] == 125


async def test_deleting_one_of_two_recomputes_hour(hass):
    a, b = reading(5, 120, 80, 60), reading(40, 130, 70, 70)
    await async_update_statistics(hass, ADDRESS, "KN-550BT", [a, b], {H14})
    await async_update_statistics(hass, ADDRESS, "KN-550BT", [a], {H14})
    (row,) = await rows(hass)
    assert (row["mean"], row["max"]) == (120, 120)


async def test_deleting_only_reading_in_hour_removes_that_hour(hass):
    h15 = H14 + timedelta(hours=1)
    a, b = reading(5, 120, 80, 60), reading(10, 140, 90, 70, hour=h15)
    await async_update_statistics(hass, ADDRESS, "KN-550BT", [a, b], {H14, h15})
    await async_update_statistics(hass, ADDRESS, "KN-550BT", [a], {h15})
    remaining = await rows(hass)
    assert [datetime.fromtimestamp(r["start"], UTC) for r in remaining] == [H14]
    assert len(await rows(hass, "pulse")) == 1
