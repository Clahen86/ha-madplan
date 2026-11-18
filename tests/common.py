"""En madplan med en uge, uden netværk og AI: kun planen, sensorerne og registret."""

import datetime

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.madplan.const import DOMAIN
from custom_components.madplan.planlaegger import Madplan


def uge() -> list[dict]:
    """Syv dage, så i dag er en af dem (dag 1 er søndag)."""
    idag = dt_util.now().date()
    start = idag - datetime.timedelta(days=(idag.weekday() + 1) % 7)
    retter = []
    for i in range(7):
        dato = (start + datetime.timedelta(days=i)).isoformat()
        retter.append({"navn": f"Ret {i + 1}", "_dato": dato, "_linjer": ["500 g pasta", "1 dåse tomater"],
                       "trin": ["Kog pastaen", "Varm sovsen"], "tid_min": 30})
    return start, retter


async def lav_madplan(hass: HomeAssistant, profil: str = "", butik: str = "rema1000") -> tuple[Madplan, str]:
    data = {"butik": butik}
    if profil:
        data["profil"] = profil
    entry = MockConfigEntry(domain=DOMAIN, data=data, title=butik)
    entry.add_to_hass(hass)
    m = Madplan(hass, entry)
    await m.async_indlaes()
    start, retter = uge()
    m.plan = {"start": start.isoformat(), "retter": retter, "status": "Klar",
              "varer": [{"key": "pasta", "navn": "Pasta", "pris": 10, "antal": 1, "tilbud": False, "str": "500 g"}],
              "ekstra": [{"uid": "e1", "navn": "Rugbrød", "behov": "madpakker", "pris": 20, "antal": 1, "tilbud": True, "str": ""}]}
    entry.runtime_data = m
    entry.mock_state(hass, ConfigEntryState.LOADED)
    reg = er.async_get(hass)
    eid = reg.async_get_or_create("sensor", DOMAIN, f"{entry.entry_id}_total", config_entry=entry, suggested_object_id=f"madplan_{butik}").entity_id
    dage = [reg.async_get_or_create("sensor", DOMAIN, f"{entry.entry_id}_dag_{i + 1}", config_entry=entry,
                                    suggested_object_id=f"madplan_{butik}_dag_{i + 1}").entity_id for i in range(7)]
    hass.states.async_set(eid, "123", {"dag_entiteter": dage, "varer_entitet": f"todo.madplan_{butik}_varer",
                                       "ekstra_entitet": f"todo.madplan_{butik}_ekstra", "profil": profil, "butik": butik,
                                       "profiler": [{"id": "hoved", "brugere": ["hemmelig-bruger"]}]})
    for i, d in enumerate(dage):
        hass.states.async_set(d, retter[i]["navn"], {"dato": retter[i]["_dato"]})
    return m, eid


@pytest.fixture
def idag_index():
    start, _ = uge()
    return (dt_util.now().date() - start).days
