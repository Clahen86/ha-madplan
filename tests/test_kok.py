"""Maddag: hvem laver mad, gemt med planen, og madplan_cook på bussen efter den fælles aftale."""

import pytest
import voluptuous as vol
from pytest_homeassistant_custom_component.common import async_capture_events

from homeassistant.core import HomeAssistant

from custom_components.madplan import DAG_KOK_SKEMA
from custom_components.madplan.const import EVENT_KOK

from .common import idag_index, lav_madplan  # noqa: F401


async def test_en_kok_gemmes_og_fyrer_eventet(hass: HomeAssistant, hass_storage, idag_index) -> None:  # noqa: F811
    hass.states.async_set("person.silas", "home", {"friendly_name": "Silas"})
    m, _ = await lav_madplan(hass)
    events = async_capture_events(hass, EVENT_KOK)
    await m.async_dag_kok(idag_index + 1, "person.silas")
    await hass.async_block_till_done()
    assert m.plan["retter"][idag_index]["kok"] == "person.silas"
    assert hass_storage[f"madplan.{m.entry.entry_id}"]["data"]["plan"]["retter"][idag_index]["kok"] == "person.silas"
    assert len(events) == 1
    d = events[0].data
    assert d["person"] == "person.silas" and d["kid"] == "Silas" and d["meal"] == f"Ret {idag_index + 1}"
    assert d["date"] == m.plan["retter"][idag_index]["_dato"]
    assert d["ingredients"] == ["500 g pasta", "1 dåse tomater"]
    assert d["recipe"] == "1. Kog pastaen\n2. Varm sovsen"
    assert "time" not in d and "url" not in d  # klar-tiden kendes ikke; ingen egen opskrift med link
    assert set(d) <= {"person", "kid", "date", "meal", "time", "recipe", "ingredients", "url"}


async def test_fri_tekst_og_ingen_kok(hass: HomeAssistant, idag_index) -> None:  # noqa: F811
    m, _ = await lav_madplan(hass)
    events = async_capture_events(hass, EVENT_KOK)
    await m.async_dag_kok(idag_index + 1, " Mormor ")
    await hass.async_block_till_done()
    assert events[-1].data["person"] == "Mormor" and events[-1].data["kid"] == "Mormor"
    await m.async_dag_kok(idag_index + 1, "")
    await hass.async_block_till_done()
    assert "kok" not in m.plan["retter"][idag_index] and len(events) == 1


async def test_morgenen_og_dage_uden_mad(hass: HomeAssistant, idag_index) -> None:  # noqa: F811
    m, _ = await lav_madplan(hass)
    events = async_capture_events(hass, EVENT_KOK)
    assert not m.fyr_kok_i_dag()  # ingen kok i dag: intet
    m.plan["retter"][idag_index]["kok"] = "Silas"
    assert m.fyr_kok_i_dag()
    await hass.async_block_till_done()
    assert len(events) == 1 and events[0].data["kid"] == "Silas"
    # Spiser ude eller en dag, der er gået: intet event
    m.plan["retter"][idag_index]["fjernet"] = True
    assert not m.fyr_kok(idag_index)
    if idag_index:
        m.plan["retter"][idag_index - 1]["kok"] = "Silas"
        assert not m.fyr_kok(idag_index - 1)


async def test_link_til_egen_opskrift(hass: HomeAssistant, idag_index) -> None:  # noqa: F811
    m, _ = await lav_madplan(hass)
    await m.async_gem_min_ret({"navn": f"Ret {idag_index + 1}", "link": "https://example.com/ret"})
    events = async_capture_events(hass, EVENT_KOK)
    await m.async_dag_kok(idag_index + 1, "Silas")
    await hass.async_block_till_done()
    assert events[0].data["url"] == "https://example.com/ret"


async def test_ingen_lytter_ingen_fejl(hass: HomeAssistant, idag_index) -> None:  # noqa: F811
    m, _ = await lav_madplan(hass)
    await m.async_dag_kok(idag_index + 1, "Silas")  # ingen lytter på eventet
    await m.async_dag_kok(99, "Silas")  # en dag, der ikke findes
    assert m.plan["retter"][idag_index]["kok"] == "Silas"


def test_skemaet() -> None:
    assert DAG_KOK_SKEMA({"dag": 3, "kok": "person.silas"})["kok"] == "person.silas"
    assert DAG_KOK_SKEMA({"dag": 3, "kok": ""})["kok"] == ""
    with pytest.raises(vol.Invalid):
        DAG_KOK_SKEMA({"dag": 8, "kok": "x"})
    with pytest.raises(vol.Invalid):
        DAG_KOK_SKEMA({"dag": 1, "kok": "x" * 61})
