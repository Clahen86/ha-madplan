"""1.24.2: alt i opskrifterne kommer på indkøbslisten, og "eller"-tilbud siger, hvilken der skal tages."""

import datetime

from homeassistant.core import HomeAssistant

from custom_components.madplan.planlaegger import _eller_til, vare_tekst

from .common import lav_madplan


def test_eller_tilbud_siger_hvilken():
    assert _eller_til("REMA 1000 Kikærter, bønner eller tomater", {"REMA 1000 tomater"}) == "tomater"
    assert _eller_til("REMA 1000 Dansk kylling", {"Kylling"}) is None
    assert _eller_til("Bønner/kikærter", {"Kidneybønner"}) == "kidneybønner"
    assert _eller_til("Mutti tomatprodukter, flere varianter", {"Hakkede tomater"}) == "hakkede tomater"
    assert _eller_til("Pålæg, div. sorter", {"Hamburgerryg"}) == "hamburgerryg"
    assert _eller_til("Udvalgte oste", {"Revet ost"}) == "revet ost"
    assert _eller_til("Rugbrød 1/2", {"Rugbrød"}) is None  # en brøk er ikke to varer
    v = {"navn": "REMA 1000 Kikærter, bønner eller tomater", "til": "tomater", "str": "240 g", "antal": 4, "tilbud": True}
    assert vare_tekst(v) == "🏷️ 4 × REMA 1000 Kikærter, bønner eller tomater → tomater (240 g)"


async def test_vare_uden_pris_falder_ikke_af_listen(hass: HomeAssistant) -> None:
    """Et tilbud, der ikke findes (forkert id) eller ikke har en pris, står på listen med sit navn - ikke væk."""
    m, _ = await lav_madplan(hass)
    start = datetime.date.today()
    m.tilbud = {"t1": {"navn": "REMA 1000 Kikærter, bønner eller tomater", "str": "240 g", "pris": 5.0}}
    ret = {"navn": "Pasta", "ingredienser": [
        {"navn": "Cherrytomater", "vare": "T:findes-ikke", "pr_person": 100, "enhed": "g"},
        {"navn": "REMA 1000 tomater", "vare": "T:t1", "pr_person": 240, "enhed": "g", "pakke": 240},
    ], "trin": []}
    m.plan = {"start": start.isoformat(), "retter": [ret] + [{"navn": "Ude", "fjernet": True, "ingredienser": []}] * 6}
    m._beregn()
    varer = {v["key"]: v for v in m.plan["varer"]}
    assert "S:cherrytomater" in varer and varer["S:cherrytomater"]["ukendt"] and varer["S:cherrytomater"]["antal"] == 1
    assert varer["T:t1"]["til"] == "tomater"


async def test_vare_uden_pris_findes_i_kataloget(hass: HomeAssistant) -> None:
    """Agurk på et tilbud uden pris: slås op i REMA's katalog - 1 stk pr. ret, ikke 400 g / AI'ens gæt på 1 g."""
    m, _ = await lav_madplan(hass)
    start = datetime.date.today()
    m.tilbud = {}
    m.katalog = {"55": {"navn": "Agurk", "str": "1 STK.", "priser": [{"pris": 8.0, "fra": "2000-01-01", "til": "2099-01-01", "kampagne": False}]}}
    m._slaa_op = lambda vid, d: ("Agurk", "1 stk", 8.0, None, False) if vid == "R:55" else (
        (vid[2:].capitalize(), "", 0.0, None, False) if str(vid).startswith("S:") else None)
    agurk = {"navn": "Agurk", "vare": "T:udloebet", "pr_person": 100, "enhed": "g", "pakke": 1}
    m.plan = {"start": start.isoformat(), "retter": [{"navn": "A", "ingredienser": [dict(agurk)], "trin": []},
              {"navn": "B", "ingredienser": [{**agurk, "vare": "S:agurk"}], "trin": []}]
              + [{"navn": "Ude", "fjernet": True, "ingredienser": []}] * 5}
    m._beregn()
    [v] = m.plan["varer"]
    assert v["key"] == "R:55" and v["antal"] == 2 and v["pris"] == 16.0


async def test_gemt_plan_rettes_ved_start(hass: HomeAssistant) -> None:
    """Ved start: det, der manglede, kommer på listen - til en dag, der er gået, skjult. En udførlig opskrift til en
    kommende dag med et "eller"-tilbud laves igen; dagens bliver (man står måske og laver den)."""
    m, _ = await lav_madplan(hass)

    async def intet(*a, **k):
        return None

    m._hent_data = intet
    idag = datetime.date.today()
    start = idag - datetime.timedelta(days=1)
    tilbud = {"t1": {"navn": "REMA 1000 Kikærter, bønner eller tomater", "str": "240 g", "pris": 5.0}}
    m.tilbud = tilbud

    def ret(navn, ing):
        return {"navn": navn, "ingredienser": ing, "trin": [], "udfoerlig": {"trin": ["x"], "tips": []}}

    cherry = {"navn": "Cherrytomater", "vare": "T:findes-ikke", "pr_person": 100, "enhed": "g"}
    eller = {"navn": "tomater", "vare": "T:t1", "pr_person": 240, "enhed": "g", "pakke": 240}
    m.plan = {"start": start.isoformat(), "tilbud": tilbud, "varer": [],
              "retter": [ret("I går", [cherry]), ret("I dag", [dict(eller)]), ret("I morgen", [dict(eller)])]
              + [{"navn": "Ude", "fjernet": True, "ingredienser": []}] * 4}
    await m._reparer_listen()
    varer = {v["key"]: v for v in m.plan["varer"]}
    assert varer["S:cherrytomater"]["skjult"]  # kun til i går
    assert not varer["T:t1"]["skjult"]  # bruges i morgen
    assert "udfoerlig" in m.plan["retter"][1] and "udfoerlig" not in m.plan["retter"][2]
    assert m.plan["rettet"] == 5


async def test_ikke_paa_listen_siges_i_opskriften(hass: HomeAssistant) -> None:
    """Dagens ret med noget, der aldrig var på listen: det står ved opskriften, AI'en får det at vide, og dagens
    udførlige opskrift laves igen."""
    m, _ = await lav_madplan(hass)

    async def intet(*a, **k):
        return None

    m._hent_data = intet
    idag = datetime.date.today()
    tilbud = {"t1": {"navn": "REMA 1000 Kikærter, bønner eller tomater", "str": "240 g", "pris": 5.0}}
    m.tilbud = tilbud
    ret = {"navn": "Pasta", "trin": [], "_linjer": ["960 g tomater", "400 g Cherrytomater"],
           "udfoerlig": {"trin": ["Skyl tomaterne"], "tips": []}, "ingredienser": [
               {"navn": "tomater", "vare": "T:t1", "pr_person": 240, "enhed": "g", "pakke": 240},
               {"navn": "Cherrytomater", "vare": "T:findes-ikke", "pr_person": 100, "enhed": "g"},
               {"navn": "Salt", "vare": "R:1", "basis": True}]}
    m.plan = {"start": idag.isoformat(), "tilbud": tilbud, "varer": [{"key": "T:t1", "kurv": True}], "retter": [ret]
              + [{"navn": "Ude", "fjernet": True, "ingredienser": []}] * 6}
    await m._reparer_listen()
    assert m.ikke_paa_listen(ret) == ["Cherrytomater"]
    assert "udfoerlig" not in ret
    linjer = m._linjer_til_ai(ret)
    assert any("IKKE KØBT" in x and "Cherrytomater" in x for x in linjer)
    assert any("købt som REMA 1000 Kikærter, bønner eller tomater" in x for x in linjer)
