"""Diagnostics download (Settings → Devices → Download diagnostics)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import IHealthBPConfigEntry
from .const import (
    CONF_EVENING_END,
    CONF_EVENING_START,
    CONF_MORNING_END,
    CONF_MORNING_START,
    CONF_ROUTINE_START,
)

# The routine windows and start date hint at the owner's daily schedule.
TO_REDACT = {
    "address",
    "serial",
    "unique_id",
    CONF_MORNING_START,
    CONF_MORNING_END,
    CONF_EVENING_START,
    CONF_EVENING_END,
    CONF_ROUTINE_START,
}
_MAC = re.compile(r"(?i)\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b|\b[0-9a-f]{12}\b")


def _scrub(value: Any) -> Any:
    """Remove Bluetooth addresses from free text (e.g. error messages)."""
    if isinstance(value, str):
        return _MAC.sub("**REDACTED**", value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IHealthBPConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    store = coordinator.store
    counts = Counter(r.status.value for r in store.visible())
    # Readings are health data and diagnostics get attached to public issues:
    # report only counts, never values or times.
    return _scrub(async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "variant": coordinator.variant.value,
            "untested": coordinator.variant.untested,
            "state": asdict(coordinator.state),
            "pending_display": dict(store.pending_display),
            "readings": dict(counts),
        },
        TO_REDACT,
    ))
