"""Reading, battery and diagnostic sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfPressure,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IHealthBPConfigEntry
from .coordinator import IHealthBPCoordinator
from .derived import BP_CATEGORIES, bp_category, mean_arterial_pressure, pulse_pressure
from .entity import IHealthBPEntity
from .storage import LoggedReading

BPM = "bpm"


@dataclass(frozen=True, kw_only=True)
class ReadingSensorDescription(SensorEntityDescription):
    """A value computed from the newest imported reading (kept in the reading log)."""

    value_fn: Callable[[LoggedReading], Any]


@dataclass(frozen=True, kw_only=True)
class StateSensorDescription(SensorEntityDescription):
    """A value from the last session; restored across restarts."""

    value_fn: Callable[[IHealthBPCoordinator], Any]
    attrs_fn: Callable[[IHealthBPCoordinator], dict[str, Any]] | None = None


READING_SENSORS = (
    ReadingSensorDescription(
        key="systolic", translation_key="systolic",
        native_unit_of_measurement=UnitOfPressure.MMHG, value_fn=lambda r: r.systolic,
    ),
    ReadingSensorDescription(
        key="diastolic", translation_key="diastolic",
        native_unit_of_measurement=UnitOfPressure.MMHG, value_fn=lambda r: r.diastolic,
    ),
    ReadingSensorDescription(
        key="pulse", translation_key="pulse",
        native_unit_of_measurement=BPM, value_fn=lambda r: r.pulse,
    ),
    ReadingSensorDescription(
        key="pulse_pressure", translation_key="pulse_pressure",
        native_unit_of_measurement=UnitOfPressure.MMHG,
        value_fn=lambda r: pulse_pressure(r.systolic, r.diastolic),
    ),
    ReadingSensorDescription(
        key="mean_arterial_pressure", translation_key="mean_arterial_pressure",
        native_unit_of_measurement=UnitOfPressure.MMHG, suggested_display_precision=1,
        value_fn=lambda r: mean_arterial_pressure(r.systolic, r.diastolic),
    ),
    ReadingSensorDescription(
        key="bp_category", translation_key="bp_category",
        device_class=SensorDeviceClass.ENUM, options=list(BP_CATEGORIES),
        value_fn=lambda r: bp_category(r.systolic, r.diastolic),
    ),
    ReadingSensorDescription(
        key="measured_at", translation_key="measured_at",
        device_class=SensorDeviceClass.TIMESTAMP, value_fn=lambda r: r.measured_at,
    ),
)


def _failure_attrs(coordinator: IHealthBPCoordinator) -> dict[str, Any]:
    return {"stage": coordinator.state.failure_stage, "reason": coordinator.state.failure_reason}


STATE_SENSORS = (
    StateSensorDescription(
        key="battery", device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda c: c.state.battery,
    ),
    StateSensorDescription(
        key="last_sync", translation_key="last_sync",
        device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.state.last_sync,
    ),
    StateSensorDescription(
        key="last_failure", translation_key="last_failure",
        device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.state.last_failure, attrs_fn=_failure_attrs,
    ),
    StateSensorDescription(
        key="connected_via", translation_key="connected_via",
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda c: c.state.proxy,
    ),
    StateSensorDescription(
        key="signal_strength", device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False,
        value_fn=lambda c: c.state.rssi,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IHealthBPConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [ReadingSensor(coordinator, d) for d in READING_SENSORS]
    entities += [StateSensor(coordinator, d) for d in STATE_SENSORS]
    entities.append(ProtocolSensor(coordinator))
    async_add_entities(entities)


class ReadingSensor(IHealthBPEntity, SensorEntity):
    entity_description: ReadingSensorDescription

    @property
    def native_value(self) -> Any:
        latest = self.coordinator.store.latest_imported()
        return self.entity_description.value_fn(latest) if latest else None


class StateSensor(IHealthBPEntity, RestoreSensor):
    entity_description: StateSensorDescription
    _restored: Any = None
    _restored_attrs: dict[str, Any] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) is not None:
            self._restored = data.native_value
        if (last := await self.async_get_last_state()) is not None:
            self._restored_attrs = dict(last.attributes)

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self.coordinator)
        if value is None and isinstance(self._restored, (int, float, str, datetime)):
            return self._restored
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs_fn = self.entity_description.attrs_fn
        if attrs_fn is None:
            return None
        if self.entity_description.value_fn(self.coordinator) is None and self._restored_attrs:
            return {k: self._restored_attrs.get(k) for k in attrs_fn(self.coordinator)}
        return attrs_fn(self.coordinator)


class ProtocolSensor(IHealthBPEntity, SensorEntity):
    """Which firmware variant the cuff speaks; legacy variants are untested."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IHealthBPCoordinator) -> None:
        super().__init__(coordinator, SensorEntityDescription(key="protocol", translation_key="protocol"))

    @property
    def native_value(self) -> str:
        info = self.coordinator.state.info
        return info.protocol_label if info else self.coordinator.variant.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"untested": self.coordinator.variant.untested}
