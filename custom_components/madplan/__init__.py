"""Madplan: ugentlig aftensmadsplan ud fra ugens tilbud."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

PLATFORMS: list[str] = []


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Sæt Madplan op fra en config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_opdateret))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Fjern Madplan."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _opdateret(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Genindlæs når indstillingerne ændres."""
    await hass.config_entries.async_reload(entry.entry_id)
