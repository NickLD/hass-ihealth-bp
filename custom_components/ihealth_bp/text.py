"""The note on the latest measurement session."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IHealthBPConfigEntry
from .const import DOMAIN
from .coordinator import IHealthBPCoordinator
from .entity import IHealthBPEntity

MAX_NOTE = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IHealthBPConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([SessionNote(entry.runtime_data)])


class SessionNote(IHealthBPEntity, TextEntity):
    _attr_native_max = MAX_NOTE

    def __init__(self, coordinator: IHealthBPCoordinator) -> None:
        super().__init__(
            coordinator, TextEntityDescription(key="session_note", translation_key="session_note")
        )

    @property
    def native_value(self) -> str:
        sessions = self.coordinator.sessions()
        if not sessions:
            return ""
        return next((r.note for r in sessions[-1].readings if r.note), "")

    async def async_set_value(self, value: str) -> None:
        sessions = self.coordinator.sessions()
        if not sessions:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_session")
        await self.coordinator.async_set_context(
            sessions[-1].readings[-1].uid, session=True, note=value
        )
