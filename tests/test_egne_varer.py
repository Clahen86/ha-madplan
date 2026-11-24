"""1.24: Egne varer - skrevet på som de står, pris kun når man beder om den, ↻ = med hver uge."""

import datetime

from homeassistant.core import HomeAssistant

from custom_components.madplan.planlaegger import EGNE, _egne_videre

from .common import lav_madplan


async def _klar(hass: HomeAssistant):
    m, _ = await lav_madplan(hass)
    m.plan["ekstra"] = []

    async def intet(*a, **k):
        return None

    m._hent_data = intet
    return m


async def test_skrevet_paa_som_det_staar_uden_pris(hass: HomeAssistant) -> None:
    m = await _klar(hass)
    await m.async_egen_vare("  Toiletpapir ")
    await m.async_egen_vare("toiletpapir")  # står der allerede
    [e] = m.plan["ekstra"]
    assert e["navn"] == "Toiletpapir" and e["egen"] and e["behov"] == EGNE and e["ukendt"] and e["pris"] == 0
    assert m.plan["ekstra_uden_pris"] == 1 and m.plan["ekstra_total"] == 0


async def test_find_priser_tilbud_foerst_ellers_almindelig_pris(hass: HomeAssistant) -> None:
    m = await _klar(hass)
    idag = datetime.date.today()
    m.tilbud = {"t1": {"navn": "Lambi toiletpapir 8 rl", "str": "8 rl", "pris": 25.0}}
    m.katalog = {"7": {"navn": "Arla Letmælk", "str": "1 l", "pris": 11.5}}
    m._find_vare = lambda v, d, b, kun_mad=True: "R:7" if "mælk" in v.lower() else "S:" + v[2:]
    m._slaa_op = lambda vid, d: ({"T:t1": ("Lambi toiletpapir 8 rl", "8 rl", 25.0, None, True),
                                  "R:7": ("Arla Letmælk", "1 l", 11.5, None, False)}).get(vid)
    for t in ("Toiletpapir", "Mælk", "Blå ting"):
        await m.async_egen_vare(t)
    varerne_foer = [dict(v) for v in m.plan["varer"]]
    m._find_egne_priser([e for e in m.plan["ekstra"] if e.get("egen")], idag)
    m._totaler()
    papir, maelk, blaa = m.plan["ekstra"]
    assert papir["tilbud"] and papir["pris"] == 25.0 and papir["vare"] == "Lambi toiletpapir 8 rl"
    assert not maelk["tilbud"] and maelk["pris"] == 11.5
    assert blaa["ikke_fundet"] and blaa["ukendt"]
    assert m.plan["ekstra_total"] == 36 and m.plan["ekstra_uden_pris"] == 1
    assert m.plan["varer"] == varerne_foer  # aftensmadens varer røres ikke


async def test_hver_uge_kommer_med_i_ny_plan(hass: HomeAssistant) -> None:
    m = await _klar(hass)
    await m.async_egen_vare("Kaffe")
    await m.async_egen_vare("Gaveindpakning")
    kaffe = m.plan["ekstra"][0]
    await m.async_hver_uge(kaffe["uid"], True)
    kaffe.update(pris=40.0, ukendt=False, hjemme=True, antal=2)
    videre = _egne_videre(m.plan["ekstra"] + [{"uid": "e1", "navn": "Rugbrød", "behov": "madpakker"}])
    assert [(e["navn"], e["antal"], e["hver_uge"], e["hjemme"], e["ukendt"]) for e in videre] == [("Kaffe", 2, True, False, True)]
