"""Flyt dag: en ret bytter plads med en anden dag - restedage følger med, kok og personer bliver på dagen."""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .common import lav_madplan


def _uge() -> list[dict]:
    return [{"navn": f"Ret {i}", "trin": [], "ingredienser": []} for i in range(7)]


async def _klar(hass: HomeAssistant, retter: list[dict]):
    m, _ = await lav_madplan(hass)

    async def intet(*a, **k):
        return None

    m._hent_data = intet
    m._beregn = lambda: None
    m.plan = {"start": "2026-11-22", "retter": retter}
    return m


async def test_to_dage_bytter(hass: HomeAssistant) -> None:
    retter = _uge()
    retter[1]["kok"] = "Mor"
    retter[4]["personer"] = 6
    m = await _klar(hass, retter)
    await m.async_flyt_ret(5, 2)  # torsdagens ret på mandag
    navne = [r["navn"] for r in m.plan["retter"]]
    assert navne[1] == "Ret 4" and navne[4] == "Ret 1"
    assert m.plan["retter"][1]["kok"] == "Mor" and "personer" not in m.plan["retter"][1]
    assert m.plan["retter"][4]["personer"] == 6 and "kok" not in m.plan["retter"][4]


async def test_rester_foelger_med(hass: HomeAssistant) -> None:
    retter = _uge()
    m = await _klar(hass, retter)
    m._lav_rester(retter, 1)  # mandag til 2 dage, tirsdag rester
    await m.async_flyt_ret(2, 5)  # til torsdag
    r = m.plan["retter"]
    assert r[4]["navn"] == "Ret 1" and r[4]["dobbelt"]
    assert r[5]["rester_fra"] == 4 and "torsdag" in r[5]["kort"]
    assert [r[1]["navn"], r[2]["navn"]] == ["Ret 4", "Ret 5"]


async def test_rester_en_dag_frem(hass: HomeAssistant) -> None:
    retter = _uge()
    m = await _klar(hass, retter)
    m._lav_rester(retter, 1)
    await m.async_flyt_ret(3, 3)  # fra restedagen: hele retten en dag frem (mandag -> tirsdag)
    r = m.plan["retter"]
    assert r[1]["navn"] == "Ret 3" and r[2]["navn"] == "Ret 1" and r[3]["rester_fra"] == 2


async def test_ikke_ind_i_andres_rester(hass: HomeAssistant) -> None:
    retter = _uge()
    m = await _klar(hass, retter)
    m._lav_rester(retter, 4)
    with pytest.raises(HomeAssistantError):
        await m.async_flyt_ret(2, 6)
    assert m.plan["retter"][1]["navn"] == "Ret 1"


async def test_ikke_paa_dag_foer_planen(hass: HomeAssistant) -> None:
    retter = _uge()
    retter[0] = {"navn": "Før planen", "fjernet": True, "forbi": True}
    m = await _klar(hass, retter)
    with pytest.raises(HomeAssistantError):
        await m.async_flyt_ret(3, 1)


async def test_madspild_ikke_senere(hass: HomeAssistant) -> None:
    retter = _uge()
    retter[1]["ingredienser"] = [{"navn": "Hakket oksekød", "vare": "T:madspild-123"}]
    m = await _klar(hass, retter)
    with pytest.raises(HomeAssistantError):
        await m.async_flyt_ret(2, 6)
    with pytest.raises(HomeAssistantError):
        await m.async_flyt_ret(6, 2)  # madspild-retten ville blive skubbet til fredag
    await m.async_flyt_ret(1, 2)  # søndagens ret på mandag: madspild-retten kommer en dag tidligere
    assert [r["navn"] for r in m.plan["retter"][:2]] == ["Ret 1", "Ret 0"]

