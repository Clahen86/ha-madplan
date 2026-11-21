"""Madplan som app fra et link: hvad linket kan se, det eneste det må ændre, siderne og administratorens links."""

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.madplan import app

from .common import lav_madplan


async def _klar(hass: HomeAssistant) -> app.AppLinks:
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "websocket_api", {})
    await app.async_setup(hass)
    return hass.data[app.DATA]


async def test_link_findes_kun_med_den_rigtige_noegle(hass: HomeAssistant, hass_storage) -> None:
    links = await _klar(hass)
    link = await links.async_opret("Køkkenet", "")
    assert links.ved_token(link["token"]) is link
    assert links.ved_token("forkert") is None and links.ved_token("") is None
    assert hass_storage["madplan.app_links"]["data"]["links"]
    lid = next(iter(links.links))
    assert await links.async_slet(lid) and links.ved_token(link["token"]) is None


async def test_appen_ser_planen_og_kan_kun_krydse_af(hass: HomeAssistant, hass_client_no_auth) -> None:
    links = await _klar(hass)
    m, eid = await lav_madplan(hass)
    datter, datter_eid = await lav_madplan(hass, profil="datter", butik="netto")
    token = (await links.async_opret("Silas", ""))["token"]
    client = await hass_client_no_auth()

    r = await client.get(f"/api/madplan/app/{token}/data")
    assert r.status == 200
    d = await r.json()
    assert d["navn"] == "Silas" and eid in d["states"] and datter_eid not in d["states"]  # kun egen profil
    assert "profiler" not in d["states"][eid]["attributes"]  # ingen HA-bruger-id'er
    assert all(x in d["states"] for x in d["states"][eid]["attributes"]["dag_entiteter"])
    varer = d["todo"]["todo.madplan_rema1000_varer"]
    assert varer[0]["uid"] == "pasta" and varer[0]["status"] == "needs_action"
    assert d["todo"]["todo.madplan_rema1000_ekstra"][0]["summary"].endswith("Rugbrød")

    r = await client.post(f"/api/madplan/app/{token}/marker",
                          json={"entity_id": eid, "liste": "varer", "uid": "pasta", "felt": "kurv", "vaerdi": True})
    assert r.status == 200 and m.plan["varer"][0]["kurv"] is True
    assert (await r.json())["todo"]["todo.madplan_rema1000_varer"][0]["status"] == "completed"
    # Ikke en anden profils plan, ikke forkerte felter, intet andet end at krydse af
    r = await client.post(f"/api/madplan/app/{token}/marker",
                          json={"entity_id": datter_eid, "liste": "varer", "uid": "pasta", "felt": "kurv", "vaerdi": True})
    assert r.status == 404 and not datter.plan["varer"][0].get("kurv")
    assert (await client.post(f"/api/madplan/app/{token}/marker", json={"entity_id": eid, "liste": "regler"})).status == 400
    for handling in ("ny_plan", "gem_regler", "en_ret", "byt_ret", "dag_kok"):
        assert (await client.post(f"/api/madplan/app/{token}/{handling}", json={"entity_id": eid, "dag": 1})).status == 404
    assert m.plan["retter"][0]["navn"] == "Ret 1"
    # Et ukendt link kan ingenting
    assert (await client.get("/api/madplan/app/forkert/data")).status == 404
    assert (await client.post("/api/madplan/app/forkert/marker",
                              json={"entity_id": eid, "liste": "varer", "uid": "pasta", "felt": "kurv", "vaerdi": False})).status == 404
    assert m.plan["varer"][0]["kurv"] is True


async def test_siderne(hass: HomeAssistant, hass_client_no_auth) -> None:
    links = await _klar(hass)
    token = (await links.async_opret("Køkkenet", ""))["token"]
    client = await hass_client_no_auth()
    r = await client.get(f"/madplan_app/{token}/")
    html = await r.text()
    assert r.status == 200 and "MADPLAN_APP" in html and f"/api/madplan/app/{token}" in html and "Installer" in html
    r = await client.get(f"/madplan_app/{token}/manifest.webmanifest")
    assert r.status == 200 and (await r.json())["start_url"] == f"/madplan_app/{token}/"
    assert (await client.get(f"/madplan_app/{token}/sw.js")).status == 200
    assert (await client.get("/madplan_app-icon/512.png")).status == 200
    assert (await client.get("/madplan_app/forkert/")).status == 404


async def test_kun_en_admin_laver_links(hass: HomeAssistant, hass_ws_client, hass_admin_user) -> None:
    links = await _klar(hass)
    await lav_madplan(hass, profil="datter", butik="netto")
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "madplan/app_links", "opret": {"navn": "Datter", "profil": "datter"}})
    r = await ws.receive_json()
    assert r["success"] and r["result"]["links"][0]["navn"] == "Datter" and r["result"]["links"][0]["profil"] == "datter"
    assert r["result"]["links"][0]["rolle"] == "boern"
    assert "/madplan_app/" in r["result"]["links"][0]["url"]
    await ws.send_json({"id": 2, "type": "madplan/app_links", "opret": {"navn": "X", "profil": "findes_ikke"}})
    assert not (await ws.receive_json())["success"]
    await ws.send_json({"id": 3, "type": "madplan/app_links", "slet": r["result"]["links"][0]["id"]})
    assert (await ws.receive_json())["result"]["links"] == [] and not links.links
    hass_admin_user.groups = []  # ikke længere administrator
    await ws.send_json({"id": 4, "type": "madplan/app_links", "opret": {"navn": "Y"}})
    r = await ws.receive_json()
    assert not r["success"] and r["error"]["code"] == "unauthorized"


async def test_integrationen_saetter_appen_op(hass: HomeAssistant, hass_client_no_auth) -> None:
    """Madplans egen opsætning: tjenesten dag_kok, appens sider og QR-makeren (uden HA's frontend og AI)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    import custom_components.madplan as mp
    import custom_components.madplan.hjaelp as hj

    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "websocket_api", {})
    with patch.object(hj, "async_setup_hjaelp", AsyncMock()), patch.object(mp, "add_extra_js_url", MagicMock()), \
            patch.object(mp.panel_custom, "async_register_panel", AsyncMock()):
        assert await mp.async_setup(hass, {})
    assert hass.services.has_service("madplan", "dag_kok") and app.DATA in hass.data
    client = await hass_client_no_auth()
    assert (await client.get("/madplan/qr.js")).status == 200
    token = (await hass.data[app.DATA].async_opret("Køkkenet", ""))["token"]
    assert hass.data["madplan_kort_url"] in await (await client.get(f"/madplan_app/{token}/")).text()


async def test_voksenlink_styrer_ugens_plan_men_ikke_resten(hass: HomeAssistant, hass_client_no_auth) -> None:
    links = await _klar(hass)
    m, eid = await lav_madplan(hass)
    _, datter_eid = await lav_madplan(hass, profil="datter", butik="netto")
    hass.states.async_set("person.silas", "home", {"friendly_name": "Silas", "user_id": "hemmelig"})
    kald = []

    async def fang(call):
        kald.append((call.service, dict(call.data)))

    for navn in ("dag_kok", "ny_plan", "gem_regler", "auto_plan"):
        hass.services.async_register("madplan", navn, fang)
    voksen = (await links.async_opret("Mor", "", "voksen"))["token"]
    barn = (await links.async_opret("Silas", ""))["token"]
    client = await hass_client_no_auth()

    d = await (await client.get(f"/api/madplan/app/{voksen}/data")).json()
    assert d["rolle"] == "voksen" and d["states"]["person.silas"]["attributes"] == {"friendly_name": "Silas"}
    assert "person.silas" not in (await (await client.get(f"/api/madplan/app/{barn}/data")).json())["states"]

    async def post(token, domain, service, data):
        return await client.post(f"/api/madplan/app/{token}/kald", json={"domain": domain, "service": service, "data": data})

    assert (await post(voksen, "madplan", "dag_kok", {"entity_id": eid, "dag": 1, "kok": "person.silas"})).status == 200
    assert (await post(voksen, "madplan", "gem_regler", {"entity_id": eid, "fri_dage": [5]})).status == 200
    assert kald == [("dag_kok", {"entity_id": eid, "dag": 1, "kok": "person.silas"}), ("gem_regler", {"entity_id": eid, "fri_dage": [5]})]
    # Ikke reglerne, ikke andre handlinger, ikke en anden profils plan, ikke andre domæner - og aldrig fra et børnelink
    assert (await post(voksen, "madplan", "gem_regler", {"entity_id": eid, "budget": 1})).status == 403
    assert (await post(voksen, "madplan", "auto_plan", {"entity_id": eid, "til": True})).status == 403
    assert (await post(voksen, "madplan", "dag_kok", {"entity_id": datter_eid, "dag": 1, "kok": "x"})).status == 403
    assert (await post(voksen, "light", "turn_on", {"entity_id": "light.stue"})).status == 400
    assert (await post(voksen, "number", "set_value", {"entity_id": "number.andet", "value": 3})).status == 403
    assert (await post(barn, "madplan", "dag_kok", {"entity_id": eid, "dag": 1, "kok": "x"})).status == 403
    assert len(kald) == 2
    # "Én ret": voksen-linket ser den og kan bruge den, børnelinket hverken ser eller kan
    hass.services.async_register("madplan", "en_ret_byt", fang)
    hass.states.async_set(eid, "123", {**hass.states.get(eid).attributes, "en_ret": [{"id": "a"}], "en_ret_status": ""})
    assert (await (await client.get(f"/api/madplan/app/{voksen}/data")).json())["states"][eid]["attributes"]["en_ret"] == [{"id": "a"}]
    assert "en_ret" not in (await (await client.get(f"/api/madplan/app/{barn}/data")).json())["states"][eid]["attributes"]
    assert (await post(voksen, "madplan", "en_ret_byt", {"entity_id": eid, "id": "a"})).status == 200
    assert (await post(barn, "madplan", "en_ret_byt", {"entity_id": eid, "id": "a"})).status == 403
    assert kald[-1] == ("en_ret_byt", {"entity_id": eid, "id": "a"}) and len(kald) == 3
    # Siden ved, om den må styre
    side = await (await client.get(f"/madplan_app/{voksen}/")).text()
    assert "voksen: true" in side
    assert "voksen: false" in await (await client.get(f"/madplan_app/{barn}/")).text()
