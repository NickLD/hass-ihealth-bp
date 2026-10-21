"""Cuff display settings. Changes wait until the cuff next connects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import IHealthBPConfigEntry
from .entity import IHealthBPEntity


@dataclass(frozen=True, kw_only=True)
class DisplaySwitchDescription(SwitchEntityDescription):
    field: str  # attribute of DisplaySettings


SWITCHES = (
    DisplaySwitchDescription(key="backlight", translation_key="backlight", field="backlight"),
    DisplaySwitchDescription(key="clock_display", translation_key="clock_display", field="clock"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IHealthBPConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(DisplaySwitch(entry.runtime_data, d) for d in SWITCHES)


class DisplaySwitch(IHealthBPEntity, SwitchEntity, RestoreEntity):
    entity_description: DisplaySwitchDescription
    _attr_entity_category = EntityCategory.CONFIG
    _restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._restored = last.state == STATE_ON

    @property
    def is_on(self) -> bool | None:
        field = self.entity_description.field
        pending = self.coordinator.store.pending_display
        if field in pending:
            return pending[field]
        display = self.coordinator.state.display
        return getattr(display, field) if display else self._restored

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"pending": self.entity_description.field in self.coordinator.store.pending_display}

    async def _async_set(self, value: bool) -> None:
        await self.coordinator.async_request_display(self.entity_description.field, value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)
