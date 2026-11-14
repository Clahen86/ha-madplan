// "Fits your home too" - the same file in each of Clahen86's apps (keep the copies alike).
// defineSuggest("appliance_watch") defines <ha-suggest-appliance-watch>: give it .hass and put it in the panel.
//   mode="card" (default): at most one suggestion - only what fits this home and isn't installed, not the first 7 days,
//                          one new a month, "No thanks" hides it for good. Nothing at all most of the time.
//   mode="list":           one quiet line "From the same developer ›" that opens the list of the other apps.
// No network: it looks only at what Home Assistant already has. What was shown or closed is kept per user in HA
// (frontend user data), shared by all the apps, so closing it in one app closes it in all.

const KEY = "clahen86_suggest";
const DAY = 86400000;
const GH = "https://github.com/Clahen86/";
const WASH = /(vaske|opvask|t(ø|o)rretumbler|washer|washing|dishwasher|dryer|tumble|wasch|trockner|sp(ü|u)lmaschine|wasmachine|droger|vaatwasser|tv(ä|a)tt|tork|disk|oppvask|lave.?linge|lave.?vaisselle|s(è|e)che)/i;

// key, repo, kind, icon, colours, installed?, fits? (only when it's for this home), what (+ why it fits)
const APPS = [
  { key: "appliance_watch", repo: "appliance-watch", kind: "integration", icon: "🧺", c: ["#14b8a6", "#0ea5e9"],
    has: (h) => comp(h, "appliance_watch"), fits: (h) => states(h).some((s) => s.attributes.device_class === "power" && WASH.test(`${s.entity_id} ${s.attributes.friendly_name || ""}`)) },
  { key: "hus_chat", repo: "ha-hus-chat", kind: "integration", icon: "💬", c: ["#ec4899", "#8b5cf6"],
    has: (h) => comp(h, "hus_chat"), fits: (h) => Object.values(h.entities || {}).filter((e) => e.platform === "mobile_app" && e.entity_id.startsWith("device_tracker.")).length >= 2 },
  { key: "heat_pilot", repo: "heat-pilot", kind: "addon", icon: "🔥", c: ["#f97316", "#ef4444"],
    has: (h) => ids(h, /varmepilot|heat_pilot/), fits: (h) => states(h).filter((s) => s.entity_id.startsWith("climate.")).length >= 2 },
  { key: "energy_pilot", repo: "Energy-pilot", kind: "addon", icon: "⚡", c: ["#22c55e", "#eab308"],
    has: (h) => ids(h, /energipilot|energy_pilot/), fits: (h) => states(h).some((s) => s.attributes.device_class === "battery" && /batter|soc|accu/i.test(s.entity_id) && !/phone|tablet|ipad|watch|remote|sensor_|motion|door/i.test(s.entity_id)) || ids(h, /^sensor\..*(pv|solar|solcelle|zon).*power/) },
  { key: "replace_device", repo: "ha-replace-device", kind: "integration", icon: "🔁", c: ["#6366f1", "#06b6d4"],
    has: (h) => comp(h, "replace_device"), fits: (h) => new Set(Object.values(h.entities || {}).filter((e) => e.device_id && ["zha", "mqtt", "zwave_js", "deconz"].includes(e.platform)).map((e) => e.device_id)).size >= 10 },
  { key: "database_doctor", repo: "ha-database-doctor", kind: "integration", icon: "🩺", c: ["#0ea5e9", "#6366f1"],
    has: (h) => comp(h, "database_doctor"), fits: (h) => comp(h, "recorder") && Object.keys(h.states || {}).length >= 1500 },
  { key: "update_guard", repo: "ha-update-guard", kind: "integration", icon: "🛡️", c: ["#64748b", "#22c55e"],
    has: (h) => comp(h, "update_guard"), fits: (h) => comp(h, "hacs") },
  { key: "madplan", repo: "ha-madplan", kind: "integration", icon: "🍽️", c: ["#f59e0b", "#ef4444"], only: ["da"],
    has: (h) => comp(h, "madplan"), fits: (h) => h.config?.country === "DK" },
];

const T = {
  da: { fits: "Passer også til dit hjem", free: "Gratis · fra samme udvikler", get: "Hent", no: "Nej tak", more: "Fra samme udvikler", installed: "Installeret", why: "Hvorfor?",
    n: { appliance_watch: "Maskiner", hus_chat: "Hus-chat", heat_pilot: "Varmepilot", energy_pilot: "Energipilot", replace_device: "Udskift enhed", database_doctor: "Database-doktor", update_guard: "Opdateringsvagt", madplan: "Madplan" },
    d: { appliance_watch: "Ved hvornår vaskemaskine, opvasker og tørretumbler virkelig er færdige.", hus_chat: "Familiens chat i Home Assistant – og huset skriver med.", heat_pilot: "Styrer varmen efter vejret, prisen og hvornår I er hjemme.", energy_pilot: "Lader batteri og bil, når strømmen er billigst.", replace_device: "Skift en død enhed ud – automationer og navne følger med.", database_doctor: "Gør databasen mindre og Home Assistant hurtigere.", update_guard: "Tjekker opdateringer for kendte fejl, før du installerer dem.", madplan: "Ugens madplan og indkøbsliste – lavet til jeres familie." },
    w: { appliance_watch: "Vi fandt en strømmåler på en af dine maskiner.", hus_chat: "Der er flere telefoner med Home Assistant-appen.", heat_pilot: "Vi fandt termostater i dit hjem.", energy_pilot: "Vi fandt et batteri eller solceller.", replace_device: "Du har mange Zigbee- eller Z-Wave-enheder.", database_doctor: "Dit Home Assistant har mange enheder.", update_guard: "Du bruger HACS.", madplan: "" } },
  en: { fits: "Fits your home too", free: "Free · from the same developer", get: "Get", no: "No thanks", more: "From the same developer", installed: "Installed", why: "Why?",
    n: { appliance_watch: "Appliance Watch", hus_chat: "House Chat", heat_pilot: "Heat Pilot", energy_pilot: "Energy Pilot", replace_device: "Replace Device", database_doctor: "Database Doctor", update_guard: "Update Guard", madplan: "Madplan" },
    d: { appliance_watch: "Knows when the washer, dishwasher and dryer are really done.", hus_chat: "The family's chat in Home Assistant – and the house writes along.", heat_pilot: "Runs the heating by the weather, the price and when you're home.", energy_pilot: "Charges the battery and the car when power is cheapest.", replace_device: "Swap a dead device – automations and names come along.", database_doctor: "Makes the database smaller and Home Assistant faster.", update_guard: "Checks updates for known problems before you install them.", madplan: "" },
    w: { appliance_watch: "We found a power plug on one of your machines.", hus_chat: "There are several phones with the Home Assistant app.", heat_pilot: "We found thermostats in your home.", energy_pilot: "We found a battery or solar panels.", replace_device: "You have many Zigbee or Z-Wave devices.", database_doctor: "Your Home Assistant has many entities.", update_guard: "You use HACS.", madplan: "" } },
  de: { fits: "Passt auch zu deinem Zuhause", free: "Kostenlos · vom selben Entwickler", get: "Holen", no: "Nein danke", more: "Vom selben Entwickler", installed: "Installiert",
    n: { appliance_watch: "Appliance Watch", hus_chat: "House Chat", heat_pilot: "Heat Pilot", energy_pilot: "Energy Pilot", replace_device: "Replace Device", database_doctor: "Database Doctor", update_guard: "Update Guard" },
    d: { appliance_watch: "Weiß, wann Waschmaschine, Spülmaschine und Trockner wirklich fertig sind.", hus_chat: "Der Familien-Chat in Home Assistant – und das Haus schreibt mit.", heat_pilot: "Heizt nach Wetter, Preis und wann ihr zu Hause seid.", energy_pilot: "Lädt Akku und Auto, wenn der Strom am günstigsten ist.", replace_device: "Ein defektes Gerät tauschen – Automationen und Namen ziehen mit.", database_doctor: "Macht die Datenbank kleiner und Home Assistant schneller.", update_guard: "Prüft Updates auf bekannte Fehler, bevor du sie installierst." },
    w: { appliance_watch: "Wir haben eine Messsteckdose an einer deiner Maschinen gefunden.", hus_chat: "Mehrere Handys haben die Home-Assistant-App.", heat_pilot: "Wir haben Thermostate gefunden.", energy_pilot: "Wir haben einen Akku oder Solarmodule gefunden.", replace_device: "Du hast viele Zigbee- oder Z-Wave-Geräte.", database_doctor: "Dein Home Assistant hat viele Entitäten.", update_guard: "Du nutzt HACS." } },
  nl: { fits: "Past ook bij jouw huis", free: "Gratis · van dezelfde ontwikkelaar", get: "Ophalen", no: "Nee, bedankt", more: "Van dezelfde ontwikkelaar", installed: "Geïnstalleerd",
    n: { appliance_watch: "Appliance Watch", hus_chat: "House Chat", heat_pilot: "Heat Pilot", energy_pilot: "Energy Pilot", replace_device: "Replace Device", database_doctor: "Database Doctor", update_guard: "Update Guard" },
    d: { appliance_watch: "Weet wanneer wasmachine, vaatwasser en droger echt klaar zijn.", hus_chat: "De gezinschat in Home Assistant – en het huis praat mee.", heat_pilot: "Stookt op het weer, de prijs en wanneer jullie thuis zijn.", energy_pilot: "Laadt batterij en auto als stroom het goedkoopst is.", replace_device: "Vervang een kapot apparaat – automaties en namen gaan mee.", database_doctor: "Maakt de database kleiner en Home Assistant sneller.", update_guard: "Controleert updates op bekende fouten voordat je ze installeert." },
    w: { appliance_watch: "We vonden een meetstekker op een van je apparaten.", hus_chat: "Meerdere telefoons hebben de Home Assistant-app.", heat_pilot: "We vonden thermostaten in je huis.", energy_pilot: "We vonden een batterij of zonnepanelen.", replace_device: "Je hebt veel Zigbee- of Z-Wave-apparaten.", database_doctor: "Je Home Assistant heeft veel entiteiten.", update_guard: "Je gebruikt HACS." } },
  sv: { fits: "Passar också ditt hem", free: "Gratis · från samma utvecklare", get: "Hämta", no: "Nej tack", more: "Från samma utvecklare", installed: "Installerad",
    n: { appliance_watch: "Appliance Watch", hus_chat: "House Chat", heat_pilot: "Heat Pilot", energy_pilot: "Energy Pilot", replace_device: "Replace Device", database_doctor: "Database Doctor", update_guard: "Update Guard" },
    d: { appliance_watch: "Vet när tvättmaskin, diskmaskin och torktumlare verkligen är klara.", hus_chat: "Familjens chatt i Home Assistant – och huset skriver med.", heat_pilot: "Styr värmen efter vädret, priset och när ni är hemma.", energy_pilot: "Laddar batteri och bil när elen är billigast.", replace_device: "Byt en trasig enhet – automationer och namn följer med.", database_doctor: "Gör databasen mindre och Home Assistant snabbare.", update_guard: "Kollar uppdateringar för kända fel innan du installerar dem." },
    w: { appliance_watch: "Vi hittade en mätande kontakt på en av dina maskiner.", hus_chat: "Flera telefoner har Home Assistant-appen.", heat_pilot: "Vi hittade termostater i ditt hem.", energy_pilot: "Vi hittade ett batteri eller solceller.", replace_device: "Du har många Zigbee- eller Z-Wave-enheter.", database_doctor: "Ditt Home Assistant har många entiteter.", update_guard: "Du använder HACS." } },
  nb: { fits: "Passer også til ditt hjem", free: "Gratis · fra samme utvikler", get: "Hent", no: "Nei takk", more: "Fra samme utvikler", installed: "Installert",
    n: { appliance_watch: "Appliance Watch", hus_chat: "House Chat", heat_pilot: "Heat Pilot", energy_pilot: "Energy Pilot", replace_device: "Replace Device", database_doctor: "Database Doctor", update_guard: "Update Guard" },
    d: { appliance_watch: "Vet når vaskemaskin, oppvaskmaskin og tørketrommel virkelig er ferdige.", hus_chat: "Familiens chat i Home Assistant – og huset skriver med.", heat_pilot: "Styrer varmen etter været, prisen og når dere er hjemme.", energy_pilot: "Lader batteri og bil når strømmen er billigst.", replace_device: "Bytt en død enhet – automasjoner og navn følger med.", database_doctor: "Gjør databasen mindre og Home Assistant raskere.", update_guard: "Sjekker oppdateringer for kjente feil før du installerer dem." },
    w: { appliance_watch: "Vi fant en målende kontakt på en av maskinene dine.", hus_chat: "Flere telefoner har Home Assistant-appen.", heat_pilot: "Vi fant termostater i hjemmet ditt.", energy_pilot: "Vi fant et batteri eller solceller.", replace_device: "Du har mange Zigbee- eller Z-Wave-enheter.", database_doctor: "Home Assistant har mange entiteter.", update_guard: "Du bruker HACS." } },
  fr: { fits: "Va aussi avec votre maison", free: "Gratuit · du même développeur", get: "Obtenir", no: "Non merci", more: "Du même développeur", installed: "Installé",
    n: { appliance_watch: "Appliance Watch", hus_chat: "House Chat", heat_pilot: "Heat Pilot", energy_pilot: "Energy Pilot", replace_device: "Replace Device", database_doctor: "Database Doctor", update_guard: "Update Guard" },
    d: { appliance_watch: "Sait quand le lave-linge, le lave-vaisselle et le sèche-linge ont vraiment fini.", hus_chat: "Le chat de la famille dans Home Assistant – et la maison écrit aussi.", heat_pilot: "Chauffe selon la météo, le prix et quand vous êtes là.", energy_pilot: "Charge la batterie et la voiture quand l'électricité est la moins chère.", replace_device: "Remplacez un appareil mort – automatisations et noms suivent.", database_doctor: "Rend la base de données plus petite et Home Assistant plus rapide.", update_guard: "Vérifie les mises à jour pour des problèmes connus avant de les installer." },
    w: { appliance_watch: "Nous avons trouvé une prise mesurant la puissance sur une de vos machines.", hus_chat: "Plusieurs téléphones ont l'app Home Assistant.", heat_pilot: "Nous avons trouvé des thermostats.", energy_pilot: "Nous avons trouvé une batterie ou des panneaux solaires.", replace_device: "Vous avez beaucoup d'appareils Zigbee ou Z-Wave.", database_doctor: "Votre Home Assistant a beaucoup d'entités.", update_guard: "Vous utilisez HACS." } },
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const comp = (h, d) => (h.config?.components || []).includes(d);
const states = (h) => Object.values(h.states || {});
const ids = (h, re) => Object.keys(h.states || {}).some((id) => re.test(id));
const lang = (h) => { const l = (h?.language || "en").split("-")[0]; return l === "no" || l === "nn" ? "nb" : T[l] ? l : "en"; };

function link(h, a) {  // opens HACS or the add-on store right on the app; GitHub when that can't be done
  if (a.kind === "addon" && comp(h, "hassio"))
    return `https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=${encodeURIComponent(GH + a.repo)}`;
  if (a.kind === "integration" && comp(h, "hacs"))
    return `https://my.home-assistant.io/redirect/hacs_repository/?owner=Clahen86&repository=${a.repo}&category=integration`;
  return GH + a.repo;
}

// The apps this home could use, best first: fits, not installed, not this app, in this language.
export function suggestions(h, self) {
  const l = lang(h);
  return APPS.filter((a) => a.key !== self && (!a.only || a.only.includes(l)) && T[l].n[a.key] && !safe(() => a.has(h)) && safe(() => a.fits(h)));
}
function safe(f) { try { return !!f(); } catch (e) { return false; } }

const CSS = `
  :host { display:block; }
  .card { position:relative; display:flex; gap:12px; align-items:center; padding:12px 14px; margin-top:12px; border-radius:18px;
    background:var(--ha-card-background, var(--card-background-color, var(--surface, #fff))); border:1px solid var(--divider-color, var(--line2, rgba(0,0,0,.08))); box-shadow:var(--ha-card-box-shadow, none); }
  .ic { flex:none; width:44px; height:44px; border-radius:13px; display:grid; place-items:center; font-size:22px; box-shadow:0 6px 16px -8px var(--c1); background:linear-gradient(135deg, var(--c1), var(--c2)); }
  .tx { flex:1; min-width:0; }
  .k { font-size:11px; font-weight:600; letter-spacing:.04em; text-transform:uppercase; color:var(--secondary-text-color, var(--muted, #646b7a)); }
  .n { font-weight:700; font-size:15px; color:var(--primary-text-color, var(--text, #1b1f2a)); margin-top:1px; }
  .d { font-size:13px; color:var(--secondary-text-color, var(--muted, #646b7a)); margin-top:2px; line-height:1.35; }
  .w { font-size:12px; color:var(--secondary-text-color, var(--muted, #646b7a)); margin-top:3px; opacity:.85; }
  .bt { display:flex; flex-direction:column; gap:6px; align-items:stretch; }
  a.get { text-decoration:none; text-align:center; font:inherit; font-size:13px; font-weight:700; color:#fff; padding:7px 14px; border-radius:99px; background:linear-gradient(135deg, var(--c1), var(--c2)); }
  button { font:inherit; font-size:12px; border:0; background:none; color:var(--secondary-text-color, var(--muted, #646b7a)); cursor:pointer; padding:2px; }
  .x { position:absolute; top:4px; right:6px; font-size:14px; opacity:.6; }
  .more { display:block; width:100%; text-align:center; margin-top:14px; font-size:13px; color:var(--secondary-text-color, var(--muted, #646b7a)); }
  .list { margin-top:8px; display:grid; gap:8px; }
  .row { display:flex; gap:10px; align-items:center; padding:8px 10px; border-radius:14px; background:var(--secondary-background-color, var(--surface2, rgba(0,0,0,.03))); }
  .row .ic { width:34px; height:34px; border-radius:10px; font-size:17px; }
  .row .n { font-size:14px; } .row .d { font-size:12px; }
  .row a.get { padding:5px 12px; font-size:12px; }
  .ok { font-size:12px; color:#22c55e; font-weight:600; }
`;

export function defineSuggest(self) {
  const name = `ha-suggest-${self.replaceAll("_", "-")}`;
  if (customElements.get(name)) return name;
  customElements.define(name, class extends HTMLElement {
    constructor() { super(); this.attachShadow({ mode: "open" }); this._data = null; this._open = false; }
    set hass(h) {
      const first = !this._hass; this._hass = h;
      if (first) this._load(); else if (this._data) this._render();
    }
    async _load() {
      try { this._data = (await this._hass.callWS({ type: "frontend/get_user_data", key: KEY }))?.value || null; } catch (e) { this._data = null; }
      if (!this._data) { this._data = { first: Date.now(), no: [], cur: null, at: 0 }; this._save(); }
      this._render();
    }
    _save() { this._hass?.callWS({ type: "frontend/set_user_data", key: KEY, value: this._data }).catch(() => {}); }
    _pick() {  // one at a time, not the first 7 days, one new a month, never one that was closed
      const d = this._data, now = Date.now();
      if (now - (d.first ?? now) < 7 * DAY) return null;
      const fit = suggestions(this._hass, self).filter((a) => !(d.no || []).includes(a.key));
      const cur = fit.find((a) => a.key === d.cur);
      if (cur) return cur;
      if (now - (d.at || 0) < 30 * DAY || !fit.length) return null;
      d.cur = fit[0].key; d.at = now; this._save();
      return fit[0];
    }
    _render() {
      const h = this._hass, t = T[lang(h)], mode = this.getAttribute("mode") || "card";
      if (mode === "list") return this._list(h, t);
      const a = this._pick();
      if (!a) { this.shadowRoot.innerHTML = ""; return; }
      this.shadowRoot.innerHTML = `<style>${CSS}</style>
        <div class="card" style="--c1:${a.c[0]};--c2:${a.c[1]}">
          <div class="ic">${a.icon}</div>
          <div class="tx"><div class="k">${esc(t.fits)}</div><div class="n">${esc(t.n[a.key])}</div>
            <div class="d">${esc(t.d[a.key] || T.en.d[a.key])}</div>${t.w[a.key] ? `<div class="w">${esc(t.w[a.key])}</div>` : ""}
            <div class="w">${esc(t.free)}</div></div>
          <div class="bt"><a class="get" href="${link(h, a)}" target="_blank" rel="noopener">${esc(t.get)}</a><button data-no>${esc(t.no)}</button></div>
        </div>`;
      this.shadowRoot.querySelector("[data-no]").onclick = () => {
        this._data.no = [...new Set([...(this._data.no || []), a.key])]; this._data.cur = null; this._save(); this._render();
      };
    }
    _list(h, t) {  // every other app: "Get" or "Installed"
      const l = lang(h);
      const apps = APPS.filter((a) => a.key !== self && (!a.only || a.only.includes(l)) && t.n[a.key]);
      this.shadowRoot.innerHTML = `<style>${CSS}</style><button class="more" data-more>${esc(t.more)} ${this._open ? "▾" : "›"}</button>
        ${this._open ? `<div class="list">${apps.map((a) => `<div class="row" style="--c1:${a.c[0]};--c2:${a.c[1]}"><div class="ic">${a.icon}</div>
          <div class="tx"><div class="n">${esc(t.n[a.key])}</div><div class="d">${esc(t.d[a.key] || T.en.d[a.key])}</div></div>
          ${safe(() => a.has(h)) ? `<span class="ok">✓ ${esc(t.installed)}</span>` : `<a class="get" href="${link(h, a)}" target="_blank" rel="noopener">${esc(t.get)}</a>`}</div>`).join("")}</div>` : ""}`;
      this.shadowRoot.querySelector("[data-more]").onclick = () => { this._open = !this._open; this._render(); };
    }
  });
  return name;
}
