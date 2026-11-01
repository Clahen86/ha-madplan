"""Fælles grundklasse for Madplans enheder."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .planlaegger import Madplan


class MadplanEntity(Entity):
    """Opdateres når planen ændres."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, madplan: Madplan, noegle: str) -> None:
        self.madplan = madplan
        self._attr_unique_id = f"{madplan.entry.entry_id}_{noegle}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, madplan.entry.entry_id)},
            name="Madplan",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, self.madplan.signal, self.async_write_ha_state))
