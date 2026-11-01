"""Madplan: ugentlig aftensmadsplan ud fra ugens tilbud."""

from __future__ import annotations

import json
from pathlib import Path

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .planlaegger import Madplan

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SENSOR, Platform.TODO]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

KORT_URL = "/madplan/madplan-card.js"
DAG_SKEMA = vol.Schema({vol.Required("dag"): vol.All(vol.Coerce(int), vol.Range(min=1, max=7))})

type MadplanConfigEntry = ConfigEntry[Madplan]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Services: ny_plan, byt_ret, fjern_ret og overfoer, plus dashboard-kortet."""
    await _registrer_kort(hass)

    def _madplan() -> Madplan:
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            return entry.runtime_data
        raise ServiceValidationError("Madplan er ikke sat op")

    async def ny_plan(call: ServiceCall) -> None:
        m = _madplan()
        m.entry.async_create_background_task(hass, m.async_ny_plan(), "madplan_ny_plan")

    async def byt_ret(call: ServiceCall) -> None:
        m = _madplan()
        m.entry.async_create_background_task(hass, m.async_byt_ret(call.data["dag"]), "madplan_byt_ret")

    async def fjern_ret(call: ServiceCall) -> None:
        await _madplan().async_fjern_ret(call.data["dag"])

    async def overfoer(call: ServiceCall) -> None:
        await _madplan().async_overfoer()

    hass.services.async_register(DOMAIN, "ny_plan", ny_plan)
    hass.services.async_register(DOMAIN, "byt_ret", byt_ret, schema=DAG_SKEMA)
    hass.services.async_register(DOMAIN, "fjern_ret", fjern_ret, schema=DAG_SKEMA)
    hass.services.async_register(DOMAIN, "overfoer", overfoer)
    return True


async def _registrer_kort(hass: HomeAssistant) -> None:
    """Gør custom:madplan-card tilgængeligt uden at brugeren skal tilføje en ressource."""
    if hass.http is None:
        return
    mappe = Path(__file__).parent
    version = json.loads(await hass.async_add_executor_job((mappe / "manifest.json").read_text))["version"]
    await hass.http.async_register_static_paths(
        [StaticPathConfig(KORT_URL, str(mappe / "frontend" / "madplan-card.js"), True)]
    )
    add_extra_js_url(hass, f"{KORT_URL}?v={version}")


async def async_setup_entry(hass: HomeAssistant, entry: MadplanConfigEntry) -> bool:
    """Sæt Madplan op fra en config entry."""
    madplan = Madplan(hass, entry)
    await madplan.async_indlaes()
    entry.runtime_data = madplan

    @callback
    def _lordag(now) -> None:
        # Ny plan lørdag formiddag, når næste uges avis er ude.
        if dt_util.as_local(now).weekday() == 5:
            entry.async_create_background_task(hass, madplan.async_ny_plan(), "madplan_lordag")

    entry.async_on_unload(async_track_time_change(hass, _lordag, hour=10, minute=0, second=0))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_opdateret))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MadplanConfigEntry) -> bool:
    """Fjern Madplan."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _opdateret(hass: HomeAssistant, entry: MadplanConfigEntry) -> None:
    """Genindlæs når indstillingerne ændres."""
    await hass.config_entries.async_reload(entry.entry_id)
