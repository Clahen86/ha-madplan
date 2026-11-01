"""Ugens vareliste. Afkrydset = lagt i kurven eller har det allerede hjemme."""

from __future__ import annotations

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import MadplanEntity
from .planlaegger import pris_tekst, vare_tekst


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([MadplanVarer(entry.runtime_data), MadplanEkstra(entry.runtime_data)])


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
                status=TodoItemStatus.COMPLETED if v.get("hjemme") or v.get("kurv") else TodoItemStatus.NEEDS_ACTION,
                # "pris · butik" for varer fra en anden kæde (fx Netto), så kortet kan gruppere dem.
                description=pris_tekst(v) + (f" · {v['butik']}" if v.get("butik") else ""),
            )
            for v in self.madplan.plan.get("varer", [])
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        await self.madplan.async_saet_hjemme(item.uid, item.status == TodoItemStatus.COMPLETED)


class MadplanEkstra(MadplanEntity, TodoListEntity):
    """Varer til ugens øvrige behov (pålæg, madpakker …). Afkrydset = i kurven eller har det. Kan slettes."""

    _attr_name = "Ekstra varer"
    _attr_icon = "mdi:basket-plus-outline"
    _attr_supported_features = (
        TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, madplan) -> None:
        super().__init__(madplan, "ekstra")

    @property
    def todo_items(self) -> list[TodoItem]:
        return [
            TodoItem(
                summary=vare_tekst(e),
                uid=e["uid"],
                status=TodoItemStatus.COMPLETED if e.get("hjemme") or e.get("kurv") else TodoItemStatus.NEEDS_ACTION,
                description=f"{pris_tekst(e)} · {e['behov']}",
            )
            for e in self.madplan.plan.get("ekstra", [])
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        # Afkrydset i HA's to-do-liste = lagt i kurven.
        await self.madplan.async_marker("ekstra", item.uid, "kurv", item.status == TodoItemStatus.COMPLETED)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        for uid in uids:
            await self.madplan.async_saet_ekstra(uid, slet=True)
