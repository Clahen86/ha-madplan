"""Selve madplanen: AI vælger retter, priser og mængder regnes ud her."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import math
import re
import time
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import kilder, soeg
from .const import (
    BUTIKKER,
    CONF_AI_ENTITY,
    CONF_BUTIK,
    CONF_INDKOBSLISTE,
    CONF_NOTIFY,
    CONF_SALLING_BUTIK,
    CONF_SALLING_NOEGLE,
    DAGE,
    DOMAIN,
    HISTORIK_UGER,
    KATALOG_MAX_ALDER,
    SALLING,
    SIGNAL_OPDATERET,
    STANDARD_PERSONER,
    STANDARD_REGLER,
    UNDGAA_UGER,
)

_LOGGER = logging.getLogger(__name__)
MAKS_PAKKER = 10
# Færre tilbud end dette til næste uge betyder, at den nye avis ikke er ude endnu.
MIN_TILBUD = 20
MAKS_EKSTRA_BUTIKKER = 2
# En anden butik bruges kun til mindst så mange forskellige varer - ellers købes de i hovedbutikken.
MIN_PR_BUTIK = 3
# Varer, hvis kilopris sammenlignes på tværs af butikkerne i prompten.
SAMMENLIGN = (
    "hakket oksekød", "hakket grisekød", "hakket kylling", "kyllingebryst", "kyllingelår", "hel kylling", "laks",
    "torsk", "bacon", "pølser", "medister", "kartofler", "løg", "gulerødder", "broccoli", "peberfrugt", "tomater",
    "agurk", "æg", "piskefløde", "revet ost", "mozzarella", "pasta", "ris",
)


class ForLangtSvar(HomeAssistantError):
    """AI'ens svar ramte loftet for længde (MAX_TOKENS)."""


class Madplan:
    """Holder planen, varelisten og historikken for én config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.butik = entry.data[CONF_BUTIK]
        self.butik_navn, self.dealer = BUTIKKER[self.butik]
        self.butik_info: dict[str, Any] = {"navn": self.butik_navn, "logo": None, "farve": None}
        # Fælles for alle butikker: ét REMA-katalog og ét AI-kald ad gangen.
        faelles = hass.data.setdefault(
            DOMAIN,
            {
                "katalog_laas": asyncio.Lock(),
                "ai_laas": asyncio.Lock(),
                "regler_store": Store(hass, 1, f"{DOMAIN}.regler"),
                "regler": None,
            },
        )
        self._faelles = faelles
        self._katalog_laas = faelles["katalog_laas"]
        self._ai_laas = faelles["ai_laas"]
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._katalog_store = Store(hass, 1, f"{DOMAIN}.katalog")
        self.plan: dict[str, Any] = {}
        self.historik: list[dict] = []
        self.personer = STANDARD_PERSONER
        self.katalog: dict[str, dict] = {}
        self.tilbud: dict[str, dict] = {}
        self._navne: list[str] = []
        # Salling Group (valgfrit): kædens eget katalog og priser i den valgte butik.
        self.salling: dict[str, dict] = {}
        self._salling_priser: dict[str, float | None] = {}
        self._salling_fejl = False
        self._salling_store = Store(hass, 1, f"{DOMAIN}.salling_{self.butik}") if self.butik in SALLING else None
        self._en_laas = asyncio.Lock()
        self._laas = asyncio.Lock()

    # ------------------------------------------------------------------ opsætning

    @property
    def signal(self) -> str:
        return SIGNAL_OPDATERET.format(self.entry.entry_id)

    @property
    def optaget(self) -> bool:
        return self._laas.locked()

    async def async_indlaes(self) -> None:
        data = await self._store.async_load()
        self.ny = data is None
        data = data or {}
        self.plan = data.get("plan", {})
        self.historik = data.get("historik", [])
        # En ny butik arver antal personer fra de andre butikker.
        andre = [e.runtime_data.personer for e in self.hass.config_entries.async_loaded_entries(DOMAIN)]
        self.personer = data.get("personer", max(andre, default=STANDARD_PERSONER))
        self.butik_info = data.get("butik_info") or self.butik_info
        self.behov = data.get("behov", [])
        self.en_ret: list[dict] = data.get("en_ret", [])
        # Andre kæder, familien også handler i (fx REMA + Netto, der ligger tæt). Kun tilbud derfra.
        self.ekstra_butikker: list[str] = [b for b in data.get("ekstra_butikker", []) if b in BUTIKKER]
        self.en_ret_status = ""
        if self._faelles["regler"] is None:
            gemt = await self._faelles["regler_store"].async_load() or {}
            self._faelles["regler"] = {**STANDARD_REGLER, **gemt}
        # En plan, der var i gang, da HA genstartede, er ikke i gang længere.
        if str(self.plan.get("status", "")).endswith("…"):
            self.plan["status"] = "Klar" if self.plan.get("retter") else "Ingen plan endnu"

    async def _gem(self) -> None:
        await self._store.async_save(
            {
                "plan": self.plan,
                "historik": self.historik,
                "personer": self.personer,
                "butik_info": self.butik_info,
                "behov": self.behov,
                "en_ret": self.en_ret,
                "ekstra_butikker": self.ekstra_butikker,
            }
        )

    @property
    def regler(self) -> dict[str, Any]:
        return self._faelles["regler"] or dict(STANDARD_REGLER)

    async def async_gem_regler(self, nye: dict[str, Any]) -> None:
        """Gemmer familiens regler (fælles for alle butikker). De bruges fra næste plan."""
        regler = {**self.regler, **{k: v for k, v in nye.items() if k in STANDARD_REGLER}}
        self._faelles["regler"] = regler
        await self._faelles["regler_store"].async_save(regler)

    def advarsler(self) -> list[str]:
        """Hvor planen bryder familiens regler. Tjekkes i koden, så det ikke koster AI-kald."""
        r = self.regler
        retter = self.plan.get("retter") or []
        if not retter:
            return []
        ud: list[str] = []
        aktive = [(i, ret) for i, ret in enumerate(retter) if not ret.get("fjernet") and ret.get("rester_fra") is None]
        forbudt = [(o, "allergi") for o in r["allergier"]] + [(o, "undgå") for o in r["undgaa"]]
        for i, ret in aktive:
            tekst = " ".join([ret.get("navn", "")] + [str(x.get("navn", "")) for x in ret.get("ingredienser", [])]).lower()
            for ord_, slags in forbudt:
                if ord_.strip() and re.search(rf"\b{re.escape(ord_.strip().lower())}", tekst):
                    ud.append(f"{DAGE[i]}: indeholder {ord_} ({slags})")
            if 1 <= i <= 5 and int(ret.get("tid_min") or 0) > r["max_tid"]:
                ud.append(f"{DAGE[i]}: tager {ret.get('tid_min')} min (højst {r['max_tid']} på hverdage)")
            elif i in (0, 6) and int(ret.get("tid_min") or 0) > r.get("max_tid_weekend", 60):
                ud.append(f"{DAGE[i]}: tager {ret.get('tid_min')} min (højst {r.get('max_tid_weekend', 60)} i weekenden)")
        for felt, navn in (("vegetar", "vegetarretter"), ("fisk", "fiskeretter")):
            if not any(felt in ret for _, ret in aktive):
                continue  # planen er lavet, før retterne blev markeret
            antal = sum(1 for _, ret in aktive if ret.get(felt))
            if r[felt] and antal < r[felt] and len(aktive) >= r[felt]:
                ud.append(f"Kun {antal} {navn} (ønsket: {r[felt]})")
        for fast in r["faste_dage"]:
            i, ret_navn = int(fast.get("dag", -1)), str(fast.get("ret", "")).lower()
            ord_ = [o for o in re.findall(r"\w{3,}", ret_navn)]
            if 0 <= i < len(retter) and ord_ and not retter[i].get("fjernet"):
                if not any(o in retter[i].get("navn", "").lower() for o in ord_):
                    ud.append(f"{DAGE[i]}: skulle være {fast['ret']}")
        for v in self.plan.get("varer", []):
            if v.get("for_mange"):
                ud.append(f"Tjek mængden af {v['navn']} – sat til {MAKS_PAKKER} pakker")
        andre: dict[str, list[str]] = {}
        for v in self.plan.get("varer", []):
            if v.get("butik") and not v.get("hjemme"):
                andre.setdefault(v["butik"], []).append(v["navn"])
        for butik, navne in andre.items():
            if len(navne) < MIN_PR_BUTIK:  # kan ske efter "Byt ret"
                ud.append(f"Kun {len(navne)} vare{'r' if len(navne) > 1 else ''} fra {butik} – er turen det værd?")
        if self.plan.get("salling_fejl"):
            ud.append("Salling-priser kunne ikke hentes for alle varer – nogle priser er ca.")
        if r["budget"] and self.plan.get("total_alle", 0) > r["budget"]:
            ud.append(f"Koster {self.plan['total_alle']} kr (budget {r['budget']} kr)")
        return ud

    def opdater(self) -> None:
        async_dispatcher_send(self.hass, self.signal)

    def _status(self, tekst: str) -> None:
        self.plan["status"] = tekst
        self.opdater()

    # ------------------------------------------------------------------ handlinger

    async def async_ny_plan(self, vent_paa_tilbud: bool = False, handler: str | None = None) -> None:
        """Ny ugeplan. handler: "i_dag" eller "i_morgen" - tilbuddene skal gælde den dag.
        vent_paa_tilbud: den automatiske lørdagsplan venter til søndag morgen, hvis næste uges
        avis ikke er ude endnu (fx REMA og Lidl, der skifter søndag)."""
        if self.optaget:
            return
        async with self._laas:
            try:
                self._status("Henter tilbud og laver madplan …")
                dag = self.handledag(handler)
                start, slut = self._plan_uge(dag)
                await self._hent_data(dag, slut, nye_tilbud=True)  # tilbuddene skal gælde på indkøbsdagen
                if vent_paa_tilbud and len(self.tilbud) < MIN_TILBUD:
                    _LOGGER.info("%s: kun %s tilbud til næste uge - venter til søndag", self.butik_navn, len(self.tilbud))
                    self._status("Næste uges tilbud er ikke ude endnu – planen laves søndag kl. 7")
                    return
                undgaa = self._seneste_retter(start.isoformat())
                # Midt på ugen planlægges kun fra i dag; dagene før står som "forbi".
                # Planen begynder på indkøbsdagen; dagene før står som "før planen".
                fra = max(0, min(6, (dag - start).days))
                # Dage uden madlavning (fx spiser ude onsdag) planlægges ikke - det sparer også AI'en.
                fri = {int(d) for d in self.regler.get("fri_dage") or []}
                dage = [i for i in range(fra, 7) if i not in fri]
                if not dage:
                    raise HomeAssistantError("Alle dage er slået fra - vælg mindst én dag")
                antal = len(dage)
                datoer = ", ".join(f"{DAGE[i]} {(start + datetime.timedelta(days=i)).isoformat()}" for i in dage)
                # Faste behov (pålæg, madpakker …) løses i samme AI-kald - gratis-kvoten tæller kald.
                behov = list(self.behov)
                instr = (
                    self._regler()
                    + f"Lav {antal} aftensmåltider for {datoer}.\n"
                    + (f"Undgå disse retter fra de seneste uger: {', '.join(undgaa)}.\n" if undgaa else "")
                    + (f"\nEKSTRA VARER: {self._behov_regler(behov)}\n" if behov else "")
                    + f'Svar KUN med JSON: {{"retter": [{antal} x '
                    + self._ret_skema()
                    + "]"
                    + (", " + self._behov_skema() if behov else "")
                    + "} med retterne i samme rækkefølge som dagene.\n\n"
                )
                svar = await self._spoerg("Madplan uge", lambda liste: instr + self._vare_tekst(liste))
                nye = svar.get("retter", [])[:antal]
                if len(nye) < antal:
                    raise HomeAssistantError(f"AI gav kun {len(nye)} retter")
                if self.ekstra_butikker:
                    self._saml_butikker(nye)
                await self.hass.async_add_executor_job(self._find_varer, nye, start)
                ai_retter = iter(nye)
                retter = [
                    {"navn": "Før planen", "fjernet": True, "forbi": True}
                    if i < fra
                    else {"navn": "Spiser ude", "fjernet": True, "fri": True, "kort": "Slået fra i planen.",
                          "trin": [], "ingredienser": []}
                    if i in fri
                    else next(ai_retter)
                    for i in range(7)
                ]
                self.plan = {
                    "start": start.isoformat(),
                    "slut": slut.isoformat(),
                    "uge": (start + datetime.timedelta(days=1)).isocalendar()[1],
                    "tilbud": self.tilbud,
                    "salling_priser": self._salling_priser,
                    "handledag": dag.isoformat(),
                    "salling_fejl": self._salling_fejl,
                    "retter": retter,
                    "lavet": dt_util.now().isoformat(timespec="minutes"),
                }
                self._beregn(ny=True)
                self._gem_historik()
                self.plan["status"] = "Klar"
                await self._gem()
                self.opdater()
                _LOGGER.info("Madplan lavet for %s - %s", start, slut)
                # Faste behov får nye tilbud hver uge.
                if behov:
                    try:
                        await self.hass.async_add_executor_job(self._gem_behov, svar.get("varer", []), behov, start)
                        self.plan["salling_priser"] = self._salling_priser
                    except Exception as e:  # noqa: BLE001 - planen er lavet; kun ekstra fejlede
                        _LOGGER.warning("Ekstra varer fejlede: %s", e)
                    await self._gem()
                    self.opdater()
            except Exception as e:  # noqa: BLE001 - vises i status på dashboardet
                _LOGGER.exception("Madplan fejlede")
                self._status(f"Fejl: {str(e)[:120]}")

    async def async_byt_ret(self, dag: int) -> None:
        if self.optaget or not self.plan.get("retter") or not 1 <= dag <= 7:
            return
        async with self._laas:
            try:
                gammel_ret = self.plan["retter"][dag - 1]
                gammel = gammel_ret.get("navn", "")
                self._status(f"Finder en ny ret til {DAGE[dag - 1].lower()} …")
                start = datetime.date.fromisoformat(self.plan["start"])
                await self._hent_data(start, start + datetime.timedelta(days=6))
                andre = [
                    r.get("navn", "") for i, r in enumerate(self.plan["retter"]) if i != dag - 1 and not r.get("fjernet")
                ]
                fravalgt = self.plan.setdefault("fravalgt", [])
                if not gammel_ret.get("fjernet"):
                    fravalgt.append(gammel)
                instr = (
                    self._regler()
                    + f"Ugens andre retter er: {', '.join(andre)}. "
                    + (f"Familien vil IKKE have: {', '.join(fravalgt)}.\n" if fravalgt else "\n")
                    + self._samme_slags(dag - 1)
                    + f"Lav én ny ret til {DAGE[dag - 1].lower()}, som er anderledes end ugens andre retter "
                    + "(andet protein eller køkken), og undgå retter fra de seneste uger: "
                    + ", ".join(self._seneste_retter(self.plan["start"]))
                    + ".\n"
                    + "Svar KUN med JSON: "
                    + self._ret_skema()
                    + "\n\n"
                )
                ret = await self._spoerg("Madplan byt ret", lambda liste: instr + self._vare_tekst(liste))
                if "retter" in ret:
                    ret = ret["retter"][0]
                if gammel_ret.get("personer"):
                    ret["personer"] = gammel_ret["personer"]  # gæsterne kommer stadig
                await self.hass.async_add_executor_job(self._find_varer, [ret], start)
                self.plan["salling_priser"] = self._salling_priser
                self._ophaev_rester(dag - 1)
                self.plan["retter"][dag - 1] = ret
                self._beregn()
                self._gem_historik()
                self.plan["status"] = "Klar"
                await self._gem()
                self.opdater()
            except Exception as e:  # noqa: BLE001
                _LOGGER.exception("Byt ret fejlede")
                self._status(f"Fejl: {str(e)[:120]}")

    def _samme_slags(self, i: int) -> str:
        """Mangler ugen en fiske- eller vegetarret uden denne dag, skal den nye ret være det.
        Så overholder et bytte reglerne - og kan rette en plan, der mangler fx fisk."""
        r = self.regler
        gammel = self.plan["retter"][i]
        andre = [ret for j, ret in enumerate(self.plan.get("retter", [])) if j != i and not ret.get("fjernet")]
        mangler = [
            (felt, navn)
            for felt, navn in (("fisk", "fiskeret"), ("vegetar", "vegetarret"))
            if r[felt] and sum(1 for ret in andre if ret.get(felt)) < r[felt]
        ]
        if not mangler:
            return ""
        # Mangler begge, så den slags, den gamle ret var.
        felt, navn = next(((f, n) for f, n in mangler if gammel.get(f)), mangler[0])
        return f"Den nye ret SKAL være en {navn}.\n"

    # ------------------------------------------------------------------ én ret (køleskab)

    async def async_en_ret(self, har: list[str], personer: int | None = None, oenske: str = "") -> None:
        """Én ret til i dag ud fra det, man har i køleskabet. Helt adskilt fra ugeplanen."""
        if self._en_laas.locked():
            return
        async with self._en_laas:
            try:
                n = int(personer or self.personer)
                har = [h.strip() for h in har if h.strip()]
                self._en_status("Finder en ret …")
                idag = dt_util.now().date()
                await self._hent_data(idag, idag, nye_tilbud=not self.tilbud)
                instr = (
                    self._regler()
                    + f"Lav ÉN aftensret til {n} personer i dag.\n"
                    + (
                        f"Familien har allerede: {', '.join(har)}. Retten SKAL bruge det, familien har (alle tingene, "
                        "hvis de passer sammen). Sæt 'har': true KUN på de ingredienser, der står på den liste - "
                        "alt andet skal købes og har 'har': false.\n"
                        if har
                        else ""
                    )
                    + (f"Ønske: {oenske.strip()}.\n" if oenske.strip() else "")
                    + "Det, der mangler, skal købes: brug helst tilbudsvarer (T:), ellers S:navn. Køb så lidt som muligt.\n"
                    + 'Svar KUN med JSON: {"ret": '
                    + self._ret_skema().replace('"basis": bool}', '"basis": bool, "har": bool}')
                    + "}\n\n"
                )
                svar = await self._spoerg("Madplan én ret", lambda liste: instr + self._vare_tekst(liste))
                ret = svar.get("ret") or (svar.get("retter") or [None])[0] or svar
                if not ret.get("navn"):
                    raise HomeAssistantError("AI'en gav ingen ret")
                await self.hass.async_add_executor_job(self._find_varer, [ret], idag)
                self.en_ret = [self._beregn_en_ret(ret, n, idag, har, oenske)] + self.en_ret[:4]
                await self._gem()
                self._en_status("")
            except Exception as e:  # noqa: BLE001 - vises på siden
                _LOGGER.exception("Én ret fejlede")
                self._en_status(f"Fejl: {str(e)[:120]}")

    def _beregn_en_ret(self, ret: dict, n: int, dato: datetime.date, har: list[str], oenske: str) -> dict:
        """Mængder, og hvad der skal købes, for én ret. Ingen AI her."""
        linjer, varer = self._koeb_til_ret(ret, n, dato, har)
        hv = self._slaa_op(ret.get("hovedvare"), dato)
        return {
            "id": f"{int(time.time())}",
            "lavet": dt_util.now().isoformat(timespec="minutes"),
            "navn": ret.get("navn", ""),
            "kort": ret.get("kort", ""),
            "tid": ret.get("tid_min"),
            "sundhed": ret.get("sundhed", ""),
            "billede": hv[3] if hv else None,
            "personer": n,
            "har": har,
            "oenske": oenske,
            "ingredienser": linjer,
            "trin": ret.get("trin", []),
            "koeb": varer,
            "koeb_total": round(sum(v["kr"] for v in varer)),
            "koeb_ca": any(v["ca"] for v in varer),
        }

    def _koeb_til_ret(self, ret: dict, n: int, dato: datetime.date, har: list[str]) -> tuple[list[str], list[dict]]:
        """(ingredienslinjer, varer at købe) for én ret til n personer - uden basisvarer og det, man har."""
        linjer, koeb = [], {}
        for ing in ret.get("ingredienser", []):
            try:
                mgd = float(ing.get("pr_person") or 0) * n
                pakke = float(ing.get("pakke") or 0)
            except (TypeError, ValueError):
                mgd, pakke = 0.0, 0.0
            enhed = ing.get("enhed", "")
            vis = f"{round(mgd) if mgd >= 10 else round(mgd, 1):g} {enhed}".strip() if mgd else ""
            linjer.append(f"{vis} {ing.get('navn', '')}".strip())
            # Det, familien har, afgøres af deres egen liste - ikke af AI'ens 'har', som kan tage fejl.
            navn_ing = str(ing.get("navn", ""))
            ing["har"] = any(soeg.samme_vare(navn_ing, h) for h in har)
            if ing["har"] or _basis(ing) or not (info := self._slaa_op(ing.get("vare"), dato)):
                continue
            navn, strr, enhedspris, _, tilbud = info
            k = koeb.setdefault(ing["vare"], {"navn": navn, "str": strr, "enhedspris": enhedspris, "tilbud": tilbud,
                                              "ukendt": ing["vare"].startswith("S:"), "ca": self._ca(ing["vare"]), "andel": 0.0})
            k["andel"] += 1.0 if ing.get("pakke_ukendt") or pakke <= 0 else mgd / pakke
        varer = []
        for k in koeb.values():
            antal = min(MAKS_PAKKER, max(1, math.ceil(k["andel"] - 0.15)))
            v = {"navn": k["navn"], "str": k["str"], "antal": antal, "pris": round(antal * k["enhedspris"], 2),
                 "tilbud": k["tilbud"], "ukendt": k["ukendt"], "anslaaet": k["ca"]}
            varer.append({"tekst": vare_tekst(v), "pris": pris_tekst(v, 0), "kr": 0 if k["ukendt"] else v["pris"],
                          "tilbud": k["tilbud"], "ca": k["ca"]})
        return linjer, varer

    async def async_slet_en_ret(self, ret_id: str) -> None:
        self.en_ret = [r for r in self.en_ret if r["id"] != ret_id]
        await self._gem()
        self.opdater()

    async def async_en_ret_paa_listen(self, ret_id: str) -> None:
        """Det, der mangler til én ret, på den valgte indkøbsliste."""
        ret = next((r for r in self.en_ret if r["id"] == ret_id), None)
        liste = self.entry.options.get(CONF_INDKOBSLISTE)
        if not ret or not liste:
            raise HomeAssistantError("Vælg en indkøbsliste under integrationens indstillinger")
        for v in ret["koeb"]:
            await self.hass.services.async_call(
                "todo", "add_item", {"entity_id": liste, "item": v["tekst"], "description": v["pris"]}, blocking=True
            )
        self._en_status(f"✅ {len(ret['koeb'])} varer lagt på indkøbslisten")

    async def async_en_ret_mail(self, ret_id: str) -> None:
        """Det, der mangler til én ret, og opskriften - sendt med den valgte notify-tjeneste (fx mail)."""
        ret = next((r for r in self.en_ret if r["id"] == ret_id), None)
        if not ret:
            raise HomeAssistantError("Retten findes ikke længere")
        await self._send_ret(ret["navn"], ret["personer"], ret.get("tid"), ret["koeb"], ret["ingredienser"],
                             ret["trin"], ret.get("har"))
        self._en_status("✅ Sendt på mail")

    async def async_dag_mail(self, dag: int) -> None:
        """Én dag fra ugeplanen på mail: varerne til netop den ret og opskriften."""
        retter = self.plan.get("retter") or []
        if not 1 <= dag <= len(retter) or retter[dag - 1].get("fjernet"):
            raise HomeAssistantError("Der er ingen ret den dag")
        ret = retter[dag - 1]
        start = datetime.date.fromisoformat(self.plan["start"])
        await self._hent_data(start, None)
        n = int(ret.get("personer") or self.personer)
        linjer, varer = self._koeb_til_ret(ret, n, start, [])
        await self._send_ret(f"{DAGE[dag - 1]}: {ret.get('navn', '')}", n, ret.get("tid_min"), varer, linjer,
                             ret.get("trin", []), None)
        self._status(f"✅ {DAGE[dag - 1]} er sendt på mail")

    async def _send_ret(self, navn: str, n: int, tid: Any, koeb: list[dict], ingredienser: list[str],
                        trin: list[str], har: list[str] | None) -> None:
        if not self._notify_tjenester():
            raise HomeAssistantError("Vælg en notify-tjeneste (fx mail) under integrationens indstillinger")
        total = round(sum(v["kr"] for v in koeb))
        ca = any(v["ca"] for v in koeb)
        besked = (
            f"{navn} · {n} personer · {tid or '?'} min\n\n"
            f"INDKØB · {self.butik_navn}" + (f" · {'ca. ' if ca else ''}{total} kr" if koeb else "") + "\n"
            + ("\n".join(f"☐ {v['tekst']}  {v['pris']}" for v in koeb) or "Intet – I har det hele 🎉")
            + "\n(Basisvarer som salt, olie og mel er ikke med.)\n"
            + (f"\nDet har I: {', '.join(har)}\n" if har else "")
            + "\nIngredienser:\n" + "\n".join(f"• {x}" for x in ingredienser)
            + "\n\nSådan gør du:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(trin, start=1))
        )
        await self._send_besked(f"Indkøb til {navn}", besked)

    def _notify_tjenester(self) -> list[str]:
        """De valgte notify-tjenester - én eller flere (fx mail og begge telefoner)."""
        v = self.entry.options.get(CONF_NOTIFY) or []
        if isinstance(v, str):
            v = v.split(",")
        return [t.strip() for t in v if t and t.strip()]

    async def _send_besked(self, titel: str, besked: str) -> None:
        """Send til alle valgte modtagere. Fejler én, kommer de andre stadig frem."""
        fejl = []
        for t in self._notify_tjenester():
            domaene, _, tjeneste = t.partition(".")
            try:
                await self.hass.services.async_call(
                    domaene, tjeneste, {"title": titel, "message": besked}, blocking=True
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Kunne ikke sende til %s: %s", t, e)
                fejl.append(t)
        if fejl and len(fejl) == len(self._notify_tjenester()):
            raise HomeAssistantError(f"Kunne ikke sende til {', '.join(fejl)}")

    def _en_status(self, tekst: str) -> None:
        self.en_ret_status = tekst
        self.opdater()

    async def async_rester(self, dag: int, til: bool) -> None:
        """Lav dagens ret til 2 dage: mængden fordobles, og næste dag bliver rester uden indkøb."""
        retter = self.plan.get("retter") or []
        i = dag - 1
        if self.optaget or not 0 <= i < 6 or i + 1 >= len(retter) or retter[i].get("fjernet"):
            raise HomeAssistantError("Retten kan ikke laves til 2 dage")
        ret = retter[i]
        if til and not ret.get("dobbelt"):
            if retter[i + 1].get("rester_fra") is not None or retter[i + 1].get("forbi"):
                raise HomeAssistantError(f"{DAGE[i + 1]} kan ikke blive restedag")
            ret["dobbelt"] = True
            retter[i + 1] = {
                "navn": f"Rester: {ret.get('navn', '')}",
                "rester_fra": i,
                "kort": f"Rester fra {DAGE[i].lower()} - intet at købe.",
                "tid_min": 10,
                "hovedvare": ret.get("hovedvare"),
                "vegetar": ret.get("vegetar"),
                "fisk": ret.get("fisk"),
                "trin": [f"Varm resterne fra {DAGE[i].lower()}, og server."],
                "ingredienser": [],
                "erstattet": retter[i + 1],
            }
        elif not til:
            self._ophaev_rester(i)
        await self._hent_data(datetime.date.fromisoformat(self.plan["start"]), None)
        self._beregn()
        await self._gem()
        self.opdater()

    def _ophaev_rester(self, i: int) -> None:
        """Byttes, fjernes eller fortrydes en dobbeltportion, får næste dag sin gamle ret igen - og omvendt."""
        retter = self.plan.get("retter") or []
        ret = retter[i]
        if ret.get("dobbelt"):
            ret.pop("dobbelt", None)
            if i + 1 < len(retter) and retter[i + 1].get("rester_fra") == i:
                retter[i + 1] = retter[i + 1].get("erstattet") or {
                    "navn": "Ingen aftensmad", "fjernet": True, "trin": [], "ingredienser": []
                }
        if (fra := ret.get("rester_fra")) is not None and 0 <= fra < len(retter):
            retter[fra].pop("dobbelt", None)

    async def async_fjern_ret(self, dag: int) -> None:
        """Ingen aftensmad den dag (ude, rester osv.). 'Byt ret' giver en ret igen."""
        if self.optaget or not self.plan.get("retter") or not 1 <= dag <= 7:
            return
        async with self._laas:
            self._ophaev_rester(dag - 1)
            self.plan["retter"][dag - 1] = {
                "navn": "Ingen aftensmad",
                "fjernet": True,
                "kort": "Ingen madlavning i dag. Tryk 'Byt ret' for at få en ret igen.",
                "trin": [],
                "ingredienser": [],
            }
            await self._hent_data(datetime.date.fromisoformat(self.plan["start"]), None)
            self._beregn()
            self.plan["status"] = "Klar"
            await self._gem()
            self.opdater()

    async def async_saet_personer(self, antal: int) -> None:
        self.personer = max(1, int(antal))
        if self.plan.get("retter") and not self.optaget:
            start = datetime.date.fromisoformat(self.plan["start"])
            await self._hent_data(start, None)
            # Pakkestørrelserne regnes forfra (rettelser i omregningen gælder også en gemt plan).
            await self.hass.async_add_executor_job(self._find_varer, self.plan["retter"], start)
            self._beregn()
        self._totaler()
        await self._gem()
        self.opdater()

    async def async_dag_personer(self, dag: int, antal: int) -> None:
        """Antal personer én dag (fx gæster). 0 eller det normale antal = følg resten af ugen."""
        retter = self.plan.get("retter") or []
        if not 1 <= dag <= len(retter) or self.optaget:
            return
        ret = retter[dag - 1]
        if antal and antal != self.personer:
            ret["personer"] = int(antal)
        else:
            ret.pop("personer", None)
        await self._hent_data(datetime.date.fromisoformat(self.plan["start"]), None)
        self._beregn()
        await self._gem()
        self.opdater()

    async def async_saet_hjemme(self, key: str, hjemme: bool) -> None:
        """Afkrydsning i HA's egen to-do-liste: lagt i kurven (eller fortrudt)."""
        await self.async_marker("varer", key, "kurv", hjemme)

    async def async_marker(self, liste: str, uid: str, felt: str, vaerdi: bool) -> None:
        """'kurv' = lagt i kurven mens man handler (tæller stadig med i prisen).
        'hjemme' = har det allerede (trækkes fra). En vare er højst det ene af dem."""
        noegle = "key" if liste == "varer" else "uid"
        for v in self.plan.get(liste, []):
            if v[noegle] == uid:
                v[felt] = vaerdi
                if vaerdi:
                    v["hjemme" if felt == "kurv" else "kurv"] = False
                elif felt == "kurv":
                    v["hjemme"] = False
        self._totaler()
        await self._gem()
        self.opdater()

    async def async_toem_kurv(self) -> None:
        for v in self.plan.get("varer", []) + self.plan.get("ekstra", []):
            v["kurv"] = False
        await self._gem()
        self.opdater()

    async def async_ekstra_antal(self, uid: str, antal: int) -> None:
        """Ret antallet af pakninger for én ekstra vare."""
        for e in self.plan.get("ekstra", []):
            if e["uid"] == uid:
                e["antal"] = max(1, int(antal))
                e["pris"] = round(e["antal"] * e["enhedspris"], 2)
        self._totaler()
        await self._gem()
        self.opdater()

    async def async_tilfoej_behov(self, tekster: list[str]) -> None:
        """Fx "pålæg" og "frugt til madpakker": AI vælger tilbudsvarer - alle i ét kald."""
        tekster = list(dict.fromkeys(t.strip() for t in tekster if t.strip()))
        if not tekster or self.optaget:
            return
        async with self._laas:
            try:
                for tekst in tekster:
                    if tekst.lower() not in (b.lower() for b in self.behov):
                        self.behov.append(tekst)
                self._status(f"Finder tilbud på {', '.join(tekster)} …")
                await self._loes_behov(tekster)
                self.plan["status"] = "Klar"
                await self._gem()
                self.opdater()
            except Exception as e:  # noqa: BLE001
                _LOGGER.exception("Ekstra vare fejlede")
                self._status(f"Fejl: {str(e)[:120]}")

    async def async_fjern_behov(self, tekst: str) -> None:
        self.behov = [b for b in self.behov if b.lower() != tekst.strip().lower()]
        self.plan["ekstra"] = [e for e in self.plan.get("ekstra", []) if e["behov"].lower() != tekst.strip().lower()]
        self._totaler()
        await self._gem()
        self.opdater()

    async def async_saet_ekstra(self, uid: str, hjemme: bool | None = None, slet: bool = False) -> None:
        """Afkryds eller slet én ekstra vare."""
        ekstra = self.plan.get("ekstra", [])
        if slet:
            self.plan["ekstra"] = [e for e in ekstra if e["uid"] != uid]
        else:
            for e in ekstra:
                if e["uid"] == uid:
                    e["hjemme"] = bool(hjemme)
        self._totaler()
        await self._gem()
        self.opdater()

    async def _loes_behov(self, behov: list[str]) -> None:
        if self.plan.get("start"):
            start = datetime.date.fromisoformat(self.plan["start"])
            await self._hent_data(start, start + datetime.timedelta(days=6))
        else:
            start, slut = self._plan_uge()
            await self._hent_data(start, slut, nye_tilbud=True)
            self.plan.update({"start": start.isoformat(), "slut": slut.isoformat(), "tilbud": self.tilbud})
        instr = (
            f"Du hjælper en dansk familie med indkøb i {self.butik_navn}. {self._behov_regler(behov)}\n"
            "Svar KUN med JSON: {" + self._behov_skema() + "}\n\n"
        )
        svar = await self._spoerg(
            "Madplan ekstra varer", lambda liste: instr + self._vare_tekst(liste, aftensmad=False)
        )
        # I en baggrundstråd: Salling-priser slås op undervejs.
        await self.hass.async_add_executor_job(self._gem_behov, svar.get("varer", []), behov, start)
        self.plan["salling_priser"] = self._salling_priser

    @staticmethod
    def _behov_regler(behov: list[str]) -> str:
        return (
            "Ud over aftensmaden skal familien bruge varer til hvert behov herunder. Vælg konkrete, almindelige "
            "varer, som familien vil kunne lide, og brug så vidt muligt tilbudsvarer (T:id fra listen). Er der "
            "ikke et passende tilbud, så skriv varen som 'S:navn' med et navn præcis fra listen ALMINDELIGE VARER "
            "(fx 'S:Leverpostej'), eller et kort, almindeligt dansk varenavn, hvis den ikke findes der. Hold det billigt, og vælg højst 3-4 forskellige varer pr. "
            f"behov. Behov: {'; '.join(behov)}"
        )

    @staticmethod
    def _behov_skema() -> str:
        return '"varer": [{"behov": str (præcis som skrevet), "vare": "T:id" eller "S:navn", "hvorfor": str (kort)}]'

    def _gem_behov(self, varer: list[dict], behov: list[str], start: datetime.date) -> None:
        nye = []
        for i, v in enumerate(varer):
            v["vare"] = self._find_vare(v.get("vare"), start, None, kun_mad=False)
            info = self._slaa_op(v.get("vare"), start)
            if not info:
                continue
            navn, strr, enhedspris, _, tilbud = info
            # Altid 1 pakning; brugeren retter selv antallet.
            antal = 1
            # AI'en staver ikke altid behovet præcis som brugeren; brug brugerens ord.
            b = str(v.get("behov") or "").lower()
            hoerer_til = next((x for x in behov if x.lower() == b), None) or next(
                (x for x in behov if b and (x.lower() in b or b in x.lower())), behov[0]
            )
            nye.append(
                {
                    "uid": f"{v['vare']}-{int(time.time())}-{i}",
                    "key": v["vare"],
                    "behov": hoerer_til,
                    "navn": navn,
                    "str": strr,
                    "antal": antal,
                    "enhedspris": enhedspris,
                    "pris": round(antal * enhedspris, 2),
                    "tilbud": tilbud,
                    "anslaaet": self._ca(v["vare"]),
                    "ukendt": v["vare"].startswith("S:"),
                    "hvorfor": v.get("hvorfor", ""),
                    "hjemme": False,
                }
            )
        if not nye:
            raise HomeAssistantError(f"Fandt ingen varer til {', '.join(behov)}")
        # Behov, der løses igen, erstatter deres gamle varer.
        loest = {b.lower() for b in behov}
        self.plan["ekstra"] = [e for e in self.plan.get("ekstra", []) if e["behov"].lower() not in loest] + nye
        self._totaler()

    async def async_overfoer(self) -> None:
        """Lægger manglende varer på indkøbslisten og/eller sender dem som besked."""
        mangler = [v for v in self.plan.get("varer", []) if not v.get("hjemme")]
        mangler += [e for e in self.plan.get("ekstra", []) if not e.get("hjemme")]
        opts = self.entry.options
        try:
            if liste := opts.get(CONF_INDKOBSLISTE):
                for v in mangler:
                    await self.hass.services.async_call(
                        "todo",
                        "add_item",
                        {
                            "entity_id": liste,
                            "item": vare_tekst(v) + (f" – {v['butik']}" if v.get("butik") else ""),
                            "description": pris_tekst(v),
                        },
                        blocking=True,
                    )
            if self._notify_tjenester():
                await self._send_besked(
                    f"Indkøbsliste uge {self.plan.get('uge', '')} – {self.butik_navn}", self._besked(mangler)
                )
            self._status(f"✅ Indkøbslisten er sendt ({len(mangler)} varer)")
        except HomeAssistantError as e:
            _LOGGER.error("Overførsel fejlede: %s", e)
            self._status(f"Fejl ved overførsel: {str(e)[:120]}")

    # ------------------------------------------------------------------ data

    @staticmethod
    def handledag(valg: str | None = None) -> datetime.date:
        """Indkøbsdagen: i dag eller i morgen. Standard er i dag - om lørdagen i morgen (søndag),
        så næste uges plan bruger søndagens tilbud."""
        idag = dt_util.now().date()
        if valg is None:
            valg = "i_morgen" if idag.weekday() == 5 else "i_dag"
        return idag + datetime.timedelta(days=1 if valg == "i_morgen" else 0)

    def _plan_uge(self, handledag: datetime.date | None = None) -> tuple[datetime.date, datetime.date]:
        """Ugen (søndag-lørdag), der handles ind til. Handles der om lørdagen, er det næste uge."""
        dag = handledag or self.handledag()
        if dag.weekday() == 5:
            start = dag + datetime.timedelta(days=1)
        else:
            start = dag - datetime.timedelta(days=(dag.weekday() + 1) % 7)
        return start, start + datetime.timedelta(days=6)

    async def _hent_data(self, start: datetime.date, slut: datetime.date | None, nye_tilbud: bool = False) -> None:
        if not self.katalog:
            async with self._katalog_laas:
                k = await self._katalog_store.async_load() or {}
                if k.get("hentet") and time.time() - k["hentet"] < KATALOG_MAX_ALDER:
                    self.katalog = k["varer"]
                else:
                    self.katalog = await kilder.hent_rema_katalog(self.hass)
                    await self._katalog_store.async_save({"hentet": time.time(), "varer": self.katalog})
        if nye_tilbud or not self.plan:
            self._salling_priser = {}
            self._salling_fejl = False
        else:
            self._salling_priser = dict(self.plan.get("salling_priser") or {})
        if self.salling_aktiv and not self.salling:
            await self._hent_salling()
        # Navnelisten tager nogle sekunder første gang; den laves uden for HA's event loop.
        if self.salling:
            self._navne = await self.hass.async_add_executor_job(
                lambda: soeg.navneliste(self.salling, start, pris=lambda _vid, _v: 1.0)
            )
        else:
            self._navne = await self.hass.async_add_executor_job(soeg.navneliste, self.katalog, start)
        if nye_tilbud:
            # Kopier, så butiksmærket ikke ændrer i det, der blev hentet.
            hentet = await kilder.hent_tilbud(self.hass, self.dealer, start, slut)
            self.tilbud = {tid: {**t, "butik": self.butik} for tid, t in hentet.items()}
            for andre in self.ekstra_butikker[:MAKS_EKSTRA_BUTIKKER]:
                try:
                    ekstra = await kilder.hent_tilbud(self.hass, BUTIKKER[andre][1], start, slut)
                except Exception as e:  # noqa: BLE001 - planen laves med hovedbutikken alene
                    _LOGGER.warning("Tilbud fra %s kunne ikke hentes: %s", BUTIKKER[andre][0], e)
                    continue
                for tid, t in ekstra.items():
                    if tid not in self.tilbud:
                        self.tilbud[tid] = {**t, "butik": andre}
            try:
                self.butik_info = await kilder.hent_butik_info(self.hass, self.dealer)
            except Exception:  # noqa: BLE001 - logo og farve er pynt
                _LOGGER.debug("Kunne ikke hente butiksinfo for %s", self.butik_navn)
        else:
            self.tilbud = self.plan.get("tilbud") or {}

    async def _hent_salling(self) -> None:
        """Kædens katalog fra Salling (gemt en uge). Fejler det, bruges REMA's katalog som før."""
        brand, feed, _ = SALLING[self.butik]
        gemt = await self._salling_store.async_load() or {}
        if gemt.get("hentet") and time.time() - gemt["hentet"] < KATALOG_MAX_ALDER and gemt.get("varer"):
            self.salling = gemt["varer"]
            return
        try:
            self.salling = await kilder.hent_salling_katalog(self.hass, self.entry.options[CONF_SALLING_NOEGLE], feed)
            await self._salling_store.async_save({"hentet": time.time(), "varer": self.salling})
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Salling-katalog for %s kunne ikke hentes - bruger ca.-priser: %s", self.butik_navn, e)
            self.salling = gemt.get("varer") or {}
            self._salling_fejl = True

    async def _spoerg(self, opgave: str, byg: Callable[[bool], str]) -> dict:
        """Spørg med navnelisten; bliver svaret for langt, så én gang til uden (som før listen kom)."""
        try:
            return await self._spoerg_ai(opgave, byg(True))
        except ForLangtSvar:
            _LOGGER.warning("%s: svaret blev for langt - prøver uden navnelisten", opgave)
            return await self._spoerg_ai(opgave, byg(False) + "\nHold svaret ekstra kort.")

    async def _spoerg_ai(self, opgave: str, instruktioner: str) -> dict:
        """Kalder ai_task; prøver igen ved travlhed (503/429). Hvert forsøg er et kald."""
        sidste_fejl = ""
        for forsoeg in range(3):
            try:
                async with self._ai_laas:
                    svar = await self.hass.services.async_call(
                        "ai_task",
                        "generate_data",
                        {
                            "entity_id": self.entry.options[CONF_AI_ENTITY],
                            "task_name": opgave,
                            "instructions": instruktioner,
                        },
                        blocking=True,
                        return_response=True,
                    )
                if data := (svar or {}).get("data"):
                    return _parse_json(data)
                sidste_fejl = "tomt svar"
            except (HomeAssistantError, ValueError) as e:
                sidste_fejl = str(e)
            if "MAX_TOKENS" in sidste_fejl.upper():
                # Et for langt svar bliver ikke kortere af at spørge igen.
                raise ForLangtSvar(sidste_fejl)
            if re.search(r"per.?day|PerDay", sidste_fejl):
                # Dagskvoten er brugt: nye forsøg ville bare bruge af morgendagens kvote.
                raise HomeAssistantError("AI'ens gratis dagskvote er brugt op – prøv igen i morgen")
            _LOGGER.warning("AI-forsøg %s fejlede: %s", forsoeg + 1, sidste_fejl[:200])
            # Kvoten pr. minut (429) nulstilles efter et minut; hurtige forsøg bruger den bare op igen.
            kvote = re.search(r"429|quota|resource.?exhausted|rate.?limit", sidste_fejl, re.I)
            await asyncio.sleep(65 if kvote else 20 + forsoeg * 20)
        raise HomeAssistantError(f"AI svarede ikke: {sidste_fejl}")

    def _vare_tekst(self, liste: bool = True, aftensmad: bool = True) -> str:
        """Ugens tilbud og REMA's navne på basisvarerne. Pris og størrelse slås op bagefter.

        Uden liste (reserveforsøget efter et for langt svar) sendes også højst 150 tilbud."""
        tilbud = [
            (tid, t) for tid, t in self.tilbud.items() if not (aftensmad and soeg.IKKE_AFTENSMAD.search(t["navn"]))
        ]
        if not liste:
            tilbud = tilbud[:150]
        linjer = []
        for butik in [self.butik, *self.ekstra_butikker]:
            egne = [(tid, t) for tid, t in tilbud if t.get("butik", self.butik) == butik]
            if not egne:
                continue
            anden = "" if butik == self.butik else " – ANDEN BUTIK"
            linjer += ["" if linjer else None, f"TILBUD I {BUTIKKER[butik][0].upper()}{anden} (id|vare|størrelse|pris kr):"]
            linjer += [f"T:{tid}|{t['navn']}|{t['str']}|{t['pris']}" for tid, t in egne]
        linjer = [x for x in linjer if x is not None]
        if self.ekstra_butikker:
            linjer += self._sammenligning(tilbud)
        if liste and self._navne:
            linjer += ["", "ALMINDELIGE VARER (skriv 'S:' + et navn præcis som her):"]
            linjer.append("; ".join(self._navne))
        return "\n".join(linjer)

    def _find_vare(self, vare: Any, dato: datetime.date, behov: tuple[float, str] | None, kun_mad: bool = True) -> str:
        """'S:søgeord' -> 'R:id' på den billigste passende vare. Andet (og søgeord uden fund) gives tilbage."""
        v = str(vare or "").strip()
        if not v.startswith("S:"):
            return v
        if self.salling and (
            vid := soeg.find_vare(self.salling, v[2:], dato, behov, kun_mad, pris=lambda e, _v: self._salling_pris(e))
        ):
            return f"N:{vid}"
        if vid := soeg.find_vare(self.katalog, v[2:], dato, behov, kun_mad):
            return f"R:{vid}"
        return "S:" + v[2:].strip().lower()

    def _find_varer(self, retter: list[dict], dato: datetime.date) -> None:
        """Slår AI'ens søgeord op for hele ugen på én gang, så samme vare bliver samme produkt,
        og pakningen vælges efter den samlede mængde."""
        for ret in retter:
            for ing in ret.get("ingredienser", []):
                # AI'en giver af og til et forkert tilbuds-id (fx clementiner til nudler) - så søges der i stedet.
                v = str(ing.get("vare") or "")
                t = self.tilbud.get(v[2:]) if v.startswith("T:") else None
                if v.startswith("T:") and not (t and soeg.ligner(str(ing.get("navn", "")), t["navn"])):
                    ing["vare"] = f"S:{ing.get('navn', '')}"
        mgd: dict[str, dict[str, float]] = {}
        for ret in retter:
            for ing in ret.get("ingredienser", []):
                if str(ing.get("vare") or "").startswith("S:"):
                    try:
                        m = float(ing.get("pr_person") or 0) * self.personer
                    except (TypeError, ValueError):
                        m = 0.0
                    e = mgd.setdefault(_soege_noegle(ing["vare"]), {})
                    e[ing.get("enhed", "")] = e.get(ing.get("enhed", ""), 0.0) + m
        fundet = {}
        for v, enheder in mgd.items():
            enhed, m = max(enheder.items(), key=lambda x: x[1])
            fundet[v] = self._find_vare(v, dato, (m, enhed) if enhed in ("g", "ml", "stk") else None)
        for ret in retter:
            for ing in ret.get("ingredienser", []):
                v = _soege_noegle(ing.get("vare"))
                if v not in fundet:
                    continue
                ing["soeg"], ing["vare"] = v[2:], fundet[v]
        # Den rigtige pakningsstørrelse frem for AI'ens gæt - både for tilbud og katalogvarer.
        for ret in retter:
            for ing in ret.get("ingredienser", []):
                v = str(ing.get("vare") or "")
                kilde = {"T": self.tilbud, "R": self.katalog, "N": self.salling}.get(v[:1]) if v[1:2] == ":" else None
                vare = kilde.get(v[2:]) if kilde is not None else None
                s = soeg.stoerrelse(vare["str"]) if vare else None
                ing.pop("pakke_ukendt", None)
                vaegt = soeg.stk_vaegt(ing.get("navn", ""))
                if s and s[1] == ing.get("enhed"):
                    ing["pakke"] = s[0]
                elif s and s[1] == "g" and ing.get("enhed") == "stk" and vaegt:
                    ing["pakke"] = round(s[0] / vaegt, 1)  # fx 1 kg løg ≈ 8 stk
                elif s and s[1] == "stk" and ing.get("enhed") == "g" and vaegt:
                    ing["pakke"] = s[0] * vaegt  # fx 1 spidskål ≈ 800 g
                elif s and ing.get("enhed") in ("g", "ml", "stk"):
                    # Kan ikke regnes om (fx gram mod en vare pr. stk): AI'ens gæt kan være helt skævt,
                    # så regn med én pakning pr. ret i stedet.
                    ing["pakke_ukendt"] = True
            hv = str(ret.get("hovedvare") or "").strip()
            if hv.startswith("S:"):
                ret["hovedvare"] = fundet.get(_soege_noegle(hv)) or self._find_vare(hv, dato, None)

    @property
    def er_rema(self) -> bool:
        return self.butik == "rema1000"

    @property
    def salling_aktiv(self) -> bool:
        o = self.entry.options
        return self.butik in SALLING and bool(o.get(CONF_SALLING_NOEGLE)) and bool(o.get(CONF_SALLING_BUTIK))

    def _ca(self, vare_id: str) -> bool:
        """Cirkapris: REMA's katalogpris brugt i en anden kæde (ikke tilbud, ikke Salling, ikke ukendt)."""
        return str(vare_id).startswith("R:") and not self.er_rema

    def _salling_pris(self, ean: str) -> float | None:
        """Pris i den valgte butik. Kaldes fra en baggrundstråd under vareopslaget; fejl giver ca.-pris."""
        if ean not in self._salling_priser:
            o = self.entry.options
            try:
                self._salling_priser[ean] = asyncio.run_coroutine_threadsafe(
                    kilder.hent_salling_pris(self.hass, o[CONF_SALLING_NOEGLE], ean, o[CONF_SALLING_BUTIK]),
                    self.hass.loop,
                ).result(30)
            except Exception as e:  # noqa: BLE001 - falder tilbage til REMA's ca.-pris
                _LOGGER.warning("Salling-pris for %s kunne ikke hentes: %s", ean, e)
                self._salling_fejl = True
                return None
        return self._salling_priser[ean]

    def _alle_butikker(self) -> str:
        navne = [self.butik_navn, *(BUTIKKER[b][0] for b in self.ekstra_butikker[:MAKS_EKSTRA_BUTIKKER])]
        return navne[0] if len(navne) == 1 else ", ".join(navne[:-1]) + " og " + navne[-1]

    def _flere_butikker(self) -> str:
        if not self.ekstra_butikker:
            return ""
        return (
            f"FLERE BUTIKKER: Familien handler i {self._alle_butikker()}, og butikkerne er ligestillede. Familien vil "
            "gerne spare: sammenlign aktivt kød, fisk, grønt og mejerivarer på tværs af butikkerne (se SAMMENLIGNING "
            "nederst) og vælg den billigste, når forskellen er mærkbar. Saml indkøbet: en butik bruges kun, hvis I "
            f"køber mindst {MIN_PR_BUTIK} forskellige varer der – så vælg hellere flere gode tilbud fra samme butik. "
            f"Varer, der ikke er på tilbud (S:), købes i {self.butik_navn}.\n"
        )

    def _sammenligning(self, tilbud: list[tuple[str, dict]]) -> list[str]:
        """Kilopris for de vigtigste varer på tværs af butikkerne, så AI'en kan se, hvor det kan betale sig."""
        dato = dt_util.now().date()
        linjer = []
        for vare in SAMMENLIGN:
            bud = []
            for butik in [self.butik, *self.ekstra_butikker[:MAKS_EKSTRA_BUTIKKER]]:
                egne = {tid: t for tid, t in tilbud if t.get("butik", self.butik) == butik and t.get("pris")}

                def enhedspris(tid: str, t: dict) -> float | None:
                    s = soeg.stoerrelse(t["str"])
                    return float(t["pris"]) / s[0] * (1 if s[1] == "stk" else 1000) if s else None

                if (tid := soeg.find_vare(egne, vare, dato, pris=enhedspris)) and (p := enhedspris(tid, egne[tid])):
                    enhed = "stk" if soeg.stoerrelse(egne[tid]["str"])[1] == "stk" else "kg"
                    bud.append((p, BUTIKKER[butik][0], tid, enhed))
            if len(bud) > 1 and len({b[3] for b in bud}) == 1:
                bud.sort()
                linjer.append(f"{vare}: " + ", ".join(f"{b} {p:.0f} kr/{e} (T:{tid})" for p, b, tid, e in bud))
        if not linjer:
            return []
        return ["", "SAMMENLIGNING – billigste tilbud pr. kg/stk i hver butik (brug det billigste, når forskellen er "
                "mærkbar):", *linjer[:14]]

    def _saml_butikker(self, retter: list[dict]) -> None:
        """En tur i en anden butik for 1-2 varer er ikke det værd: de varer købes i hovedbutikken i stedet.
        Kører i koden efter AI'en, så det ikke koster ekstra kald."""
        pr_butik: dict[str, set[str]] = {}
        for ret in retter:
            for ing in ret.get("ingredienser", []):
                v = str(ing.get("vare") or "")
                if self._anden_butik(v):
                    pr_butik.setdefault(self.tilbud[v[2:]]["butik"], set()).add(v)
        for butik, varer in pr_butik.items():
            if len(varer) >= MIN_PR_BUTIK:
                continue
            _LOGGER.info("Kun %s vare(r) fra %s - købes i %s i stedet", len(varer), BUTIKKER[butik][0], self.butik_navn)
            for ret in retter:
                for ing in ret.get("ingredienser", []):
                    if ing.get("vare") in varer:
                        ing["vare"] = f"S:{ing.get('navn', '')}"
                if ret.get("hovedvare") in varer:
                    ret["hovedvare"] = None

    def _anden_butik(self, vare_id: str) -> str | None:
        """Navnet på den anden kæde, hvis varen er et tilbud derfra - ellers None (hovedbutikken)."""
        if str(vare_id).startswith("T:") and (t := self.tilbud.get(str(vare_id)[2:])):
            if (b := t.get("butik")) and b != self.butik and b in BUTIKKER:
                return BUTIKKER[b][0]
        return None

    async def async_saet_ekstra_butikker(self, butikker: list[str]) -> None:
        self.ekstra_butikker = [b for b in dict.fromkeys(butikker) if b in BUTIKKER and b != self.butik][
            :MAKS_EKSTRA_BUTIKKER
        ]
        await self._gem()
        self.opdater()

    def _familiens_regler(self) -> str:
        """Familiens egne regler fra panelet, som tekst til AI'en."""
        r = self.regler
        n = self.personer
        dele = []
        if r["budget"]:
            dele.append(
                f"BUDGET: hele ugens aftensmad må højst koste {r['budget']} kr for {n} personer "
                f"(ca. {r['budget'] / 7 / n:.0f} kr pr. person pr. ret)."
            )
        else:
            dele.append("BUDGET: sigt efter højst 15 kr pr. person pr. ret.")
        if r["allergier"]:
            dele.append(f"ALLERGI – må ALDRIG indgå i nogen ret, heller ikke i saucer o.l.: {', '.join(r['allergier'])}.")
        if r["undgaa"]:
            dele.append(f"Familien vil ikke have: {', '.join(r['undgaa'])}.")
        if r["oeko"]:
            dele.append("Vælg økologiske varer, når prisforskellen er lille (skriv fx 'S:økologisk letmælk').")
        if r["favoritter"]:
            dele.append(
                f"Familiens yndlingsretter – tag gerne 1-2 med, hvis de ikke var med de seneste uger: "
                f"{', '.join(r['favoritter'])}."
            )
        if r["faste_dage"]:
            faste = "; ".join(f"{DAGE[int(f['dag'])]}: {f['ret']}" for f in r["faste_dage"] if 0 <= int(f["dag"]) < 7)
            dele.append(f"FASTE DAGE – disse dage SKAL have denne ret: {faste}.")
        if r["krav"].strip():
            dele.append(f"Andre krav fra familien: {r['krav'].strip()}")
        return "\n".join(dele) + "\n"

    def _regler(self) -> str:
        r = self.regler
        varieret = []
        if r["fisk"]:
            varieret.append(f"mindst {r['fisk']} fiskeret{'ter' if r['fisk'] > 1 else ''}")
        if r["vegetar"]:
            varieret.append(f"mindst {r['vegetar']} vegetarret{'ter' if r['vegetar'] > 1 else ''}")
        boern = r.get("husstand", "boernefamilie") == "boernefamilie"
        koekkener = ", ".join(r.get("koekkener") or []) or "dansk, italiensk, asiatisk, mexicansk osv."
        return (
            f"Du er en dansk madplanlægger for {'en børnefamilie' if boern else 'en husstand med voksne'}. "
            "Retterne skal være: billige, nemme, "
            f"forholdsvis sunde (grøntsager i hver ret), hurtige (højst {r['max_tid']} min fra start til "
            f"servering på hverdage, højst {r.get('max_tid_weekend', 60)} min søndag og lørdag), "
            f"{'børnevenlige og ' if boern else ''}smage godt. Byg retterne primært på "
            f"ugens tilbudsvarer fra {self._alle_butikker()} (T:id fra listen). Varer, der ikke er på tilbud, skriver "
            "du som 'S:navn', hvor navn står PRÆCIS som på listen ALMINDELIGE VARER (fx 'S:Hakkede tomater', "
            "'S:Piskefløde 36%', 'S:Basmati ris'). Kun hvis varen slet ikke findes på listen, skriver du et kort, "
            "almindeligt dansk varenavn uden mærke og mængde. "
            + (
                ""
                if self.er_rema or self.salling_aktiv
                else "Varer uden tilbud får kun en cirkapris, så brug tilbudsvarer (T:) til så mange "
                "ingredienser som muligt – altid til kød, fisk, ost og grøntsager, når der findes et passende "
                "tilbud – og S:-varer kun til det, der ikke er på tilbud. "
            )
            + "Varier proteinet"
            + (f": {' og '.join(varieret)} om ugen, og" if varieret else ":")
            + f" samme protein højst to gange. Varier også køkkenet ({koekkener}).\n"
            + "Genbrug gerne den samme vare i flere retter (fx resten af en pakke hakket kød, fløde, ost eller "
            "grøntsager), så der bliver mindst muligt tilovers, og indkøbslisten bliver kort.\n"
            + self._flere_butikker()
            + self._familiens_regler()
            + "Undgå dyre varer (and, mørbrad, oksesteg, rejer, færdigretter) med mindre tilbudsprisen gør "
            "retten billig.\n"
            "TID: 'tid_min' er den samlede tid fra start til servering og skal være realistisk. Vælg "
            "kun retter, der reelt kan nås inden for tidsgrænsen for den dag (gryderetter, lasagne og "
            "steg kun, når der er tid nok).\n"
            "For hver ingrediens: 'pr_person' er mængden pr. person, 'enhed' er g, ml eller stk, og "
            "'pakke' er hvor meget af samme enhed der er i varens pakning (læs størrelsen på tilbud; for S:-varer "
            "en almindelig pakningsstørrelse). "
            "Sæt 'basis': true for basisvarer de fleste har hjemme (salt, peber, olie, smør, mel, "
            "sukker, tørrede krydderier, bouillon). 'hovedvare' er id'et på rettens vigtigste vare.\n"
            "Opskriftens trin skal være korte og konkrete på dansk: højst 6 trin. 'kort' højst 12 ord og "
            "'sundhed' højst 8 ord. Svar med kompakt JSON uden linjeskift.\n"
        )

    @staticmethod
    def _ret_skema() -> str:
        return (
            '{"navn": str, "kort": str (én linje), "tid_min": int, "sundhed": str (kort), '
            '"vegetar": bool, "fisk": bool, '
            '"hovedvare": "T:id" eller "S:navn", "trin": [str], '
            '"ingredienser": [{"navn": str, "pr_person": number, "enhed": "g"|"ml"|"stk", '
            '"vare": "T:id" eller "S:navn", "pakke": number, "basis": bool}]}'
        )

    # ------------------------------------------------------------------ beregning

    def _slaa_op(self, vare_id: Any, dato: datetime.date) -> tuple | None:
        """(navn, størrelse, pris, billede, tilbud) for et T:/R:-id, eller None."""
        if not vare_id or ":" not in str(vare_id):
            return None
        kilde, vid = str(vare_id).split(":", 1)
        if kilde == "T":
            t = self.tilbud.get(vid)
            if t and t.get("pris"):
                return t["navn"], t["str"], float(t["pris"]), t.get("billede"), True
        elif kilde == "R" and (v := self.katalog.get(vid)):
            if pris := kilder.rema_pris(v, dato):
                return v["navn"], v["str"], float(pris), v.get("billede"), False
        elif kilde == "N" and (v := self.salling.get(vid)) and (pris := self._salling_priser.get(vid)):
            return v["navn"], v["str"], float(pris), v.get("billede"), False
        elif kilde == "S" and vid.strip():
            # Søgeord uden fund i kataloget: kommer på listen uden pris i stedet for et gæt.
            return vid.strip().capitalize(), "", 0.0, None, False
        return None

    def _beregn(self, ny: bool = False) -> None:
        """Mængder og priser ud fra antal personer. Ingen AI her."""
        n = self.personer
        start = datetime.date.fromisoformat(self.plan["start"])
        forbrug: dict[str, dict] = {}
        for i, ret in enumerate(self.plan["retter"]):
            pris = 0.0
            linjer = []
            # Gæster en enkelt dag: den dag har sit eget antal personer.
            # Dobbeltportion: der laves også til resterne næste dag.
            n_ret = int(ret.get("personer") or n) * (2 if ret.get("dobbelt") else 1)
            for ing in ret.get("ingredienser", []):
                try:
                    mgd = float(ing.get("pr_person") or 0) * n_ret
                    pakke = float(ing.get("pakke") or 0)
                except (TypeError, ValueError):
                    mgd, pakke = 0.0, 0.0
                enhed = ing.get("enhed", "")
                vis = f"{round(mgd) if mgd >= 10 else round(mgd, 1):g} {enhed}".strip() if mgd else ""
                linjer.append(f"{vis} {ing.get('navn', '')}".strip())
                info = self._slaa_op(ing.get("vare"), start)
                if not info:
                    continue
                navn, strr, enhedspris, _, tilbud = info
                f = forbrug.setdefault(
                    ing["vare"],
                    {"navn": navn, "str": strr, "pris": enhedspris, "tilbud": tilbud, "andel": 0.0, "basis": True},
                )
                f["butik"] = self._anden_butik(ing["vare"])
                # Uden for REMA er normalprisen kun et cirkatal.
                f["ukendt"] = ing["vare"].startswith("S:")
                f["anslaaet"] = self._ca(ing["vare"])
                f["basis"] = f["basis"] and _basis(ing)
                if not _basis(ing) and (pakke > 0 or ing.get("pakke_ukendt")):
                    andel = 1.0 if ing.get("pakke_ukendt") else mgd / pakke
                    f["andel"] += andel
                    pris += andel * enhedspris
            hv = self._slaa_op(ret.get("hovedvare"), start)
            ret["_billede"] = hv[3] if hv else None
            ret["_pris"] = round(pris)
            ret["_linjer"] = linjer
            ret["_dato"] = (start + datetime.timedelta(days=i)).isoformat()
        # Basisvarer starter som "har hjemme"; ellers huskes brugerens valg.
        gamle = {} if ny else {v["key"]: v.get("hjemme", False) for v in self.plan.get("varer", [])}
        i_kurv = set() if ny else {v["key"] for v in self.plan.get("varer", []) if v.get("kurv")}
        varer = []
        for key, f in forbrug.items():
            antal = 1 if f["basis"] else max(1, math.ceil(f["andel"] - 0.15))
            # Sikkerhedsgrænse: en enkelt vare til en uges aftensmad er aldrig 400 pakker.
            if antal > MAKS_PAKKER:
                _LOGGER.warning("Usandsynlig mængde af %s (%s pakker) - sat til %s", f["navn"], antal, MAKS_PAKKER)
                f["for_mange"] = True
                antal = MAKS_PAKKER
            varer.append(
                {
                    "key": key,
                    "navn": f["navn"],
                    "str": f["str"],
                    "antal": antal,
                    "pris": round(antal * f["pris"], 2),
                    "tilbud": f["tilbud"],
                    "anslaaet": f.get("anslaaet", False),
                    "ukendt": f.get("ukendt", False),
                    "basis": f["basis"],
                    "for_mange": f.get("for_mange", False),
                    "hjemme": gamle.get(key, f["basis"]),
                    "kurv": key in i_kurv,
                    "butik": f.get("butik"),
                }
            )
        varer.sort(key=lambda v: (v["basis"], bool(v.get("butik")), not v["tilbud"], v["navn"]))
        self.plan["varer"] = varer
        self.plan["personer"] = n
        # Tilbuddene skal købes, før det første af dem udløber.
        brugt = {k[2:] for k in forbrug if k.startswith("T:")}
        self.plan["handl_senest"] = min((t["til"] for k, t in self.tilbud.items() if k in brugt and t.get("til")), default=None)
        self.plan["total_alle"] = round(sum(v["pris"] for v in varer))
        self._totaler()

    def _totaler(self) -> None:
        varer = self.plan.get("varer", [])
        self.plan["total"] = round(sum(v["pris"] for v in varer if not v.get("hjemme")))
        # Delt op i butikkens rigtige priser og cirkapriser (kun uden for REMA).
        self.plan["total_ca"] = round(sum(v["pris"] for v in varer if not v.get("hjemme") and v.get("anslaaet")))
        self.plan["total_alle_ca"] = round(sum(v["pris"] for v in varer if v.get("anslaaet")))
        self.plan["sparet"] = round(sum(v["pris"] for v in varer if v.get("hjemme")))
        self.plan["antal_mangler"] = sum(1 for v in varer if not v.get("hjemme"))
        ekstra = self.plan.get("ekstra", [])
        self.plan["ekstra_total"] = round(sum(e["pris"] for e in ekstra if not e.get("hjemme")))
        self.plan["ekstra_ca"] = round(sum(e["pris"] for e in ekstra if not e.get("hjemme") and e.get("anslaaet")))

    def _besked(self, mangler: list[dict]) -> str:
        try:
            start = datetime.date.fromisoformat(self.plan["start"])
            slut = start + datetime.timedelta(days=6)
            periode = f"{start.day}/{start.month}–{slut.day}/{slut.month}"
        except (KeyError, ValueError):
            periode = ""
        retter = [f"{DAGE[i]}: {r.get('navn', '')}" for i, r in enumerate(self.plan.get("retter", [])) if not r.get("fjernet")]
        opskrifter = []
        for i, r in enumerate(self.plan.get("retter", [])):
            if r.get("fjernet"):
                continue
            blok = [
                "─" * 30,
                f"{DAGE[i].upper()}: {r.get('navn', '')}",
                f"⏱️ {r.get('tid_min', '?')} min · 💰 ca. {r.get('_pris', '?')} kr"
                + (f" · 👥 {r['personer']} personer" if r.get("personer") else ""),
                "",
                "Ingredienser:",
            ]
            blok += [f"• {x}" for x in r.get("_linjer", [])]
            blok += ["", "Sådan gør du:"]
            blok += [f"{n}. {t}" for n, t in enumerate(r.get("trin", []), start=1)]
            opskrifter.append("\n".join(blok))
        ekstra = [v for v in mangler if "behov" in v]
        mangler = [v for v in mangler if "behov" not in v]
        ekstra_tekst = ""
        if ekstra:
            ekstra_tekst = f"\n\nEKSTRA · {len(ekstra)} varer · ca. {self.plan.get('ekstra_total', 0)} kr\n"
            for behov in dict.fromkeys(e["behov"] for e in ekstra):
                ekstra_tekst += f"\n{behov.capitalize()}:\n" + "\n".join(
                    f"☐ {vare_tekst(e)}  {pris_tekst(e, 0)}" for e in ekstra if e["behov"] == behov
                )
        return (
            f"Madplan uge {self.plan.get('uge', '')} ({periode}) · {self.plan.get('personer', '')} personer\n\n"
            + "\n".join(retter)
            + f"\n\nINDKØB · {len(mangler)} varer · ca. {self.plan.get('total', 0)} kr"
            + (f" (heraf ca. {self.plan['total_ca']} kr anslået)" if self.plan.get("total_ca") else "")
            + "\n"
            + f"🏷️ = på tilbud i {self.butik_navn}" + ("" if self.er_rema else " · ca. = anslået pris") + "\n\n"
            + "\n".join(f"☐ {vare_tekst(v)}  {pris_tekst(v, 0)}" for v in mangler if not v.get("butik"))
            + "".join(
                f"\n\nFRA {butik.upper()}:\n"
                + "\n".join(f"☐ {vare_tekst(v)}  {pris_tekst(v, 0)}" for v in mangler if v.get("butik") == butik)
                for butik in dict.fromkeys(v["butik"] for v in mangler if v.get("butik"))
            )
            + ekstra_tekst
            + "\n\n\nOPSKRIFTER\n"
            + "\n\n".join(opskrifter)
        )

    # ------------------------------------------------------------------ historik

    def _seneste_retter(self, start: str) -> list[str]:
        navne: list[str] = []
        for uge in self.historik[-(UNDGAA_UGER + 1) :]:
            if uge.get("start") != start:
                navne += uge.get("retter", [])
        return navne

    def _gem_historik(self) -> None:
        h = [u for u in self.historik if u.get("start") != self.plan["start"]]
        h.append(
            {
                "start": self.plan["start"],
                "retter": [
                    r.get("navn", "") for r in self.plan["retter"] if not r.get("fjernet") and r.get("rester_fra") is None
                ],
            }
        )
        self.historik = h[-HISTORIK_UGER:]


def vare_tekst(v: dict) -> str:
    """Kort varenavn til lister, fx '🏷️ 2 × Kyllingebryst (900 g)'."""
    mark = "🏷️ " if v["tilbud"] else ""
    # REMA's "underline" er fx "1 KG. / DANMARK KL. 1" -> behold kun størrelsen.
    strr = v["str"].split(" / ")[0].replace("pcs", "stk").replace("GR.", "g").replace("KG.", "kg")
    strr = strr.replace("LTR.", "l").replace("ML.", "ml").replace("STK.", "stk").strip()
    antal = f"{v['antal']} × " if v["antal"] > 1 else ""
    return f"{mark}{antal}{v['navn']} ({strr})" if strr else f"{mark}{antal}{v['navn']}"


def _basis(ing: dict) -> bool:
    """Basisvare (salt, olie, mel …): AI'en skal mene det, og navnet skal passe."""
    return bool(ing.get("basis")) and soeg.er_basis(str(ing.get("navn", "")))


def _soege_noegle(vare: Any) -> str:
    """'S:Hakkede Tomater ' -> 'S:hakkede tomater', så samme søgeord kun slås op én gang."""
    v = str(vare or "").strip()
    return "S:" + v[2:].strip().lower() if v[:2].upper() == "S:" else v


def pris_tekst(v: dict, decimaler: int = 2) -> str:
    if v.get("ukendt"):
        return "pris ukendt"
    return f"{'ca. ' if v.get('anslaaet') else ''}{v['pris']:.{decimaler}f} kr"


def _parse_json(tekst: Any) -> dict:
    if isinstance(tekst, dict):
        return tekst
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(tekst).strip())
    return json.loads(t[t.find("{") : t.rfind("}") + 1])
