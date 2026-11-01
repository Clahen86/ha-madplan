"""Ugens vareliste. Afkrydset = har det allerede hjemme."""

from __future__ import annotations

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import MadplanEntity
from .planlaegger import pris_tekst, vare_tekst


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([MadplanVarer(entry.runtime_data)])


class MadplanVarer(MadplanEntity, TodoListEntity):
    _attr_name = "Varer"
    _attr_icon = "mdi:cart"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM

    def __init__(self, madplan) -> None:
        super().__init__(madplan, "varer")

    @property
    def todo_items(self) -> list[TodoItem]:
        return [
            TodoItem(
                summary=vare_tekst(v),
                uid=v["key"],
                status=TodoItemStatus.COMPLETED if v.get("hjemme") else TodoItemStatus.NEEDS_ACTION,
                description=pris_tekst(v),
            )
            for v in self.madplan.plan.get("varer", [])
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        await self.madplan.async_saet_hjemme(item.uid, item.status == TodoItemStatus.COMPLETED)
