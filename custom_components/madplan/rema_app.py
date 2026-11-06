"""Indkøbslisten i REMA 1000-appen (valgfrit, uofficielt).

REMA 1000 har ingen offentlig API til indkøbslister. Her bruges de samme kald som rema1000.dk og webshoppen,
med brugerens egen REMA-konto - samme fremgangsmåde som ha-rema1000 (MIT) og rema1000-dk (MIT) har beskrevet.
Det kan holde op med at virke, hvis REMA ændrer deres side; så fejler kun afsendelsen til appen, resten virker.

Der logges ind hver gang, listen sendes (det sker sjældent), så der gemmes ingen tokens.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import aiohttp
from yarl import URL

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

_LOGGER = logging.getLogger(__name__)

LOGIN_API = "https://cphapp.rema1000.dk/api/oauth2/login"
LOGIN_HOST = "login.rema1000.dk"
SITES = ("https://shop.rema1000.dk", "https://rema1000.dk")
API = "https://api.digital.rema1000.dk/api"
STORE_ID = 1
HEAD = {"Accept": "application/json", "X-Device": "web", "X-Locale": "da", "X-Timezone": "Copenhagen/Europe"}
TID = aiohttp.ClientTimeout(total=30)


class RemaFejl(Exception):
    """kode: "login" (forkert e-mail/kodeord) eller "forbindelse" (REMA svarer ikke som ventet)."""

    def __init__(self, kode: str, tekst: str = "") -> None:
        super().__init__(tekst or kode)
        self.kode = kode


def _session(hass: HomeAssistant) -> aiohttp.ClientSession:
    # Eget cookie-jar: login-flowet sætter access_token som cookie.
    return async_create_clientsession(hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar())


async def _login(session: aiohttp.ClientSession, email: str, kode: str) -> tuple[str, str]:
    """(access_token, site). Siden starter selv login (OAuth2/PKCE); e-mail og kodeord sendes til REMA's login."""
    for site in SITES:
        try:
            async with session.get(
                f"{site}/konto/auth", params={"redirect_uri": "/konto"}, headers={"Accept": "text/html"}, timeout=TID
            ) as r:
                login_url = str(r.url)
            if LOGIN_HOST not in login_url:
                continue
            async with session.post(
                LOGIN_API,
                json={"email": email, "password": kode},
                headers={**HEAD, "X-Language": "da", "Origin": f"https://{LOGIN_HOST}", "Referer": login_url},
                timeout=TID,
            ) as r:
                if r.status in (400, 401, 403, 422):
                    raise RemaFejl("login")
                r.raise_for_status()
                videre = (await r.json(content_type=None) or {}).get("redirect_uri")
            if not videre:
                raise RemaFejl("login")
            async with session.get(videre.replace("http://", "https://", 1), headers={"Accept": "text/html"}, timeout=TID):
                pass
            if token := session.cookie_jar.filter_cookies(URL(site)).get("access_token"):
                return token.value, site
        except RemaFejl:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as e:
            _LOGGER.debug("REMA-login via %s fejlede: %s", site, e)
    raise RemaFejl("forbindelse", "REMA's login svarede ikke som ventet")


def _bruger(token: str) -> str:
    """Bruger-id fra access_token (et JWT)."""
    try:
        del_ = token.split(".")[1]
        return str(json.loads(base64.urlsafe_b64decode(del_ + "=" * (-len(del_) % 4)))["sub"])
    except (IndexError, KeyError, ValueError) as e:
        raise RemaFejl("forbindelse", "Uventet svar fra REMA's login") from e


async def async_test(hass: HomeAssistant, email: str, kode: str) -> None:
    """Prøv at logge ind (fra opsætningen). Rejser RemaFejl."""
    session = _session(hass)
    try:
        await _login(session, email, kode)
    finally:
        await session.close()


async def async_send(hass: HomeAssistant, email: str, kode: str, varer: list[dict[str, Any]]) -> int:
    """Læg varer på den primære liste i REMA-appen. varer: [{"product_id": int} eller {"name": str}, "amount": int].
    Står varen allerede på listen, lægges antallet til. Giver antallet af varer tilbage."""
    session = _session(hass)
    try:
        token, site = await _login(session, email, kode)
        hoved = {**HEAD, "Authorization": f"Bearer {token}", "Origin": site}

        async def kald(metode: str, sti: str, **kw: Any) -> Any:
            async with session.request(metode, API + sti, headers=hoved, timeout=TID, **kw) as r:
                if r.status >= 400:
                    raise RemaFejl("forbindelse", f"REMA svarede {r.status} på {sti}")
                return await r.json(content_type=None)

        lister = (await kald(
            "GET", f"/v3/users/{_bruger(token)}/shopping-lists",
            params={"per_page": 100, "include": "users,items_count", "sort": "-latest_activity_at"},
        ) or {}).get("data") or []
        if not lister:
            raise RemaFejl("forbindelse", "Ingen indkøbsliste i REMA-appen")
        liste = next((x for x in lister if x.get("is_primary")), lister[0])
        lid = liste["id"]

        # Det, der allerede står på listen (så antallet lægges til i stedet for en ny linje).
        findes: dict[Any, dict] = {}
        try:
            d = await kald("GET", f"/v2/shoppinglists/{lid}", params={"with": "users,items"})
            d = d.get("data", d) if isinstance(d, dict) else {}
            items = d.get("items") or []
            items = items.get("data", []) if isinstance(items, dict) else items
            for it in items:
                if it.get("bought"):
                    continue
                findes[it.get("store_item_id") or str(it.get("name", "")).lower()] = it
        except (RemaFejl, AttributeError, TypeError) as e:
            _LOGGER.debug("Kunne ikke læse REMA-listen (lægger bare til): %s", e)

        antal = 0
        for v in varer:
            mgd = max(1, int(v.get("amount") or 1))
            noegle = v.get("product_id") or str(v.get("name", "")).lower()
            if (gammel := findes.get(noegle)) and gammel.get("id"):
                try:
                    ny = int(float(gammel.get("amount") or 0)) + mgd
                except (TypeError, ValueError):
                    ny = mgd
                await kald("PATCH", f"/v2/shoppinglists/{lid}/items/{gammel['id']}", json={"amount": ny, "bought": False})
            else:
                body: dict[str, Any] = {"amount": mgd, "store_id": STORE_ID}
                if v.get("product_id"):
                    body["store_item_id"] = v["product_id"]
                else:
                    body["name"] = v["name"]
                await kald("POST", f"/v2/shoppinglists/{lid}/items", json=body)
            antal += 1
        return antal
    except (aiohttp.ClientError, TimeoutError) as e:
        raise RemaFejl("forbindelse", str(e)) from e
    finally:
        await session.close()
