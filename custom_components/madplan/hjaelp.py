"""Hjælp: tjek madplan, få hjælp og lær sammen.

- Tjek madplan (service madplan.tjek): henter tilbuddene fra hver valgt kæde, prøver Salling-nøglen, ser at AI'en og
  beskederne findes - og viser ✅/❌ for hver del.
- Få hjælp (service madplan.faa_hjaelp): brugerens besked, op til 3 billeder, tjekket og en kort diagnose sendes
  privat til udvikleren (samme modtager som Energipilot, mærket "madplan"). Kun når brugeren trykker.
- Lær sammen (slået til, kan slås fra): én gang i døgnet en lille anonym linje (version, kæder, hvilke funktioner der
  bruges), antal tilbud pr. kæde når de hentes, varer søgningen ikke kunne finde, og fejl i appen.

- Svar: når udvikleren skriver en kommentar på hjælpebeskeden, henter Madplan den hver time i 60 dage (med sit eget
  install-id, så ingen andre kan læse den), viser den under Hjælp og giver en besked i Home Assistant. Brugeren kan
  skrive tilbage derfra.

Sendes aldrig: allergier, husstand, kostmål, regler, opskrifter, indkøbslister, navne, adresse eller nøgler.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
import time
import traceback
import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import BUTIKKER, CONF_AI_ENTITY, CONF_NOTIFY, CONF_SALLING_NOEGLE, DOMAIN

_LOGGER = logging.getLogger(__name__)
URL = "https://ep-reports.clahen86.workers.dev"
HOVED = {"x-ep-client": "madplan"}
DOEGN = 24 * 3600
SVAR_DAGE = 60


class Hjaelp:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store = Store(hass, 1, f"{DOMAIN}.hjaelp")
        self.d: dict[str, Any] = {}
        self._fejl_sendt: dict[str, str] = {}
        self._ikke_fundet: set[str] = set()
        self.seneste_fejl: list[str] = []

    async def async_indlaes(self) -> None:
        self.d = await self.store.async_load() or {}
        if not self.d.get("install"):
            self.d["install"] = uuid.uuid4().hex
            await self.store.async_save(self.d)

    @property
    def del_anonymt(self) -> bool:
        return self.d.get("del", True) is not False

    async def async_saet_del(self, til: bool) -> None:
        self.d["del"] = bool(til)
        await self.store.async_save(self.d)

    def version(self) -> str:
        try:
            import json
            from pathlib import Path

            return json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]
        except Exception:  # noqa: BLE001
            return "?"

    def _madplaner(self) -> list[Any]:
        return [e.runtime_data for e in self.hass.config_entries.async_loaded_entries(DOMAIN) if getattr(e, "runtime_data", None)]

    # ---------- sende ----------
    async def _post(self, sti: str, data: dict[str, Any], timeout: int = 20) -> dict[str, Any] | None:
        try:
            s = async_get_clientsession(self.hass)
            async with s.post(f"{URL}{sti}", json=data, headers=HOVED, timeout=timeout) as r:
                svar = await r.json(content_type=None)
                return svar if r.status == 200 else {"error": svar.get("error") or f"http_{r.status}"}
        except Exception as e:  # noqa: BLE001 - aldrig i vejen for madplanen
            return {"error": "unreachable", "detail": str(e)[:120]}

    def _linje(self, kind: str, data: dict[str, Any]) -> None:
        """En lille anonym linje i baggrunden - kun når det er slået til."""
        if not self.del_anonymt:
            return
        self.hass.async_create_background_task(self._post("/t", {"kind": kind, "install": self.d.get("install"), **data}), "madplan lær sammen")

    # ---------- lær sammen ----------
    def tilbud(self, antal: dict[str, int]) -> None:
        self._linje("offers", {"offers": antal})

    def ikke_fundet(self, navn: str) -> None:
        navn = str(navn).strip().lower()[:40]
        if navn and len(self._ikke_fundet) < 200:
            self._ikke_fundet.add(navn)

    def fejl(self, record: logging.LogRecord) -> None:
        if not record.exc_info or not record.exc_info[1]:
            return
        exc = record.exc_info[1]
        rammer = [r for r in traceback.extract_tb(record.exc_info[2]) if "madplan" in r.filename]
        hvor = f"{os.path.basename(rammer[-1].filename)}:{rammer[-1].lineno} {rammer[-1].name}" if rammer else "?"
        tekst = f"{type(exc).__name__} at {hvor}"
        self.seneste_fejl = (self.seneste_fejl + [tekst])[-10:]
        h = hashlib.sha1(tekst.encode()).hexdigest()[:16]
        idag = datetime.date.today().isoformat()
        if self._fejl_sendt.get(h) == idag:
            return
        self._fejl_sendt[h] = idag
        self._linje("error", {"hash": h, "text": tekst, "version": self.version()})

    def daglig(self) -> dict[str, Any]:
        planer = self._madplaner()
        hoved = planer[0] if planer else None
        ai = (hoved.entry.options.get(CONF_AI_ENTITY) or "") if hoved else ""
        return {
            "version": self.version(), "ha": str(getattr(self.hass.config, "version", "") or "")[:12] or None,
            "chain": [p.butik_navn for p in planer],
            "extra": sorted({BUTIKKER[b][0] for p in planer for b in (p.ekstra_butikker or []) if b in BUTIKKER}),
            "ai": ai.split(".", 1)[1].split("_")[0] if "." in ai else None,  # fx "gemini" - aldrig nøgler
            "salling": any(p.salling_aktiv for p in planer),
            "profiles": len(((getattr(hoved, "profiler", None) or {}).get("profiler") or {})) if hoved else 0,
            "features": {"auto_plan": any(getattr(p, "auto_plan", False) for p in planer),
                         "rester": any(bool((p.regler or {}).get("rester")) for p in planer),
                         "mine_retter": any(bool(getattr(p, "mine_retter", None)) for p in planer),
                         "kcal": any(bool((p.regler or {}).get("kcal")) for p in planer),
                         "mail": any(bool(p.entry.options.get(CONF_NOTIFY)) for p in planer)},
        }

    # ---------- svar fra udvikleren ----------
    def vil_have_svar(self) -> bool:
        return time.time() - float((self.d.get("seneste_hjaelp") or {}).get("t") or 0) < SVAR_DAGE * DOEGN

    async def async_hent_svar(self, besked: bool = True) -> dict[str, Any]:
        d = await self._post("/replies", {"install": self.d.get("install")})
        if not d or "reports" not in d:
            return self.d.get("svar") or {}
        self.d["svar"] = {"reports": d["reports"][:5], "t": time.time()}
        dev = sum(1 for r in self.d["svar"]["reports"] for m in r.get("msgs") or [] if m.get("from") == "dev")
        set_ = int(self.d.get("svar_set") or 0)
        self.d["svar_set"] = dev
        await self.store.async_save(self.d)
        if besked and dev > set_:
            from homeassistant.components import persistent_notification

            persistent_notification.async_create(self.hass, "💬 Udvikleren har svaret på din besked. Åbn Madplan → 🛟 Hjælp for at læse og svare.",
                                                 title="Madplan", notification_id="madplan_svar")
        return self.d["svar"]

    async def async_skriv_tilbage(self, rapport: str, tekst: str) -> dict[str, Any]:
        svar = await self._post("/reply", {"install": self.d.get("install"), "id": str(rapport)[:40], "text": str(tekst)[:4000]})
        if svar and svar.get("ok"):
            await self.async_hent_svar(besked=False)
            return {"ok": True, **self.status()}
        return {"ok": False, "error": (svar or {}).get("error", "unreachable"), **self.status()}

    async def async_dagens_runde(self, _now: Any = None) -> None:
        if self.vil_have_svar() and time.time() - float((self.d.get("svar") or {}).get("t") or 0) >= 3000:
            await self.async_hent_svar()
        if not self.del_anonymt:
            return
        if time.time() - float(self.d.get("sendt") or 0) >= DOEGN:
            svar = await self._post("/t", {"kind": "daily", "install": self.d["install"], "data": self.daglig()})
            if svar and svar.get("ok"):
                self.d["sendt"] = time.time()
                await self.store.async_save(self.d)
        if self._ikke_fundet:
            ord_, self._ikke_fundet = sorted(self._ikke_fundet)[:30], set()
            await self._post("/t", {"kind": "nomatch", "install": self.d["install"], "terms": ord_})

    # ---------- tjek madplan ----------
    async def async_tjek(self) -> list[dict[str, Any]]:
        from . import kilder

        ud: list[dict[str, Any]] = []
        idag = datetime.date.today()
        planer = self._madplaner()
        if not planer:
            return [{"del": "Madplan", "ok": False, "tekst": "Ingen butik sat op endnu"}]
        kaeder = {}
        for p in planer:
            kaeder[p.butik_navn] = p.dealer
            for b in (p.ekstra_butikker or []):
                if b in BUTIKKER:
                    kaeder.setdefault(BUTIKKER[b][0], BUTIKKER[b][1])
        for navn, dealer in kaeder.items():
            try:
                n = len(await kilder.hent_tilbud(self.hass, dealer, idag, idag + datetime.timedelta(days=6)))
                ud.append({"del": f"Tilbud fra {navn}", "ok": n > 0, "tekst": f"{n} tilbud" if n else "Ingen tilbud lige nu"})
            except Exception as e:  # noqa: BLE001
                ud.append({"del": f"Tilbud fra {navn}", "ok": False, "tekst": f"Kunne ikke hentes ({type(e).__name__})"})
        hoved = planer[0]
        noegle = hoved.entry.options.get(CONF_SALLING_NOEGLE)
        if noegle:
            try:
                ok = bool(await kilder.hent_salling_butikker(self.hass, noegle, "netto", self.hass.config.latitude, self.hass.config.longitude, 30))
                ud.append({"del": "Salling-nøgle", "ok": ok, "tekst": "Virker" if ok else "Svarer ikke"})
            except Exception as e:  # noqa: BLE001
                ud.append({"del": "Salling-nøgle", "ok": False, "tekst": f"Afvist ({type(e).__name__})"})
        ai = hoved.entry.options.get(CONF_AI_ENTITY)
        st = self.hass.states.get(ai) if ai else None
        ud.append({"del": "AI", "ok": bool(st and st.state != "unavailable"),
                   "tekst": "Klar" if st and st.state != "unavailable" else ("Ikke valgt" if not ai else "Ikke tilgængelig")})
        modtagere = hoved._notify_tjenester() if hasattr(hoved, "_notify_tjenester") else []
        if modtagere:
            mangler = [m for m in modtagere if not self.hass.services.has_service(*(m.partition(".")[::2] if "." in m else ("notify", m)))]
            ud.append({"del": "Beskeder", "ok": not mangler, "tekst": "Klar" if not mangler else f"{len(mangler)} modtager findes ikke"})
        self.d["tjek"] = {"t": time.time(), "resultat": ud}
        await self.store.async_save(self.d)
        return ud

    # ---------- få hjælp ----------
    async def async_faa_hjaelp(self, besked: str, billeder: list[dict[str, Any]]) -> dict[str, Any]:
        tjek = (self.d.get("tjek") or {}).get("resultat") or await self.async_tjek()
        diag = {"version": self.version(), "ha": {"country": self.hass.config.country, "version": getattr(self.hass.config, "version", None)},
                "opsaetning": self.daglig(), "fejl": self.seneste_fejl,
                "planer": [{"butik": p.butik_navn, "retter": len(((p.plan or {}).get("dage") or [])), "tilbud": len(p.tilbud or {})} for p in self._madplaner()]}
        billeder = [{"name": str(b.get("name") or "billede")[:60], "data": b["data"]} for b in (billeder or [])[:3]
                    if isinstance(b, dict) and isinstance(b.get("data"), str) and len(b["data"]) <= 2_000_000]
        svar = await self._post("/", {"note": str(besked or "")[:4000], "images": billeder, "diagnostics": diag, "lang": "da",
                                      "install": self.d.get("install"),  # så svaret kan finde tilbage hertil
                                      "test": {"results": [{"part": "madplan", "step": t["del"], "result": "ok" if t["ok"] else "failed", "why": t["tekst"]} for t in tjek]}},
                                timeout=60)
        if svar and svar.get("ok"):
            self.d["seneste_hjaelp"] = {"id": svar.get("id"), "t": time.time()}
            self.d["svar"] = {}
            await self.store.async_save(self.d)
            return {"ok": True, "id": svar.get("id")}
        return {"ok": False, "error": (svar or {}).get("error", "unreachable")}

    def status(self) -> dict[str, Any]:
        return {"del": self.del_anonymt, "tjek": self.d.get("tjek"), "seneste_hjaelp": self.d.get("seneste_hjaelp"), "svar": self.d.get("svar") or {}}

    async def async_status(self) -> dict[str, Any]:
        """Til kortet: svarene hentes friske, når de er mere end 5 minutter gamle."""
        if self.vil_have_svar() and time.time() - float((self.d.get("svar") or {}).get("t") or 0) > 300:
            await self.async_hent_svar(besked=False)
        return self.status()


class FejlHaandtering(logging.Handler):
    def __init__(self, hjaelp: Hjaelp) -> None:
        super().__init__(level=logging.WARNING)
        self.h = hjaelp

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.h.fejl(record)
        except Exception:  # noqa: BLE001
            pass


async def async_setup_hjaelp(hass: HomeAssistant) -> Hjaelp:
    h = Hjaelp(hass)
    await h.async_indlaes()
    logging.getLogger(__package__).addHandler(FejlHaandtering(h))
    from homeassistant.helpers.event import async_track_time_interval

    async_track_time_interval(hass, h.async_dagens_runde, datetime.timedelta(hours=1))
    hass.loop.call_later(600, lambda: hass.async_create_task(h.async_dagens_runde()))
    return h
