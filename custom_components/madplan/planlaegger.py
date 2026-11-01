"""Selve madplanen: AI vælger retter, priser og mængder regnes ud her."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import math
import re
import time
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
    UNDGAA_UGER,
)

_LOGGER = logging.getLogger(__name__)


class Madplan:
    """Holder planen, varelisten og historikken for én config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.butik = entry.data[CONF_BUTIK]
        self.butik_navn, self.dealer = BUTIKKER[self.butik]
        self.butik_info: dict[str, Any] = {"navn": self.butik_navn, "logo": None, "farve": None}
        # Fælles for alle butikker: ét REMA-katalog og ét AI-kald ad gangen.
        faelles = hass.data.setdefault(DOMAIN, {"katalog_laas": asyncio.Lock(), "ai_laas": asyncio.Lock()})
        self._katalog_laas = faelles["katalog_laas"]
        self._ai_laas = faelles["ai_laas"]
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._katalog_store = Store(hass, 1, f"{DOMAIN}.katalog")
        self.plan: dict[str, Any] = {}
        self.historik: list[dict] = []
        self.personer = STANDARD_PERSONER
        self.katalog: dict[str, dict] = {}
        self.tilbud: dict[str, dict] = {}
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
            }
        )

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
                # Faste behov (pålæg, madpakker …) løses i samme AI-kald - gratis-kvoten tæller kald.
                behov = list(self.behov)
                instr = (
                    self._regler()
                    + f"Lav 7 aftensmåltider for {DAGE[0]} {start.isoformat()} til {DAGE[6]} {slut.isoformat()}.\n"
                    + (f"Undgå disse retter fra de seneste uger: {', '.join(undgaa)}.\n" if undgaa else "")
                    + (f"\nEKSTRA VARER: {self._behov_regler(behov)}\n" if behov else "")
                    + 'Svar KUN med JSON: {"retter": [7 x '
                    + self._ret_skema()
                    + "]"
                    + (", " + self._behov_skema() if behov else "")
                    + "} med retterne i rækkefølge søndag til lørdag.\n\n"
                    + self._vare_tekst()
                )
                svar = await self._spoerg_ai("Madplan uge", instr)
                retter = svar.get("retter", [])[:7]
                if len(retter) < 7:
                    raise HomeAssistantError(f"AI gav kun {len(retter)} retter")
                self._find_varer(retter, start)
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
                    + f"Lav én ny ret til {DAGE[dag - 1].lower()}, som er anderledes end ugens andre retter "
                    + "(andet protein eller køkken), og undgå retter fra de seneste uger: "
                    + ", ".join(self._seneste_retter(self.plan["start"]))
                    + ".\n"
                    + "Svar KUN med JSON: "
                    + self._ret_skema()
                    + "\n\n"
                    + self._vare_tekst()
                )
                ret = await self._spoerg_ai("Madplan byt ret", instr)
                if "retter" in ret:
                    ret = ret["retter"][0]
                self._find_varer([ret], start)
                self.plan["retter"][dag - 1] = ret
                self._beregn()
                self._gem_historik()
                self.plan["status"] = "Klar"
                await self._gem()
                self.opdater()
            except Exception as e:  # noqa: BLE001
                _LOGGER.exception("Byt ret fejlede")
                self._status(f"Fejl: {str(e)[:120]}")

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
            await self._hent_data(datetime.date.fromisoformat(self.plan["start"]), None)
            self._beregn()
        self._totaler()
        await self._gem()
        self.opdater()

    async def async_saet_hjemme(self, key: str, hjemme: bool) -> None:
        """Afkrydsning i varelisten: varen er allerede hjemme."""
        for v in self.plan.get("varer", []):
            if v["key"] == key:
                v["hjemme"] = hjemme
        self._totaler()
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

    async def async_tilfoej_behov(self, tekst: str) -> None:
        """Fx "pålæg" eller "frugt til madpakker": AI vælger tilbudsvarer til en uge."""
        tekst = tekst.strip()
        if not tekst or self.optaget:
            return
        async with self._laas:
            try:
                if tekst.lower() not in (b.lower() for b in self.behov):
                    self.behov.append(tekst)
                self._status(f"Finder tilbud på {tekst} …")
                await self._loes_behov([tekst])
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
            "Svar KUN med JSON: {" + self._behov_skema() + "}\n\n" + self._vare_tekst()
        )
        svar = await self._spoerg_ai("Madplan ekstra varer", instr)
        self._gem_behov(svar.get("varer", []), behov, start)

    @staticmethod
    def _behov_regler(behov: list[str]) -> str:
        return (
            "Ud over aftensmaden skal familien bruge varer til hvert behov herunder. Vælg konkrete, almindelige "
            "varer, som familien vil kunne lide, og brug så vidt muligt tilbudsvarer (T:id fra listen). Er der "
            "ikke et passende tilbud, så skriv varen som 'S:søgeord' (et kort, almindeligt dansk varenavn uden "
            "mærke og mængde, fx 'S:leverpostej'). Hold det billigt, og vælg højst 3-4 forskellige varer pr. "
            f"behov. Behov: {'; '.join(behov)}"
        )

    @staticmethod
    def _behov_skema() -> str:
        return '"varer": [{"behov": str (præcis som skrevet), "vare": "T:id" eller "S:søgeord", "hvorfor": str (kort)}]'

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
        if nye_tilbud:
            self.tilbud = await kilder.hent_tilbud(self.hass, self.dealer, start, slut)
            try:
                self.butik_info = await kilder.hent_butik_info(self.hass, self.dealer)
            except Exception:  # noqa: BLE001 - logo og farve er pynt
                _LOGGER.debug("Kunne ikke hente butiksinfo for %s", self.butik_navn)
        else:
            self.tilbud = self.plan.get("tilbud") or {}

    async def _spoerg_ai(self, opgave: str, instruktioner: str) -> dict:
        """Kalder ai_task; prøver igen ved travlhed (503/429)."""
        sidste_fejl = ""
        for forsoeg in range(5):
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
            if re.search(r"per.?day|PerDay", sidste_fejl):
                # Dagskvoten er brugt: nye forsøg ville bare bruge af morgendagens kvote.
                raise HomeAssistantError("AI'ens gratis dagskvote er brugt op – prøv igen i morgen")
            _LOGGER.warning("AI-forsøg %s fejlede: %s", forsoeg + 1, sidste_fejl[:200])
            # Kvoten pr. minut (429) nulstilles efter et minut; hurtige forsøg bruger den bare op igen.
            kvote = re.search(r"429|quota|resource.?exhausted|rate.?limit", sidste_fejl, re.I)
            await asyncio.sleep(65 if kvote else 20 + forsoeg * 20)
        raise HomeAssistantError(f"AI svarede ikke: {sidste_fejl}")

    def _vare_tekst(self) -> str:
        """Kun ugens tilbud. Resten skriver AI'en som søgeord, og de slås op i REMA's katalog
        bagefter - hele sortimentet i hvert kald ville bruge ca. 50.000 tokens."""
        linjer = [f"TILBUD I {self.butik_navn.upper()} (id|vare|størrelse|pris kr):"]
        linjer += [f"T:{tid}|{t['navn']}|{t['str']}|{t['pris']}" for tid, t in self.tilbud.items()]
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
                # Den rigtige pakningsstørrelse frem for AI'ens gæt.
                if ing["vare"].startswith("R:") and (
                    (s := soeg.stoerrelse(self.katalog[ing["vare"][2:]]["str"])) and s[1] == ing.get("enhed")
                ):
                    ing["pakke"] = s[0]
            hv = str(ret.get("hovedvare") or "").strip()
            if hv.startswith("S:"):
                ret["hovedvare"] = fundet.get(_soege_noegle(hv)) or self._find_vare(hv, dato, None)

    @property
    def er_rema(self) -> bool:
        return self.butik == "rema1000"

    def _regler(self) -> str:
        return (
            "Du er en dansk madplanlægger for en børnefamilie. Retterne skal være: billige, nemme, "
            "forholdsvis sunde (grøntsager i hver ret), hurtige (højst 40 min aktiv tid på hverdage, "
            "højst 60 min søndag og lørdag), børnevenlige og smage godt. Byg retterne primært på "
            f"ugens tilbudsvarer fra {self.butik_navn} (T:id fra listen). Varer, der ikke er på tilbud, skriver "
            "du som 'S:søgeord': et kort, almindeligt dansk varenavn, som det står i et supermarked, uden mærke "
            "og mængde (fx 'S:hakkede tomater', 'S:piskefløde', 'S:basmati ris', 'S:løg', 'S:letmælk'). "
            + (
                ""
                if self.er_rema
                else "Varer uden tilbud får kun en cirkapris, så brug tilbudsvarer (T:) til så mange "
                "ingredienser som muligt – altid til kød, fisk, ost og grøntsager, når der findes et passende "
                "tilbud – og S:-varer kun til det, der ikke er på tilbud. "
            )
            + "Varier proteinet: mindst én fiskeret og én vegetarret om ugen, og samme protein højst to "
            "gange. Varier også køkkenet (dansk, italiensk, asiatisk, mexicansk osv.).\n"
            "BUDGET: sigt efter højst 15 kr pr. person pr. ret. Undgå dyre varer (and, mørbrad, "
            "oksesteg, rejer, færdigretter) med mindre tilbudsprisen gør retten billig.\n"
            "TID: 'tid_min' er den samlede tid fra start til servering og skal være realistisk. Vælg "
            "kun retter, der reelt kan nås inden for tidsgrænsen (fx ikke flæskesteg eller gryderetter "
            "med lang simretid).\n"
            "For hver ingrediens: 'pr_person' er mængden pr. person, 'enhed' er g, ml eller stk, og "
            "'pakke' er hvor meget af samme enhed der er i varens pakning (læs størrelsen på tilbud; for S:-varer "
            "en almindelig pakningsstørrelse). "
            "Sæt 'basis': true for basisvarer de fleste har hjemme (salt, peber, olie, smør, mel, "
            "sukker, tørrede krydderier, bouillon). 'hovedvare' er id'et på rettens vigtigste vare.\n"
            "Opskriftens trin skal være korte og konkrete på dansk.\n"
        )

    @staticmethod
    def _ret_skema() -> str:
        return (
            '{"navn": str, "kort": str (én linje), "tid_min": int, "sundhed": str (kort), '
            '"hovedvare": "T:id" eller "S:søgeord", "trin": [str], '
            '"ingredienser": [{"navn": str, "pr_person": number, "enhed": "g"|"ml"|"stk", '
            '"vare": "T:id" eller "S:søgeord", "pakke": number, "basis": bool}]}'
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
            for ing in ret.get("ingredienser", []):
                try:
                    mgd = float(ing.get("pr_person") or 0) * n
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
                if not ing.get("basis") and pakke > 0:
                    andel = mgd / pakke
                    f["andel"] += andel
                    pris += andel * enhedspris
            hv = self._slaa_op(ret.get("hovedvare"), start)
            ret["_billede"] = hv[3] if hv else None
            ret["_pris"] = round(pris)
            ret["_linjer"] = linjer
            ret["_dato"] = (start + datetime.timedelta(days=i)).isoformat()
        # Basisvarer starter som "har hjemme"; ellers huskes brugerens valg.
        gamle = {} if ny else {v["key"]: v.get("hjemme", False) for v in self.plan.get("varer", [])}
        varer = []
        for key, f in forbrug.items():
            antal = 1 if f["basis"] else max(1, math.ceil(f["andel"] - 0.15))
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
                    "hjemme": gamle.get(key, f["basis"]),
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
                f"⏱️ {r.get('tid_min', '?')} min · 💰 ca. {r.get('_pris', '?')} kr",
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
