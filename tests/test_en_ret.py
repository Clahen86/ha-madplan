"""Én ret kan det samme som en ret i ugeplanen: byt, udførlig opskrift, personer, gem som min ret og REMA-appen."""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .common import lav_madplan


def _ret(**kw) -> dict:
    r = {"id": "a", "navn": "Kyllingewok", "personer": 2, "har": ["ris"], "oenske": "asiatisk", "trin": ["Steg"],
         "ingredienser": ["300 g Kylling", "ris (efter smag)"], "koeb": [], "koeb_total": 0, "koeb_ca": False,
         "_ing": [{"navn": "Kylling", "pr_person": 150, "enhed": "g", "vare": "R:123", "pakke": 0},
                  {"navn": "Ris", "pr_person": 80, "enhed": "g", "vare": "R:9", "pakke": 0}]}
    r.update(kw)
    return r


async def _klar(hass: HomeAssistant):
    m, _ = await lav_madplan(hass)

    async def intet(*a, **k):
        return None

    m._hent_data = intet
    m._slaa_op = lambda vare, dato: ("Kyllingebryst", "500 g", 40.0, None, False) if vare == "R:123" else None
    m.en_ret = [_ret()]
    return m


async def test_flere_personer_regner_maengder_og_indkoeb_om(hass: HomeAssistant) -> None:
    m = await _klar(hass)
    m.en_ret[0]["udfoerlig"] = {"trin": ["gammel"], "tips": []}
    await m.async_en_ret_personer("a", 4)
    r = m.en_ret[0]
    assert r["personer"] == 4 and r["ingredienser"][0] == "600 g Kylling"
    assert [v["navn"] for v in r["koeb"]] == ["Kyllingebryst"]  # risen har de
    assert r["koeb"][0]["key"] == "R:123" and r["koeb_total"] == 40 and r["pr_person"] == 10.0
    assert "udfoerlig" not in r  # mængderne i trinene passer ikke længere


async def test_en_gammel_ret_kan_ikke_regnes_om(hass: HomeAssistant) -> None:
    m = await _klar(hass)
    m.en_ret[0].pop("_ing")
    with pytest.raises(HomeAssistantError):
        await m.async_en_ret_personer("a", 4)


async def test_byt_finder_en_anden_ud_fra_det_samme(hass: HomeAssistant) -> None:
    m = await _klar(hass)
    kald = []

    async def en_ret(har, personer, oenske, erstat=None):
        kald.append((har, personer, oenske, erstat))

    m.async_en_ret = en_ret
    await m.async_en_ret_byt("a")
    assert kald == [(["ris"], 2, "asiatisk", "a")]
    with pytest.raises(HomeAssistantError):
        await m.async_en_ret_byt("findes-ikke")


async def test_gem_som_min_ret(hass: HomeAssistant) -> None:
    m = await _klar(hass)
    gemt = []

    async def gem(data):
        gemt.append(data)
        return "m1"

    m.async_gem_min_ret = gem
    m.en_ret[0]["udfoerlig"] = {"trin": ["Skær kyllingen", "Steg i 5 min"], "tips": []}
    await m.async_en_ret_gem("a")
    assert gemt == [{"navn": "Kyllingewok", "portioner": 2, "ingredienser": "300 g Kylling\nris (efter smag)",
                     "fremgangsmaade": "Skær kyllingen\nSteg i 5 min"}]
    assert m.en_ret[0]["min_ret"] == "m1" and m.en_ret_status.startswith("✅")


async def test_til_rema_appen(hass: HomeAssistant) -> None:
    m = await _klar(hass)
    await m.async_en_ret_personer("a", 4)
    with pytest.raises(HomeAssistantError):  # ikke sat op
        await m.async_en_ret_rema("a")
    hass.config_entries.async_update_entry(m.entry, options={"rema_email": "x@y.dk", "rema_kode": "k"})
    m.katalog = {"123": {"navn": "Kyllingebryst"}}
    sendt = []

    async def send(varer, retter=None):
        sendt.append((varer, retter))
        return "✅ 1 varer lagt i REMA-appen"

    m._send_til_rema = send
    await m.async_en_ret_rema("a")
    varer, retter = sendt[0]
    assert varer == [{"key": "R:123", "navn": "Kyllingebryst", "str": "500 g", "antal": 1, "pris": 40.0, "tilbud": False}]
    assert retter[0]["ingredienser"][0]["navn"] == "Kylling"  # rettens eget navn for varen, som ugeplanen
    assert m.en_ret_status.startswith("✅ 1")


def test_rema_bruger_rettens_egne_navne(hass: HomeAssistant) -> None:
    from custom_components.madplan.planlaegger import Madplan

    m = Madplan.__new__(Madplan)
    m.plan = {}
    m.katalog = {"55": {"navn": "REMA 1000 Kyllingebryst", "str": "500 g"}}
    ud = m._rema_varer([{"key": "S:Kylling", "navn": "Noget andet", "antal": 2}],
                       [{"ingredienser": [{"vare": "S:Kylling", "navn": "Kyllingebryst"}]}])
    assert ud == [{"product_id": 55, "amount": 2}]
