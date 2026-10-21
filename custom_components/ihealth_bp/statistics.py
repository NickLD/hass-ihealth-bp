"""Hourly long-term statistics at the time readings were taken, rebuilt from the reading log."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .storage import LoggedReading

METRICS = {
    "systolic": ("Systolic", "mmHg"),
    "diastolic": ("Diastolic", "mmHg"),
    "pulse": ("Pulse", "bpm"),
}


def statistic_id(address: str, metric: str) -> str:
    return f"{DOMAIN}:{address.replace(':', '').lower()}_{metric}"


def hour_start(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def hourly_buckets(readings: list[LoggedReading]) -> dict[str, list[StatisticData]]:
    """Per metric, one row per hour: mean/min/max, and the hour's last reading as state."""
    by_hour: dict[datetime, list[LoggedReading]] = defaultdict(list)
    for reading in readings:
        by_hour[hour_start(reading.measured_at)].append(reading)
    buckets: dict[str, list[StatisticData]] = {metric: [] for metric in METRICS}
    for start in sorted(by_hour):
        group = sorted(by_hour[start], key=lambda r: r.measured_at)
        for metric in METRICS:
            values = [getattr(r, metric) for r in group]
            buckets[metric].append(
                StatisticData(
                    start=start,
                    mean=sum(values) / len(values),
                    min=min(values),
                    max=max(values),
                    state=values[-1],
                )
            )
    return buckets


async def async_update_statistics(
    hass: HomeAssistant,
    address: str,
    device_name: str,
    readings: list[LoggedReading],
    hours: set[datetime],
) -> None:
    """Rewrite the given hours from ``readings`` (the imported readings).

    External statistics can be overwritten but not deleted row by row, so when an
    hour has become empty the whole series is cleared and rebuilt.
    """
    buckets = hourly_buckets(readings)
    present = {row["start"] for row in buckets["systolic"]}
    if any(hour_start(h) not in present for h in hours):
        get_instance(hass).async_clear_statistics(
            [statistic_id(address, metric) for metric in METRICS]
        )
        wanted = present
    else:
        wanted = {hour_start(h) for h in hours}
    for metric, (label, unit) in METRICS.items():
        rows = [row for row in buckets[metric] if row["start"] in wanted]
        if not rows:
            continue
        metadata = StatisticMetaData(
            has_sum=False,
            mean_type=StatisticMeanType.ARITHMETIC,
            name=f"{device_name} {label}",
            source=DOMAIN,
            statistic_id=statistic_id(address, metric),
            unit_class=None,
            unit_of_measurement=unit,
        )
        async_add_external_statistics(hass, metadata, rows)
