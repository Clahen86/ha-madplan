"""Henter tilbud fra eTilbudsavis (Tjek) og normalpriser fra REMA 1000."""

from __future__ import annotations

import datetime
import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import REMA_URL, TJEK_URL

_LOGGER = logging.getLogger(__name__)
_HEADERS = {"User-Agent": "HomeAssistant-madplan"}


async def _hent_json(hass: HomeAssistant, url: str) -> Any:
    session = async_get_clientsession(hass)
    async with session.get(url, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as r:
        r.raise_for_status()
        return await r.json(content_type=None)


async def hent_rema_katalog(hass: HomeAssistant) -> dict[str, dict]:
    """Hele REMA's sortiment med priser (ca. 80 sider)."""
    varer: dict[str, dict] = {}
    side, sidste = 1, 1
    while side <= sidste and side <= 80:
        d = await _hent_json(hass, REMA_URL.format(side=side))
        sidste = d.get("meta", {}).get("pagination", {}).get("last_page", 1)
        for p in d.get("data", []):
            billede = (p.get("images") or [{}])[0].get("medium")
            varer[str(p["id"])] = {
                "navn": p.get("name", "").strip().capitalize(),
                "str": (p.get("underline") or "").strip(),
                "priser": [
                    {
                        "pris": pr.get("price"),
                        "fra": (pr.get("starting_at") or "")[:10],
                        "til": (pr.get("ending_at") or "")[:10],
                        "kampagne": bool(pr.get("is_campaign") or pr.get("is_advertised")),
                    }
                    for pr in p.get("prices", [])
                ],
                "billede": billede,
            }
        side += 1
    _LOGGER.debug("REMA-katalog hentet: %s varer", len(varer))
    return varer


async def hent_tilbud(hass: HomeAssistant, dealer: str, start: datetime.date, slut: datetime.date) -> dict[str, dict]:
    """Tilbud fra eTilbudsavis, der gælder i hele resten af planugen."""
    tz = dt_util.get_default_time_zone()
    fra = max(start, dt_util.now().date())
    vindue_fra = datetime.datetime.combine(fra, datetime.time(12, 0), tz)
    vindue_til = datetime.datetime.combine(slut, datetime.time(12, 0), tz)
    tilbud: dict[str, dict] = {}
    for offset in range(0, 1000, 100):
        d = await _hent_json(hass, TJEK_URL.format(dealer=dealer, offset=offset))
        if not d:
            break
        for o in d:
            try:
                o_fra = datetime.datetime.fromisoformat(o["run_from"].replace("Z", "+00:00"))
                o_til = datetime.datetime.fromisoformat(o["run_till"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if o_fra > vindue_fra or o_til < vindue_til:
                continue
            q = o.get("quantity") or {}
            size = (q.get("size") or {}).get("from")
            unit = ((q.get("unit") or {}).get("symbol")) or ""
            pieces = (q.get("pieces") or {}).get("from") or 1
            tilbud[o["id"]] = {
                "navn": o.get("heading", "").strip(),
                "pris": (o.get("pricing") or {}).get("price"),
                "str": f"{pieces} x {size} {unit}" if pieces and pieces > 1 else f"{size or ''} {unit}".strip(),
                "billede": (o.get("images") or {}).get("view") or (o.get("images") or {}).get("thumb"),
            }
        if len(d) < 100:
            break
    return tilbud


def rema_pris(vare: dict, dato: datetime.date) -> float | None:
    d = dato.isoformat()
    gyldige = [p for p in vare["priser"] if p["pris"] and p["fra"] <= d <= p["til"]]
    if not gyldige:
        gyldige = [p for p in vare["priser"] if p["pris"] and not p["kampagne"]] or [
            p for p in vare["priser"] if p["pris"]
        ]
    if not gyldige:
        return None
    # Normalpris frem for en kampagne, der slutter midt i ugen.
    gyldige.sort(key=lambda p: (p["kampagne"], p["til"]))
    return gyldige[0]["pris"]
