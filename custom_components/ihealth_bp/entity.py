"""Base entity: always available (the cuff sleeps), refreshed after every sync."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN
from .coordinator import IHealthBPCoordinator


class IHealthBPEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: IHealthBPCoordinator, description: EntityDescription) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.address)})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


def routine_entities(
    hass: HomeAssistant,
    coordinator: IHealthBPCoordinator,
    domain: str,
    entities: list[IHealthBPEntity],
) -> list[IHealthBPEntity]:
    """The routine entities to add: all of them, or none (removing old ones) with it off."""
    if coordinator.routine_enabled:
        return entities
    registry = er.async_get(hass)
    for entity in entities:
        if entity_id := registry.async_get_entity_id(domain, DOMAIN, entity.unique_id):
            registry.async_remove(entity_id)
    return []
