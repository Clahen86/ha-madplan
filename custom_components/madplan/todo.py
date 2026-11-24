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


def varer(madplan) -> list[TodoItem]:
    """Aftensmadens varer. Også appen fra et link bruger dem."""
    return [
        TodoItem(
            summary=vare_tekst(v),
            uid=v["key"],
            status=TodoItemStatus.COMPLETED if v.get("hjemme") or v.get("kurv") else TodoItemStatus.NEEDS_ACTION,
            # "pris · butik" for varer fra en anden kæde (fx Netto), så kortet kan gruppere dem.
            description=pris_tekst(v) + (f" · {v['butik']}" if v.get("butik") else ""),
        )
        for v in madplan.plan.get("varer", [])
        if not v.get("skjult")  # købt og "Tøm kurven" trykket
    ]


def ekstra(madplan) -> list[TodoItem]:
    """Varer til ugens øvrige behov (pålæg, madpakker …)."""
    return [
        TodoItem(
            summary=vare_tekst(e),
            uid=e["uid"],
            status=TodoItemStatus.COMPLETED if e.get("hjemme") or e.get("kurv") else TodoItemStatus.NEEDS_ACTION,
            description=f"{_egen_pris(e)} · {e['behov']}",
        )
        for e in madplan.plan.get("ekstra", [])
        if not e.get("skjult")  # ↻-vare, der er købt: kommer igen næste uge
    ]


def _egen_pris(e: dict) -> str:
    """En egen vare har ingen pris, før man beder om den - og "ikke fundet", når butikken ikke har den."""
    if e.get("egen") and e.get("ukendt"):
        return "ikke fundet" if e.get("ikke_fundet") else ""
    return pris_tekst(e)


class MadplanVarer(MadplanEntity, TodoListEntity):
    _attr_name = "Varer"
    _attr_icon = "mdi:cart"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM

    def __init__(self, madplan) -> None:
        super().__init__(madplan, "varer")

    @property
    def todo_items(self) -> list[TodoItem]:
        return varer(self.madplan)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        await self.madplan.async_saet_hjemme(item.uid, item.status == TodoItemStatus.COMPLETED)


class MadplanEkstra(MadplanEntity, TodoListEntity):
    """Øvrige indkøb (det, man selv skriver på). Afkrydset = i kurven eller har det. Kan slettes."""

    _attr_name = "Øvrige indkøb"
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
        return ekstra(self.madplan)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        # Afkrydset i HA's to-do-liste = lagt i kurven.
        await self.madplan.async_marker("ekstra", item.uid, "kurv", item.status == TodoItemStatus.COMPLETED)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        for uid in uids:
            await self.madplan.async_saet_ekstra(uid, slet=True)
