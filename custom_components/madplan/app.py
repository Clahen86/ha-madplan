"""Madplan som app fra et hemmeligt link - for familien uden Home Assistant-login.

Linket åbner ugens madplan, opskrifterne og indkøbslisten (samme madplan-card.js som i Home Assistant) på en side
for sig, som kan lægges på hjemmeskærmen som en app. Linket er nøglen. Et link har en rolle:

- børn (standard): kan kun læse madplanen og krydse varer af på indkøbslisten
- voksen: kan også styre ugens plan - ny madplan, bytte eller fjerne en ret, dage, personer, hvem der laver mad,
  ekstra varer og sende indkøbslisten - og bruge "Én ret" (hvad har I i køleskabet). Kun Madplans egne handlinger
  på linkets egne planer (STYR), aldrig regler, profiler, hjælp eller andet i Home Assistant.
"""

from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from http import HTTPStatus
from pathlib import Path
from typing import Any

import voluptuous as vol
from aiohttp import web

from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from . import todo
from .const import DOMAIN

PAGE = "/madplan_app"
API = "/api/madplan/app"
DATA = "madplan_app"  # hass.data - ikke hass.data[DOMAIN], det er planernes fælles opslag
# Det, appen ikke skal se: HA-brugernes id'er og ting, man kun bruger i Home Assistant.
SKJULT = frozenset({"profiler", "auto_planer", "mine_retter", "en_ret", "en_ret_status"})
EN_RET = frozenset({"en_ret", "en_ret_status"})  # "Én ret" - kun for et voksen-link
ROLLER = ("boern", "voksen")
# Det, et voksen-link må kalde: Madplans egne handlinger for ugens plan og "Én ret". Ikke regler, profiler, hjælp osv.
STYR = frozenset({"ny_plan", "byt_ret", "fjern_ret", "flyt_ret", "udfoerlig_opskrift", "overfoer", "tilfoej_behov", "fjern_behov",
                  "ekstra_antal", "marker", "toem_kurv", "dag_kok", "dag_personer", "rester", "dag_mail",
                  "en_ret", "slet_en_ret", "en_ret_paa_listen", "en_ret_mail", "en_ret_byt", "en_ret_udfoerlig",
                  "en_ret_personer", "en_ret_gem", "en_ret_rema"})
KALD = vol.Schema(
    {
        vol.Required("domain"): vol.In(["madplan", "number"]),
        vol.Required("service"): str,
        vol.Required("data"): {vol.Required("entity_id"): str, vol.Extra: object},
    }
)
MARKER = vol.Schema(
    {
        vol.Required("entity_id"): str,
        vol.Required("liste"): vol.In(["varer", "ekstra"]),
        vol.Required("uid"): vol.All(str, vol.Length(min=1, max=200)),
        vol.Required("felt"): vol.In(["kurv", "hjemme"]),
        vol.Required("vaerdi"): bool,
    }
)


class AppLinks:
    """Linkene: id -> navn, profil, token og hvornår det blev lavet."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, 1, f"{DOMAIN}.app_links")
        self.links: dict[str, dict[str, Any]] = {}

    async def async_indlaes(self) -> None:
        self.links = (await self._store.async_load() or {}).get("links", {})

    async def _gem(self) -> None:
        await self._store.async_save({"links": self.links})

    def ved_token(self, token: str) -> dict[str, Any] | None:
        for link in self.links.values():
            if secrets.compare_digest(str(link.get("token") or ""), str(token or "")):
                return link
        return None

    async def async_opret(self, navn: str, profil: str, rolle: str = "boern") -> dict[str, Any]:
        lid = uuid.uuid4().hex[:10]
        self.links[lid] = {"navn": navn.strip()[:40], "profil": profil, "token": secrets.token_urlsafe(24),
                           "oprettet": time.time(), "rolle": rolle if rolle in ROLLER else "boern"}
        await self._gem()
        return self.links[lid]

    async def async_slet(self, lid: str) -> bool:
        if self.links.pop(lid, None) is None:
            return False
        await self._gem()
        return True


async def async_setup(hass: HomeAssistant) -> None:
    links = AppLinks(hass)
    await links.async_indlaes()
    hass.data[DATA] = links
    websocket_api.async_register_command(hass, ws_links)
    if hass.http is not None:
        hass.http.register_view(AppSideView(hass))
        hass.http.register_view(AppIkonView())
        hass.http.register_view(AppApiView(hass))


def _madplaner(hass: HomeAssistant, profil: str) -> list:
    return [e.runtime_data for e in hass.config_entries.async_loaded_entries(DOMAIN) if e.runtime_data.profil == profil]


def _plan_id(hass: HomeAssistant, m) -> str | None:
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{m.entry.entry_id}_total")


def _tilstand(s, skjul: frozenset[str] = SKJULT) -> dict[str, Any]:
    return {"entity_id": s.entity_id, "state": s.state, "attributes": {k: v for k, v in s.attributes.items() if k not in skjul}}


def oejebliksbillede(hass: HomeAssistant, link: dict[str, Any]) -> dict[str, Any]:
    """Alt hvad kortet skal bruge til linkets profil: planernes og dagenes tilstand og indkøbslisterne."""
    states: dict[str, Any] = {}
    lister: dict[str, list[dict[str, Any]]] = {}
    for m in _madplaner(hass, link.get("profil") or ""):
        eid = _plan_id(hass, m)
        if not eid or not (s := hass.states.get(eid)):
            continue
        states[eid] = _tilstand(s, SKJULT - EN_RET if voksen(link) else SKJULT)
        a = s.attributes
        for x in [*(a.get("dag_entiteter") or []), a.get("personer_entitet")]:
            if x and (d := hass.states.get(x)):
                states[x] = _tilstand(d)
        for x, varer in ((a.get("varer_entitet"), todo.varer), (a.get("ekstra_entitet"), todo.ekstra)):
            if x:
                lister[x] = [{"uid": i.uid, "summary": i.summary, "status": str(i.status), "description": i.description}
                             for i in varer(m)]
    if voksen(link):  # "Hvem laver mad?": husets personer, kun navnet
        for p in hass.states.async_all("person"):
            states[p.entity_id] = {"entity_id": p.entity_id, "state": "", "attributes": {"friendly_name": p.name}}
    return {"navn": link.get("navn"), "rolle": rolle(link), "states": states, "todo": lister}


def rolle(link: dict[str, Any]) -> str:
    return "voksen" if link.get("rolle") == "voksen" else "boern"


def voksen(link: dict[str, Any]) -> bool:
    return rolle(link) == "voksen"


def tilladt(hass: HomeAssistant, link: dict[str, Any], d: dict[str, Any]):
    """Planen, hvis et voksen-link må lave det kald, ellers None (eller en tekst med grunden)."""
    if not voksen(link):
        return None
    eid = d["data"].get("entity_id")
    planer = {_plan_id(hass, m): m for m in _madplaner(hass, link.get("profil") or "")}
    if d["domain"] == "number":  # antal personer: kun planens egen
        if d["service"] != "set_value":
            return None
        for pid, m in planer.items():
            s = pid and hass.states.get(pid)
            if s and s.attributes.get("personer_entitet") == eid and set(d["data"]) <= {"entity_id", "value"}:
                return m
        return None
    if eid not in planer:
        return None
    if d["service"] == "gem_regler":  # kun ugens frie dage, ikke reglerne
        return planer[eid] if set(d["data"]) <= {"entity_id", "fri_dage"} else None
    return planer[eid] if d["service"] in STYR else None


def _link(hass: HomeAssistant, token: str) -> dict[str, Any] | None:
    links: AppLinks | None = hass.data.get(DATA)
    return links.ved_token(token) if links else None


class AppSideView(HomeAssistantView):
    """Selve siden, dens manifest (så den kan installeres som en app) og dens service worker."""

    url = PAGE + "/{token}/{fil:.*}"
    extra_urls = [PAGE + "/{token}"]
    name = "madplan:app"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, token: str, fil: str = "") -> web.StreamResponse:
        link = _link(self.hass, token)
        if not link:
            return web.Response(status=HTTPStatus.NOT_FOUND, text="Dette link er ikke længere i brug.")
        base = f"{PAGE}/{token}"
        if fil == "manifest.webmanifest":
            return web.json_response(
                {"name": f"Madplan · {link['navn']}", "short_name": "Madplan", "start_url": f"{base}/", "scope": f"{base}/",
                 "id": f"{base}/", "display": "standalone", "background_color": "#fafafa", "theme_color": "#3f51b5",
                 "icons": [{"src": f"{PAGE}-icon/256.png", "sizes": "256x256", "type": "image/png", "purpose": "any"},
                           {"src": f"{PAGE}-icon/512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}]},
                content_type="application/manifest+json",
            )
        if fil == "sw.js":
            return web.Response(text=SW, content_type="application/javascript",
                                headers={"Service-Worker-Allowed": f"{base}/", "Cache-Control": "no-cache"})
        if fil not in ("", "index.html"):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        html = (SIDE.replace("{{base}}", base).replace("{{api}}", f"{API}/{token}")
                .replace("{{voksen}}", "true" if voksen(link) else "false")
                .replace("{{js}}", self.hass.data.get("madplan_kort_url", "/madplan/madplan-card.js")))
        return web.Response(text=html, content_type="text/html",
                            headers={"Cache-Control": "no-cache", "Referrer-Policy": "no-referrer"})


class AppIkonView(HomeAssistantView):
    url = PAGE + "-icon/{size}.png"
    name = "madplan:app_ikon"
    requires_auth = False

    async def get(self, request: web.Request, size: str) -> web.StreamResponse:
        ikon = Path(__file__).parent / "brand" / ("icon@2x.png" if size == "512" else "icon.png")
        return web.FileResponse(ikon, headers={"Cache-Control": "public, max-age=86400"})


class AppApiView(HomeAssistantView):
    """Det eneste, et link kan: læse madplanen (data) og krydse en vare af (marker)."""

    url = API + "/{token}/{handling}"
    name = "api:madplan:app"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, token: str, handling: str) -> web.Response:
        link = _link(self.hass, token)
        if not link or handling != "data":
            return self.json_message("Ukendt", HTTPStatus.NOT_FOUND)
        return self.json(oejebliksbillede(self.hass, link), headers={"Cache-Control": "no-store"})

    async def post(self, request: web.Request, token: str, handling: str) -> web.Response:
        link = _link(self.hass, token)
        if not link:
            return self.json_message("Dette link er ikke længere i brug", HTTPStatus.NOT_FOUND)
        if handling == "kald":
            return await self._kald(request, link)
        if handling != "marker":
            return self.json_message("Ukendt", HTTPStatus.NOT_FOUND)
        try:
            d = MARKER(await request.json())
        except (ValueError, vol.Invalid):
            return self.json_message("Forkert forespørgsel", HTTPStatus.BAD_REQUEST)
        # Kun en plan i linkets egen profil.
        m = next((m for m in _madplaner(self.hass, link.get("profil") or "") if _plan_id(self.hass, m) == d["entity_id"]), None)
        if m is None:
            return self.json_message("Ukendt madplan", HTTPStatus.NOT_FOUND)
        await m.async_marker(d["liste"], d["uid"], d["felt"], d["vaerdi"])
        return self.json(oejebliksbillede(self.hass, link))

    async def _kald(self, request: web.Request, link: dict[str, Any]) -> web.Response:
        """Et voksen-link styrer ugens plan. En ny plan (AI) kan tage et minut: så svarer vi før, og den kører færdig."""
        try:
            d = KALD(await request.json())
        except (ValueError, vol.Invalid):
            return self.json_message("Forkert forespørgsel", HTTPStatus.BAD_REQUEST)
        if tilladt(self.hass, link, d) is None:
            return self.json_message("Det kan dette link ikke", HTTPStatus.FORBIDDEN)
        opgave = self.hass.async_create_task(
            self.hass.services.async_call(d["domain"], d["service"], d["data"], blocking=True, context=Context())
        )
        try:
            await asyncio.wait_for(asyncio.shield(opgave), 15)
        except TimeoutError:
            pass  # kører videre; appen henter planen igen
        except (HomeAssistantError, vol.Invalid, ValueError) as err:
            return self.json_message(str(err) or "Det gik ikke", HTTPStatus.BAD_REQUEST)
        return self.json(oejebliksbillede(self.hass, link))


def _app_url(hass: HomeAssistant) -> tuple[str, bool]:
    """Hvor et link åbner: Nabu Casa (eller jeres egen adresse udefra) først, så det også virker hjemmefra."""
    from homeassistant.helpers.network import NoURLAvailableError, get_url

    try:
        return get_url(hass, allow_internal=False, allow_ip=False, prefer_cloud=True), True
    except NoURLAvailableError:
        try:
            return get_url(hass, prefer_external=False), False
        except NoURLAvailableError:
            return "", False


def _liste(hass: HomeAssistant, links: AppLinks) -> dict[str, Any]:
    base, ude = _app_url(hass)
    return {"ude": ude, "links": [{"id": lid, "navn": x.get("navn"), "profil": x.get("profil") or "", "oprettet": x.get("oprettet"),
                                   "rolle": rolle(x), "url": f"{base}{PAGE}/{x['token']}/"}
                                  for lid, x in sorted(links.links.items(), key=lambda kv: kv[1].get("oprettet", 0))]}


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/app_links",
        vol.Optional("opret"): {vol.Required("navn"): vol.All(str, vol.Length(min=1, max=40)), vol.Optional("profil", default=""): str,
                                vol.Optional("rolle", default="boern"): vol.In(ROLLER)},
        vol.Optional("slet"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_links(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Madplan som app fra et link: laves og slettes af en administrator - til familien uden login."""
    links: AppLinks = hass.data[DATA]
    if o := msg.get("opret"):
        profil = "" if o["profil"] == "hoved" else o["profil"]
        if profil and not any(e.runtime_data.profil == profil for e in hass.config_entries.async_loaded_entries(DOMAIN)):
            connection.send_error(msg["id"], "invalid", "Ukendt profil")
            return
        await links.async_opret(o["navn"], profil, o["rolle"])
    if lid := msg.get("slet"):
        await links.async_slet(lid)
    connection.send_result(msg["id"], _liste(hass, links))


SW = """// Madplan-appen: kan installeres på hjemmeskærmen. Alt hentes frisk fra Home Assistant.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
"""

SIDE = """<!doctype html>
<html lang="da"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Madplan</title>
<link rel="manifest" href="{{base}}/manifest.webmanifest">
<link rel="icon" href="/madplan_app-icon/256.png"><link rel="apple-touch-icon" href="/madplan_app-icon/256.png">
<meta name="theme-color" content="#3f51b5"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Madplan"><meta name="apple-mobile-web-app-status-bar-style" content="default">
<style>
html,body{margin:0;height:100%;background:#fafafa;font-family:-apple-system,Roboto,"Segoe UI",sans-serif}
body{display:flex;flex-direction:column;height:100vh;height:100dvh}
madplan-panel{flex:1;min-height:0;display:block;--primary-color:#03a9f4;--primary-text-color:#212121;--secondary-text-color:#727272;
  --divider-color:rgba(0,0,0,.12);--card-background-color:#fff;--secondary-background-color:#e5e5e5;--primary-background-color:#fafafa;
  --warning-color:#ffa600;--error-color:#db4437;--success-color:#43a047}
@media (prefers-color-scheme: dark){html,body{background:#111}
  madplan-panel{--primary-text-color:#e1e1e1;--secondary-text-color:#9b9b9b;--divider-color:rgba(225,225,225,.12);
  --card-background-color:#1c1c1c;--secondary-background-color:#282828;--primary-background-color:#111}}
</style></head><body>
<script>
// Kortet taler med Home Assistant gennem linket i stedet for et login: en lille stand-in for HA's forbindelse.
(() => {
  const API = "{{api}}";
  window.MADPLAN_APP = { api: API, base: "{{base}}", voksen: {{voksen}} };
  // Ikoner som i Home Assistant: HA's egne mdi-filer, som ikke kræver login.
  if (!customElements.get("ha-icon")) {
    let meta = null;
    const filer = {};
    const sti = async (navn) => {
      meta = meta || fetch("/static/mdi/iconMetadata.json").then((r) => r.json());
      const m = await meta;
      let fil = m.parts[0].file;
      for (const p of m.parts) { if (p.start && navn < p.start) break; fil = p.file; }
      filer[fil] = filer[fil] || fetch(`/static/mdi/${fil}.json`).then((r) => r.json());
      return (await filer[fil])[navn];
    };
    customElements.define("ha-icon", class extends HTMLElement {
      static get observedAttributes() { return ["icon"]; }
      constructor() { super(); this.attachShadow({ mode: "open" }).innerHTML =
        '<style>:host{display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;flex:none;width:var(--mdc-icon-size,24px);height:var(--mdc-icon-size,24px)}svg{width:100%;height:100%;fill:currentColor}</style><svg viewBox="0 0 24 24"><path></path></svg>'; }
      set icon(v) { this.setAttribute("icon", v); }
      get icon() { return this.getAttribute("icon"); }
      attributeChangedCallback() {
        const navn = (this.getAttribute("icon") || "").replace(/^mdi:/, "");
        this._navn = navn;
        sti(navn).then((d) => { if (this._navn === navn) this.shadowRoot.querySelector("path").setAttribute("d", d || ""); }).catch(() => {});
      }
    });
  }
  const vaek = () => { document.body.innerHTML = '<p style="padding:40px 24px;text-align:center;color:#888;font-size:16px">🔒 Dette link er ikke længere i brug.</p>'; };
  const abonnenter = {};  // indkøbslisterne: entity_id -> kortets callbacks
  let sidst = "", data = null;
  const dark = matchMedia("(prefers-color-scheme: dark)");
  const conn = {
    subscribeMessage(cb, msg) {
      if (msg.type !== "todo/item/subscribe") return Promise.reject(new Error("unsupported"));
      (abonnenter[msg.entity_id] = abonnenter[msg.entity_id] || new Set()).add(cb);
      if (data) Promise.resolve().then(() => cb({ items: data.todo[msg.entity_id] || [] }));
      return Promise.resolve(async () => abonnenter[msg.entity_id].delete(cb));
    },
    sendMessagePromise: (msg) => msg.type === "frontend/get_user_data" ? Promise.resolve({ value: null }) : Promise.reject(new Error("unsupported")),
  };
  const vis = (d) => {
    const s = JSON.stringify(d);
    if (!d || s === sidst) return;
    sidst = s;
    data = d;
    window.MADPLAN_APP.vist = true;
    const el = document.querySelector("madplan-panel");
    if (el) el.hass = hass();
    for (const [id, cbs] of Object.entries(abonnenter)) for (const cb of cbs) cb({ items: d.todo[id] || [] });
  };
  const svar = (r) => (r.status === 404 ? (vaek(), null) : r.ok ? r.json() : null);
  const hent = () => fetch(`${API}/data`, { cache: "no-store" }).then(svar).then(vis).catch(() => {});
  // Børn: kun kryds en vare af. Voksne: også ugens plan - serveren tjekker hvert kald.
  const post = (sti, body) => fetch(`${API}/${sti}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const fejl = async (r) => { if (r.status === 404) return svar(r); if (!r.ok) { let t = "Det gik ikke"; try { t = (await r.json()).message || t; } catch (e) { /* */ } alert(t); return null; } return r.json(); };
  const callService = (domain, service, d) => {
    if (window.MADPLAN_APP.voksen && d && d.entity_id) {
      return post("kald", { domain, service, data: d }).then(fejl).then((x) => { vis(x); setTimeout(hent, 4000); setTimeout(hent, 20000); });
    }
    return domain === "madplan" && service === "marker" ? post("marker", d).then(svar).then(vis) : Promise.reject(new Error("Ikke i appen"));
  };
  const hass = () => ({ connection: conn, states: data ? data.states : {}, user: { id: "", name: data && data.navn, is_admin: false },
    language: "da", locale: { language: "da" }, themes: { darkMode: dark.matches }, callService,
    callWS: () => Promise.reject(new Error("Ikke i appen")) });
  window.MADPLAN_APP.hent = hent;
  window.MADPLAN_APP.hass = hass;
  setInterval(() => { if (document.visibilityState === "visible") hent(); }, 30000);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") hent(); });
})();
</script>
<script type="module" src="{{js}}"></script>
<script type="module">
(async () => {
  const A = window.MADPLAN_APP;
  await customElements.whenDefined("madplan-panel");
  const el = document.createElement("madplan-panel");
  document.body.prepend(el);
  await A.hent();
  if (!A.vist) el.hass = A.hass();  // uden data endnu: kortet viser sig selv tomt, til næste hentning
  if ("serviceWorker" in navigator) navigator.serviceWorker.register(`${A.base}/sw.js`, { scope: `${A.base}/` }).catch(() => {});
})();
// "Læg på hjemmeskærmen": en knap, hvor browseren kan installere siden som en app, og et kort tip på iPhone/iPad.
(() => {
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (standalone) return;
  try { if (Number(localStorage.getItem("mp_install_senere")) > Date.now()) return; } catch (e) { /* privat */ }
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const DEL = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-3px"><path d="M12 3v12M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg>';
  let spurgt = null, boks = null;
  const luk = (senere) => {
    if (boks) { boks.remove(); boks = null; }
    if (senere) { try { localStorage.setItem("mp_install_senere", String(Date.now() + 7 * 864e5)); } catch (e) { /* privat */ } }
  };
  const vis = () => {
    if (boks) return;
    boks = document.createElement("div");
    boks.setAttribute("role", "dialog");
    boks.style.cssText = "position:fixed;left:12px;right:12px;bottom:max(12px,env(safe-area-inset-bottom));z-index:50;max-width:440px;margin:0 auto;" +
      "background:#fff;color:#22304a;border-radius:20px;padding:14px 16px;box-shadow:0 10px 30px rgba(34,48,74,.18);display:flex;gap:12px;align-items:center";
    const hvordan = spurgt ? "Så åbner den som en app med ét tryk." : `Tryk på Del ${DEL} og vælg »Føj til hjemmeskærm«.`;
    boks.innerHTML = '<img src="/madplan_app-icon/256.png" alt="" width="44" height="44" style="border-radius:12px;flex:none">' +
      '<div style="flex:1;min-width:0"><div style="font-weight:800;font-size:15px;line-height:1.2">Læg Madplan på hjemmeskærmen</div>' +
      `<div style="font-size:13px;color:#55627a;margin-top:2px">${hvordan}</div></div>` +
      (spurgt ? '<button data-i style="flex:none;border:0;border-radius:999px;padding:10px 16px;background:#3f51b5;color:#fff;font-weight:800;font-size:14px">Installer</button>' : "") +
      '<button data-x aria-label="Ikke nu" style="flex:none;border:0;background:none;color:#55627a;font-size:22px;line-height:1;padding:4px">&times;</button>';
    boks.querySelector("[data-x]").onclick = () => luk(true);
    const go = boks.querySelector("[data-i]");
    if (go) go.onclick = () => { spurgt.prompt(); spurgt.userChoice.then((c) => { luk(c.outcome !== "accepted"); spurgt = null; }).catch(() => luk(false)); };
    document.body.appendChild(boks);
  };
  addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); spurgt = e; luk(false); setTimeout(vis, 1200); });
  addEventListener("appinstalled", () => luk(false));
  if (ios && window.isSecureContext) setTimeout(vis, 2500);
})();
</script></body></html>
"""
