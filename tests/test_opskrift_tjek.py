"""Ugeplanen 22/11: karbonader 'med ærter' uden ærter, 50 g oksekød pr. person, flæskesteg på 60 min, 'Creme' -
og 'Tørrede krydderier' fundet som soltørrede tomater."""
import datetime

from custom_components.madplan import soeg
from custom_components.madplan.planlaegger import ret_problemer


def _ret(navn, ing, tid=30, trin=None):
    return {"navn": navn, "tid_min": tid, "trin": trin or [],
            "ingredienser": [{"navn": n, "pr_person": m, "enhed": e} for n, m, e in ing]}


def test_navnet_skal_passe():
    p = ret_problemer(_ret("Karbonader med ærter", [("Karbonader", 200, "g"), ("Majs", 100, "g"), ("Kartofler", 200, "g")]))
    assert any("ærter" in x for x in p)
    assert ret_problemer(_ret("Laksefilet med salat", [("Laksefilet", 140, "g"), ("Agurk", 50, "g")])) == []
    assert ret_problemer(_ret("Medister med rodfrugter", [("Medister", 150, "g"), ("Rodfrugtmix", 150, "g")])) == []


def test_for_lidt_koed_og_for_kort_tid():
    p = ret_problemer(_ret("Mexicansk oksekød-pande", [("Hakket dansk oksekød 15-18%", 50, "g"), ("Løg", 50, "g")]))
    assert any("50 g kød" in x for x in p)
    p = ret_problemer(_ret("Flæskesteg med rosenkål", [("Flæskesteg", 250, "g"), ("Rosenkål", 100, "g")], tid=60))
    assert any("mindst 90" in x for x in p)
    assert ret_problemer(_ret("Linsedahl", [("Røde linser", 80, "g")])) == []  # ingen kød: intet krav


def test_uklart_varenavn():
    assert any("Creme" in x for x in ret_problemer(_ret("Taco", [("Hakket oksekød", 150, "g"), ("Creme", 30, "g")])))


def test_tillaegsord_er_ingen_vare():
    kat = {"1": {"navn": "Soltørrede tomater", "str": "280 g", "pris": 14}}
    assert soeg.find_vare(kat, "Tørrede krydderier", datetime.date(2026, 11, 22), pris=lambda v, x: 14) is None


def test_navne_og_trin_ryddes():
    from custom_components.madplan.planlaegger import rens_ret

    ret = {"trin": ["Kog 100 g pasta efter anvisning.", "Skær 175g kylling pr. person i stykker."],
           "ingredienser": [{"navn": "S:Øko. kartofler", "vare": "S:Øko. kartofler"},
                            {"navn": "REMA 1000 tomater, 400 g", "vare": "T:1"},
                            {"navn": "", "vare": "R:9"}, {"navn": "", "vare": "S:Peber"}]}
    rens_ret(ret, lambda v: {"navn": "Salt m/jod"} if v == "R:9" else None)
    assert [i["navn"] for i in ret["ingredienser"]] == ["Øko. kartofler", "REMA 1000 tomater", "Salt m/jod", "Peber"]
    assert ret["trin"] == ["Kog pasta efter anvisning.", "Skær kylling i stykker."]


def test_vare_id_som_navn_bliver_varens_navn():
    """1.23.1: AI'en skrev tilbuddets id som navn - på ingredienslisten stod "400 g 9J6SDCIVEVPUWof3Xbh-L"."""
    from custom_components.madplan.planlaegger import rens_ret

    tilbud = {"9J6SDCIVEVPUWof3Xbh-L": {"navn": "REMA 1000 hakkede tomater"}}
    ret = {"ingredienser": [{"navn": "9J6SDCIVEVPUWof3Xbh-L", "vare": "T:9J6SDCIVEVPUWof3Xbh-L"},
                            {"navn": "T:9J6SDCIVEVPUWof3Xbh-L", "vare": "S:tomater"},
                            {"navn": "Oregano", "vare": "R:5"}]}
    rens_ret(ret, lambda v: tilbud.get(v[2:]) if v.startswith("T:") else {"navn": "Oregano tørret"})
    assert [i["navn"] for i in ret["ingredienser"]] == ["REMA 1000 hakkede tomater", "REMA 1000 hakkede tomater", "Oregano"]


def test_gemt_plan_faar_navnet_ved_start():
    """En plan lavet før rettelsen bliver rettet ved start, uden ny plan og uden AI."""
    from types import SimpleNamespace

    from custom_components.madplan.planlaegger import Madplan

    vid = "9J6SDCIVEVPUWof3Xbh-L"
    m = SimpleNamespace(plan={"tilbud": {vid: {"navn": "REMA 1000 hakkede tomater"}}, "retter": [
        {"ingredienser": [{"navn": vid, "vare": f"T:{vid}"}, {"navn": "Salt", "vare": "R:1"}],
         "_linjer": [f"400 g {vid}", "16 g Salt"], "udfoerlig": {"trin": [f"Tilsæt {vid}."], "tips": []}},
        {"fjernet": True, "ingredienser": []},
    ]})
    Madplan._ret_id_navne(m)
    ret = m.plan["retter"][0]
    assert ret["_linjer"] == ["400 g REMA 1000 hakkede tomater", "16 g Salt"]
    assert ret["ingredienser"][0]["navn"] == "REMA 1000 hakkede tomater"
    assert ret["udfoerlig"]["trin"] == ["Tilsæt REMA 1000 hakkede tomater."]
