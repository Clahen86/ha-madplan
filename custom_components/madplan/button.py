"""Knapper til ny plan og overførsel af indkøbslisten."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import MadplanEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([NyPlanKnap(entry.runtime_data), OverfoerKnap(entry.runtime_data)])


class NyPlanKnap(MadplanEntity, ButtonEntity):
    _attr_name = "Ny plan"
    _attr_icon = "mdi:autorenew"

    def __init__(self, madplan) -> None:
        super().__init__(madplan, "ny_plan")

    async def async_press(self) -> None:
        self.madplan.entry.async_create_background_task(self.hass, self.madplan.async_ny_plan(), "madplan_ny_plan")


class OverfoerKnap(MadplanEntity, ButtonEntity):
    _attr_name = "Send indkøbsliste"
    _attr_icon = "mdi:cart-arrow-right"

    def __init__(self, madplan) -> None:
        super().__init__(madplan, "overfoer")

    async def async_press(self) -> None:
        await self.madplan.async_overfoer()
