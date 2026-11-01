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
    DAGE,
    DOMAIN,
    HISTORIK_UGER,
    KATALOG_MAX_ALDER,
    SIGNAL_OPDATERET,
    STANDARD_PERSONER,
    STANDARD_REGLER,
    UNDGAA_UGER,
)

_LOGGER = logging.getLogger(__name__)
MAKS_PAKKER = 10


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
        aktive = [(i, ret) for i, ret in enumerate(retter) if not ret.get("fjernet")]
        forbudt = [(o, "allergi") for o in r["allergier"]] + [(o, "undgå") for o in r["undgaa"]]
        for i, ret in aktive:
            tekst = " ".join([ret.get("navn", "")] + [str(x.get("navn", "")) for x in ret.get("ingredienser", [])]).lower()
            for ord_, slags in forbudt:
                if ord_.strip() and re.search(rf"\b{re.escape(ord_.strip().lower())}", tekst):
                    ud.append(f"{DAGE[i]}: indeholder {ord_} ({slags})")
            if 1 <= i <= 5 and int(ret.get("tid_min") or 0) > r["max_tid"]:
                ud.append(f"{DAGE[i]}: tager {ret.get('tid_min')} min (højst {r['max_tid']} på hverdage)")
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
        if r["budget"] and self.plan.get("total_alle", 0) > r["budget"]:
            ud.append(f"Koster {self.plan['total_alle']} kr (budget {r['budget']} kr)")
        return ud

    def opdater(self) -> None:
        async_dispatcher_send(self.hass, self.signal)

    def _status(self, tekst: str) -> None:
        self.plan["status"] = tekst
        self.opdater()

    # ------------------------------------------------------------------ handlinger

    async def async_ny_plan(self) -> None:
        if self.optaget:
            return
        async with self._laas:
            try:
                self._status("Henter tilbud og laver madplan …")
                start, slut = self._plan_uge()
                await self._hent_data(start, slut, nye_tilbud=True)
                undgaa = self._seneste_retter(start.isoformat())
                # Midt på ugen planlægges kun fra i dag; dagene før står som "forbi".
                fra = max(0, min(6, (dt_util.now().date() - start).days))
                antal = 7 - fra
                # Faste behov (pålæg, madpakker …) løses i samme AI-kald - gratis-kvoten tæller kald.
                behov = list(self.behov)
                instr = (
                    self._regler()
                    + f"Lav {antal} aftensmåltider for {DAGE[fra]} "
                    + f"{(start + datetime.timedelta(days=fra)).isoformat()} til {DAGE[6]} {slut.isoformat()}.\n"
                    + (f"Undgå disse retter fra de seneste uger: {', '.join(undgaa)}.\n" if undgaa else "")
                    + (f"\nEKSTRA VARER: {self._behov_regler(behov)}\n" if behov else "")
                    + f'Svar KUN med JSON: {{"retter": [{antal} x '
                    + self._ret_skema()
                    + "]"
                    + (", " + self._behov_skema() if behov else "")
                    + f"}} med retterne i rækkefølge {DAGE[fra].lower()} til lørdag.\n\n"
                )
                svar = await self._spoerg("Madplan uge", lambda liste: instr + self._vare_tekst(liste))
                nye = svar.get("retter", [])[:antal]
                if len(nye) < antal:
                    raise HomeAssistantError(f"AI gav kun {len(nye)} retter")
                await self.hass.async_add_executor_job(self._find_varer, nye, start)
                retter = [{"navn": "Før planen", "fjernet": True, "forbi": True} for _ in range(fra)] + nye
                self.plan = {
                    "start": start.isoformat(),
                    "slut": slut.isoformat(),
                    "uge": (start + datetime.timedelta(days=1)).isocalendar()[1],
                    "tilbud": self.tilbud,
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
                        self._gem_behov(svar.get("varer", []), behov, start)
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
            if ing["har"] or ing.get("basis") or not (info := self._slaa_op(ing.get("vare"), dato)):
                continue
            navn, strr, enhedspris, _, tilbud = info
            k = koeb.setdefault(ing["vare"], {"navn": navn, "str": strr, "enhedspris": enhedspris, "tilbud": tilbud,
                                              "ukendt": ing["vare"].startswith("S:"), "andel": 0.0})
            k["andel"] += 1.0 if ing.get("pakke_ukendt") or pakke <= 0 else mgd / pakke
        varer = []
        for k in koeb.values():
            antal = min(MAKS_PAKKER, max(1, math.ceil(k["andel"] - 0.15)))
            v = {"navn": k["navn"], "str": k["str"], "antal": antal, "pris": round(antal * k["enhedspris"], 2),
                 "tilbud": k["tilbud"], "ukendt": k["ukendt"], "anslaaet": not k["tilbud"] and not self.er_rema and not k["ukendt"]}
            varer.append({"tekst": vare_tekst(v), "pris": pris_tekst(v, 0), "kr": 0 if k["ukendt"] else v["pris"], "tilbud": k["tilbud"]})
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
            "koeb_ca": not self.er_rema and any(not v["tilbud"] for v in varer),
        }

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

    def _en_status(self, tekst: str) -> None:
        self.en_ret_status = tekst
        self.opdater()

    async def async_fjern_ret(self, dag: int) -> None:
        """Ingen aftensmad den dag (ude, rester osv.). 'Byt ret' giver en ret igen."""
        if self.optaget or not self.plan.get("retter") or not 1 <= dag <= 7:
            return
        async with self._laas:
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
        self._gem_behov(svar.get("varer", []), behov, start)

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
                    "anslaaet": not tilbud and not self.er_rema and not v["vare"].startswith("S:"),
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
                        {"entity_id": liste, "item": vare_tekst(v), "description": pris_tekst(v)},
                        blocking=True,
                    )
            if notify := opts.get(CONF_NOTIFY):
                domaene, _, tjeneste = notify.partition(".")
                await self.hass.services.async_call(
                    domaene,
                    tjeneste,
                    {
                        "title": f"Indkøbsliste uge {self.plan.get('uge', '')} – {self.butik_navn}",
                        "message": self._besked(mangler),
                    },
                    blocking=True,
                )
            self._status(f"✅ Indkøbslisten er sendt ({len(mangler)} varer)")
        except HomeAssistantError as e:
            _LOGGER.error("Overførsel fejlede: %s", e)
            self._status(f"Fejl ved overførsel: {str(e)[:120]}")

    # ------------------------------------------------------------------ data

    def _plan_uge(self) -> tuple[datetime.date, datetime.date]:
        """Lørdag planlægges næste uge; søndag-fredag den igangværende uge."""
        idag = dt_util.now().date()
        if idag.weekday() == 5:
            start = idag + datetime.timedelta(days=1)
        else:
            start = idag - datetime.timedelta(days=(idag.weekday() + 1) % 7)
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
        # Navnelisten tager nogle sekunder første gang; den laves uden for HA's event loop.
        self._navne = await self.hass.async_add_executor_job(soeg.navneliste, self.katalog, start)
        if nye_tilbud:
            self.tilbud = await kilder.hent_tilbud(self.hass, self.dealer, start, slut)
            try:
                self.butik_info = await kilder.hent_butik_info(self.hass, self.dealer)
            except Exception:  # noqa: BLE001 - logo og farve er pynt
                _LOGGER.debug("Kunne ikke hente butiksinfo for %s", self.butik_navn)
        else:
            self.tilbud = self.plan.get("tilbud") or {}

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
        linjer = [f"TILBUD I {self.butik_navn.upper()} (id|vare|størrelse|pris kr):"]
        linjer += [f"T:{tid}|{t['navn']}|{t['str']}|{t['pris']}" for tid, t in tilbud]
        if liste and self._navne:
            linjer += ["", "ALMINDELIGE VARER (skriv 'S:' + et navn præcis som her):"]
            linjer.append("; ".join(self._navne))
        return "\n".join(linjer)

    def _find_vare(self, vare: Any, dato: datetime.date, behov: tuple[float, str] | None, kun_mad: bool = True) -> str:
        """'S:søgeord' -> 'R:id' på den billigste passende vare. Andet (og søgeord uden fund) gives tilbage."""
        v = str(vare or "").strip()
        if not v.startswith("S:"):
            return v
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
                vare = self.tilbud.get(v[2:]) if v.startswith("T:") else self.katalog.get(v[2:]) if v.startswith("R:") else None
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
        return (
            "Du er en dansk madplanlægger for en børnefamilie. Retterne skal være: billige, nemme, "
            f"forholdsvis sunde (grøntsager i hver ret), hurtige (højst {r['max_tid']} min fra start til "
            f"servering på hverdage, højst {max(60, r['max_tid'])} min søndag og lørdag), børnevenlige og "
            "smage godt. Byg retterne primært på "
            f"ugens tilbudsvarer fra {self.butik_navn} (T:id fra listen). Varer, der ikke er på tilbud, skriver "
            "du som 'S:navn', hvor navn står PRÆCIS som på listen ALMINDELIGE VARER (fx 'S:Hakkede tomater', "
            "'S:Piskefløde 36%', 'S:Basmati ris'). Kun hvis varen slet ikke findes på listen, skriver du et kort, "
            "almindeligt dansk varenavn uden mærke og mængde. "
            + (
                ""
                if self.er_rema
                else "Varer uden tilbud får kun en cirkapris, så brug tilbudsvarer (T:) til så mange "
                "ingredienser som muligt – altid til kød, fisk, ost og grøntsager, når der findes et passende "
                "tilbud – og S:-varer kun til det, der ikke er på tilbud. "
            )
            + "Varier proteinet"
            + (f": {' og '.join(varieret)} om ugen, og" if varieret else ":")
            + " samme protein højst to gange. Varier også køkkenet (dansk, italiensk, asiatisk, mexicansk osv.).\n"
            + self._familiens_regler()
            + "Undgå dyre varer (and, mørbrad, oksesteg, rejer, færdigretter) med mindre tilbudsprisen gør "
            "retten billig.\n"
            "TID: 'tid_min' er den samlede tid fra start til servering og skal være realistisk. Vælg "
            "kun retter, der reelt kan nås inden for tidsgrænsen (fx ikke flæskesteg eller gryderetter "
            "med lang simretid).\n"
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
            n_ret = int(ret.get("personer") or n)
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
                # Uden for REMA er normalprisen kun et cirkatal.
                f["ukendt"] = ing["vare"].startswith("S:")
                f["anslaaet"] = not tilbud and not self.er_rema and not f["ukendt"]
                f["basis"] = f["basis"] and bool(ing.get("basis"))
                if not ing.get("basis") and (pakke > 0 or ing.get("pakke_ukendt")):
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
                }
            )
        varer.sort(key=lambda v: (v["basis"], not v["tilbud"], v["navn"]))
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
            + "\n".join(f"☐ {vare_tekst(v)}  {pris_tekst(v, 0)}" for v in mangler)
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
            {"start": self.plan["start"], "retter": [r.get("navn", "") for r in self.plan["retter"] if not r.get("fjernet")]}
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
