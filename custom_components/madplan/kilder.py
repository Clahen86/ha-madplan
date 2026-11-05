"""Henter tilbud fra eTilbudsavis (Tjek) og normalpriser fra REMA 1000."""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    IKKE_MAD,
    IKKE_MAD_AVIS,
    REMA_URL,
    SALLING_URL,
    TJEK_CATALOGS_URL,
    TJEK_DEALER_OFFERS_URL,
    TJEK_DEALER_URL,
    TJEK_URL,
)

_LOGGER = logging.getLogger(__name__)
_HEADERS = {"User-Agent": "HomeAssistant-madplan"}


async def _hent_json(hass: HomeAssistant, url: str) -> Any:
    session = async_get_clientsession(hass)
    async with session.get(url, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as r:
        r.raise_for_status()
        return await r.json(content_type=None)


async def hent_butik_info(hass: HomeAssistant, dealer: str) -> dict[str, str | None]:
    """Kædens navn, logo og farve fra eTilbudsavis."""
    d = await _hent_json(hass, TJEK_DEALER_URL.format(dealer=dealer))
    farve = d.get("color")
    return {"navn": d.get("name"), "logo": d.get("logo"), "farve": f"#{farve}" if farve else None}


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
    """Madvarer på tilbud fra eTilbudsavis på indkøbsdagen (planens start eller i dag).

    Der handles ind én gang, så tilbuddet skal gælde den dag (kl. 12-20). Kæderne skifter avis på
    forskellige ugedage (ABC onsdag, 365 torsdag, Salling/Coop fredag, Netto lørdag, REMA/Lidl søndag),
    så det kan ikke kræves, at det gælder dagen efter - så ville en plan lavet dagen før et avisskifte
    næsten ikke få tilbud.
    """
    tz = dt_util.get_default_time_zone()
    fra = max(start, dt_util.now().date())
    vindue_fra = datetime.datetime.combine(fra, datetime.time(12, 0), tz)
    vindue_til = vindue_fra + datetime.timedelta(hours=8)
    tilbud: dict[str, dict] = {}
    # Hent pr. avis: API'et bladrer højst 1000 tilbud, og fx Bilka har flere i alt.
    aviser = await _hent_json(hass, TJEK_CATALOGS_URL.format(dealer=dealer)) or []
    if not aviser:
        # Nogle kæder (fx Løvbjerg) har kun løse tilbud uden avis.
        aviser = [{"id": None, "run_from": vindue_fra.isoformat(), "run_till": vindue_til.isoformat()}]
    set_foer: set[tuple] = set()
    for avis in aviser:
        try:
            a_fra = datetime.datetime.fromisoformat(avis["run_from"].replace("Z", "+00:00"))
            a_til = datetime.datetime.fromisoformat(avis["run_till"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if a_fra > vindue_fra or a_til < vindue_til or IKKE_MAD_AVIS.search(avis.get("label") or ""):
            continue
        for offset in range(0, 1000, 100):
            url = (
                TJEK_URL.format(catalog=avis["id"], offset=offset)
                if avis["id"]
                else TJEK_DEALER_OFFERS_URL.format(dealer=dealer, offset=offset)
            )
            d = await _hent_json(hass, url)
            for o in d or []:
                try:
                    o_fra = datetime.datetime.fromisoformat(o["run_from"].replace("Z", "+00:00"))
                    o_til = datetime.datetime.fromisoformat(o["run_till"].replace("Z", "+00:00"))
                except (KeyError, ValueError):
                    continue
                if o_fra > vindue_fra or o_til < vindue_til or IKKE_MAD.search(o.get("heading", "")):
                    continue
                q = o.get("quantity") or {}
                size = (q.get("size") or {}).get("from")
                unit = ((q.get("unit") or {}).get("symbol")) or ""
                pieces = (q.get("pieces") or {}).get("from") or 1
                navn = o.get("heading", "").strip()
                pris = (o.get("pricing") or {}).get("price")
                strr = f"{pieces} x {size} {unit}" if pieces and pieces > 1 else f"{size or ''} {unit}".strip()
                # Samme vare i flere aviser (fx én avis pr. butik hos ABC Lavpris) tælles én gang.
                if (navn, pris, strr) in set_foer:
                    continue
                set_foer.add((navn, pris, strr))
                tilbud[o["id"]] = {
                    "navn": navn,
                    "pris": pris,
                    "str": strr,
                    "billede": (o.get("images") or {}).get("view") or (o.get("images") or {}).get("thumb"),
                    "til": dt_util.as_local(o_til).date().isoformat(),
                }
            if not d or len(d) < 100:
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


# ---------------------------------------------------------------- Salling Group (valgfrit)


async def _salling(hass: HomeAssistant, noegle: str, sti: str) -> Any:
    """Kald Salling Groups API. Feeds svarer med en henvisning (307) til en fil, som hentes uden nøgle."""
    session = async_get_clientsession(hass)
    tid = aiohttp.ClientTimeout(total=30)
    hoved = {"Authorization": f"Bearer {noegle}", **_HEADERS}
    async with session.get(SALLING_URL + sti, headers=hoved, timeout=tid, allow_redirects=False) as r:
        if r.status in (301, 302, 307, 308):
            url = r.headers.get("Location") or (await r.json(content_type=None)).get("redirectUrl")
            async with session.get(url, headers=_HEADERS, timeout=tid) as r2:
                r2.raise_for_status()
                return await r2.json(content_type=None)
        r.raise_for_status()
        return await r.json(content_type=None)


async def hent_salling_butikker(
    hass: HomeAssistant, noegle: str, brand: str, lat: float, lon: float, radius: int
) -> list[dict]:
    """Kædens butikker nærmest hjemmet: [{"id", "navn", "km"}]."""
    d = await _salling(
        hass, noegle, f"/v2/stores?brand={brand}&geo={lat},{lon}&radius={radius}&per_page=30&fields=id,name,address,distance_km"
    )
    return [
        {"id": b["id"], "navn": b.get("name") or "", "by": (b.get("address") or {}).get("city") or "", "km": b.get("distance_km")}
        for b in d or []
    ]


async def hent_salling_katalog(hass: HomeAssistant, noegle: str, feed: str) -> dict[str, dict]:
    """Kædens ca. 1000 mest købte varer: {ean: {navn, str, billede}}. Priserne slås op enkeltvis."""
    varer: dict[str, dict] = {}
    for p in await _salling(hass, noegle, f"/v1/recommendations/most-bought/{feed}/feed") or []:
        ean = (p.get("gtins") or [None])[0]
        navn = (p.get("description") or p.get("name") or "").strip()
        if not ean or not navn:
            continue
        mgd, enhed = p.get("contents"), (p.get("contentsUnit") or "").strip()
        varer[ean] = {
            "navn": navn[:1].upper() + navn[1:],
            "str": f"{mgd:g} {enhed}".strip() if isinstance(mgd, (int, float)) else enhed,
            "billede": p.get("image"),
        }
    _LOGGER.debug("Salling-katalog %s: %s varer", feed, len(varer))
    return varer


_FRYSES = re.compile(r"kød|kod|fjerkræ|kylling|okse|svin|gris|lam|hakket|fisk|laks|torsk|rejer|pølse|bacon|kalkun|and\b", re.I)


async def hent_salling_madspild(hass: HomeAssistant, noegle: str, butik_id: str) -> list[dict]:
    """Butikkens madspild-varer (ekstra nedsat, kort dato) med lager lige nu:
    [{ean, navn, pris, foer, pct, stk, til, opdateret, fryses, billede}]."""
    d = await _salling(hass, noegle, f"/v1/food-waste/{butik_id}")
    varer = []
    for c in (d or {}).get("clearances") or []:
        o, p = c.get("offer") or {}, c.get("product") or {}
        navn = (p.get("description") or "").strip()
        if not navn or not o.get("newPrice") or (o.get("stock") or 0) <= 0:
            continue
        if navn.isupper():
            navn = navn.lower()  # Salling skriver ofte madspild-navne med store bogstaver
        kategori = " ".join(str(v) for v in (p.get("categories") or {}).values())
        varer.append(
            {
                "ean": o.get("ean") or p.get("ean") or "",
                "navn": navn[:1].upper() + navn[1:],
                "pris": float(o["newPrice"]),
                "foer": float(o.get("originalPrice") or 0) or None,
                "pct": round(float(o.get("percentDiscount") or 0)),
                "stk": o.get("stock"),
                "til": o.get("endTime"),
                "opdateret": o.get("lastUpdate"),
                "fryses": bool(_FRYSES.search(f"{kategori} {navn}")),
                "billede": p.get("image"),
            }
        )
    return varer


async def hent_salling_pris(hass: HomeAssistant, noegle: str, ean: str, butik_id: str) -> float | None:
    """Prisen i den valgte butik, eller None hvis butikken ikke fører varen."""
    try:
        d = await _salling(hass, noegle, f"/v2/products/{ean}?storeId={butik_id}")
    except aiohttp.ClientResponseError as e:
        if e.status == 404:
            return None
        raise
    pris = ((d or {}).get("instore") or {}).get("price")
    return float(pris) if pris else None
