"""Flags from the newest imported reading."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IHealthBPConfigEntry
from .entity import IHealthBPEntity
from .storage import LoggedReading


@dataclass(frozen=True, kw_only=True)
class FlagDescription(BinarySensorEntityDescription):
    value_fn: Callable[[LoggedReading], bool]


FLAGS = (
    FlagDescription(
        key="irregular_pulse", translation_key="irregular_pulse",
        device_class=BinarySensorDeviceClass.PROBLEM, value_fn=lambda r: r.irregular_pulse,
    ),
    FlagDescription(
        key="body_movement", translation_key="body_movement",
        device_class=BinarySensorDeviceClass.PROBLEM, value_fn=lambda r: r.body_movement,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IHealthBPConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(FlagSensor(entry.runtime_data, d) for d in FLAGS)


class FlagSensor(IHealthBPEntity, BinarySensorEntity):
    entity_description: FlagDescription

    @property
    def is_on(self) -> bool | None:
        latest = self.coordinator.store.latest_imported()
        return self.entity_description.value_fn(latest) if latest else None
