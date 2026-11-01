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
    this._ekstra = [];
    this._inputs = this._inputs || {};
    this._kladde = this._kladde || [];
    this._fane = this._fane || "ing";
    this._visHjemme = false;
    this._bekraeft = null;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (ev) => this._klik(ev));
      // Det, man er ved at skrive, overlever, når kortet tegnes igen.
      this.shadowRoot.addEventListener("input", (ev) => {
        if (ev.target.name) this._inputs[ev.target.name] = ev.target.value;
      });
      this.shadowRoot.addEventListener("change", (ev) => this._aendret(ev));
      this.shadowRoot.addEventListener("submit", (ev) => {
        ev.preventDefault();
        this._indsend(ev.target);
      });
    }
    this._sidst = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (this._udseende === undefined) this._hentUdseende();
    const planer = this._planer();
    if (!this._valgt || !planer.includes(this._valgt)) this._valgt = planer[0];
    const p = hass.states[this._valgt];
    if (this._cfg.vis_indkob && p && this._listeNoegle(p.attributes) !== this._lister) this._abonner(p.attributes);
    // Tegn kun igen, når madplanens egne enheder ændrer sig.
    const ids = [...planer];
    if (p) ids.push(p.attributes.personer_entitet, ...(p.attributes.dag_entiteter || []));
    const noegle = ids.map((id) => hass.states[id]);
    if (this._sidst && noegle.length === this._sidst.length && noegle.every((s, i) => s === this._sidst[i])) return;
    this._sidst = noegle;
    this._tegn();
  }

  connectedCallback() {
    const p = this._hass?.states[this._valgt];
    if (p && this._cfg?.vis_indkob && !this._unsubs?.length) this._abonner(p.attributes);
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

  _listeNoegle(a) {
    return `${a.varer_entitet}|${a.ekstra_entitet}`;
  }

  _afmeld() {
    for (const u of this._unsubs || []) u.then((f) => f()).catch(() => {});
    this._unsubs = [];
  }

  /** Lyt på butikkens to lister: aftensmadens varer og ekstra varer. */
  _abonner(a) {
    this._afmeld();
    this._lister = this._listeNoegle(a);
    this._varerId = a.varer_entitet;
    this._ekstraId = a.ekstra_entitet;
    this._varer = [];
    this._ekstra = [];
    if (!this.isConnected) return;
    for (const [id, felt] of [
      [this._varerId, "_varer"],
      [this._ekstraId, "_ekstra"],
    ]) {
      if (!id) continue;
      this._unsubs.push(
        this._hass.connection
          .subscribeMessage(
            (msg) => {
              this[felt] = msg.items || [];
              this._tegn();
            },
            { type: "todo/item/subscribe", entity_id: id },
          )
          .catch(() => () => {}),
      );
    }
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
    if (["ny", "byt", "fjern", "send", "fjernbehov", "toemkurv"].includes(h) && this._bekraeft !== id) {
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
        if (this._hass.states[this._valgt]) this._abonner(this._hass.states[this._valgt].attributes);
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
        // Tryk = i kurven (eller tilbage på listen). En vare, I har hjemme, kommer tilbage på listen.
        const t = el.dataset.tilstand;
        this._kald("madplan", "marker", {
          entity_id: plan,
          liste: el.dataset.liste,
          uid: el.dataset.uid,
          felt: t === "hjemme" ? "hjemme" : "kurv",
          vaerdi: t === "",
        });
        break;
      }
      case "husknap":
        this._kald("madplan", "marker", {
          entity_id: plan,
          liste: el.dataset.liste,
          uid: el.dataset.uid,
          felt: "hjemme",
          vaerdi: !el.classList.contains("til"),
        });
        break;
      case "dpers": {
        const da = this._hass.states[(a.dag_entiteter || [])[dag - 1]]?.attributes || {};
        const d = Number(el.dataset.d);
        const ny = d === 0 ? 0 : Math.min(30, Math.max(1, Number(da.personer || n) + d));
        this._kald("madplan", "dag_personer", { entity_id: plan, dag, personer: ny === n ? 0 : ny });
        break;
      }
      case "design":
        this._gemUdseende({ design: el.dataset.v });
        break;
      case "farve":
        this._gemUdseende({ farve: el.dataset.v || null });
        break;
      case "toemkurv":
        this._kald("madplan", "toem_kurv", { entity_id: plan });
        break;
      case "slet":
        ev.stopPropagation();
        this._kald("todo", "remove_item", { entity_id: this._ekstraId, item: el.dataset.uid });
        break;
      case "eplus":
      case "eminus": {
        const nu = Number(el.dataset.antal || 1);
        const ny = h === "eplus" ? nu + 1 : nu - 1;
        if (ny >= 1) this._kald("madplan", "ekstra_antal", { entity_id: plan, uid: el.dataset.uid, antal: ny });
        break;
      }
      case "fjernbehov":
        this._kald("madplan", "fjern_behov", { entity_id: plan, tekst: el.dataset.tekst });
        break;
      case "kladdefjern":
        this._kladde.splice(Number(el.dataset.i), 1);
        break;
      case "findbehov": {
        // Alt i kladden (og det, der står i feltet) løses i ét AI-kald.
        const tekst = [...this._kladde, (this._inputs.behov || "").trim()].filter((t) => t.length >= 2);
        if (tekst.length) this._kald("madplan", "tilfoej_behov", { entity_id: plan, tekst });
        this._kladde = [];
        this._inputs.behov = "";
        break;
      }
      case "rstep": {
        const r = a.regler || {};
        const felt = el.dataset.felt;
        const [min, max, trin] = { vegetar: [0, 7, 1], fisk: [0, 7, 1], max_tid: [15, 120, 5] }[felt];
        const ny = Math.min(max, Math.max(min, Number(r[felt] || 0) + Number(el.dataset.d) * trin));
        this._gemRegler({ [felt]: ny });
        break;
      }
      case "rtoggle":
        this._gemRegler({ [el.dataset.felt]: !(a.regler || {})[el.dataset.felt] });
        break;
      case "rfjern": {
        const liste = [...((a.regler || {})[el.dataset.felt] || [])];
        liste.splice(Number(el.dataset.i), 1);
        this._gemRegler({ [el.dataset.felt]: liste });
        break;
      }
    }
    this._tegn();
  }

  /** Enter i et felt: et behov i kladden eller en ny ting på en af reglernes lister. */
  _indsend(form) {
    const a = this._hass.states[this._valgt]?.attributes || {};
    const r = a.regler || {};
    if (form.dataset.form === "behov") {
      const tekst = (this._inputs.behov || "").trim();
      if (tekst.length >= 2 && !this._kladde.some((k) => k.toLowerCase() === tekst.toLowerCase())) this._kladde.push(tekst);
      this._inputs.behov = "";
    } else if (form.dataset.form === "rliste") {
      const felt = form.dataset.felt;
      const tekst = (this._inputs[`r_${felt}`] || "").trim();
      const liste = r[felt] || [];
      if (tekst && !liste.some((x) => x.toLowerCase() === tekst.toLowerCase())) this._gemRegler({ [felt]: [...liste, tekst] });
      this._inputs[`r_${felt}`] = "";
    } else if (form.dataset.form === "rfast") {
      const dag = Number(form.querySelector("select").value);
      const ret = (this._inputs.r_fast || "").trim();
      if (ret) this._gemRegler({ faste_dage: [...(r.faste_dage || []).filter((f) => f.dag !== dag), { dag, ret }] });
      this._inputs.r_fast = "";
    }
    this._fokusNavn = form.querySelector("input")?.name;
    this._tegn();
  }

  /** Felter, der gemmes, når man forlader dem (budget og andre krav). */
  _aendret(ev) {
    const navn = ev.target.name;
    if (navn === "r_budget") {
      const v = ev.target.value.trim();
      this._gemRegler({ budget: v ? Math.max(0, Math.round(Number(v))) : null });
    } else if (navn === "r_krav") {
      this._gemRegler({ krav: ev.target.value.trim() });
    }
  }

  _gemRegler(aendring) {
    this._kald("madplan", "gem_regler", aendring);
  }

  _fokuser(navn) {
    const i = navn && this.shadowRoot.querySelector(`[name="${navn}"]`);
    if (i) {
      i.focus();
      if (i.setSelectionRange && i.type !== "number") i.setSelectionRange(i.value.length, i.value.length);
    }
  }

  /** Design og farve gemmes på HA-brugeren, så valget følger med på alle enheder. */
  _hentUdseende() {
    this._udseende = {};
    this._hass.connection
      .sendMessagePromise({ type: "frontend/get_user_data", key: "madplan_udseende" })
      .then((r) => {
        this._udseende = r?.value || {};
        this._tegn();
      })
      .catch(() => {});
  }

  _gemUdseende(aendring) {
    this._udseende = { ...this._udseende, ...aendring };
    this._hass.connection
      .sendMessagePromise({ type: "frontend/set_user_data", key: "madplan_udseende", value: this._udseende })
      .catch(() => {});
  }

  _farve(a) {
    return this._udseende?.farve || a.butik_farve || "#3f51b5";
  }

  /** Antal personer én dag - fx når der kommer gæster. */
  _dagPersoner(a, dag) {
    return `<div class="dagpers ${a.gaester ? "gaester" : ""}"><ha-icon icon="mdi:account-group"></ha-icon>
      <span class="dptekst">${a.gaester ? "Gæster i dag" : "Personer i dag"}</span>
      <div class="stepper"><button data-h="dpers" data-dag="${dag}" data-d="-1" aria-label="Færre">−</button>
        <span>${esc(a.personer ?? this._personer())}</span><button data-h="dpers" data-dag="${dag}" data-d="1" aria-label="Flere">+</button></div>
      ${a.gaester ? `<button class="nulstil" data-h="dpers" data-dag="${dag}" data-d="0">Som resten af ugen</button>` : ""}</div>`;
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
      ? `${this._dagPersoner(a, dag)}<div class="overskrift">Ingredienser · ${esc(a.personer ?? this._personer())} personer</div>${ing}
         <div class="overskrift">Sådan gør du</div>${trin}`
      : `${this._dagPersoner(a, dag)}<div class="faner">
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

  /** "kurv" = lagt i kurven, "hjemme" = har det hjemme, "" = skal købes. Afkrydset i to-do-listen er en af de to første. */
  _tilstand(v) {
    if (v.status !== "completed") return "";
    const kurv = this._hass.states[this._valgt]?.attributes.kurv || [];
    return kurv.includes(v.uid) ? "kurv" : "hjemme";
  }

  _indkob(s) {
    if (!this._cfg.vis_indkob || !this._varerId) return "";
    const alle = [...this._varer, ...this._ekstra];
    const tilKoeb = alle.filter((v) => this._tilstand(v) === "").length;
    const iKurv = alle.filter((v) => this._tilstand(v) === "kurv").length;
    const pct = tilKoeb + iKurv ? Math.round((iKurv / (tilKoeb + iKurv)) * 100) : 0;
    const varer = this._varer;
    const linje = (v) => this._vareLinje(v, "varer");
    const koeb = varer.filter((v) => this._tilstand(v) === "");
    const kurv = varer.filter((v) => this._tilstand(v) === "kurv");
    const hjemme = varer.filter((v) => this._tilstand(v) === "hjemme");
    return `<div class="indkob">
      <div class="sektion"><ha-icon icon="mdi:cart-outline"></ha-icon><span>Indkøb</span>
        <span class="mangler">${koeb.length + kurv.length} varer · ${kr(s.state)}</span></div>
      <div class="hjaelp">Tryk på en vare, når den er i kurven. Har I den allerede, så tryk på <ha-icon icon="mdi:home-outline"></ha-icon>, så trækkes den fra.${
        s.attributes.anslaaede_priser ? ` Priser med "ca." er anslået; tilbudspriser er ${esc(s.attributes.butik)}s egne.` : ""
      }</div>
      <div class="kurvstatus"><span><ha-icon icon="mdi:cart-check"></ha-icon><b>${iKurv}</b> af ${tilKoeb + iKurv} i kurven</span>
        ${iKurv ? this._knap("toemkurv", "Tøm kurven", "mdi:cart-remove", "graa lille") : ""}</div>
      <div class="fremdrift"><div style="width:${pct}%"></div></div>
      ${koeb.map(linje).join("")}
      ${kurv.map(linje).join("")}
      ${
        hjemme.length
          ? `<button class="vis-hjemme" data-h="hjemme"><ha-icon icon="${this._visHjemme ? "mdi:chevron-up" : "mdi:chevron-down"}"></ha-icon>Har hjemme (${hjemme.length})</button>
             ${this._visHjemme ? hjemme.map(linje).join("") : ""}`
          : ""
      }
      ${this._ekstraSektion(s)}
      <div class="knapper">${this._knap("send", "Send indkøbsliste", "mdi:send", "fuld")}</div>
    </div>`;
  }

  _vareLinje(v, liste) {
    const t = this._tilstand(v);
    const tilbud = v.summary.startsWith("🏷️");
    // "2 × REMA 1000 Hakket oksekød (400 g)" -> antal, navn og størrelse hver for sig, så navnet får plads.
    const [, antal, raa, str] = /^(?:(\d+) × )?(.*?)(?: \(([^()]*)\))?$/.exec(v.summary.replace(/^🏷️\s*/, ""));
    const navn = raa.replace(/^REMA 1000 /i, "");
    const pris = (v.description || "").split(" · ")[0].replace(".00", "").replace(/(\d)\.(\d)/, "$1,$2");
    // På ekstra-listen vises antallet i knapperne i stedet for i navnet.
    const meta = [antal && liste !== "ekstra" ? `<b>${esc(antal)} ×</b>` : "", str ? esc(str) : ""].filter(Boolean).join(" ");
    return `<div class="vare ${t}" data-h="vare" data-liste="${liste}" data-uid="${esc(v.uid)}" data-tilstand="${t}">
      <span class="tjek">${t === "kurv" ? '<ha-icon icon="mdi:check"></ha-icon>' : t === "hjemme" ? '<ha-icon icon="mdi:home"></ha-icon>' : ""}</span>
      <span class="vtekst"><span class="vnavn">${esc(navn)}</span>
        ${meta || tilbud ? `<span class="vmeta">${meta}${tilbud ? `<span class="tag">Tilbud</span>` : ""}</span>` : ""}</span>
      <span class="vhoejre"><span class="vpris">${esc(pris)}</span>
        ${liste === "ekstra" && t !== "hjemme" ? this._antalKnapper(v) : ""}</span>
      ${
        t === "kurv"
          ? ""
          : `<button class="husknap ${t === "hjemme" ? "til" : ""}" data-h="husknap" data-liste="${liste}" data-uid="${esc(v.uid)}"
              aria-label="${t === "hjemme" ? "Skal alligevel købes" : "Har det hjemme"}"><ha-icon icon="${t === "hjemme" ? "mdi:home" : "mdi:home-outline"}"></ha-icon></button>`
      }
    </div>`;
  }

  _antalKnapper(v) {
    const antal = Number((/^(?:🏷️\s*)?(\d+) × /.exec(v.summary) || [])[1] || 1);
    const uid = esc(v.uid);
    return `<span class="antal" data-h="ingen">
      ${
        antal > 1
          ? `<button data-h="eminus" data-uid="${uid}" data-antal="${antal}" aria-label="Færre">−</button>`
          : `<button data-h="slet" data-uid="${uid}" aria-label="Fjern"><ha-icon icon="mdi:delete-outline"></ha-icon></button>`
      }
      <b>${antal}</b>
      <button data-h="eplus" data-uid="${uid}" data-antal="${antal}" aria-label="Flere">+</button></span>`;
  }

  /** Ekstra varer ud over aftensmaden: man skriver et behov, og AI finder tilbud. */
  _ekstraSektion(s) {
    if (!this._ekstraId) return "";
    const a = s.attributes;
    const behov = a.behov || [];
    const mangler = this._ekstra.filter((v) => this._tilstand(v) !== "hjemme");
    const raekke = { "": 0, kurv: 1, hjemme: 2 };
    const gruppe = (b) => {
      const varer = this._ekstra
        .filter((v) => (v.description || "").split(" · ")[1] === b)
        .sort((x, y) => raekke[this._tilstand(x)] - raekke[this._tilstand(y)]);
      if (!varer.length) return "";
      return `<div class="gruppe">${esc(b.charAt(0).toUpperCase() + b.slice(1))}</div>${varer
        .map((v) => this._vareLinje(v, "ekstra"))
        .join("")}`;
    };
    const finder = (a.status || "").startsWith("Finder tilbud");
    const antal = this._kladde.length + ((this._inputs.behov || "").trim().length >= 2 ? 1 : 0);
    return `<div class="ekstra">
      <div class="sektion"><ha-icon icon="mdi:basket-plus-outline"></ha-icon><span>Ekstra</span>
        ${this._ekstra.length ? `<span class="mangler">${mangler.length} varer · ${a.ekstra_ca ? "ca. " : ""}${kr(a.ekstra_total)}</span>` : ""}</div>
      <div class="hjaelp">Hvad skal I ellers bruge i ugen? Skriv én ting ad gangen og tryk +. Tryk så "Find tilbud", så finder den tilbud på det hele på én gang. Der sættes 1 af hver på, og du retter selv antallet. Det huskes til de næste uger.</div>
      <form class="behov-form" data-form="behov"><input name="behov" autocomplete="off" enterkeyhint="done" placeholder="Fx pålæg, rugbrød, frugt …"
          value="${esc(this._inputs.behov || "")}"><button type="submit" class="plusknap" aria-label="Tilføj"><ha-icon icon="mdi:plus"></ha-icon></button></form>
      ${
        this._kladde.length
          ? `<div class="chips kladde">${this._kladde
              .map((k, i) => `<button class="chip-kladde" data-h="kladdefjern" data-i="${i}">${esc(k)}<ha-icon icon="mdi:close"></ha-icon></button>`)
              .join("")}</div>`
          : ""
      }
      ${
        antal || finder
          ? `<button class="knap findknap" data-h="findbehov" ${finder ? "disabled" : ""}>
              <ha-icon icon="${finder ? "mdi:timer-sand" : "mdi:star-four-points"}"></ha-icon>${finder ? "Søger …" : `Find tilbud (${antal})`}</button>`
          : ""
      }
      ${
        behov.length
          ? `<div class="gemt">Huskes hver uge</div><div class="chips">${behov
              .map((b, i) => {
                const bek = this._bekraeft === `fjernbehov-${i + 1}`;
                return `<button class="chip-behov ${bek ? "bekraeft" : ""}" data-h="fjernbehov" data-dag="${i + 1}" data-tekst="${esc(b)}">
                  ${bek ? "Fjern?" : esc(b)}<ha-icon icon="mdi:close"></ha-icon></button>`;
              })
              .join("")}</div>`
          : ""
      }
      ${behov.map(gruppe).join("")}
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
    const farve = this._farve(a);
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
    const fokus = this._fokusNavn || this.shadowRoot.activeElement?.name;
    this._fokusNavn = null;
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
    if (fokus) this._fokuser(fokus);
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
  .vare { display: flex; align-items: center; gap: 10px; padding: 10px 2px; border-bottom: 1px solid var(--divider-color); cursor: pointer; }
  .tjek { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--secondary-text-color); flex: none;
    display: grid; place-items: center; }
  .tjek ha-icon { --mdc-icon-size: 15px; }
  .vtekst { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .vnavn { line-height: 1.3; overflow-wrap: anywhere; }
  .vmeta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 12px; color: var(--secondary-text-color); }
  .vmeta b { color: var(--primary-text-color); font-weight: 700; }
  .vmeta .tag { margin-left: 0; }
  .vhoejre { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }
  .vare.hjemme .vnavn, .vare.kurv .vnavn { text-decoration: line-through; color: var(--secondary-text-color); }
  .vare.kurv .tjek { background: #2e7d32; border-color: #2e7d32; color: #fff; }
  .vare.hjemme .tjek { background: var(--secondary-background-color); border-color: var(--divider-color); color: var(--secondary-text-color); }
  .vare.kurv, .vare.hjemme { opacity: .75; }
  .husknap { width: 34px; height: 34px; flex: none; border-radius: 50%; border: none; cursor: pointer; display: grid; place-items: center;
    background: none; color: var(--secondary-text-color); }
  .husknap ha-icon { --mdc-icon-size: 20px; }
  .husknap.til { color: color-mix(in srgb, var(--brand) 70%, var(--primary-text-color)); }
  .hjaelp ha-icon { --mdc-icon-size: 15px; vertical-align: -2px; }
  .kurvstatus { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 8px 0 6px; font-size: 14px; min-height: 34px; }
  .kurvstatus > span { display: inline-flex; align-items: center; gap: 6px; }
  .kurvstatus ha-icon { --mdc-icon-size: 18px; color: #2e7d32; }
  .knap.lille { padding: 6px 12px; font-size: 13px; }
  .dagpers { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 12px 0 4px; padding: 8px 10px; border-radius: 18px;
    background: var(--secondary-background-color); }
  .dagpers > ha-icon { color: color-mix(in srgb, var(--brand) 70%, var(--primary-text-color)); }
  .dagpers .dptekst { flex: 1; font-weight: 600; }
  .dagpers.gaester { background: color-mix(in srgb, var(--brand) 14%, transparent); }
  .dagpers .stepper { display: inline-flex; align-items: center; gap: 4px; padding: 3px; border-radius: 20px; background: var(--card-background-color); }
  .dagpers .stepper button { width: 30px; height: 30px; border-radius: 50%; border: none; cursor: pointer; font-size: 18px;
    background: var(--secondary-background-color); color: var(--primary-text-color); }
  .dagpers .stepper span { min-width: 24px; text-align: center; font-weight: 800; }
  .dagpers .nulstil { flex-basis: 100%; border: none; background: none; color: var(--secondary-text-color); font: inherit; font-size: 13px;
    text-align: right; cursor: pointer; text-decoration: underline; padding: 0; }
  .gaest { display: inline-flex; align-items: center; gap: 2px; color: color-mix(in srgb, var(--brand) 70%, var(--primary-text-color)); }
  .gaest ha-icon { --mdc-icon-size: 14px; }
  .tag { font-size: 11px; font-weight: 700; padding: 1px 6px; border-radius: 6px; background: var(--brand);
    color: var(--brand-tekst); vertical-align: middle; margin-left: 4px; }
  .vpris { color: var(--secondary-text-color); white-space: nowrap; font-size: 14px; }
  .ekstra { margin-top: 22px; padding-top: 16px; border-top: 2px solid var(--divider-color); }
  .behov-form { display: flex; gap: 8px; margin: 8px 0; }
  .behov-form input { flex: 1; min-width: 0; padding: 10px 14px; border-radius: 22px; border: 1px solid var(--divider-color);
    background: var(--card-background-color); color: var(--primary-text-color); font: inherit; outline: none; }
  .behov-form input:focus { border-color: var(--brand); }
  .behov-form button { display: inline-flex; align-items: center; gap: 6px; border: none; border-radius: 22px; padding: 0 14px;
    background: var(--brand); color: var(--brand-tekst); font: inherit; font-weight: 500; cursor: pointer; white-space: nowrap; }
  .behov-form button[disabled] { opacity: .6; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0 6px; }
  .chip-behov { display: inline-flex; align-items: center; gap: 4px; padding: 5px 8px 5px 12px; border-radius: 16px;
    border: 1px solid var(--divider-color); background: var(--card-background-color); cursor: pointer; font-size: 13px; }
  .chip-behov ha-icon { --mdc-icon-size: 14px; opacity: .6; }
  .chip-behov.bekraeft { background: #ef6c00; color: #fff; border-color: #ef6c00; }
  .gemt { font-size: 12px; color: var(--secondary-text-color); margin: 10px 2px 2px; }
  .behov-form .plusknap { width: 42px; padding: 0; justify-content: center; flex: none; }
  .behov-form .plusknap ha-icon { --mdc-icon-size: 22px; }
  .chip-kladde { display: inline-flex; align-items: center; gap: 4px; padding: 6px 8px 6px 12px; border-radius: 16px; border: none;
    background: color-mix(in srgb, var(--brand) 16%, transparent); color: var(--primary-text-color); cursor: pointer; font: inherit;
    font-size: 14px; font-weight: 600; animation: ind .15s ease-out; }
  .chip-kladde ha-icon { --mdc-icon-size: 15px; opacity: .6; }
  @keyframes ind { from { transform: scale(.8); opacity: 0; } }
  .findknap { width: 100%; padding: 12px; margin: 4px 0 8px; font-weight: 700; }
  .findknap[disabled] { opacity: .6; }
  .gruppe { margin: 14px 0 2px; font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: .4px;
    color: var(--secondary-text-color); }
  .antal { display: inline-flex; align-items: center; gap: 2px; border: 1px solid var(--divider-color); border-radius: 18px;
    padding: 2px; flex: none; }
  .antal button { width: 28px; height: 28px; border-radius: 50%; border: none; background: none; cursor: pointer;
    font-size: 18px; line-height: 1; display: grid; place-items: center; color: var(--primary-text-color); }
  .antal button ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); }
  .antal b { min-width: 18px; text-align: center; font-size: 14px; }
  .mp { display: flex; align-items: center; gap: 8px; margin: 10px 0 4px; font-size: 14px; }
  .mp span:first-of-type { flex: 1; }
  .slet { border: none; background: none; cursor: pointer; color: var(--secondary-text-color); padding: 4px; display: grid; }
  .slet ha-icon { --mdc-icon-size: 16px; }
  .vis-hjemme { display: flex; align-items: center; gap: 4px; border: none; background: none; padding: 12px 0 4px;
    cursor: pointer; color: var(--secondary-text-color); font-weight: 500; }

  .tom { display: flex; gap: 14px; align-items: center; padding: 20px; }
  .tom > ha-icon { --mdc-icon-size: 40px; color: var(--brand, var(--primary-color)); }
`;

/** Sidepanel: Madplan som en app med faner i toppen. Registreres automatisk af integrationen. */
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

  _billede(a, klasse) {
    return `<span class="${klasse}">${
      a.fjernet
        ? `<ha-icon icon="mdi:silverware-variant"></ha-icon>`
        : a.billede
          ? `<img src="${esc(a.billede)}" alt="" loading="lazy">`
          : `<ha-icon icon="mdi:food"></ha-icon>`
    }</span>`;
  }

  _overblik(s, n) {
    const a = s.attributes;
    const status = a.status && a.status !== "Klar" ? a.status : "";
    const arbejder = status.endsWith("…");
    return `<section class="overblik">
      <div class="tiles">
        <div class="tile hoved"><span class="ikon"><ha-icon icon="mdi:cart"></ha-icon></span>
          <b>${kr(s.state)}</b><small>${a.pris_ca ? "ca. pris at købe" : "at købe"}</small></div>
        <div class="tile"><span class="ikon"><ha-icon icon="mdi:silverware-fork-knife"></ha-icon></span>
          <b>${esc(String(a.pr_kuvert || 0).replace(".", ","))} kr</b><small>pr. kuvert</small></div>
        <div class="tile"><span class="ikon"><ha-icon icon="mdi:home-heart"></ha-icon></span>
          <b>${kr(a.sparet || 0)}</b><small>har I hjemme</small></div>
      </div>
      ${
        a.pris_ca
          ? `<div class="andel"><div class="abar"><div style="width:${Math.round(((a.pris_praecis || 0) / ((a.pris_praecis || 0) + a.pris_ca)) * 100)}%"></div></div>
             <div class="atekst"><span>${kr(a.pris_praecis)} tilbudspriser</span><span>ca. ${kr(a.pris_ca)} anslået</span></div></div>`
          : ""
      }
      ${a.handl_senest ? `<div class="info"><ha-icon icon="mdi:calendar-clock"></ha-icon>Tilbuddene gælder til ${esc(this._dato(a.handl_senest))}</div>` : ""}
      ${
        (a.advarsler || []).length
          ? `<button class="advarsler" data-h="side" data-side="regler"><ha-icon icon="mdi:alert-outline"></ha-icon>
              <span><b>Planen bryder ${a.advarsler.length === 1 ? "en af jeres regler" : `${a.advarsler.length} af jeres regler`}</b>
              ${a.advarsler.map((x) => `<small>${esc(x)}</small>`).join("")}</span></button>`
          : ""
      }
      ${
        status
          ? `<div class="statuspille ${arbejder ? "" : status.startsWith("✅") ? "ok" : "fejl"}">${arbejder ? '<span class="prik-puls"></span>' : '<ha-icon icon="mdi:information-outline"></ha-icon>'}${esc(status)}</div>`
          : ""
      }
      <div class="styring">
        ${
          n !== undefined
            ? `<div class="stepper"><button data-h="minus" aria-label="Færre">−</button>
               <span><ha-icon icon="mdi:account-group"></ha-icon>${esc(Math.round(Number(n)))} pers.</span>
               <button data-h="plus" aria-label="Flere">+</button></div>`
            : ""
        }
        ${this._knap("ny", "Ny madplan", "mdi:auto-fix", "stor")}
      </div>
    </section>`;
  }

  _ugeSide(s, n, dage) {
    const idag = idagIso();
    const iAften = dage.findIndex((d) => d?.attributes.dato === idag);
    let html = this._overblik(s, n);
    if (iAften >= 0 && !dage[iAften].attributes.fjernet) {
      const d = dage[iAften];
      const a = d.attributes;
      html += `<button class="aften" data-h="aabn" data-dag="${iAften + 1}">
        ${this._billede(a, "abillede")}
        <span class="atekst2"><span class="etiket"><ha-icon icon="mdi:star-four-points"></ha-icon>I aften</span>
          <span class="anavn">${esc(d.state)}</span>
          <span class="ameta"><span><ha-icon icon="mdi:timer-outline"></ha-icon>${esc(a.tid ?? "?")} min</span>
            <span><ha-icon icon="mdi:cash"></ha-icon>${kr(a.pris)}</span>${a.gaester ? `<span><ha-icon icon="mdi:account-group"></ha-icon>${esc(a.personer)} pers.</span>` : ""}</span></span>
        <ha-icon class="pil" icon="mdi:arrow-right"></ha-icon></button>`;
    }
    html += `<div class="afsnit">Ugens retter</div><div class="dagliste">${dage
      .map((d, i) => {
        if (!d || i === iAften) return "";
        const a = d.attributes;
        const dato = (a.dato_kort || "").split("/")[0];
        return `<button class="dagrad ${a.fjernet ? "fjernet" : ""} ${a.dato && a.dato < idag ? "forbi" : ""}" data-h="aabn" data-dag="${i + 1}">
          <span class="datoblok"><small>${KORT[i]}</small><b>${esc(dato)}</b></span>
          <span class="rtekst"><span class="rnavn">${a.fjernet ? "Ingen aftensmad" : esc(d.state)}</span>
            ${a.fjernet ? `<span class="rinfo">Spiser ude</span>` : `<span class="rinfo">${esc(a.tid ?? "?")} min · ${kr(a.pris)}${a.gaester ? ` · <b class="gaest"><ha-icon icon="mdi:account-group"></ha-icon>${esc(a.personer)}</b>` : ""}</span>`}</span>
          ${this._billede(a, "rbillede")}
        </button>`;
      })
      .join("")}</div>`;
    return html;
  }

  _retSide(dage) {
    const i = this._dagValgt;
    const d = dage[i];
    const a = d?.attributes || {};
    const nav = `<div class="retnav">
        <button data-h="forrige" aria-label="Forrige dag"><ha-icon icon="mdi:chevron-left"></ha-icon></button>
        <span>${DAGE[i]} <small>${esc(a.dato_kort || "")}</small></span>
        <button data-h="naeste" aria-label="Næste dag"><ha-icon icon="mdi:chevron-right"></ha-icon></button></div>`;
    if (!d || a.fjernet || d.state === "–") return nav + this._dag(d, i);
    return `${nav}<article class="ret">
      <div class="retbillede">${a.billede ? `<img src="${esc(a.billede)}" alt="">` : `<ha-icon icon="mdi:food"></ha-icon>`}</div>
      <h1>${esc(d.state)}</h1>
      ${a.kort ? `<p class="kort">${esc(a.kort)}</p>` : ""}
      <div class="fakta">
        <span><ha-icon icon="mdi:timer-outline"></ha-icon>${esc(a.tid ?? "?")} min</span>
        <span><ha-icon icon="mdi:cash"></ha-icon>${kr(a.pris)}</span>
        <span><ha-icon icon="mdi:account"></ha-icon>${esc(String(a.pr_person ?? "?").replace(".", ","))} kr/pers.</span>
      </div>
      ${a.sundhed ? `<div class="sundhed"><ha-icon icon="mdi:leaf"></ha-icon>${esc(a.sundhed)}</div>` : ""}
      ${this._dagPersoner(a, i + 1)}
      <div class="kasse"><div class="overskrift"><ha-icon icon="mdi:basket-outline"></ha-icon>Ingredienser
          <small>${esc(a.personer ?? this._personer())} personer</small></div>
        <ul class="ing">${(a.ingredienser || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div class="kasse"><div class="overskrift"><ha-icon icon="mdi:chef-hat"></ha-icon>Sådan gør du</div>
        <ol class="trin">${(a.trin || []).map((x) => `<li><span>${esc(x)}</span></li>`).join("")}</ol></div>
      <div class="knapper">
        ${this._knap("byt", "Byt ret", "mdi:swap-horizontal", "", i + 1)}
        ${this._knap("fjern", "Spiser ude", "mdi:close", "graa", i + 1)}
      </div>
    </article>`;
  }

  /** Familiens regler: fælles for alle butikker og bruges fra næste plan. Koster ingen ekstra AI-kald. */
  _reglerSide(a) {
    const r = a.regler || {};
    const stepper = (felt, enhed) => `<div class="stepper"><button data-h="rstep" data-felt="${felt}" data-d="-1" aria-label="Færre">−</button>
        <span>${esc(r[felt] ?? 0)}${enhed}</span><button data-h="rstep" data-felt="${felt}" data-d="1" aria-label="Flere">+</button></div>`;
    const liste = (felt, ikon, titel, hjaelp, eksempel, klasse = "") => `<section class="rkort">
        <div class="rtitel"><span class="rikon ${klasse}"><ha-icon icon="${ikon}"></ha-icon></span><span><b>${titel}</b><small>${hjaelp}</small></span></div>
        ${
          (r[felt] || []).length
            ? `<div class="chips">${r[felt]
                .map((x, i) => `<button class="rchip ${klasse}" data-h="rfjern" data-felt="${felt}" data-i="${i}">${esc(x)}<ha-icon icon="mdi:close"></ha-icon></button>`)
                .join("")}</div>`
            : ""
        }
        <form class="behov-form" data-form="rliste" data-felt="${felt}"><input name="r_${felt}" autocomplete="off" enterkeyhint="done"
          placeholder="${eksempel}" value="${esc(this._inputs[`r_${felt}`] || "")}"><button type="submit" class="plusknap" aria-label="Tilføj"><ha-icon icon="mdi:plus"></ha-icon></button></form>
      </section>`;
    const faste = (r.faste_dage || []).slice().sort((x, y) => x.dag - y.dag);
    return `<div class="rintro"><ha-icon icon="mdi:information-outline"></ha-icon>Reglerne gælder alle butikker og bruges fra næste madplan. De koster ikke ekstra AI-kald.</div>
      <section class="rkort">
        <div class="rtitel"><span class="rikon"><ha-icon icon="mdi:wallet-outline"></ha-icon></span><span><b>Budget</b><small>Hele ugens aftensmad</small></span></div>
        <label class="budget"><input name="r_budget" type="number" inputmode="numeric" min="0" step="50" placeholder="Intet budget"
          value="${esc(this._inputs.r_budget ?? r.budget ?? "")}"><span>kr. pr. uge</span></label>
      </section>
      <section class="rkort">
        <div class="rlinje"><span class="rikon"><ha-icon icon="mdi:timer-outline"></ha-icon></span><span class="rnavn2"><b>Maks tid</b><small>På hverdage</small></span>${stepper("max_tid", " min")}</div>
        <div class="rlinje"><span class="rikon groen"><ha-icon icon="mdi:sprout"></ha-icon></span><span class="rnavn2"><b>Vegetarretter</b><small>Mindst pr. uge</small></span>${stepper("vegetar", "")}</div>
        <div class="rlinje"><span class="rikon blaa"><ha-icon icon="mdi:fish"></ha-icon></span><span class="rnavn2"><b>Fiskeretter</b><small>Mindst pr. uge</small></span>${stepper("fisk", "")}</div>
        <div class="rlinje"><span class="rikon groen"><ha-icon icon="mdi:leaf"></ha-icon></span><span class="rnavn2"><b>Økologi</b><small>Når prisforskellen er lille</small></span>
          <button class="kontakt ${r.oeko ? "til" : ""}" data-h="rtoggle" data-felt="oeko" role="switch" aria-checked="${r.oeko ? "true" : "false"}" aria-label="Økologi"><span></span></button></div>
      </section>
      ${liste("allergier", "mdi:alert-octagon-outline", "Allergier", "Må aldrig indgå", "Fx nødder", "roed")}
      ${liste("undgaa", "mdi:thumb-down-outline", "Undgå", "Det vil I ikke have", "Fx svampe eller lever")}
      ${liste("favoritter", "mdi:heart-outline", "Yndlingsretter", "Kommer med en gang imellem", "Fx lasagne", "lyseroed")}
      <section class="rkort">
        <div class="rtitel"><span class="rikon"><ha-icon icon="mdi:calendar-star"></ha-icon></span><span><b>Faste dage</b><small>Fx fredag er pizzadag</small></span></div>
        ${faste
          .map((f) => `<div class="fastrad"><span class="fdag">${DAGE[f.dag]}</span><span class="fret">${esc(f.ret)}</span>
            <button class="ikonknap" data-h="rfjern" data-felt="faste_dage" data-i="${(r.faste_dage || []).indexOf(f)}" aria-label="Fjern"><ha-icon icon="mdi:close"></ha-icon></button></div>`)
          .join("")}
        <form class="behov-form" data-form="rfast"><select name="r_dag">${DAGE.map((d, i) => `<option value="${i}" ${i === 5 ? "selected" : ""}>${d}</option>`).join("")}</select>
          <input name="r_fast" autocomplete="off" enterkeyhint="done" placeholder="Fx pizza" value="${esc(this._inputs.r_fast || "")}">
          <button type="submit" class="plusknap" aria-label="Tilføj"><ha-icon icon="mdi:plus"></ha-icon></button></form>
      </section>
      <section class="rkort">
        <div class="rtitel"><span class="rikon"><ha-icon icon="mdi:text-box-outline"></ha-icon></span><span><b>Andre krav</b><small>Gemmes, når du trykker udenfor</small></span></div>
        <textarea name="r_krav" rows="3" placeholder="Fx frilandsæg og økologisk mælk. Børnene kan ikke lide stærk mad.">${esc(this._inputs.r_krav ?? r.krav ?? "")}</textarea>
      </section>
      ${this._udseendeKort(a)}`;
  }

  /** Udseende: kun for den, der er logget ind - ikke en del af familiens regler. */
  _udseendeKort(a) {
    const u = this._udseende || {};
    const design = u.design || "farverig";
    const farver = [
      ["#2e7d32", "Grøn"],
      ["#1565c0", "Blå"],
      ["#6a1b9a", "Lilla"],
      ["#ef6c00", "Orange"],
      ["#c2185b", "Pink"],
      ["#00897b", "Petrol"],
      ["#37474f", "Grafit"],
    ];
    const designs = [
      ["farverig", "Farverig"],
      ["lys", "Lys"],
      ["moerk", "Mørk"],
    ];
    return `<section class="rkort">
        <div class="rtitel"><span class="rikon"><ha-icon icon="mdi:palette-outline"></ha-icon></span><span><b>Udseende</b><small>Kun for dig – følger din bruger</small></span></div>
        <div class="designs">${designs
          .map(([v, navn]) => `<button class="dvalg dv-${v} ${design === v ? "valgt" : ""}" data-h="design" data-v="${v}" aria-pressed="${design === v}">
              <span class="dmini"><span class="dtop"><i></i><i></i></span><span class="dkrop"><i></i><i></i></span></span><span>${navn}</span></button>`)
          .join("")}</div>
        <div class="farver">
          <button class="fvalg butik ${!u.farve ? "valgt" : ""}" data-h="farve" data-v="" style="--f:${esc(a.butik_farve || "#3f51b5")}" aria-label="Butikkens farve">
            ${a.butik_logo ? `<img src="${esc(a.butik_logo)}" alt="">` : ""}</button>
          ${farver
            .map(([f, navn]) => `<button class="fvalg ${u.farve === f ? "valgt" : ""}" data-h="farve" data-v="${f}" style="--f:${f}" aria-label="${navn}"></button>`)
            .join("")}
        </div>
        <div class="fhjaelp">${u.farve ? "Egen farve" : "Butikkens egen farve"}</div>
      </section>`;
  }

  _fane(side, tekst, ikon, antal = 0) {
    return `<button class="${this._side === side ? "aktiv" : ""}" data-h="side" data-side="${side}">
      <ha-icon icon="${ikon}"></ha-icon><span>${tekst}</span>${antal ? `<span class="badge">${antal}</span>` : ""}</button>`;
  }

  _butikChips(planer) {
    if (planer.length < 2) return "";
    const totaler = planer
      .map((e) => this._hass.states[e])
      .filter((s) => s.attributes.antal_retter)
      .map((s) => s.attributes.total_alle);
    const min = totaler.length > 1 ? Math.min(...totaler) : null;
    return `<div class="bchips">${planer
      .map((e) => {
        const a = this._hass.states[e].attributes;
        const billigst = min !== null && a.antal_retter && a.total_alle === min;
        return `<button class="bchip ${e === this._valgt ? "valgt" : ""}" data-h="butik" data-id="${esc(e)}">
          ${a.butik_logo ? `<img src="${esc(a.butik_logo)}" alt="">` : ""}<span>${esc(a.butik)}</span>
          <small>${a.antal_retter ? `${a.total_alle_ca ? "ca. " : ""}${kr(a.total_alle)}` : "–"}</small>
          ${billigst ? `<em>Billigst</em>` : ""}</button>`;
      })
      .join("")}</div>`;
  }

  _tegn() {
    if (!this._hass || !this.shadowRoot) return;
    const planer = this._planer();
    const s = this._hass.states[this._valgt];
    const gammel = this.shadowRoot.querySelector(".indhold");
    const rul = gammel && !this._tilTop ? gammel.scrollTop : 0;
    this._tilTop = false;
    const fokus = this._fokusNavn || this.shadowRoot.activeElement?.name;
    this._fokusNavn = null;
    const tilfoejUrl = "/config/integrations/dashboard/add?domain=madplan";
    let farve = "#3f51b5";
    let krop;
    let under = "";
    let logo = "";
    if (!s) {
      krop = `<div class="velkommen"><ha-icon icon="mdi:storefront-outline"></ha-icon><h2>Vælg din første butik</h2>
        <p>Madplanen laves ud fra ugens tilbud i den butik, du vælger.</p>
        <a class="knap stor" href="${tilfoejUrl}"><ha-icon icon="mdi:plus"></ha-icon>Tilføj butik</a></div>`;
    } else {
      const a = s.attributes;
      farve = this._farve(a);
      logo = a.butik_logo ? `<span class="hlogo"><img src="${esc(a.butik_logo)}" alt=""></span>` : "";
      under = `${esc(a.butik)}${a.uge ? ` · uge ${esc(a.uge)}` : ""}${a.periode ? ` · ${esc(a.periode)}` : ""}`;
      const n = this._hass.states[a.personer_entitet]?.state;
      const dage = (a.dag_entiteter || []).map((e) => this._hass.states[e]);
      if (this._dagValgt == null) {
        const i = dage.findIndex((d) => d?.attributes.dato === idagIso());
        this._dagValgt = i >= 0 ? i : 0;
      }
      const harPlan = a.antal_retter > 0 || dage.some((d) => d && d.state !== "–");
      if (!harPlan && this._side === "regler") {
        krop = this._reglerSide(a);
      } else if (!harPlan) {
        krop = `${this._overblik(s, n)}<div class="velkommen"><ha-icon icon="mdi:chef-hat"></ha-icon><h2>Ingen madplan endnu</h2>
          <p>Tryk "Ny madplan" for at få ugens retter ud fra tilbuddene i ${esc(a.butik)}.</p></div>`;
      } else if (this._side === "ret") {
        krop = this._retSide(dage);
      } else if (this._side === "indkob") {
        krop = this._indkob(s);
      } else if (this._side === "regler") {
        krop = this._reglerSide(a);
      } else {
        krop = this._ugeSide(s, n, dage);
      }
    }
    const mangler = [...this._varer, ...this._ekstra].filter((v) => v.status !== "completed").length;
    this.shadowRoot.innerHTML = `<style>${CSS}${PANEL_CSS}</style>
      <div class="app design-${esc(this._udseende?.design || "farverig")}" style="--brand:${esc(farve)};--brand-tekst:${tekstPaa(farve)}">
        <header class="hero">
          <div class="hrad">
            <ha-menu-button></ha-menu-button>${logo}
            <div class="htekst"><div class="htitel">Madplan</div>${under ? `<div class="hunder">${under}</div>` : ""}</div>
            <a class="hplus" href="${tilfoejUrl}" title="Tilføj butik"><ha-icon icon="mdi:storefront-plus-outline"></ha-icon></a>
          </div>
          ${s ? this._butikChips(planer) : ""}
          ${
            s
              ? `<nav class="topfaner">${this._fane("uge", "Uge", "mdi:calendar-week")}${this._fane("ret", "Opskrift", "mdi:chef-hat")}${this._fane(
                  "indkob",
                  "Indkøb",
                  "mdi:cart-outline",
                  mangler,
                )}${this._fane("regler", "Regler", "mdi:tune-variant")}</nav>`
              : ""
          }
        </header>
        <main class="indhold"><div class="ramme">${krop}</div></main>
      </div>`;
    const m = this.shadowRoot.querySelector("ha-menu-button");
    if (m) {
      m.hass = this._hass;
      m.narrow = this._narrow;
    }
    this.shadowRoot.querySelector(".indhold").scrollTop = rul;
    if (fokus) this._fokuser(fokus);
  }
}

const PANEL_CSS = `
  :host { display: block; height: 100%; background: var(--primary-background-color); color: var(--primary-text-color); }
  .app { display: flex; flex-direction: column; height: 100%; container-type: inline-size; }

  /* Top med kædens farver, butiksvalg og faner */
  .hero { flex: none; color: var(--brand-tekst); padding: 0 12px 14px; border-radius: 0 0 28px 28px;
    background:
      radial-gradient(circle at 85% -20%, rgba(255,255,255,.28), transparent 45%),
      radial-gradient(circle at 0% 120%, rgba(0,0,0,.25), transparent 50%),
      linear-gradient(140deg, var(--brand), color-mix(in srgb, var(--brand) 62%, #000));
    box-shadow: 0 6px 20px color-mix(in srgb, var(--brand) 35%, transparent); z-index: 1; }
  .hrad { display: flex; align-items: center; gap: 10px; height: 60px; }
  .hlogo { width: 40px; height: 40px; border-radius: 12px; background: #fff; display: grid; place-items: center;
    padding: 4px; box-sizing: border-box; flex: none; box-shadow: 0 2px 6px rgba(0,0,0,.2); }
  .hlogo img { max-width: 100%; max-height: 100%; object-fit: contain; }
  .htekst { flex: 1; min-width: 0; }
  .htitel { font-size: 22px; font-weight: 800; letter-spacing: -.3px; line-height: 1.1; }
  .hunder { font-size: 13px; opacity: .85; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .hplus { width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; color: inherit;
    background: rgba(255,255,255,.18); flex: none; }
  .hplus ha-icon { --mdc-icon-size: 22px; }
  .bchips { display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; padding: 4px 0 10px; }
  .bchips::-webkit-scrollbar { display: none; }
  .bchip { position: relative; display: flex; align-items: center; gap: 6px; flex: none; padding: 6px 12px 6px 6px;
    border-radius: 20px; border: none; cursor: pointer; background: rgba(255,255,255,.18); color: inherit; }
  .bchip img { width: 28px; height: 28px; border-radius: 50%; background: #fff; object-fit: contain; padding: 2px; box-sizing: border-box; }
  .bchip span { font-weight: 600; }
  .bchip small { opacity: .8; color: inherit; }
  .bchip.valgt { background: #fff; color: #1c1c1c; box-shadow: 0 2px 8px rgba(0,0,0,.2); }
  .bchip em { position: absolute; top: -8px; right: 4px; font-style: normal; font-size: 9px; font-weight: 800; letter-spacing: .5px;
    text-transform: uppercase; background: #2e7d32; color: #fff; border-radius: 6px; padding: 1px 5px; }
  .topfaner { display: flex; width: 100%; box-sizing: border-box; gap: 4px; padding: 4px; border-radius: 18px; background: rgba(0,0,0,.2); }
  .topfaner button { position: relative; flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
    padding: 10px 6px; border: none; border-radius: 14px; background: none; color: inherit; opacity: .85;
    font-weight: 600; font-size: 14px; cursor: pointer; transition: background .2s; }
  .topfaner button.aktiv { background: #fff; color: #1c1c1c; opacity: 1; box-shadow: 0 2px 8px rgba(0,0,0,.18); }
  .topfaner ha-icon { --mdc-icon-size: 20px; }
  .badge { background: #e53935; color: #fff; font-size: 11px; font-weight: 800; border-radius: 10px; padding: 1px 6px; }

  .indhold { flex: 1; overflow-y: auto; -webkit-overflow-scrolling: touch; }
  .ramme { max-width: 920px; margin: 0 auto; padding: 16px 14px 28px; }

  /* Overblik */
  .overblik { background: var(--card-background-color); border-radius: 24px; padding: 14px;
    box-shadow: 0 4px 18px rgba(0,0,0,.07); }
  .tiles { display: grid; grid-template-columns: 1.3fr 1fr 1fr; gap: 8px; }
  .tile { display: flex; flex-direction: column; gap: 2px; padding: 12px; border-radius: 18px;
    background: var(--secondary-background-color); min-width: 0; }
  .tile .ikon { width: 30px; height: 30px; border-radius: 10px; display: grid; place-items: center; margin-bottom: 6px;
    background: color-mix(in srgb, var(--brand) 18%, transparent); color: color-mix(in srgb, var(--brand) 70%, var(--primary-text-color)); }
  .tile.hoved { background: linear-gradient(140deg, var(--brand), color-mix(in srgb, var(--brand) 70%, #000)); color: var(--brand-tekst); }
  .tile.hoved .ikon { background: rgba(255,255,255,.22); color: inherit; }
  .tile b { font-size: 19px; font-weight: 800; letter-spacing: -.3px; white-space: nowrap; }
  .tile.hoved b { font-size: 22px; }
  .tile small { font-size: 12px; opacity: .75; color: inherit; }
  .andel { margin-top: 12px; }
  .abar { height: 8px; border-radius: 4px; background: var(--secondary-background-color); overflow: hidden; }
  .abar div { height: 100%; border-radius: 4px; background: linear-gradient(90deg, var(--brand), color-mix(in srgb, var(--brand) 60%, #fff)); }
  .atekst { display: flex; justify-content: space-between; font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; }
  .info { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--secondary-text-color); margin-top: 10px; }
  .statuspille { display: flex; align-items: center; gap: 8px; margin-top: 10px; padding: 8px 12px; border-radius: 14px; font-size: 14px;
    background: color-mix(in srgb, var(--brand) 12%, transparent); }
  .statuspille.ok { background: rgba(46,125,50,.12); color: #2e7d32; }
  .statuspille.fejl { background: rgba(229,57,53,.12); color: #c62828; }
  .prik-puls { width: 10px; height: 10px; border-radius: 50%; background: var(--brand); animation: puls 1.2s ease-in-out infinite; flex: none; }
  @keyframes puls { 0%,100% { transform: scale(.7); opacity: .5; } 50% { transform: scale(1.15); opacity: 1; } }
  .styring { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
  .stepper { display: inline-flex; align-items: center; gap: 4px; padding: 4px; border-radius: 22px; background: var(--secondary-background-color); }
  .stepper button { width: 34px; height: 34px; border-radius: 50%; border: none; background: var(--card-background-color);
    font-size: 20px; cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,.12); color: var(--primary-text-color); }
  .stepper span { display: inline-flex; align-items: center; gap: 5px; padding: 0 8px; font-weight: 700; }
  .knap.stor { padding: 12px 20px; font-weight: 700; box-shadow: 0 4px 12px color-mix(in srgb, var(--brand) 40%, transparent); text-decoration: none; }

  /* I aften */
  .aften { display: flex; align-items: center; gap: 14px; width: 100%; margin-top: 16px; padding: 14px; border: none;
    border-radius: 24px; text-align: left; cursor: pointer; color: var(--brand-tekst);
    background: radial-gradient(circle at 100% 0%, rgba(255,255,255,.25), transparent 40%),
      linear-gradient(140deg, var(--brand), color-mix(in srgb, var(--brand) 65%, #000));
    box-shadow: 0 8px 24px color-mix(in srgb, var(--brand) 35%, transparent); }
  .abillede { width: 92px; height: 92px; border-radius: 22px; background: #fff; display: grid; place-items: center;
    overflow: hidden; flex: none; color: #bdbdbd; box-shadow: 0 4px 12px rgba(0,0,0,.2); }
  .abillede img { width: 100%; height: 100%; object-fit: contain; }
  .atekst2 { flex: 1; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .etiket { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 800; letter-spacing: .6px;
    text-transform: uppercase; opacity: .9; }
  .etiket ha-icon { --mdc-icon-size: 14px; }
  .anavn { font-size: 20px; font-weight: 800; line-height: 1.2; letter-spacing: -.2px; }
  .ameta { display: flex; gap: 12px; font-size: 13px; opacity: .9; }
  .ameta span { display: inline-flex; align-items: center; gap: 4px; }
  .ameta ha-icon { --mdc-icon-size: 15px; }
  .pil { --mdc-icon-size: 22px; opacity: .8; }

  /* Ugens retter */
  .afsnit { font-size: 13px; font-weight: 800; text-transform: uppercase; letter-spacing: .6px; color: var(--secondary-text-color);
    margin: 22px 4px 10px; }
  .dagliste { display: grid; gap: 10px; }
  @container (min-width: 720px) { .dagliste { grid-template-columns: 1fr 1fr; } }
  .dagrad { display: flex; align-items: center; gap: 12px; width: 100%; padding: 10px; border: none; border-radius: 20px;
    text-align: left; cursor: pointer; background: var(--card-background-color); color: var(--primary-text-color);
    box-shadow: 0 2px 10px rgba(0,0,0,.06); transition: transform .1s; }
  .dagrad:active, .aften:active { transform: scale(.98); }
  .dagrad.fjernet, .dagrad.forbi { opacity: .55; }
  .datoblok { width: 50px; height: 56px; border-radius: 16px; flex: none; display: flex; flex-direction: column; align-items: center;
    justify-content: center; background: color-mix(in srgb, var(--brand) 14%, transparent);
    color: color-mix(in srgb, var(--brand) 70%, var(--primary-text-color)); }
  .datoblok small { font-size: 11px; font-weight: 800; text-transform: uppercase; color: inherit; }
  .datoblok b { font-size: 20px; font-weight: 800; line-height: 1; }
  .rtekst { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .rnavn { font-weight: 700; font-size: 15px; line-height: 1.25; }
  .rinfo { font-size: 13px; color: var(--secondary-text-color); }
  .rbillede { width: 60px; height: 60px; border-radius: 16px; background: #fff; display: grid; place-items: center;
    overflow: hidden; flex: none; color: #bdbdbd; border: 1px solid var(--divider-color); }
  .rbillede img { width: 100%; height: 100%; object-fit: contain; }

  /* Opskrift */
  .retnav { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; font-weight: 800; font-size: 18px; }
  .retnav small { font-weight: 500; color: var(--secondary-text-color); font-size: 14px; }
  .retnav button { width: 42px; height: 42px; border-radius: 50%; border: none; background: var(--card-background-color);
    box-shadow: 0 2px 8px rgba(0,0,0,.1); cursor: pointer; display: grid; place-items: center; color: var(--primary-text-color); }
  .retnav ha-icon { --mdc-icon-size: 24px; }
  .ret { background: var(--card-background-color); border-radius: 26px; padding: 16px; box-shadow: 0 4px 18px rgba(0,0,0,.07); }
  .retbillede { height: 190px; border-radius: 20px; display: grid; place-items: center; color: #bdbdbd;
    background: radial-gradient(circle, #fff 55%, color-mix(in srgb, var(--brand) 15%, #fff)); }
  .retbillede img { max-height: 170px; max-width: 85%; object-fit: contain; }
  .retbillede ha-icon { --mdc-icon-size: 64px; }
  .ret h1 { font-size: 24px; font-weight: 800; letter-spacing: -.4px; line-height: 1.2; margin: 16px 0 4px; }
  .ret .kort { margin: 0; color: var(--secondary-text-color); }
  .ret .fakta span { background: color-mix(in srgb, var(--brand) 12%, transparent); }
  .ret .fakta ha-icon { color: color-mix(in srgb, var(--brand) 70%, var(--primary-text-color)); }
  .kasse { margin-top: 16px; padding: 14px; border-radius: 20px; background: var(--secondary-background-color); }
  .kasse .overskrift { display: flex; align-items: center; gap: 8px; margin: 0 0 6px; font-size: 16px; font-weight: 800; }
  .kasse .overskrift small { margin-left: auto; font-weight: 500; }
  .kasse .overskrift ha-icon { color: color-mix(in srgb, var(--brand) 70%, var(--primary-text-color)); --mdc-icon-size: 20px; }
  .kasse .ing li { border-bottom-color: var(--divider-color); }
  .kasse .trin li { padding: 8px 0; }

  /* Indkøb */
  .ramme .indkob { margin: 0; border-radius: 26px; background: var(--card-background-color); box-shadow: 0 4px 18px rgba(0,0,0,.07); }
  .ramme .sektion { font-size: 20px; font-weight: 800; }
  .ramme .fremdrift { height: 8px; border-radius: 4px; }
  .ramme .detalje { background: var(--card-background-color); margin: 0; border: none; border-radius: 24px; box-shadow: 0 4px 18px rgba(0,0,0,.07); }

  /* Advarsler på ugesiden */
  .advarsler { display: flex; gap: 10px; width: 100%; margin-top: 10px; padding: 10px 12px; border: none; border-radius: 16px; text-align: left;
    cursor: pointer; font: inherit; background: rgba(239,108,0,.12); color: var(--primary-text-color); }
  .advarsler > ha-icon { color: #ef6c00; flex: none; }
  .advarsler span { display: flex; flex-direction: column; gap: 2px; }
  .advarsler small { color: var(--secondary-text-color); }

  /* Regler */
  .rintro { display: flex; gap: 8px; align-items: flex-start; font-size: 13px; color: var(--secondary-text-color); margin: 0 4px 12px; }
  .rintro ha-icon { --mdc-icon-size: 18px; flex: none; }
  .rkort { background: var(--card-background-color); border-radius: 24px; padding: 14px; margin-bottom: 12px;
    box-shadow: 0 4px 18px rgba(0,0,0,.07); }
  .rtitel { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
  .rtitel > span:last-child, .rnavn2 { display: flex; flex-direction: column; min-width: 0; }
  .rtitel small, .rnavn2 small { color: var(--secondary-text-color); font-size: 13px; }
  .rtitel b, .rnavn2 b { font-size: 16px; }
  .rikon { width: 40px; height: 40px; border-radius: 14px; display: grid; place-items: center; flex: none;
    background: color-mix(in srgb, var(--brand) 16%, transparent); color: color-mix(in srgb, var(--brand) 70%, var(--primary-text-color)); }
  .rikon.groen { background: rgba(46,125,50,.14); color: #2e7d32; }
  .rikon.blaa { background: rgba(21,101,192,.14); color: #1565c0; }
  .rikon.roed { background: rgba(198,40,40,.14); color: #c62828; }
  .rikon.lyseroed { background: rgba(216,27,96,.14); color: #d81b60; }
  .rlinje { display: flex; align-items: center; gap: 12px; padding: 8px 0; }
  .rlinje + .rlinje { border-top: 1px solid var(--divider-color); }
  .rnavn2 { flex: 1; }
  .rlinje .stepper span { min-width: 54px; justify-content: center; }
  .rchip { display: inline-flex; align-items: center; gap: 4px; padding: 7px 9px 7px 13px; border-radius: 18px; border: none; cursor: pointer;
    font: inherit; font-size: 14px; font-weight: 600; background: color-mix(in srgb, var(--brand) 14%, transparent); color: var(--primary-text-color); }
  .rchip.roed { background: rgba(198,40,40,.12); }
  .rchip.lyseroed { background: rgba(216,27,96,.12); }
  .rchip ha-icon { --mdc-icon-size: 15px; opacity: .6; }
  .kontakt { width: 52px; height: 32px; border-radius: 16px; border: none; padding: 3px; cursor: pointer; flex: none;
    background: var(--divider-color); transition: background .2s; }
  .kontakt span { display: block; width: 26px; height: 26px; border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.3);
    transition: transform .2s; }
  .kontakt.til { background: #2e7d32; }
  .kontakt.til span { transform: translateX(20px); }
  .budget { display: flex; align-items: center; gap: 10px; }
  .budget input { width: 140px; padding: 10px 14px; border-radius: 22px; border: 1px solid var(--divider-color); font: inherit;
    font-size: 18px; font-weight: 700; background: var(--card-background-color); color: var(--primary-text-color); outline: none; }
  .budget input:focus, .rkort textarea:focus, .rkort select:focus { border-color: var(--brand); }
  .budget span { color: var(--secondary-text-color); }
  .fastrad { display: flex; align-items: center; gap: 10px; padding: 8px 4px; border-bottom: 1px solid var(--divider-color); }
  .fdag { font-weight: 800; width: 76px; flex: none; }
  .fret { flex: 1; }
  .ikonknap { width: 32px; height: 32px; border-radius: 50%; border: none; cursor: pointer; display: grid; place-items: center;
    background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .ikonknap ha-icon { --mdc-icon-size: 16px; }
  .rkort select { padding: 0 10px; border-radius: 22px; border: 1px solid var(--divider-color); font: inherit; outline: none;
    background: var(--card-background-color); color: var(--primary-text-color); }
  .rkort textarea { width: 100%; box-sizing: border-box; padding: 12px 14px; border-radius: 18px; border: 1px solid var(--divider-color);
    font: inherit; resize: vertical; outline: none; background: var(--card-background-color); color: var(--primary-text-color); }
  /* Smal telefon: ikon over tekst i fanerne, mindre tællere under Regler */
  @container (max-width: 420px) {
    .topfaner button { flex-direction: column; gap: 2px; padding: 6px 2px; font-size: 12px; }
    .topfaner ha-icon { --mdc-icon-size: 20px; }
    .topfaner .badge { position: absolute; top: 2px; right: calc(50% - 26px); font-size: 10px; padding: 0 5px; }
    .rlinje { gap: 10px; }
    .rikon { width: 34px; height: 34px; border-radius: 12px; }
    .rtitel b, .rnavn2 b { font-size: 15px; }
    .rtitel small, .rnavn2 small { font-size: 12px; }
    .rlinje .stepper button { width: 30px; height: 30px; font-size: 18px; }
    .rlinje .stepper span { min-width: 40px; padding: 0 4px; }
    .ramme { padding: 12px 10px 24px; }
    .tiles { gap: 6px; }
    .tile { padding: 10px; }
    .tile b { font-size: 16px; }
    .tile.hoved b { font-size: 18px; }
  }

  /* Udseende */
  .designs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .dvalg { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 8px; border-radius: 18px; cursor: pointer;
    border: 2px solid transparent; background: var(--secondary-background-color); color: var(--primary-text-color); font: inherit; font-weight: 600; }
  .dvalg.valgt { border-color: var(--brand); }
  .dmini { width: 100%; height: 64px; border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; background: var(--primary-background-color); }
  .dtop { height: 26px; display: flex; gap: 4px; align-items: center; padding: 0 6px;
    background: linear-gradient(140deg, var(--brand), color-mix(in srgb, var(--brand) 62%, #000)); }
  .dtop i { height: 8px; flex: 1; border-radius: 4px; background: rgba(255,255,255,.5); }
  .dtop i:first-child { background: #fff; }
  .dkrop { flex: 1; display: flex; flex-direction: column; gap: 4px; padding: 6px; }
  .dkrop i { height: 10px; border-radius: 4px; background: var(--card-background-color); }
  .dv-lys .dtop { background: var(--card-background-color); border-bottom: 1px solid var(--divider-color); }
  .dv-lys .dtop i { background: var(--secondary-background-color); }
  .dv-lys .dtop i:first-child { background: var(--brand); }
  .dv-moerk .dtop { background: #18181b; }
  .dv-moerk .dtop i { background: #3a3a40; }
  .dv-moerk .dtop i:first-child { background: var(--brand); }
  .farver { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
  .fvalg { width: 40px; height: 40px; border-radius: 50%; border: 3px solid var(--card-background-color); cursor: pointer; padding: 0;
    background: var(--f); box-shadow: 0 0 0 2px transparent; display: grid; place-items: center; overflow: hidden; }
  .fvalg.valgt { box-shadow: 0 0 0 2px var(--f); }
  .fvalg.butik { background: #fff; box-shadow: 0 0 0 1px var(--divider-color); }
  .fvalg.butik.valgt { box-shadow: 0 0 0 2px var(--f); }
  .fvalg img { width: 80%; height: 80%; object-fit: contain; }
  .fhjaelp { font-size: 13px; color: var(--secondary-text-color); margin-top: 8px; }

  /* Design: Lys - hvid top, farven kun som accent */
  .design-lys .hero { background: var(--card-background-color); color: var(--primary-text-color); box-shadow: 0 2px 14px rgba(0,0,0,.06); }
  .design-lys .hplus, .design-lys .bchip { background: var(--secondary-background-color); }
  .design-lys .bchip.valgt, .design-lys .topfaner button.aktiv { background: var(--brand); color: var(--brand-tekst); }
  .design-lys .topfaner { background: var(--secondary-background-color); }
  .design-lys .hlogo { box-shadow: 0 0 0 1px var(--divider-color); }
  /* Design: Mørk - mørk top med farven i faner og knapper */
  .design-moerk .hero { background: radial-gradient(circle at 85% -20%, color-mix(in srgb, var(--brand) 45%, transparent), transparent 55%),
      linear-gradient(160deg, #222226, #0e0e11); color: #fff; box-shadow: 0 6px 20px rgba(0,0,0,.3); }
  .design-moerk .bchip.valgt, .design-moerk .topfaner button.aktiv { background: var(--brand); color: var(--brand-tekst); }
  .design-moerk .topfaner { background: rgba(255,255,255,.08); }

  .velkommen { text-align: center; padding: 40px 20px; }
  .velkommen > ha-icon { --mdc-icon-size: 56px; color: var(--brand); }
  .velkommen h2 { margin: 12px 0 4px; font-weight: 800; }
  .velkommen p { color: var(--secondary-text-color); margin: 0 0 18px; }
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
