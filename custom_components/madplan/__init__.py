"""Madplan: ugentlig aftensmadsplan ud fra ugens tilbud."""

from __future__ import annotations

import json
from pathlib import Path

import voluptuous as vol

from homeassistant.components import panel_custom
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import BUTIKKER, DOMAIN
from .planlaegger import Madplan

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SENSOR, Platform.TODO]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

KORT_URL = "/madplan/madplan-card.js"
NY_PLAN_SKEMA = vol.Schema(
    {vol.Optional("entity_id"): cv.entity_id, vol.Optional("handler"): vol.In(["i_dag", "i_morgen"])}
)
SKEMA = vol.Schema({vol.Optional("entity_id"): cv.entity_id})
_TEKST = vol.All(cv.string, vol.Length(min=2, max=80))
BEHOV_SKEMA = SKEMA.extend({vol.Required("tekst"): _TEKST})
# Flere behov på én gang løses i ét AI-kald.
NYE_BEHOV_SKEMA = SKEMA.extend({vol.Required("tekst"): vol.All(cv.ensure_list, [_TEKST], vol.Length(min=1, max=12))})
_LISTE = vol.All(cv.ensure_list, [vol.All(cv.string, vol.Length(min=1, max=60))], vol.Length(max=30))
REGLER_SKEMA = vol.Schema(
    {
        vol.Optional("budget"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=0, max=10000))),
        vol.Optional("oeko"): cv.boolean,
        vol.Optional("allergier"): _LISTE,
        vol.Optional("undgaa"): _LISTE,
        vol.Optional("favoritter"): _LISTE,
        vol.Optional("vegetar"): vol.All(vol.Coerce(int), vol.Range(min=0, max=7)),
        vol.Optional("fisk"): vol.All(vol.Coerce(int), vol.Range(min=0, max=7)),
        vol.Optional("max_tid"): vol.All(vol.Coerce(int), vol.Range(min=10, max=180)),
        vol.Optional("max_tid_weekend"): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
        vol.Optional("husstand"): vol.In(["boernefamilie", "voksne"]),
        vol.Optional("koekkener"): _LISTE,
        vol.Optional("fri_dage"): vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=6))]),
        vol.Optional("faste_dage"): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required("dag"): vol.All(vol.Coerce(int), vol.Range(min=0, max=6)),
                        vol.Required("ret"): vol.All(cv.string, vol.Length(min=1, max=60)),
                    }
                )
            ],
            vol.Length(max=7),
        ),
        vol.Optional("krav"): vol.All(cv.string, vol.Length(max=2000)),
        vol.Optional("niveau"): vol.In(["hverdag", "hygge", "gourmet"]),
        vol.Optional("min_varer_ekstra"): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
    }
)
ANTAL_SKEMA = SKEMA.extend(
    {vol.Required("uid"): cv.string, vol.Required("antal"): vol.All(vol.Coerce(int), vol.Range(min=1, max=50))}
)
MARKER_SKEMA = SKEMA.extend(
    {
        vol.Required("liste"): vol.In(["varer", "ekstra"]),
        vol.Required("uid"): cv.string,
        vol.Required("felt"): vol.In(["kurv", "hjemme"]),
        vol.Required("vaerdi"): cv.boolean,
    }
)
EN_RET_SKEMA = SKEMA.extend(
    {
        vol.Optional("har", default=[]): vol.All(cv.ensure_list, [vol.All(cv.string, vol.Length(min=1, max=60))], vol.Length(max=20)),
        vol.Optional("personer"): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
        vol.Optional("oenske", default=""): vol.All(cv.string, vol.Length(max=120)),
    }
)
EN_RET_ID_SKEMA = SKEMA.extend({vol.Required("id"): cv.string})
DAG_SKEMA = SKEMA.extend({vol.Required("dag"): vol.All(vol.Coerce(int), vol.Range(min=1, max=7))})
EKSTRA_BUTIKKER_SKEMA = SKEMA.extend(
    {vol.Required("butikker"): vol.All(cv.ensure_list, [vol.In(list(BUTIKKER))], vol.Length(max=2))}
)
RESTER_SKEMA = DAG_SKEMA.extend({vol.Optional("til", default=True): cv.boolean})
DAG_PERSONER_SKEMA = DAG_SKEMA.extend({vol.Required("personer"): vol.All(vol.Coerce(int), vol.Range(min=0, max=30))})

type MadplanConfigEntry = ConfigEntry[Madplan]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Services: ny_plan, byt_ret, fjern_ret og overfoer, plus dashboard-kortet."""
    await _registrer_kort(hass)

    def _madplaner(call: ServiceCall, alle: bool = False) -> list[Madplan]:
        """Madplanen for entity_id, eller den eneste (alle for ny_plan) hvis den er udeladt."""
        indlaest = [e.runtime_data for e in hass.config_entries.async_loaded_entries(DOMAIN)]
        if not indlaest:
            raise ServiceValidationError("Madplan er ikke sat op")
        if entity_id := call.data.get("entity_id"):
            reg = er.async_get(hass)
            ent = reg.async_get(entity_id)
            valgt = [m for m in indlaest if ent and m.entry.entry_id == ent.config_entry_id]
            if not valgt:
                raise ServiceValidationError(f"{entity_id} hører ikke til en madplan")
            return valgt
        if len(indlaest) == 1 or alle:
            return indlaest
        raise ServiceValidationError("Der er flere butikker; angiv entity_id")

    async def ny_plan(call: ServiceCall) -> None:
        for m in _madplaner(call, alle=True):
            m.entry.async_create_background_task(
                hass, m.async_ny_plan(handler=call.data.get("handler")), "madplan_ny_plan"
            )

    async def byt_ret(call: ServiceCall) -> None:
        m = _madplaner(call)[0]
        m.entry.async_create_background_task(hass, m.async_byt_ret(call.data["dag"]), "madplan_byt_ret")

    async def fjern_ret(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_fjern_ret(call.data["dag"])

    async def overfoer(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_overfoer()

    async def tilfoej_behov(call: ServiceCall) -> None:
        m = _madplaner(call)[0]
        m.entry.async_create_background_task(hass, m.async_tilfoej_behov(call.data["tekst"]), "madplan_behov")

    async def auto_plan(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_saet_auto_plan(call.data["til"])

    async def ekstra_butikker(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_saet_ekstra_butikker(call.data["butikker"])

    async def rester(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_rester(call.data["dag"], call.data["til"])

    async def dag_personer(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_dag_personer(call.data["dag"], call.data["personer"])

    async def en_ret(call: ServiceCall) -> None:
        m = _madplaner(call)[0]
        d = call.data
        m.entry.async_create_background_task(
            hass, m.async_en_ret(d["har"], d.get("personer"), d["oenske"]), "madplan_en_ret"
        )

    async def slet_en_ret(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_slet_en_ret(call.data["id"])

    async def dag_mail(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_dag_mail(call.data["dag"])

    async def en_ret_mail(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_en_ret_mail(call.data["id"])

    async def en_ret_paa_listen(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_en_ret_paa_listen(call.data["id"])

    async def marker(call: ServiceCall) -> None:
        d = call.data
        await _madplaner(call)[0].async_marker(d["liste"], d["uid"], d["felt"], d["vaerdi"])

    async def toem_kurv(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_toem_kurv()

    async def gem_regler(call: ServiceCall) -> None:
        # Reglerne er fælles; alle butikkers sensorer viser dem og deres advarsler.
        madplaner = _madplaner(call, alle=True)
        await madplaner[0].async_gem_regler(dict(call.data))
        for m in madplaner:
            m.opdater()

    async def ekstra_antal(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_ekstra_antal(call.data["uid"], call.data["antal"])

    async def fjern_behov(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_fjern_behov(call.data["tekst"])

    hass.services.async_register(DOMAIN, "ny_plan", ny_plan, schema=NY_PLAN_SKEMA)
    hass.services.async_register(DOMAIN, "byt_ret", byt_ret, schema=DAG_SKEMA)
    hass.services.async_register(DOMAIN, "fjern_ret", fjern_ret, schema=DAG_SKEMA)
    hass.services.async_register(DOMAIN, "overfoer", overfoer, schema=SKEMA)
    hass.services.async_register(DOMAIN, "tilfoej_behov", tilfoej_behov, schema=NYE_BEHOV_SKEMA)
    hass.services.async_register(DOMAIN, "gem_regler", gem_regler, schema=REGLER_SKEMA)
    hass.services.async_register(DOMAIN, "marker", marker, schema=MARKER_SKEMA)
    hass.services.async_register(DOMAIN, "en_ret", en_ret, schema=EN_RET_SKEMA)
    hass.services.async_register(DOMAIN, "slet_en_ret", slet_en_ret, schema=EN_RET_ID_SKEMA)
    hass.services.async_register(DOMAIN, "en_ret_paa_listen", en_ret_paa_listen, schema=EN_RET_ID_SKEMA)
    hass.services.async_register(DOMAIN, "en_ret_mail", en_ret_mail, schema=EN_RET_ID_SKEMA)
    hass.services.async_register(DOMAIN, "dag_mail", dag_mail, schema=DAG_SKEMA)
    hass.services.async_register(DOMAIN, "dag_personer", dag_personer, schema=DAG_PERSONER_SKEMA)
    hass.services.async_register(DOMAIN, "rester", rester, schema=RESTER_SKEMA)
    hass.services.async_register(DOMAIN, "ekstra_butikker", ekstra_butikker, schema=EKSTRA_BUTIKKER_SKEMA)
    hass.services.async_register(DOMAIN, "auto_plan", auto_plan, schema=SKEMA.extend({vol.Required("til"): cv.boolean}))
    hass.services.async_register(DOMAIN, "toem_kurv", toem_kurv, schema=SKEMA)
    hass.services.async_register(DOMAIN, "fjern_behov", fjern_behov, schema=BEHOV_SKEMA)
    hass.services.async_register(DOMAIN, "ekstra_antal", ekstra_antal, schema=ANTAL_SKEMA)
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
    # Eget punkt i sidemenuen, så madplanen virker som en app uden opsætning af dashboards.
    if "madplan" not in hass.data.get("frontend_panels", {}):
        await panel_custom.async_register_panel(
            hass,
            webcomponent_name="madplan-panel",
            frontend_url_path="madplan",
            module_url=f"{KORT_URL}?v={version}",
            sidebar_title="Madplan",
            sidebar_icon="mdi:silverware-fork-knife",
        )


async def async_setup_entry(hass: HomeAssistant, entry: MadplanConfigEntry) -> bool:
    """Sæt Madplan op fra en config entry."""
    madplan = Madplan(hass, entry)
    await madplan.async_indlaes()
    entry.runtime_data = madplan

    @callback
    def _automatisk(now) -> None:
        if not madplan.auto_plan:
            return  # "sovende" butik: laver kun plan, når man selv trykker
        nu = dt_util.as_local(now)
        # Lørdag kl. 10: næste uges plan - venter, hvis den nye avis ikke er ude endnu.
        if nu.weekday() == 5 and nu.hour == 10:
            entry.async_create_background_task(hass, madplan.async_ny_plan(vent_paa_tilbud=True), "madplan_lordag")
        # Søndag kl. 7: lav planen, hvis lørdagens ventede (eller ikke blev lavet).
        elif nu.weekday() == 6 and nu.hour == 7 and madplan.plan.get("start") != nu.date().isoformat():
            entry.async_create_background_task(hass, madplan.async_ny_plan(), "madplan_sondag")

    entry.async_on_unload(async_track_time_change(hass, _automatisk, hour=[7, 10], minute=0, second=0))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Hovedsensoren peger på de andre enheder; nu er de alle registreret.
    madplan.opdater()
    if madplan.ny:
        # Ny butik: lav den første plan med det samme, så kortet ikke står tomt.
        entry.async_create_background_task(hass, madplan.async_ny_plan(), "madplan_foerste_plan")
    entry.async_on_unload(entry.add_update_listener(_opdateret))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MadplanConfigEntry) -> bool:
    """Fjern Madplan."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _opdateret(hass: HomeAssistant, entry: MadplanConfigEntry) -> None:
    """Genindlæs når indstillingerne ændres."""
    await hass.config_entries.async_reload(entry.entry_id)
