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
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util, slugify

from .const import BUTIKKER, CONF_PROFIL, DOMAIN
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
        vol.Optional("entity_id"): cv.entity_id,
        vol.Optional("budget"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=0, max=10000))),
        vol.Optional("oeko"): cv.boolean,
        vol.Optional("madspild"): cv.boolean,
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
        vol.Optional("mine_hyppighed"): vol.In(["aldrig", "nogle", "ofte"]),
        vol.Optional("kcal"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=200, max=2000))),
        vol.Optional("protein"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=5, max=150))),
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
# Familiens egen opskrift. Uden id oprettes en ny (eller den med samme navn rettes).
MIN_RET_SKEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_id,
        vol.Optional("id"): cv.string,
        vol.Optional("navn"): vol.All(cv.string, vol.Length(min=1, max=60)),
        vol.Optional("aktiv"): cv.boolean,
        vol.Optional("dage"): vol.All(vol.Coerce(int), vol.In([1, 2])),
        vol.Optional("portioner"): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
        # Kun almindelige web-links, så kortet aldrig viser et javascript:-link.
        vol.Optional("link"): vol.Any("", vol.All(cv.string, vol.Length(max=300), vol.Match(r"^https?://"))),
        vol.Optional("noter"): vol.All(cv.string, vol.Length(max=400)),
        vol.Optional("ingredienser"): vol.All(cv.string, vol.Length(max=2000)),
        vol.Optional("fremgangsmaade"): vol.All(cv.string, vol.Length(max=4000)),
    }
)
MIN_RET_ID_SKEMA = vol.Schema({vol.Optional("entity_id"): cv.entity_id, vol.Required("id"): cv.string})
DAG_SKEMA = SKEMA.extend({vol.Required("dag"): vol.All(vol.Coerce(int), vol.Range(min=1, max=7))})
EKSTRA_BUTIKKER_SKEMA = SKEMA.extend(
    {vol.Required("butikker"): vol.All(cv.ensure_list, [vol.In(list(BUTIKKER))], vol.Length(max=2))}
)
RESTER_SKEMA = DAG_SKEMA.extend({vol.Optional("til", default=True): cv.boolean})
DAG_PERSONER_SKEMA = DAG_SKEMA.extend({vol.Required("personer"): vol.All(vol.Coerce(int), vol.Range(min=0, max=30))})

PROFIL_SKEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_id,
        vol.Optional("id"): cv.string,  # tom = ny profil; "" kan ikke sendes, så hovedprofilen hedder "hoved"
        vol.Required("navn"): vol.All(cv.string, vol.Length(min=1, max=40)),
        vol.Optional("brugere", default=[]): vol.All(cv.ensure_list, [cv.string], vol.Length(max=50)),
        vol.Optional("butik"): vol.In(list(BUTIKKER)),
    }
)
SLET_PROFIL_SKEMA = vol.Schema({vol.Optional("entity_id"): cv.entity_id, vol.Required("id"): cv.string})

type MadplanConfigEntry = ConfigEntry[Madplan]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Services: ny_plan, byt_ret, fjern_ret og overfoer, plus dashboard-kortet."""
    await _registrer_kort(hass)
    from .hjaelp import async_setup_hjaelp

    hjaelp = await async_setup_hjaelp(hass)
    hass.data["madplan_hjaelp"] = hjaelp  # ikke i hass.data[DOMAIN]: det er planernes fælles opslag

    async def tjek(call: ServiceCall) -> ServiceResponse:
        return {"resultat": await hjaelp.async_tjek()}

    async def faa_hjaelp(call: ServiceCall) -> ServiceResponse:
        return await hjaelp.async_faa_hjaelp(call.data.get("besked", ""), call.data.get("billeder") or [])

    async def hjaelp_status(call: ServiceCall) -> ServiceResponse:
        return await hjaelp.async_status()

    async def skjul_svar(call: ServiceCall) -> ServiceResponse:
        return await hjaelp.async_skjul(call.data["noegle"])

    async def skriv_tilbage(call: ServiceCall) -> ServiceResponse:
        return await hjaelp.async_skriv_tilbage(call.data["id"], call.data["tekst"])

    async def del_anonymt(call: ServiceCall) -> None:
        await hjaelp.async_saet_del(call.data["til"])

    hass.services.async_register(DOMAIN, "tjek", tjek, schema=vol.Schema({}), supports_response=SupportsResponse.ONLY)
    hass.services.async_register(
        DOMAIN, "faa_hjaelp", faa_hjaelp, supports_response=SupportsResponse.ONLY,
        schema=vol.Schema({vol.Optional("besked", default=""): vol.All(cv.string, vol.Length(max=4000)),
                           vol.Optional("billeder", default=[]): vol.All(cv.ensure_list, vol.Length(max=3), [dict])}),
    )
    hass.services.async_register(DOMAIN, "hjaelp_status", hjaelp_status, schema=vol.Schema({}), supports_response=SupportsResponse.ONLY)
    hass.services.async_register(
        DOMAIN, "skriv_tilbage", skriv_tilbage, supports_response=SupportsResponse.ONLY,
        schema=vol.Schema({vol.Required("id"): cv.string, vol.Required("tekst"): vol.All(cv.string, vol.Length(min=1, max=4000))}),
    )
    hass.services.async_register(DOMAIN, "skjul_svar", skjul_svar, supports_response=SupportsResponse.ONLY,
                                 schema=vol.Schema({vol.Required("noegle"): cv.string}))
    hass.services.async_register(DOMAIN, "del_anonymt", del_anonymt, schema=vol.Schema({vol.Required("til"): cv.boolean}))

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

    async def udfoerlig(call: ServiceCall) -> None:
        m = _madplaner(call)[0]
        m.entry.async_create_background_task(hass, m.async_udfoerlig(call.data["dag"]), "madplan_udfoerlig")

    async def fjern_ret(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_fjern_ret(call.data["dag"])

    async def overfoer(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_overfoer(call.data.get("til", "liste"))

    async def tilfoej_behov(call: ServiceCall) -> None:
        m = _madplaner(call)[0]
        m.entry.async_create_background_task(hass, m.async_tilfoej_behov(call.data["tekst"]), "madplan_behov")

    async def auto_plan(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_saet_auto_plan(call.data["til"])
        # Alle butikker viser den samlede liste, så de opdateres alle.
        for e in hass.config_entries.async_loaded_entries(DOMAIN):
            e.runtime_data.opdater()

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

    def _alle(call: ServiceCall) -> list[Madplan]:
        """Regler og Mine retter er fælles for butikkerne i samme profil: den med entity_id først, så resten.
        Uden entity_id er det hovedprofilen (som før profilerne)."""
        if not (indlaest := [e.runtime_data for e in hass.config_entries.async_loaded_entries(DOMAIN)]):
            raise ServiceValidationError("Madplan er ikke sat op")
        if call.data.get("entity_id"):
            valgt = _madplaner(call)[0]
        else:
            valgt = next((m for m in indlaest if not m.profil), indlaest[0])
        return [valgt] + [m for m in indlaest if m.profil == valgt.profil and m is not valgt]

    async def gem_regler(call: ServiceCall) -> None:
        madplaner = _alle(call)
        await madplaner[0].async_gem_regler({k: v for k, v in call.data.items() if k != "entity_id"})
        for m in madplaner:
            m.opdater()

    async def gem_min_ret(call: ServiceCall) -> ServiceResponse:
        madplaner = _alle(call)
        ret_id = await madplaner[0].async_gem_min_ret({k: v for k, v in call.data.items() if k != "entity_id"})
        for m in madplaner:
            m.opdater()
        return {"id": ret_id}

    async def slet_min_ret(call: ServiceCall) -> None:
        madplaner = _alle(call)
        await madplaner[0].async_slet_min_ret(call.data["id"])
        for m in madplaner:
            m.opdater()

    async def _admin(call: ServiceCall) -> None:
        """Profiler styres kun af en administrator - ellers kunne en profil flytte sig selv over i en anden."""
        bruger = await hass.auth.async_get_user(call.context.user_id) if call.context.user_id else None
        if bruger is not None and not bruger.is_admin:
            raise Unauthorized(context=call.context)

    def _opdater_alle() -> None:
        for e in hass.config_entries.async_loaded_entries(DOMAIN):
            e.runtime_data.opdater()

    async def gem_profil(call: ServiceCall) -> ServiceResponse:
        """Ny profil (med sin første butik) eller ret navn og brugere. Hovedprofilen har id "hoved"."""
        await _admin(call)
        alle = _alle(call)
        m = alle[0]
        reg = {"hoved": m.profiler["hoved"], "profiler": {k: dict(v) for k, v in m.profiler["profiler"].items()}}
        pid = call.data.get("id") or ""
        navn = call.data["navn"].strip()
        brugere = list(dict.fromkeys(call.data["brugere"]))
        # En bruger hører kun til én profil.
        for k, v in reg["profiler"].items():
            if k != pid:
                v["brugere"] = [b for b in v.get("brugere", []) if b not in brugere]
        if pid == "hoved":
            reg["hoved"] = navn
        elif pid:
            if pid not in reg["profiler"]:
                raise ServiceValidationError("Profilen findes ikke")
            reg["profiler"][pid].update(navn=navn, brugere=brugere)
        else:
            base = slugify(navn) or "profil"
            pid, i = base, 2
            while pid in reg["profiler"] or pid == "hoved":
                pid, i = f"{base}_{i}", i + 1
            reg["profiler"][pid] = {"navn": navn, "brugere": brugere}
        await m.async_gem_profiler(reg)
        if call.data.get("butik") and pid != "hoved" and not any(
            e.data.get(CONF_PROFIL) == pid and e.data.get("butik") == call.data["butik"]
            for e in hass.config_entries.async_entries(DOMAIN)
        ):
            # Samme AI og nøgler som de andre butikker - men ikke jeres mail, liste eller REMA-login.
            kilde = next(
                (e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get("butik") == call.data["butik"]),
                m.entry,
            )
            options = {k: v for k, v in kilde.options.items() if k not in ("notify_service", "indkobsliste", "rema_email", "rema_kode")}
            await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "profil"}, data={"butik": call.data["butik"], CONF_PROFIL: pid, "options": options}
            )
        _opdater_alle()
        return {"id": pid}

    async def slet_profil(call: ServiceCall) -> None:
        """Profilen, dens butikker, planer, regler og retter. Hovedprofilen kan ikke slettes."""
        await _admin(call)
        pid = call.data["id"]
        if pid in ("", "hoved"):
            raise ServiceValidationError("Hovedprofilen kan ikke slettes")
        m = _alle(call)[0]
        reg = {"hoved": m.profiler["hoved"], "profiler": {k: v for k, v in m.profiler["profiler"].items() if k != pid}}
        await m.async_gem_profiler(reg)
        for e in list(hass.config_entries.async_entries(DOMAIN)):
            if e.data.get(CONF_PROFIL) == pid:
                await hass.config_entries.async_remove(e.entry_id)
        hass.data.get(DOMAIN, {}).get("profiler", {}).pop(pid, None)
        for navn in (f"{DOMAIN}.regler_{pid}", f"{DOMAIN}.mine_retter_{pid}"):
            await Store(hass, 1, navn).async_remove()
        _opdater_alle()

    async def hent_min_ret(call: ServiceCall) -> ServiceResponse:
        m = next((m for m in _alle(call)[0].mine_retter if m["id"] == call.data["id"]), None)
        if m is None:
            raise ServiceValidationError("Retten findes ikke")
        return dict(m)

    async def madspild_butikker(call: ServiceCall) -> ServiceResponse:
        return {"butikker": await _madplaner(call)[0].async_madspild_butikker()}

    async def skift_madspild_butik(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_skift_madspild_butik(call.data["butik_id"], call.data.get("navn", ""))

    async def ekstra_antal(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_ekstra_antal(call.data["uid"], call.data["antal"])

    async def fjern_behov(call: ServiceCall) -> None:
        await _madplaner(call)[0].async_fjern_behov(call.data["tekst"])

    hass.services.async_register(DOMAIN, "ny_plan", ny_plan, schema=NY_PLAN_SKEMA)
    hass.services.async_register(DOMAIN, "byt_ret", byt_ret, schema=DAG_SKEMA)
    hass.services.async_register(DOMAIN, "fjern_ret", fjern_ret, schema=DAG_SKEMA)
    hass.services.async_register(DOMAIN, "udfoerlig_opskrift", udfoerlig, schema=DAG_SKEMA)
    hass.services.async_register(
        DOMAIN, "overfoer", overfoer, schema=SKEMA.extend({vol.Optional("til", default="liste"): vol.In(["liste", "rema"])})
    )
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
    hass.services.async_register(
        DOMAIN, "gem_min_ret", gem_min_ret, schema=MIN_RET_SKEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(DOMAIN, "slet_min_ret", slet_min_ret, schema=MIN_RET_ID_SKEMA)
    hass.services.async_register(
        DOMAIN, "madspild_butikker", madspild_butikker, schema=SKEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, "skift_madspild_butik", skift_madspild_butik,
        schema=SKEMA.extend({vol.Required("butik_id"): cv.string, vol.Optional("navn"): vol.All(cv.string, vol.Length(max=80))}),
    )
    hass.services.async_register(DOMAIN, "gem_profil", gem_profil, schema=PROFIL_SKEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "slet_profil", slet_profil, schema=SLET_PROFIL_SKEMA)
    hass.services.async_register(
        DOMAIN, "hent_min_ret", hent_min_ret, schema=MIN_RET_ID_SKEMA, supports_response=SupportsResponse.ONLY
    )
    return True


async def _registrer_kort(hass: HomeAssistant) -> None:
    """Gør custom:madplan-card tilgængeligt uden at brugeren skal tilføje en ressource."""
    if hass.http is None:
        return
    mappe = Path(__file__).parent
    version = json.loads(await hass.async_add_executor_job((mappe / "manifest.json").read_text))["version"]
    # Også filens tid, så browseren henter kortet igen efter en rettelse uden ny version.
    tid = int(await hass.async_add_executor_job(lambda: (mappe / "frontend" / "madplan-card.js").stat().st_mtime))
    version = f"{version}-{tid}"
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

    @callback
    def _madspild(_now) -> None:
        # Er de nedsatte varer stadig der? Hver halve time i butikkernes åbningstid.
        entry.async_create_background_task(hass, madplan.async_opdater_madspild(), "madplan_madspild")

    entry.async_on_unload(
        async_track_time_change(hass, _madspild, hour=list(range(7, 22)), minute=[0, 30], second=0)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Hovedsensoren peger på de andre enheder; nu er de alle registreret. De andre butikker opdateres også,
    # så deres samlede liste (automatisk plan) får den nye butik med.
    for e in hass.config_entries.async_entries(DOMAIN):
        if isinstance(getattr(e, "runtime_data", None), Madplan):
            e.runtime_data.opdater()
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
