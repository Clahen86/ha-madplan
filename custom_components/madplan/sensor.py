"""Sensorer: ugens total og én sensor pr. dag."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DAGE, DOMAIN
from .entity import MadplanEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    madplan = entry.runtime_data
    async_add_entities([MadplanSensor(madplan)] + [MadplanDagSensor(madplan, i) for i in range(7)])


def _kort_dato(iso: str | None) -> str:
    try:
        d = datetime.date.fromisoformat(iso or "")
    except ValueError:
        return ""
    return f"{d.day}/{d.month}"


class MadplanSensor(MadplanEntity, SensorEntity):
    """Hvad der mangler at blive købt (kr), med ugens overblik som attributter."""

    _attr_name = None
    _attr_icon = "mdi:silverware-fork-knife"
    _attr_native_unit_of_measurement = "kr"

    def __init__(self, madplan) -> None:
        super().__init__(madplan, "total")

    @property
    def native_value(self) -> int:
        p = self.madplan.plan
        return p.get("total", p.get("total_alle", 0)) or 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self.madplan.plan
        retter = p.get("retter") or []
        n = p.get("personer") or self.madplan.personer
        total = self.native_value
        aktive = sum(1 for r in retter if not r.get("fjernet"))
        try:
            start = datetime.date.fromisoformat(p["start"])
            slut = start + datetime.timedelta(days=6)
            periode = f"{start.day}/{start.month} – {slut.day}/{slut.month}"
        except (KeyError, ValueError):
            periode = ""
        reg = er.async_get(self.hass)
        eid = self.madplan.entry.entry_id

        def find(platform: str, noegle: str) -> str | None:
            return reg.async_get_entity_id(platform, DOMAIN, f"{eid}_{noegle}")

        info = self.madplan.butik_info
        return {
            "butik": self.madplan.butik_navn,
            "butik_logo": info.get("logo"),
            "butik_farve": info.get("farve"),
            "anslaaede_priser": not self.madplan.er_rema and not self.madplan.salling_aktiv,
            "salling_butik": self.madplan.entry.options.get("salling_butik_navn") if self.madplan.salling_aktiv else None,
            "dag_entiteter": [find("sensor", f"dag_{i + 1}") for i in range(7)],
            "personer_entitet": find("number", "personer"),
            "varer_entitet": find("todo", "varer"),
            "ekstra_entitet": find("todo", "ekstra"),
            "behov": self.madplan.behov,
            "regler": self.madplan.regler,
            "en_ret": self.madplan.en_ret,
            "en_ret_status": self.madplan.en_ret_status,
            # Afkrydset i to-do-listerne er enten "i kurven" eller "har hjemme"; kortet skal kende forskel.
            "kurv": [v["key"] for v in p.get("varer", []) if v.get("kurv")]
            + [e["uid"] for e in p.get("ekstra", []) if e.get("kurv")],
            "advarsler": self.madplan.advarsler(),
            "ekstra_total": p.get("ekstra_total", 0),
            "ekstra_ca": p.get("ekstra_ca", 0),
            "status": p.get("status", "Ingen plan endnu"),
            "uge": p.get("uge"),
            "periode": periode,
            "personer": n,
            "total_alle": p.get("total_alle", 0),
            "pris_praecis": total - p.get("total_ca", 0),
            "pris_ca": p.get("total_ca", 0),
            "total_alle_ca": p.get("total_alle_ca", 0),
            "sparet": p.get("sparet", 0),
            "antal_mangler": p.get("antal_mangler", 0),
            "pr_kuvert": round(total / (aktive * n), 1) if total and n and aktive else 0,
            "antal_retter": aktive,
            "retter": [r.get("navn", "") for r in retter],
            "lavet": p.get("lavet"),
            "handl_senest": p.get("handl_senest"),
        }


class MadplanDagSensor(MadplanEntity, SensorEntity):
    """Dagens ret med opskrift som attributter. Dag 1 er søndag."""

    _attr_icon = "mdi:food"

    def __init__(self, madplan, i: int) -> None:
        super().__init__(madplan, f"dag_{i + 1}")
        self._i = i
        self._attr_name = DAGE[i]

    def _ret(self) -> dict:
        retter = self.madplan.plan.get("retter") or []
        return retter[self._i] if self._i < len(retter) else {}

    @property
    def native_value(self) -> str:
        return self._ret().get("navn", "–")[:250]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._ret()
        n = r.get("personer") or self.madplan.plan.get("personer") or self.madplan.personer
        return {
            "dag": DAGE[self._i],
            "personer": n,
            "gaester": bool(r.get("personer")),
            "fjernet": bool(r.get("fjernet")),
            "forbi": bool(r.get("forbi")),
            "dato": r.get("_dato"),
            "dato_kort": _kort_dato(r.get("_dato")),
            "kort": r.get("kort", ""),
            "tid": r.get("tid_min"),
            "pris": r.get("_pris"),
            "pr_person": round((r.get("_pris") or 0) / n, 1) if n else None,
            "sundhed": r.get("sundhed", ""),
            "billede": r.get("_billede"),
            "ingredienser": r.get("_linjer", []),
            "trin": r.get("trin", []),
        }
