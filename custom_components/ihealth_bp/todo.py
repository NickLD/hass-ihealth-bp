"""The Readings list: review, approve and delete readings."""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import IHealthBPConfigEntry
from .const import DOMAIN
from .coordinator import IHealthBPCoordinator
from .entity import IHealthBPEntity
from .storage import LoggedReading, ReadingStatus


def reading_summary(reading: LoggedReading) -> str:
    local = dt_util.as_local(reading.measured_at)
    return (
        f"{local:%b} {local.day} {local:%H:%M} — "
        f"{reading.systolic}/{reading.diastolic}, pulse {reading.pulse}"
    )


def reading_description(reading: LoggedReading) -> str | None:
    flags = [
        label
        for label, on in (
            ("Irregular pulse", reading.irregular_pulse),
            ("Body movement", reading.body_movement),
        )
        if on
    ]
    return ", ".join(flags) or None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IHealthBPConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ReadingsList(entry.runtime_data)])


class ReadingsList(IHealthBPEntity, TodoListEntity):
    _attr_supported_features = (
        TodoListEntityFeature.DELETE_TODO_ITEM | TodoListEntityFeature.UPDATE_TODO_ITEM
    )

    def __init__(self, coordinator: IHealthBPCoordinator) -> None:
        super().__init__(coordinator, EntityDescription(key="readings", translation_key="readings"))

    @property
    def todo_items(self) -> list[TodoItem]:
        return [
            TodoItem(
                summary=reading_summary(r),
                uid=r.uid,
                status=(
                    TodoItemStatus.COMPLETED
                    if r.status is ReadingStatus.IMPORTED
                    else TodoItemStatus.NEEDS_ACTION
                ),
                description=reading_description(r),
            )
            for r in self.coordinator.store.visible()
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """The only allowed change is ticking a pending reading, which imports it."""
        reading = self.coordinator.store.find(item.uid or "")
        if reading is None or reading.status is ReadingStatus.DELETED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="reading_not_found"
            )
        unchanged_text = item.summary in (None, reading_summary(reading))
        if (
            unchanged_text
            and reading.status is ReadingStatus.PENDING
            and item.status == TodoItemStatus.COMPLETED
        ):
            await self.coordinator.async_approve_reading(reading.uid)
            return
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="item_change_not_allowed"
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        for uid in uids:
            try:
                await self.coordinator.async_delete_reading(uid)
            except KeyError as err:  # already deleted, e.g. by a concurrent call
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="reading_not_found"
                ) from err
