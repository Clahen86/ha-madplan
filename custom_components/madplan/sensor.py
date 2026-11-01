"""Sensorer: ugens total og én sensor pr. dag."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DAGE
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
        return {
            "status": p.get("status", "Ingen plan endnu"),
            "uge": p.get("uge"),
            "periode": periode,
            "personer": n,
            "total_alle": p.get("total_alle", 0),
            "sparet": p.get("sparet", 0),
            "antal_mangler": p.get("antal_mangler", 0),
            "pr_kuvert": round(total / (aktive * n), 1) if total and n and aktive else 0,
            "antal_retter": aktive,
            "retter": [r.get("navn", "") for r in retter],
            "lavet": p.get("lavet"),
        }


class MadplanDagSensor(MadplanEntity, SensorEntity):
    """Dagens ret med opskrift som attributter. Dag 1 er søndag."""

    _attr_icon = "mdi:food"

    def __init__(self, madplan, i: int) -> None:
        super().__init__(madplan, f"dag_{i + 1}")
        self._i = i
        self._attr_name = DAGE[i]
        self.entity_id = f"sensor.madplan_dag_{i + 1}"

    def _ret(self) -> dict:
        retter = self.madplan.plan.get("retter") or []
        return retter[self._i] if self._i < len(retter) else {}

    @property
    def native_value(self) -> str:
        return self._ret().get("navn", "–")[:250]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._ret()
        n = self.madplan.plan.get("personer") or self.madplan.personer
        return {
            "dag": DAGE[self._i],
            "fjernet": bool(r.get("fjernet")),
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
