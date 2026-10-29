"""Discard the latest measurement session."""

from __future__ import annotations

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IHealthBPConfigEntry
from .const import DOMAIN
from .coordinator import IHealthBPCoordinator
from .entity import IHealthBPEntity, routine_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IHealthBPConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        routine_entities(hass, coordinator, BUTTON_DOMAIN, [DiscardLatestSession(coordinator)])
    )


class DiscardLatestSession(IHealthBPEntity, ButtonEntity):
    def __init__(self, coordinator: IHealthBPCoordinator) -> None:
        super().__init__(
            coordinator,
            EntityDescription(
                key="discard_latest_session", translation_key="discard_latest_session"
            ),
        )

    async def async_press(self) -> None:
        sessions = self.coordinator.sessions()
        if not sessions:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_session")
        try:
            await self.coordinator.async_delete_session(sessions[-1].readings[-1].uid)
        except KeyError as err:  # discarded by a concurrent call
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_session"
            ) from err
