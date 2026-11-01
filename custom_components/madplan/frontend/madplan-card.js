/* Madplan-kort: ugens retter, opskrifter og indkøbsliste – for én eller flere butikker. */

const DAGE = ["Søndag", "Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag"];
const KORT = ["Søn", "Man", "Tir", "Ons", "Tor", "Fre", "Lør"];

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const kr = (v) => `${Math.round(Number(v) || 0).toLocaleString("da-DK")} kr`;

function idagIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Mørk tekst på lyse kædefarver (fx Netto-gul), ellers hvid. */
function tekstPaa(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return "#fff";
  const n = parseInt(m[1], 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.62 ? "#1c1c1c" : "#fff";
}

class MadplanCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._cfg = { titel: "Ugens madplan", vis_indkob: true, ...config };
    this._varer = [];
    this._fane = this._fane || "ing";
    this._visHjemme = false;
    this._bekraeft = null;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (ev) => this._klik(ev));
    }
    this._sidst = null;
  }

  set hass(hass) {
    this._hass = hass;
    const planer = this._planer();
    if (!this._valgt || !planer.includes(this._valgt)) this._valgt = planer[0];
    const p = hass.states[this._valgt];
    const varer = p?.attributes.varer_entitet;
    if (this._cfg.vis_indkob && varer !== this._varerId) this._abonner(varer);
    // Tegn kun igen, når madplanens egne enheder ændrer sig.
    const ids = [...planer];
    if (p) ids.push(p.attributes.personer_entitet, ...(p.attributes.dag_entiteter || []));
    const noegle = ids.map((id) => hass.states[id]);
    if (this._sidst && noegle.length === this._sidst.length && noegle.every((s, i) => s === this._sidst[i])) return;
    this._sidst = noegle;
    this._tegn();
  }

  connectedCallback() {
    if (this._hass && this._varerId && !this._unsub) {
      const id = this._varerId;
      this._varerId = null;
      this._abonner(id);
    }
  }

  disconnectedCallback() {
    this._afmeld();
  }

  getCardSize() {
    return 14;
  }

  getGridOptions() {
    return { columns: "full" };
  }

  _planer() {
    if (this._cfg.entities) return this._cfg.entities.filter((e) => this._hass.states[e]);
    if (this._cfg.entity) return [this._cfg.entity];
    return Object.keys(this._hass.states)
      .filter((e) => e.startsWith("sensor.") && Array.isArray(this._hass.states[e].attributes.dag_entiteter))
      .sort();
  }

  _afmeld() {
    if (this._unsub) this._unsub.then((u) => u()).catch(() => {});
    this._unsub = null;
  }

  _abonner(entity) {
    this._afmeld();
    this._varerId = entity;
    this._varer = [];
    if (!entity || !this.isConnected) return;
    this._unsub = this._hass.connection
      .subscribeMessage(
        (msg) => {
          this._varer = msg.items || [];
          this._tegn();
        },
        { type: "todo/item/subscribe", entity_id: entity },
      )
      .catch(() => (this._unsub = null));
  }

  _kald(domain, service, data = {}) {
    return this._hass.callService(domain, service, data);
  }

  _klik(ev) {
    const el = ev.target.closest("[data-h]");
    if (!el) return;
    const h = el.dataset.h;
    const dag = Number(el.dataset.dag || 0);
    const id = `${h}-${dag}`;
    if (["ny", "byt", "fjern", "send"].includes(h) && this._bekraeft !== id) {
      this._bekraeft = id;
      clearTimeout(this._timer);
      this._timer = setTimeout(() => {
        this._bekraeft = null;
        this._tegn();
      }, 4000);
      this._tegn();
      return;
    }
    this._bekraeft = null;
    const plan = this._valgt;
    const a = this._hass.states[plan]?.attributes || {};
    const n = Number(this._hass.states[a.personer_entitet]?.state || 0);
    switch (h) {
      case "butik":
        this._valgt = el.dataset.id;
        this._dagValgt = null;
        this._abonner(this._hass.states[this._valgt]?.attributes.varer_entitet);
        break;
      case "dag":
        this._dagValgt = dag - 1;
        break;
      case "aabn":
        this._dagValgt = dag - 1;
        this._side = "ret";
        this._tilTop = true;
        break;
      case "side":
        this._side = el.dataset.side;
        this._tilTop = true;
        break;
      case "forrige":
      case "naeste":
        this._dagValgt = (this._dagValgt + (h === "naeste" ? 1 : 6)) % 7;
        this._tilTop = true;
        break;
      case "fane":
        this._fane = el.dataset.fane;
        break;
      case "ny":
        this._kald("madplan", "ny_plan", { entity_id: plan });
        break;
      case "byt":
        this._kald("madplan", "byt_ret", { entity_id: plan, dag });
        break;
      case "fjern":
        this._kald("madplan", "fjern_ret", { entity_id: plan, dag });
        break;
      case "send":
        this._kald("madplan", "overfoer", { entity_id: plan });
        break;
      case "plus":
      case "minus":
        this._kald("number", "set_value", {
          entity_id: a.personer_entitet,
          value: Math.min(12, Math.max(1, n + (h === "plus" ? 1 : -1))),
        });
        break;
      case "hjemme":
        this._visHjemme = !this._visHjemme;
        break;
      case "vare": {
        const v = this._varer.find((x) => x.uid === el.dataset.uid);
        if (v)
          this._kald("todo", "update_item", {
            entity_id: this._varerId,
            item: v.uid,
            status: v.status === "completed" ? "needs_action" : "completed",
          });
        break;
      }
    }
    this._tegn();
  }

  _personer() {
    const a = this._hass.states[this._valgt]?.attributes || {};
    return Math.round(Number(this._hass.states[a.personer_entitet]?.state || a.personer || 0));
  }

  _knap(h, tekst, ikon, klasse = "", dag = 0) {
    const b = this._bekraeft === `${h}-${dag}`;
    return `<button class="knap ${klasse} ${b ? "bekraeft" : ""}" data-h="${h}" data-dag="${dag}">
      <ha-icon icon="${b ? "mdi:check-bold" : ikon}"></ha-icon><span>${b ? "Tryk igen" : tekst}</span></button>`;
  }

  // ------------------------------------------------------------------ dele

  _butikker(planer) {
    if (planer.length < 2) return "";
    const totaler = planer
      .map((e) => this._hass.states[e])
      .filter((s) => s.attributes.antal_retter)
      .map((s) => s.attributes.total_alle);
    const min = totaler.length > 1 ? Math.min(...totaler) : null;
    return `<div class="butikker">${planer
      .map((e) => {
        const a = this._hass.states[e].attributes;
        const billigst = min !== null && a.antal_retter && a.total_alle === min;
        return `<button class="butik ${e === this._valgt ? "valgt" : ""}" data-h="butik" data-id="${esc(e)}"
            style="--b:${esc(a.butik_farve || "var(--primary-color)")}">
          ${a.butik_logo ? `<img src="${esc(a.butik_logo)}" alt="">` : `<ha-icon icon="mdi:store"></ha-icon>`}
          <span class="bnavn">${esc(a.butik)}</span>
          <span class="btotal">${a.antal_retter ? `${a.total_alle_ca ? "ca. " : ""}${kr(a.total_alle)}` : "–"}</span>
          ${billigst ? `<span class="billigst">Billigst</span>` : ""}
        </button>`;
      })
      .join("")}</div>`;
  }

  _top(s, n) {
    const a = s.attributes;
    const status = a.status && a.status !== "Klar" ? a.status : "";
    const arbejder = status.endsWith("…");
    return `<div class="top">
      <div class="top-linje">
        ${a.butik_logo ? `<div class="logo"><img src="${esc(a.butik_logo)}" alt="${esc(a.butik)}"></div>` : ""}
        <div class="top-tekst">
          <div class="titel">${esc(this._cfg.titel)}</div>
          <div class="under">${esc(a.butik)}${a.uge ? ` · uge ${esc(a.uge)}` : ""}${a.periode ? ` · ${esc(a.periode)}` : ""}</div>
        </div>
      </div>
      <div class="tal">
        <div class="stor"><b>${a.pris_ca ? "ca. " : ""}${kr(s.state)}</b><small>at købe</small></div>
        <div><b>${esc(String(a.pr_kuvert || 0).replace(".", ","))} kr</b><small>pr. kuvert</small></div>
        ${a.sparet ? `<div><b>${kr(a.sparet)}</b><small>har I hjemme</small></div>` : ""}
      </div>
      ${this._fordeling(a)}
      ${a.handl_senest ? `<div class="senest"><ha-icon icon="mdi:calendar-clock"></ha-icon>Tilbuddene gælder til ${esc(this._dato(a.handl_senest))}</div>` : ""}
      ${arbejder ? `<div class="arbejder"><div class="streg"></div></div>` : ""}
      ${status ? `<div class="status ${arbejder ? "" : "fejl"}"><ha-icon icon="${arbejder ? "mdi:chef-hat" : "mdi:information-outline"}"></ha-icon>${esc(status)}</div>` : ""}
      <div class="handlinger">
        ${
          n !== undefined
            ? `<div class="personer"><button class="rund" data-h="minus" aria-label="Færre">−</button>
               <span><ha-icon icon="mdi:account-group"></ha-icon>${esc(Math.round(Number(n)))}</span>
               <button class="rund" data-h="plus" aria-label="Flere">+</button></div>`
            : ""
        }
        ${this._knap("ny", "Ny madplan", "mdi:auto-fix", "lys")}
      </div>
    </div>`;
  }

  _dato(iso) {
    const d = new Date(`${iso}T12:00:00`);
    return isNaN(d) ? iso : `${KORT[d.getDay()].toLowerCase()} ${d.getDate()}/${d.getMonth() + 1}`;
  }

  /** Hvor meget af prisen der er butikkens egne priser, og hvor meget der er cirkapriser. */
  _fordeling(a) {
    if (!a.pris_ca) return "";
    const ialt = (a.pris_praecis || 0) + a.pris_ca;
    const pct = ialt ? Math.round(((a.pris_praecis || 0) / ialt) * 100) : 0;
    return `<div class="fordeling">
      <div class="fbar"><div style="width:${pct}%"></div></div>
      <div class="ftekst"><span><i class="prik fuld"></i>${kr(a.pris_praecis)} tilbudspriser</span>
        <span><i class="prik"></i>ca. ${kr(a.pris_ca)} anslået</span></div>
    </div>`;
  }

  _uge(dage, valgt) {
    const idag = idagIso();
    return `<div class="uge">${dage
      .map((d, i) => {
        if (!d) return "";
        const a = d.attributes;
        return `<button class="pille ${i === valgt ? "valgt" : ""} ${a.dato === idag ? "idag" : ""} ${a.fjernet ? "fjernet" : ""}"
            data-h="dag" data-dag="${i + 1}">
          <span class="pdag">${a.dato === idag ? "I dag" : KORT[i]}</span>
          <span class="pdato">${esc(a.dato_kort || "")}</span>
          <span class="pbillede">${
            a.fjernet
              ? `<ha-icon icon="mdi:silverware-variant"></ha-icon>`
              : a.billede
                ? `<img src="${esc(a.billede)}" alt="" loading="lazy">`
                : `<ha-icon icon="mdi:food"></ha-icon>`
          }</span>
          <span class="pnavn">${a.fjernet ? "Ingen" : esc(d.state)}</span>
        </button>`;
      })
      .join("")}</div>`;
  }

  _dag(d, i) {
    if (!d) return "";
    const a = d.attributes;
    const dag = i + 1;
    if (a.fjernet) {
      return `<div class="detalje tom-dag">
        <ha-icon icon="mdi:silverware-variant"></ha-icon>
        <div><b>${DAGE[i]}: ingen aftensmad</b><br><small>Tryk "Byt ret" for at få en ret igen.</small></div>
        <div class="knapper">${this._knap("byt", "Byt ret", "mdi:swap-horizontal", "", dag)}</div>
      </div>`;
    }
    const ing = `<ul class="ing">${(a.ingredienser || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    const trin = `<ol class="trin">${(a.trin || []).map((x) => `<li><span>${esc(x)}</span></li>`).join("")}</ol>`;
    // I panelet er der plads til både ingredienser og fremgangsmåde; i kortet bruges faner.
    const liste = this._fuld
      ? `<div class="overskrift">Ingredienser · ${esc(this._personer())} personer</div>${ing}
         <div class="overskrift">Sådan gør du</div>${trin}`
      : `<div class="faner">
          <button class="${this._fane === "ing" ? "aktiv" : ""}" data-h="fane" data-fane="ing">Ingredienser</button>
          <button class="${this._fane === "trin" ? "aktiv" : ""}" data-h="fane" data-fane="trin">Sådan gør du</button>
        </div>${this._fane === "ing" ? ing : trin}`;
    return `<div class="detalje">
      <div class="hero">${a.billede ? `<img src="${esc(a.billede)}" alt="">` : `<ha-icon icon="mdi:food"></ha-icon>`}
        <span class="dagmaerke">${DAGE[i]} ${esc(a.dato_kort || "")}</span></div>
      <div class="info">
        <div class="navn">${esc(d.state)}</div>
        ${a.kort ? `<div class="kort">${esc(a.kort)}</div>` : ""}
        <div class="fakta">
          <span><ha-icon icon="mdi:timer-outline"></ha-icon>${esc(a.tid ?? "?")} min</span>
          <span><ha-icon icon="mdi:cash"></ha-icon>${kr(a.pris)}</span>
          <span><ha-icon icon="mdi:account"></ha-icon>${esc(String(a.pr_person ?? "?").replace(".", ","))} kr/pers.</span>
        </div>
        ${a.sundhed ? `<div class="sundhed"><ha-icon icon="mdi:leaf"></ha-icon>${esc(a.sundhed)}</div>` : ""}
        ${liste}
        <div class="knapper">
          ${this._knap("byt", "Byt ret", "mdi:swap-horizontal", "", dag)}
          ${this._knap("fjern", "Spiser ude", "mdi:close", "graa", dag)}
        </div>
      </div>
    </div>`;
  }

  _indkob(s) {
    if (!this._cfg.vis_indkob || !this._varerId) return "";
    const varer = this._varer;
    const mangler = varer.filter((v) => v.status !== "completed");
    const hjemme = varer.filter((v) => v.status === "completed");
    const pct = varer.length ? Math.round((hjemme.length / varer.length) * 100) : 0;
    const linje = (v) => {
      const h = v.status === "completed";
      const tilbud = v.summary.startsWith("🏷️");
      const navn = v.summary.replace(/^🏷️\s*/, "");
      const pris = (v.description || "").replace(".00", "").replace(".", ",");
      return `<div class="vare ${h ? "hjemme" : ""}" data-h="vare" data-uid="${esc(v.uid)}">
        <span class="tjek">${h ? '<ha-icon icon="mdi:check"></ha-icon>' : ""}</span>
        <span class="vnavn">${esc(navn)}${tilbud ? ` <span class="tag">Tilbud</span>` : ""}</span>
        <span class="vpris">${esc(pris)}</span></div>`;
    };
    return `<div class="indkob">
      <div class="sektion"><ha-icon icon="mdi:cart-outline"></ha-icon><span>Indkøb</span>
        <span class="mangler">${mangler.length} varer · ${kr(s.state)}</span></div>
      <div class="hjaelp">Tryk på det, I har hjemme, så trækkes det fra.${
        s.attributes.anslaaede_priser ? ` Priser med "ca." er anslået; tilbudspriser er ${esc(s.attributes.butik)}s egne.` : ""
      }</div>
      <div class="fremdrift"><div style="width:${pct}%"></div></div>
      ${mangler.map(linje).join("")}
      ${
        hjemme.length
          ? `<button class="vis-hjemme" data-h="hjemme"><ha-icon icon="${this._visHjemme ? "mdi:chevron-up" : "mdi:chevron-down"}"></ha-icon>Har hjemme (${hjemme.length})</button>
             ${this._visHjemme ? hjemme.map(linje).join("") : ""}`
          : ""
      }
      <div class="knapper">${this._knap("send", "Send indkøbsliste", "mdi:send", "fuld")}</div>
    </div>`;
  }

  // ------------------------------------------------------------------ tegning

  _tegn() {
    if (!this._hass || !this.shadowRoot) return;
    const planer = this._planer();
    const s = this._hass.states[this._valgt];
    if (!s) {
      this.shadowRoot.innerHTML = `<style>${CSS}</style><ha-card><div class="tom">
        <ha-icon icon="mdi:silverware-fork-knife"></ha-icon><div>Madplan er ikke sat op endnu.<br>
        <small>Tilføj integrationen under Indstillinger → Enheder og tjenester.</small></div></div></ha-card>`;
      return;
    }
    const a = s.attributes;
    const farve = a.butik_farve || "#3f51b5";
    const n = this._hass.states[a.personer_entitet]?.state;
    const dage = (a.dag_entiteter || []).map((e) => this._hass.states[e]);
    const idag = idagIso();
    if (this._dagValgt == null) {
      const i = dage.findIndex((d) => d?.attributes.dato === idag);
      this._dagValgt = i >= 0 ? i : 0;
    }
    const harPlan = a.antal_retter > 0 || dage.some((d) => d && d.state !== "–");
    const uge = this.shadowRoot.querySelector(".uge");
    const rul = uge ? uge.scrollLeft : null;
    this.shadowRoot.innerHTML = `<style>${CSS}</style>
      <ha-card style="--brand:${esc(farve)};--brand-tekst:${tekstPaa(farve)}">
        ${this._butikker(planer)}
        ${this._top(s, n)}
        ${
          harPlan
            ? `${this._uge(dage, this._dagValgt)}${this._dag(dage[this._dagValgt], this._dagValgt)}${this._indkob(s)}`
            : `<div class="tom"><ha-icon icon="mdi:chef-hat"></ha-icon><div><b>Ingen madplan endnu</b><br>
               <small>Tryk "Ny madplan" for at få ugens retter ud fra tilbuddene i ${esc(a.butik)}.</small></div></div>`
        }
      </ha-card>`;
    const nyUge = this.shadowRoot.querySelector(".uge");
    if (nyUge) {
      if (rul !== null) nyUge.scrollLeft = rul;
      else nyUge.querySelector(".valgt")?.scrollIntoView({ block: "nearest", inline: "center" });
    }
  }
}

const CSS = `
  :host { --radius: 16px; }
  ha-card { overflow: hidden; container-type: inline-size; }
  ha-icon { --mdc-icon-size: 18px; flex: none; }
  button { font: inherit; color: inherit; }
  small { color: var(--secondary-text-color); }

  /* Butiksvælger */
  .butikker { display: flex; gap: 8px; padding: 12px 12px 0; overflow-x: auto; scrollbar-width: none; }
  .butik { position: relative; display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 12px;
    border: 1px solid var(--divider-color); background: var(--card-background-color); cursor: pointer; flex: none; }
  .butik img { height: 24px; width: 40px; object-fit: contain; background: #fff; border-radius: 6px; padding: 2px; }
  .butik.valgt { border: 2px solid var(--b); box-shadow: 0 2px 8px rgba(0,0,0,.12); }
  .bnavn { font-weight: 500; }
  .btotal { color: var(--secondary-text-color); font-size: 13px; }
  .billigst { position: absolute; top: -7px; right: 6px; font-size: 10px; font-weight: 700; padding: 1px 6px;
    border-radius: 6px; background: #2e7d32; color: #fff; text-transform: uppercase; letter-spacing: .4px; }

  /* Top */
  .top { margin: 12px; padding: 16px; border-radius: var(--radius); color: var(--brand-tekst);
    background: linear-gradient(135deg, var(--brand), color-mix(in srgb, var(--brand) 70%, #000)); }
  .top-linje { display: flex; align-items: center; gap: 12px; }
  .logo { background: #fff; border-radius: 12px; padding: 6px; width: 44px; height: 44px; display: grid; place-items: center; flex: none; }
  .logo img { max-width: 100%; max-height: 100%; object-fit: contain; }
  .titel { font-size: 22px; font-weight: 600; line-height: 1.2; }
  .under { opacity: .85; font-size: 14px; }
  .tal { display: flex; gap: 22px; margin: 16px 0 4px; flex-wrap: wrap; align-items: flex-end; }
  .tal div { display: flex; flex-direction: column; }
  .tal b { font-size: 18px; }
  .tal .stor b { font-size: 30px; line-height: 1.1; }
  .tal small { color: inherit; opacity: .8; }
  .fordeling { margin-top: 10px; font-size: 13px; }
  .fbar { height: 6px; border-radius: 3px; background: rgba(255,255,255,.3); overflow: hidden; }
  .fbar div { height: 100%; background: var(--brand-tekst); border-radius: 3px; }
  .ftekst { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin-top: 4px; opacity: .9; }
  .ftekst span { display: inline-flex; align-items: center; gap: 5px; }
  .prik { width: 8px; height: 8px; border-radius: 50%; background: rgba(255,255,255,.4); display: inline-block; }
  .prik.fuld { background: var(--brand-tekst); }
  .senest { display: flex; align-items: center; gap: 6px; margin-top: 8px; font-size: 13px; opacity: .9; }
  .arbejder { height: 4px; border-radius: 2px; background: rgba(255,255,255,.3); overflow: hidden; margin-top: 10px; }
  .streg { height: 100%; width: 40%; background: var(--brand-tekst); border-radius: 2px; animation: glid 1.4s ease-in-out infinite; }
  @keyframes glid { from { transform: translateX(-100%); } to { transform: translateX(250%); } }
  .status { display: flex; gap: 8px; align-items: center; margin-top: 10px; font-size: 14px; }
  .status.fejl { background: rgba(0,0,0,.2); padding: 8px 10px; border-radius: 10px; }
  .handlinger { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
  .personer { display: inline-flex; align-items: center; gap: 6px; background: rgba(255,255,255,.18); border-radius: 22px; padding: 4px; }
  .personer span { display: inline-flex; align-items: center; gap: 4px; padding: 0 6px; font-weight: 600; }
  .rund { width: 32px; height: 32px; border-radius: 50%; border: none; background: rgba(255,255,255,.25);
    color: var(--brand-tekst); font-size: 20px; line-height: 1; cursor: pointer; }

  /* Knapper */
  .knapper { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
  .knap { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: none; border-radius: 22px;
    padding: 9px 16px; cursor: pointer; font-weight: 500; background: var(--brand); color: var(--brand-tekst); transition: transform .1s; }
  .knap:active { transform: scale(.96); }
  .knap.lys { background: #fff; color: #1c1c1c; }
  .knap.graa { background: var(--secondary-background-color); color: var(--primary-text-color); }
  .knap.fuld { width: 100%; padding: 12px; }
  .knap.bekraeft { background: #ef6c00 !important; color: #fff !important; }

  /* Ugestribe */
  .uge { display: grid; grid-template-columns: repeat(7, minmax(84px, 1fr)); gap: 8px; padding: 4px 12px 8px;
    overflow-x: auto; scrollbar-width: none; scroll-snap-type: x mandatory; }
  .uge::-webkit-scrollbar, .butikker::-webkit-scrollbar { display: none; }
  .pille { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 10px 6px; border-radius: 14px;
    border: 1px solid var(--divider-color); background: var(--card-background-color); cursor: pointer; scroll-snap-align: center; }
  .pille.valgt { border: 2px solid var(--brand); background: color-mix(in srgb, var(--brand) 10%, var(--card-background-color)); }
  .pille.idag .pdag { background: var(--brand); color: var(--brand-tekst); padding: 0 8px; border-radius: 8px; }
  .pille.fjernet { opacity: .55; }
  .pdag { font-weight: 700; font-size: 13px; }
  .pdato { font-size: 12px; color: var(--secondary-text-color); }
  .pbillede { width: 48px; height: 48px; border-radius: 50%; background: #fff; display: grid; place-items: center;
    overflow: hidden; margin: 4px 0; border: 1px solid var(--divider-color); color: #9e9e9e; }
  .pbillede img { width: 100%; height: 100%; object-fit: contain; }
  .pnavn { font-size: 11px; line-height: 1.25; text-align: center; display: -webkit-box; -webkit-line-clamp: 2;
    -webkit-box-orient: vertical; overflow: hidden; min-height: 2.5em; }

  /* Dagens ret */
  .detalje { margin: 4px 12px 12px; border-radius: var(--radius); border: 1px solid var(--divider-color); overflow: hidden; }
  .hero { position: relative; background: #fff; height: 170px; display: grid; place-items: center; color: #bdbdbd; }
  .hero img { max-height: 150px; max-width: 80%; object-fit: contain; }
  .hero ha-icon { --mdc-icon-size: 64px; }
  .dagmaerke { position: absolute; left: 12px; top: 12px; background: var(--brand); color: var(--brand-tekst);
    padding: 4px 10px; border-radius: 10px; font-size: 13px; font-weight: 600; }
  .info { padding: 14px 16px 16px; }
  .navn { font-size: 20px; font-weight: 600; line-height: 1.25; }
  .kort { color: var(--secondary-text-color); margin-top: 4px; }
  .fakta { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0 8px; }
  .fakta span { display: inline-flex; align-items: center; gap: 5px; padding: 5px 10px; border-radius: 16px;
    background: var(--secondary-background-color); font-size: 13px; font-weight: 500; }
  .sundhed { display: flex; align-items: center; gap: 6px; color: #2e7d32; font-size: 14px; }
  .faner { display: flex; gap: 4px; margin: 14px 0 6px; background: var(--secondary-background-color); border-radius: 12px; padding: 3px; }
  .faner button { flex: 1; border: none; background: none; padding: 8px; border-radius: 10px; cursor: pointer;
    font-weight: 500; color: var(--secondary-text-color); }
  .faner button.aktiv { background: var(--card-background-color); color: var(--primary-text-color); box-shadow: 0 1px 3px rgba(0,0,0,.15); }
  .ing { list-style: none; padding: 0; margin: 8px 0 0; columns: 2 200px; column-gap: 20px; }
  .ing li { padding: 6px 0; border-bottom: 1px dashed var(--divider-color); break-inside: avoid; }
  .trin { list-style: none; padding: 0; margin: 8px 0 0; counter-reset: t; }
  .trin li { display: flex; gap: 10px; padding: 6px 0; counter-increment: t; }
  .trin li::before { content: counter(t); flex: none; width: 24px; height: 24px; border-radius: 50%; background: var(--brand);
    color: var(--brand-tekst); display: grid; place-items: center; font-size: 13px; font-weight: 700; }
  .overskrift { font-weight: 600; font-size: 15px; margin: 18px 0 4px; }
  .tom-dag { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 16px; }
  .tom-dag > ha-icon { --mdc-icon-size: 36px; color: var(--secondary-text-color); }
  .tom-dag .knapper { margin: 0 0 0 auto; }
  @container (min-width: 640px) {
    .detalje:not(.tom-dag) { display: grid; grid-template-columns: 280px 1fr; }
    .hero { height: auto; min-height: 220px; }
  }

  /* Indkøb */
  .indkob { margin: 0 12px 16px; padding: 16px; border-radius: var(--radius); background: var(--secondary-background-color); }
  .sektion { display: flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 600; }
  .sektion ha-icon { --mdc-icon-size: 22px; }
  .mangler { margin-left: auto; font-size: 14px; font-weight: 500; color: var(--secondary-text-color); }
  .hjaelp { font-size: 13px; color: var(--secondary-text-color); margin: 4px 0 10px; }
  .fremdrift { height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; margin-bottom: 8px; }
  .fremdrift div { height: 100%; background: #2e7d32; border-radius: 3px; transition: width .3s; }
  .vare { display: flex; align-items: center; gap: 12px; padding: 10px 4px; border-bottom: 1px solid var(--divider-color); cursor: pointer; }
  .tjek { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--secondary-text-color); flex: none;
    display: grid; place-items: center; }
  .vare.hjemme .tjek { background: #2e7d32; border-color: #2e7d32; color: #fff; }
  .tjek ha-icon { --mdc-icon-size: 15px; }
  .vnavn { flex: 1; }
  .vare.hjemme .vnavn { text-decoration: line-through; color: var(--secondary-text-color); }
  .tag { font-size: 11px; font-weight: 700; padding: 1px 6px; border-radius: 6px; background: var(--brand);
    color: var(--brand-tekst); vertical-align: middle; margin-left: 4px; }
  .vpris { color: var(--secondary-text-color); white-space: nowrap; font-size: 14px; }
  .vis-hjemme { display: flex; align-items: center; gap: 4px; border: none; background: none; padding: 12px 0 4px;
    cursor: pointer; color: var(--secondary-text-color); font-weight: 500; }

  .tom { display: flex; gap: 14px; align-items: center; padding: 20px; }
  .tom > ha-icon { --mdc-icon-size: 40px; color: var(--brand, var(--primary-color)); }
`;

/** Sidepanel: Madplan som en app med faner i bunden. Registreres automatisk af integrationen. */
class MadplanPanel extends MadplanCard {
  constructor() {
    super();
    this.setConfig({});
    this._side = "uge";
    this._fuld = true;
  }

  set narrow(v) {
    this._narrow = v;
    const m = this.shadowRoot?.querySelector("ha-menu-button");
    if (m) m.narrow = v;
  }

  set panel(_v) {}

  set route(_v) {}

  set hass(hass) {
    super.hass = hass;
    const m = this.shadowRoot?.querySelector("ha-menu-button");
    if (m) m.hass = hass;
  }

  _ugeListe(dage) {
    const idag = idagIso();
    return `<div class="dagliste">${dage
      .map((d, i) => {
        if (!d) return "";
        const a = d.attributes;
        const erIdag = a.dato === idag;
        return `<button class="dagrad ${erIdag ? "idag" : ""} ${a.fjernet ? "fjernet" : ""}" data-h="aabn" data-dag="${i + 1}">
          <span class="rbillede">${
            a.fjernet
              ? `<ha-icon icon="mdi:silverware-variant"></ha-icon>`
              : a.billede
                ? `<img src="${esc(a.billede)}" alt="" loading="lazy">`
                : `<ha-icon icon="mdi:food"></ha-icon>`
          }</span>
          <span class="rtekst">
            <span class="rdag">${DAGE[i]} ${esc(a.dato_kort || "")}${erIdag ? " · I aften" : ""}</span>
            <span class="rnavn">${a.fjernet ? "Ingen aftensmad" : esc(d.state)}</span>
            ${a.fjernet ? "" : `<span class="rinfo">${esc(a.tid ?? "?")} min · ${kr(a.pris)}</span>`}
          </span>
          <ha-icon icon="mdi:chevron-right"></ha-icon>
        </button>`;
      })
      .join("")}</div>`;
  }

  _ret(dage) {
    const i = this._dagValgt;
    const a = dage[i]?.attributes || {};
    return `<div class="retnav">
        <button data-h="forrige" aria-label="Forrige dag"><ha-icon icon="mdi:chevron-left"></ha-icon></button>
        <span>${DAGE[i]} ${esc(a.dato_kort || "")}</span>
        <button data-h="naeste" aria-label="Næste dag"><ha-icon icon="mdi:chevron-right"></ha-icon></button>
      </div>${this._dag(dage[i], i)}`;
  }

  _fane(side, tekst, ikon, antal = 0) {
    return `<button class="${this._side === side ? "aktiv" : ""}" data-h="side" data-side="${side}">
      <span class="ikonramme"><ha-icon icon="${ikon}"></ha-icon></span>${tekst}
      ${antal ? `<span class="badge">${antal}</span>` : ""}</button>`;
  }

  _tegn() {
    if (!this._hass || !this.shadowRoot) return;
    const planer = this._planer();
    const s = this._hass.states[this._valgt];
    const gammel = this.shadowRoot.querySelector(".indhold");
    const rul = gammel && !this._tilTop ? gammel.scrollTop : 0;
    this._tilTop = false;
    const tilfoej = `<a class="tilfoej" href="/config/integrations/dashboard/add?domain=madplan"><ha-icon icon="mdi:plus"></ha-icon>Butik</a>`;
    let farve = "#3f51b5";
    let krop;
    if (!s) {
      krop = `<div class="tom"><ha-icon icon="mdi:storefront-outline"></ha-icon><div><b>Vælg din første butik</b><br>
        <small>Madplanen laves ud fra ugens tilbud i den butik, du vælger.</small><br>${tilfoej}</div></div>`;
    } else {
      const a = s.attributes;
      farve = a.butik_farve || farve;
      const n = this._hass.states[a.personer_entitet]?.state;
      const dage = (a.dag_entiteter || []).map((e) => this._hass.states[e]);
      if (this._dagValgt == null) {
        const i = dage.findIndex((d) => d?.attributes.dato === idagIso());
        this._dagValgt = i >= 0 ? i : 0;
      }
      const harPlan = a.antal_retter > 0 || dage.some((d) => d && d.state !== "–");
      if (!harPlan) {
        krop = `${this._top(s, n)}<div class="tom"><ha-icon icon="mdi:chef-hat"></ha-icon><div><b>Ingen madplan endnu</b><br>
          <small>Tryk "Ny madplan" for at få ugens retter ud fra tilbuddene i ${esc(a.butik)}.</small></div></div>`;
      } else if (this._side === "ret") {
        krop = this._ret(dage);
      } else if (this._side === "indkob") {
        krop = this._indkob(s);
      } else {
        krop = `${this._top(s, n)}${this._ugeListe(dage)}`;
      }
    }
    const mangler = this._varer.filter((v) => v.status !== "completed").length;
    this.shadowRoot.innerHTML = `<style>${CSS}${PANEL_CSS}</style>
      <div class="app" style="--brand:${esc(farve)};--brand-tekst:${tekstPaa(farve)}">
        <header class="bar"><ha-menu-button></ha-menu-button><div class="bar-titel">Madplan</div></header>
        ${s ? `<div class="butikbar">${planer.length > 1 ? this._butikker(planer) : ""}${tilfoej}</div>` : ""}
        <main class="indhold"><div class="ramme">${krop}</div></main>
        ${
          s
            ? `<nav class="bund">${this._fane("uge", "Uge", "mdi:calendar-week")}${this._fane("ret", "Opskrift", "mdi:chef-hat")}${this._fane(
                "indkob",
                "Indkøb",
                "mdi:cart-outline",
                mangler,
              )}</nav>`
            : ""
        }
      </div>`;
    const m = this.shadowRoot.querySelector("ha-menu-button");
    if (m) {
      m.hass = this._hass;
      m.narrow = this._narrow;
    }
    this.shadowRoot.querySelector(".indhold").scrollTop = rul;
  }
}

const PANEL_CSS = `
  :host { display: block; height: 100%; background: var(--primary-background-color); color: var(--primary-text-color); }
  .app { display: flex; flex-direction: column; height: 100%; container-type: inline-size; }
  .bar { display: flex; align-items: center; height: 56px; padding: 0 4px; flex: none;
    background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); }
  .bar-titel { font-size: 20px; font-weight: 400; margin-left: 12px; }
  .butikbar { display: flex; align-items: center; gap: 8px; flex: none; padding-right: 12px; }
  .butikbar .butikker { flex: 1; padding-bottom: 4px; }
  .butikbar .butikker + .tilfoej { margin: 12px 0 0; }
  .butikbar > .tilfoej:only-child { margin: 12px 12px 0 auto; }
  .tilfoej { display: inline-flex; align-items: center; gap: 4px; padding: 8px 12px; border-radius: 12px; flex: none;
    border: 1px dashed var(--divider-color); color: var(--primary-text-color); text-decoration: none; font-weight: 500; margin-top: 8px; }
  .indhold { flex: 1; overflow-y: auto; -webkit-overflow-scrolling: touch; }
  .ramme { max-width: 960px; margin: 0 auto; padding-bottom: 20px; }
  .bund { flex: none; display: flex; background: var(--card-background-color); border-top: 1px solid var(--divider-color);
    padding-bottom: env(safe-area-inset-bottom); }
  .bund button { flex: 1; position: relative; display: flex; flex-direction: column; align-items: center; gap: 2px;
    padding: 8px 0 10px; border: none; background: none; color: var(--secondary-text-color); font-size: 12px; cursor: pointer; }
  .bund button.aktiv { color: var(--primary-text-color); font-weight: 600; }
  .ikonramme { display: flex; padding: 4px 20px; border-radius: 16px; transition: background .2s; }
  .bund .aktiv .ikonramme { background: color-mix(in srgb, var(--brand) 25%, transparent); }
  .bund ha-icon { --mdc-icon-size: 24px; }
  .badge { position: absolute; top: 4px; left: calc(50% + 10px); background: #d32f2f; color: #fff; font-size: 10px;
    font-weight: 700; border-radius: 9px; padding: 1px 5px; }
  .dagliste { display: grid; gap: 10px; padding: 0 12px; }
  @container (min-width: 720px) { .dagliste { grid-template-columns: 1fr 1fr; } }
  .dagrad { display: flex; align-items: center; gap: 12px; width: 100%; padding: 10px; border-radius: 16px; text-align: left;
    border: 1px solid var(--divider-color); background: var(--card-background-color); cursor: pointer; }
  .dagrad:active { transform: scale(.99); }
  .dagrad.idag { border: 2px solid var(--brand); }
  .dagrad.fjernet { opacity: .6; }
  .rbillede { width: 72px; height: 72px; border-radius: 12px; background: #fff; display: grid; place-items: center;
    overflow: hidden; flex: none; color: #bdbdbd; }
  .rbillede img { width: 100%; height: 100%; object-fit: contain; }
  .rbillede ha-icon { --mdc-icon-size: 32px; }
  .rtekst { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .rdag { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .4px; color: var(--secondary-text-color); }
  .idag .rdag { color: color-mix(in srgb, var(--brand) 70%, var(--primary-text-color)); }
  .rnavn { font-weight: 600; font-size: 16px; line-height: 1.25; }
  .rinfo { font-size: 13px; color: var(--secondary-text-color); }
  .retnav { display: flex; align-items: center; justify-content: space-between; padding: 12px 12px 4px; font-weight: 600; font-size: 17px; }
  .retnav button { width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--divider-color);
    background: var(--card-background-color); cursor: pointer; display: grid; place-items: center; }
  .retnav ha-icon { --mdc-icon-size: 24px; }
  .ramme .indkob { margin-top: 12px; background: var(--card-background-color); border: 1px solid var(--divider-color); }
  .ramme .detalje { background: var(--card-background-color); }
`;


if (!customElements.get("madplan-card")) {
  customElements.define("madplan-card", MadplanCard);
  customElements.define("madplan-panel", MadplanPanel);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "madplan-card",
    name: "Madplan",
    description: "Ugens madplan med opskrifter og indkøbsliste – for én eller flere butikker.",
    preview: false,
  });
}
