"""Diagnostics download (Settings → Devices → Download diagnostics)."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import IHealthBPConfigEntry

TO_REDACT = {"address", "serial", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IHealthBPConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    store = coordinator.store
    counts = Counter(r.status.value for r in store.visible())
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "variant": coordinator.variant.value,
            "untested": coordinator.variant.untested,
            "state": asdict(coordinator.state),
            "pending_display": asdict(store.pending_display) if store.pending_display else None,
            "readings": dict(counts),
            "recent_readings": [
                {k: v for k, v in r.as_dict().items() if k != "uid"} for r in store.visible()[:5]
            ],
        },
        TO_REDACT,
    )
