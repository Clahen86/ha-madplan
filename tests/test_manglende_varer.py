"""1.24.2: alt i opskrifterne kommer på indkøbslisten, og "eller"-tilbud siger, hvilken der skal tages."""

import datetime

from homeassistant.core import HomeAssistant

from custom_components.madplan.planlaegger import _eller_til, vare_tekst

from .common import lav_madplan


def test_eller_tilbud_siger_hvilken():
    assert _eller_til("REMA 1000 Kikærter, bønner eller tomater", {"REMA 1000 tomater"}) == "tomater"
    assert _eller_til("REMA 1000 Dansk kylling", {"Kylling"}) is None
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
    assert "S:cherrytomater" in varer and varer["S:cherrytomater"]["ukendt"]
    assert varer["T:t1"]["til"] == "tomater"


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
    assert m.plan["rettet"] == 2
