"""Antal personer, som mængder og priser regnes ud fra."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import MadplanEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([MadplanPersoner(entry.runtime_data), MadplanMadpakker(entry.runtime_data)])


class MadplanPersoner(MadplanEntity, NumberEntity):
    _attr_name = "Personer"
    _attr_icon = "mdi:account-group"
    _attr_native_min_value = 1
    _attr_native_max_value = 12
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, madplan) -> None:
        super().__init__(madplan, "personer")

    @property
    def native_value(self) -> float:
        return self.madplan.personer

    async def async_set_native_value(self, value: float) -> None:
        await self.madplan.async_saet_personer(int(value))


class MadplanMadpakker(MadplanEntity, NumberEntity):
    """Madpakker pr. hverdag; bruges til ekstra varer som rugbrød og pålæg."""

    _attr_name = "Madpakker"
    _attr_icon = "mdi:food-takeout-box-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 12
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, madplan) -> None:
        super().__init__(madplan, "madpakker")

    @property
    def native_value(self) -> float:
        return self.madplan.madpakker

    async def async_set_native_value(self, value: float) -> None:
        await self.madplan.async_saet_madpakker(int(value))
