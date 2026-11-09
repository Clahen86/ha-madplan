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
    if (!this._valgt || !planer.includes(this._valgt)) {
      // Den butik, man sidst så på, også når Madplan åbnes igen.
      let sidst = null;
      try {
        sidst = localStorage.getItem("madplan_butik");
      } catch (e) {
        /* privat vindue */
      }
      this._valgt = planer.includes(sidst) ? sidst : planer[0];
    }
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
    const alle = Object.keys(this._hass.states)
      .filter((e) => e.startsWith("sensor.") && Array.isArray(this._hass.states[e].attributes.dag_entiteter))
      .sort();
    // Kun den profil, den indloggede bruger hører til ("" = hovedprofilen). En administrator kan se en anden.
    const profil = this._profil(alle);
    const mine = alle.filter((e) => (this._hass.states[e].attributes.profil || "") === profil);
    return mine.length ? mine : alle.filter((e) => !this._hass.states[e].attributes.profil);
  }

  /** Profilen, kortet viser: den, brugeren er sat på - eller den, en administrator har valgt at se. */
  _profil(alle) {
    const profiler = (alle.length && this._hass.states[alle[0]].attributes.profiler) || [];
    const ids = profiler.map((p) => (p.id === "hoved" ? "" : p.id));
    if (this._hass.user?.is_admin) {
      let vis = this._profilVis;
      if (vis === undefined) {
        try {
          vis = localStorage.getItem("madplan_profil");
        } catch (e) {
          vis = null;
        }
      }
      if (vis !== null && vis !== undefined && ids.includes(vis)) return vis;
    }
    const uid = this._hass.user?.id;
    const p = profiler.find((x) => x.id !== "hoved" && (x.brugere || []).includes(uid));
    return p ? p.id : "";
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
    if (["ny", "byt", "fjern", "send", "fjernbehov", "toemkurv", "enslet", "mslet"].includes(h) && this._bekraeft !== id) {
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
        try {
          localStorage.setItem("madplan_butik", this._valgt);
        } catch (e) {
          /* privat vindue: huskes ikke */
        }
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
        this._kald("madplan", "ny_plan", { entity_id: plan, handler: this._handler || a.handler_standard || "i_dag" });
        this._handler = null;
        break;
      case "rester": {
        // På restedagen (eller en dobbeltportion) fortrydes; ellers laves dagens ret til 2 dage.
        const da = this._hass.states[(a.dag_entiteter || [])[dag - 1]]?.attributes || {};
        this._kald("madplan", "rester", { entity_id: plan, dag, til: !da.dobbelt }).catch(() => {});
        break;
      }
      case "profilvis": {
        // Kun for administratoren: se (og ret) en anden profils madplan på denne enhed.
        this._profilVis = el.dataset.id === "hoved" ? "" : el.dataset.id;
        try {
          localStorage.setItem("madplan_profil", this._profilVis);
        } catch (e) {
          /* privat vindue */
        }
        this._valgt = null;
        this._sidst = null;
        this.hass = this._hass;
        break;
      }
      case "profilbruger": {
        const p = (a.profiler || []).find((x) => x.id === el.dataset.id);
        if (!p) break;
        const b = new Set(p.brugere || []);
        b.has(el.dataset.u) ? b.delete(el.dataset.u) : b.add(el.dataset.u);
        this._kald("madplan", "gem_profil", { entity_id: plan, id: p.id, navn: p.navn, brugere: [...b] });
        break;
      }
      case "profilbutik": {
        const p = (a.profiler || []).find((x) => x.id === el.dataset.id);
        const butik = this.shadowRoot.querySelector(`select[name="pb_${el.dataset.id}"]`)?.value;
        if (p && butik) this._kald("madplan", "gem_profil", { entity_id: plan, id: p.id, navn: p.navn, brugere: p.brugere || [], butik });
        break;
      }
      case "profilslet": {
        const p = (a.profiler || []).find((x) => x.id === el.dataset.id);
        if (p && confirm(`Slet profilen "${p.navn}" med dens planer, regler og retter?`)) {
          if (this._profilVis === p.id) this._profilVis = "";
          this._kald("madplan", "slet_profil", { entity_id: plan, id: p.id });
        }
        break;
      }
      case "autoplan":
        this._kald("madplan", "auto_plan", { entity_id: el.dataset.id, til: el.dataset.til !== "1" });
        break;
      case "ekstrabutik": {
        const valgt = new Set(a.ekstra_butikker || []);
        const k = el.dataset.k;
        if (valgt.has(k)) valgt.delete(k);
        else if (valgt.size < 2) valgt.add(k);
        this._kald("madplan", "ekstra_butikker", { entity_id: plan, butikker: [...valgt] });
        break;
      }
      case "fridag": {
        const fri = new Set((a.regler || {}).fri_dage || []);
        const i = Number(el.dataset.i);
        if (fri.has(i)) fri.delete(i);
        else if (fri.size < 6) fri.add(i);
        this._gemRegler({ fri_dage: [...fri].sort() });
        break;
      }
      case "handler":
        this._handler = el.dataset.v;
        break;
      // Mine retter: familiens egne opskrifter, fælles for alle butikker.
      case "gemmin": {
        // Planens ret gemmes med de ingredienser og trin, den har nu - så kan den rettes til bagefter.
        const da = this._hass.states[(a.dag_entiteter || [])[dag - 1]];
        if (!da) break;
        const x = da.attributes;
        this._minRet({
          navn: da.state.slice(0, 60),
          dage: x.dobbelt ? 2 : 1,
          portioner: Math.min(30, Math.max(1, Number(x.personer || this._personer() || 4) * (x.dobbelt ? 2 : 1))),
          ingredienser: (x.ingredienser || []).join("\n").slice(0, 2000),
          fremgangsmaade: (x.trin || []).join("\n").slice(0, 4000),
        });
        break;
      }
      case "maktiv":
      case "mdage":
      case "mport": {
        const m = (a.mine_retter || []).find((x) => x.id === el.dataset.id);
        if (!m) break;
        if (h === "maktiv") this._minRet({ id: m.id, aktiv: !m.aktiv });
        else if (h === "mdage") this._minRet({ id: m.id, dage: m.dage === 2 ? 1 : 2 });
        else {
          const d = this._mineData[m.id];
          const n = Math.min(30, Math.max(1, Number(d?.portioner || 4) + Number(el.dataset.d)));
          if (d) d.portioner = n;
          this._minRet({ id: m.id, portioner: n });
        }
        break;
      }
      case "mslet": {
        const m = (a.mine_retter || [])[dag - 1];
        if (!m) break;
        this._kald("madplan", "slet_min_ret", { entity_id: this._valgt, id: m.id });
        this._mineAaben = null;
        break;
      }
      case "maaben": {
        const id = el.dataset.id;
        this._mineAaben = this._mineAaben === id ? null : id;
        if (this._mineAaben) this._hentMinRet(id);
        break;
      }
      case "byt":
        this._kald("madplan", "byt_ret", { entity_id: plan, dag });
        break;
      case "udfoerlig":
        this._kald("madplan", "udfoerlig_opskrift", { entity_id: plan, dag });
        break;
      case "fjern":
        this._kald("madplan", "fjern_ret", { entity_id: plan, dag });
        break;
      case "send":
        this._kald("madplan", "overfoer", { entity_id: plan, til: "liste" });
        break;
      case "sendrema":
        this._kald("madplan", "overfoer", { entity_id: plan, til: "rema" });
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
      case "harfjern":
        this._har.splice(Number(el.dataset.i), 1);
        break;
      case "enpers":
        this._enPers = Math.min(30, Math.max(1, (this._enPers ?? Math.round(n || a.personer || 4)) + Number(el.dataset.d)));
        break;
      case "findret": {
        // Det, der står i feltet, kommer også med.
        const har = [...(this._har || []), (this._inputs.har || "").trim()].filter(Boolean);
        this._kald("madplan", "en_ret", {
          entity_id: plan,
          har,
          personer: this._enPers ?? Math.round(n || a.personer || 4),
          oenske: (this._inputs.oenske || "").trim(),
        });
        this._har = har;
        this._inputs.har = "";
        this._enValgt = null;
        break;
      }
      case "envaelg":
        this._enValgt = el.dataset.id;
        this._tilTop = true;
        break;
      case "enslet": {
        const r = (a.en_ret || []).find((x) => x.id === this._enValgt) || (a.en_ret || [])[0];
        if (r) this._kald("madplan", "slet_en_ret", { entity_id: plan, id: r.id });
        this._enValgt = null;
        break;
      }
      case "dagmail":
        this._kald("madplan", "dag_mail", { entity_id: plan, dag }).catch(() => {});
        break;
      case "enmail": {
        const r = (a.en_ret || []).find((x) => x.id === this._enValgt) || (a.en_ret || [])[0];
        if (r) this._kald("madplan", "en_ret_mail", { entity_id: plan, id: r.id }).catch(() => {});
        break;
      }
      case "enliste": {
        const r = (a.en_ret || []).find((x) => x.id === this._enValgt) || (a.en_ret || [])[0];
        if (r) this._kald("madplan", "en_ret_paa_listen", { entity_id: plan, id: r.id }).catch(() => {});
        break;
      }
      case "toemkurv":
        this._kald("madplan", "toem_kurv", { entity_id: plan });
        break;
      case "mdbutikker":
        // "Handler i en anden butik i dag": kædens butikker nær hjemmet.
        if (this._mdButikker) {
          this._mdButikker = null;
          this._tegn();
          break;
        }
        this._mdButikker = "henter";
        this._tegn();
        this._hass.connection
          .sendMessagePromise({ type: "call_service", domain: "madplan", service: "madspild_butikker", service_data: { entity_id: plan }, return_response: true })
          .then((r) => (this._mdButikker = r?.response?.butikker || []))
          .catch(() => (this._mdButikker = []))
          .finally(() => this._tegn());
        break;
      case "mdskift":
        this._mdButikker = "skifter";
        this._tegn();
        this._kald("madplan", "skift_madspild_butik", { entity_id: plan, butik_id: el.dataset.id, navn: el.dataset.navn })
          .finally(() => {
            this._mdButikker = null;
            this._tegn();
          });
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
        const [min, max, trin] = {
          vegetar: [0, 7, 1], fisk: [0, 7, 1], max_tid: [15, 120, 5], max_tid_weekend: [15, 240, 15], min_varer_ekstra: [1, 5, 1],
        }[felt];
        const ny = Math.min(max, Math.max(min, Number(r[felt] ?? (felt === "min_varer_ekstra" ? 3 : 0)) + Number(el.dataset.d) * trin));
        this._gemRegler({ [felt]: ny });
        break;
      }
      case "rvalg":
        this._gemRegler({ [el.dataset.felt]: el.dataset.v });
        break;
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
    } else if (form.dataset.form === "har") {
      const tekst = (this._inputs.har || "").trim();
      this._har = this._har || [];
      if (tekst && !this._har.some((k) => k.toLowerCase() === tekst.toLowerCase())) this._har.push(tekst);
      this._inputs.har = "";
    } else if (form.dataset.form === "rliste") {
      const felt = form.dataset.felt;
      const tekst = (this._inputs[`r_${felt}`] || "").trim();
      const liste = r[felt] || [];
      if (tekst && !liste.some((x) => x.toLowerCase() === tekst.toLowerCase())) this._gemRegler({ [felt]: [...liste, tekst] });
      this._inputs[`r_${felt}`] = "";
    } else if (form.dataset.form === "mny") {
      const navn = (this._inputs.m_navn || "").trim().slice(0, 60);
      // Den nye ret åbnes med det samme, så man kan skrive opskriften ind.
      if (navn)
        this._minRet({ navn }).then((id) => {
          if (!id) return;
          this._mineAaben = id;
          this._hentMinRet(id);
        });
      this._inputs.m_navn = "";
    } else if (form.dataset.form === "nyprofil") {
      const navn = (this._inputs.p_navn || "").trim();
      const butik = form.querySelector("select")?.value;
      if (navn) this._kald("madplan", "gem_profil", { entity_id: this._valgt, navn, brugere: [], butik });
      this._inputs.p_navn = "";
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
    } else if (navn === "r_kcal" || navn === "r_protein") {
      const [min, max] = navn === "r_kcal" ? [200, 2000] : [5, 150];
      const v = ev.target.value.trim();
      this._gemRegler({ [navn.slice(2)]: v ? Math.min(max, Math.max(min, Math.round(Number(v)))) : null });
      delete this._inputs[navn];
    } else if (navn === "r_krav") {
      this._gemRegler({ krav: ev.target.value.trim() });
    } else if (/^m_(link|noter|ingredienser|fremgangsmaade)_\w+$/.test(navn)) {
      const [, felt, id] = navn.split("_");
      let v = ev.target.value.trim();
      if (felt === "link" && v && !/^https?:\/\//i.test(v)) v = `https://${v}`;
      v = v.slice(0, { link: 300, noter: 400, ingredienser: 2000, fremgangsmaade: 4000 }[felt]);
      if (this._mineData[id]) this._mineData[id][felt] = v;
      delete this._inputs[navn];
      this._minRet({ id, [felt]: v });
    }
  }

  _gemRegler(aendring) {
    this._kald("madplan", "gem_regler", { entity_id: this._valgt, ...aendring });
  }

  /** Gemmer en egen opskrift og giver dens id tilbage. */
  _minRet(data) {
    return this._hass.connection
      .sendMessagePromise({ type: "call_service", domain: "madplan", service: "gem_min_ret", service_data: { entity_id: this._valgt, ...data }, return_response: true })
      .then((r) => r?.response?.id)
      .catch(() => null);
  }

  /** Hele opskriften hentes først, når den åbnes - sensoren har kun overblikket. */
  _hentMinRet(id) {
    this._mineData = this._mineData || {};
    this._hass.connection
      .sendMessagePromise({ type: "call_service", domain: "madplan", service: "hent_min_ret", service_data: { entity_id: this._valgt, id }, return_response: true })
      .then((r) => {
        if (r?.response) this._mineData[id] = r.response;
        this._tegn();
      })
      .catch(() => {});
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

  /** "Lav til 2 dage": dobbelt portion i dag, rester i morgen - eller fortryd. */
  _resterKnap(a, i, dage) {
    if (a.rester_fra) return this._knap("rester", "Fortryd rester", "mdi:undo", "graa", i);
    if (a.dobbelt) return this._knap("rester", "Kun 1 dag", "mdi:undo", "graa", i + 1);
    const naeste = dage[i + 1]?.attributes;
    if (i >= 6 || !naeste || naeste.forbi || naeste.rester_fra) return "";
    return this._knap("rester", "Lav til 2 dage", "mdi:pot-mix-outline", "graa", i + 1);
  }

  /** Hvilke dage næste plan skal lave aftensmad til (fx ikke onsdag, hvor I spiser ude). Huskes. */
  _dageValg(a) {
    const fri = new Set((a.regler || {}).fri_dage || []);
    return `<div class="dagevalg"><span>Planen laves for</span><div>${KORT.map(
      (k, i) => `<button class="${fri.has(i) ? "" : "til"}" data-h="fridag" data-i="${i}" aria-pressed="${!fri.has(i)}" title="${DAGE[i]}">${k.slice(0, 2)}</button>`,
    ).join("")}</div></div>`;
  }

  /** Hvornår der handles: tilbuddene i den nye plan skal gælde den dag. */
  _handlerValg(a) {
    const v = this._handler || a.handler_standard || "i_dag";
    return `<div class="handler" role="group" aria-label="Jeg handler">
      <span>Jeg handler</span>
      <button class="${v === "i_dag" ? "valgt" : ""}" data-h="handler" data-v="i_dag">I dag</button>
      <button class="${v === "i_morgen" ? "valgt" : ""}" data-h="handler" data-v="i_morgen">I morgen</button></div>`;
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
          <span class="pnavn">${a.forbi ? "–" : a.fjernet ? "Ingen" : esc(d.state)}</span>
        </button>`;
      })
      .join("")}</div>`;
  }

  /** "Sådan gør du": the short steps with a button for the detailed recipe - or the detailed recipe itself. */
  _trin(a, dag) {
    const u = a.udfoerlig, st = a.udfoerlig_status || "";
    return u
      ? `<div class="udf-mark"><ha-icon icon="mdi:book-open-variant"></ha-icon>Udførlig opskrift</div>
         <ol class="trin">${(u.trin || []).map((x) => `<li><span>${esc(x)}</span></li>`).join("")}</ol>
         ${(u.tips || []).length ? `<div class="udf-tips"><b>Tips</b><ul>${u.tips.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}`
      : `<ol class="trin">${(a.trin || []).map((x) => `<li><span>${esc(x)}</span></li>`).join("")}</ol>
         ${st === "laver" ? `<div class="udf-knap venter"><ha-icon icon="mdi:loading"></ha-icon>Skriver den udførlige opskrift …</div>`
           : `<button class="udf-knap" data-h="udfoerlig" data-dag="${dag}"><ha-icon icon="mdi:book-open-variant"></ha-icon>Vis udførlig opskrift</button>
              ${st.startsWith("fejl") ? `<div class="udf-fejl">Det lykkedes ikke – prøv igen om lidt.</div>` : ""}`}`;
  }

  _dag(d, i) {
    if (!d) return "";
    const a = d.attributes;
    const dag = i + 1;
    if (a.fjernet) {
      return `<div class="detalje tom-dag">
        <ha-icon icon="mdi:silverware-variant"></ha-icon>
        <div><b>${DAGE[i]}: ${a.forbi ? "før planen" : "ingen aftensmad"}</b><br><small>${
          a.forbi ? "Planen blev lavet senere på ugen. Tryk &quot;Byt ret&quot;, hvis I vil have en ret alligevel." : "Tryk &quot;Byt ret&quot; for at få en ret igen."
        }</small></div>
        <div class="knapper">${this._knap("byt", "Byt ret", "mdi:swap-horizontal", "", dag)}</div>
      </div>`;
    }
    const ing = `<ul class="ing">${(a.ingredienser || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    const trin = this._trin(a, dag);
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
        <span class="mangler">${koeb.length + kurv.length} varer${hjemme.length ? ` · ${hjemme.length} har I` : ""} · ${kr(s.state)}</span></div>
      ${this._regnerMed(s, hjemme)}
      <div class="hjaelp">Tryk på en vare, når den er i kurven. Har I den allerede, så tryk på <ha-icon icon="mdi:home-outline"></ha-icon>, så trækkes den fra.${
        s.attributes.anslaaede_priser ? ` Priser med "ca." er anslået; tilbudspriser er ${esc(s.attributes.butik)}s egne.` : ""
      }</div>${this._madspildInfo(s.attributes)}${this._madspildButik(s.attributes)}
      <div class="kurvstatus"><span><ha-icon icon="mdi:cart-check"></ha-icon><b>${iKurv}</b> af ${tilKoeb + iKurv} i kurven</span>
        ${iKurv ? this._knap("toemkurv", "Tøm kurven", "mdi:cart-remove", "graa lille") : ""}</div>
      <div class="fremdrift"><div style="width:${pct}%"></div></div>
      ${this._perButik(koeb, linje)}
      ${kurv.map(linje).join("")}
      ${
        hjemme.length
          ? `<button class="vis-hjemme" data-h="hjemme"><ha-icon icon="${this._visHjemme ? "mdi:chevron-up" : "mdi:chevron-down"}"></ha-icon>Har hjemme (${hjemme.length})</button>
             ${this._visHjemme ? hjemme.map(linje).join("") : ""}`
          : ""
      }
      ${this._ekstraSektion(s)}
      <div class="knapper">${s.attributes.har_rema ? this._knap("sendrema", "Send til REMA-appen", "mdi:cellphone-arrow-down", "fuld") : ""}
        ${this._knap("send", "Send indkøbsliste", "mdi:send", s.attributes.har_rema ? "fuld graa" : "fuld")}</div>
    </div>`;
  }

  /** Det, planen selv regner med, I har hjemme - synligt øverst, så man opdager det, man mangler. */
  _regnerMed(s, hjemme) {
    const auto = new Set(s.attributes.auto_hjemme || []);
    const tjek = new Set(s.attributes.tjek || []);
    const varer = hjemme.filter((v) => auto.has(v.uid))
      .sort((a, b) => Number(tjek.has(b.uid)) - Number(tjek.has(a.uid)));
    if (!varer.length) return "";
    // Kun navnet: uden tilbudsmærke, antal og størrelse ("🏷️ 2 × Løg (750 g)" -> "Løg").
    const navn = (v) => esc(String(v.summary || "").replace(/\s*\(.*\)\s*$/, "").replace(/^[^\p{L}\d]+/u, "").replace(/^\d+\s*×\s*/, ""));
    return `<div class="regnermed"><div class="rm-top"><ha-icon icon="mdi:fridge-outline"></ha-icon>
      <span>Vi regner med, I har det her. <b>Tryk på det, I mangler</b>, så kommer det på listen.</span></div>
      <div class="rm-chips">${varer.map((v) => `<button class="rm-chip til ${tjek.has(v.uid) ? "rm-tjek" : ""}" data-h="husknap" data-liste="varer" data-uid="${esc(v.uid)}">${tjek.has(v.uid) ? `<ha-icon icon="mdi:alert-circle-outline"></ha-icon>` : ""}${navn(v)}${tjek.has(v.uid) ? `<small>Tjek</small>` : ""}</button>`).join("")}</div></div>`;
  }

  /** Hovedbutikkens varer først, så "Fra Netto" osv. for varer fra andre kæder. */
  _perButik(varer, linje) {
    const butik = (v) => (v.description || "").split(" · ")[1] || "";
    const andre = [...new Set(varer.map(butik).filter(Boolean))];
    return (
      varer.filter((v) => !butik(v)).map(linje).join("") +
      andre
        .map((b) => `<div class="gruppe"><ha-icon icon="mdi:storefront-outline"></ha-icon> Fra ${esc(b)}</div>${varer.filter((v) => butik(v) === b).map(linje).join("")}`)
        .join("")
    );
  }

  _mdBrug(md) {
    // Bruges den i dag eller i morgen: "Brug i dag". Senere (kun kød og fisk): "Frys samme dag".
    if (!md.brug) return "";
    const dage = Math.round((new Date(`${md.brug}T12:00`) - new Date(new Date().toDateString() + " 12:00")) / 86400000);
    if (dage > 1 && md.fryses) return `<span class="mdtag frys"><ha-icon icon="mdi:snowflake"></ha-icon>Frys samme dag – til ${esc(new Date(`${md.brug}T12:00`).toLocaleDateString("da-DK", { weekday: "long" }))}</span>`;
    const naar = dage <= 0 ? "i dag" : dage === 1 ? "i morgen" : new Date(`${md.brug}T12:00`).toLocaleDateString("da-DK", { weekday: "long" });
    return `<span class="mdtag"><ha-icon icon="mdi:silverware-fork-knife"></ha-icon>Bruges ${esc(naar)}</span>`;
  }

  _madspildButik(a) {
    // Madspild gælder kun én butik. Handler man et andet sted i dag, tjekkes den butik i stedet.
    const har = Object.keys(a.madspild || {}).length || (a.madspild_udsolgt || []).length || a.madspild_anden_butik;
    if (!a.kan_madspild || !har) return "";
    const b = this._mdButikker;
    const liste = b === "henter" || b === "skifter"
      ? `<div class="mdliste"><span class="hjaelp">${b === "henter" ? "Henter butikker …" : "Tjekker madspild i butikken …"}</span></div>`
      : Array.isArray(b)
        ? `<div class="mdliste">${b.length ? b.map((x) => `<button class="mdvalg ${x.valgt ? "valgt" : ""}" data-h="mdskift" data-id="${esc(x.id)}" data-navn="${esc(x.navn)}">
              <span>${esc(x.navn)}${x.egen ? " <small>(din butik)</small>" : ""}</span><small>${typeof x.km === "number" ? `${x.km.toFixed(1).replace(".", ",")} km` : ""}</small></button>`).join("")
            : `<span class="hjaelp">Kunne ikke hente butikkerne.</span>`}
            <span class="hjaelp">Varer, den butik ikke har, byttes til den almindelige vare og pris – og kommer tilbage, hvis de dukker op igen. Retterne er de samme.</span></div>`
        : "";
    return `<div class="mdbutik"><ha-icon icon="mdi:storefront-outline"></ha-icon><span>Madspild fra <b>${esc(a.madspild_butik || "")}</b></span>
        <button class="mdskiftknap" data-h="mdbutikker">${b ? "Luk" : "Handler et andet sted?"}</button></div>${liste}`;
  }

  _madspildInfo(a) {
    // Hvorfor der ingen madspild-varer er på listen, når reglen er slået til.
    if (!a.kan_madspild || !(a.regler || {}).madspild || Object.keys(a.madspild || {}).length) return "";
    const f = a.madspild_fundet;
    const tekst = f == null
      ? "Madspild bruges kun, når der handles i dag eller i morgen – lav en ny plan med handel i dag."
      : f === 0
        ? `Ingen nedsatte madvarer i ${esc(a.salling_butik || a.butik)} lige nu. Prøv igen om formiddagen, hvor der oftest er flest.`
        : `Der var ${f} nedsatte varer, men ingen passede til ugens retter.`;
    return `<div class="hjaelp"><ha-icon icon="mdi:clock-fast"></ha-icon> ${tekst}</div>`;
  }

  _vareLinje(v, liste) {
    const t = this._tilstand(v);
    const tilbud = v.summary.startsWith("🏷️");
    // "2 × REMA 1000 Hakket oksekød (400 g)" -> antal, navn og størrelse hver for sig, så navnet får plads.
    const [, antal, raa, str] = /^(?:(\d+) × )?(.*?)(?: \(([^()]*)\))?$/.exec(v.summary.replace(/^🏷️\s*/, ""));
    const navn = raa.replace(/^REMA 1000 /i, "");
    const pris = (v.description || "").split(" · ")[0].replace(".00", "").replace(/(\d)\.(\d)/, "$1,$2");
    // Varer fra en anden kæde (fx Netto) har butikken efter prisen: "12.00 kr · Netto".
    const butik = liste === "varer" ? (v.description || "").split(" · ")[1] : "";
    // Madspild: ekstra nedsat i dag og kan blive udsolgt. Reserven er den almindelige vare.
    const pa = (this._hass.states[this._valgt] || {}).attributes || {};
    const md = liste === "varer" ? (pa.madspild || {})[v.uid] : null;
    const byttet = liste === "varer" && (pa.madspild_udsolgt || []).includes(v.uid);
    const rest = liste === "varer" && (pa.madspild_rest || []).includes(v.uid);
    // Brugt flere dage, og hvad der er tilovers af pakken - fx "Man · Ons" og "Rest ca. 600 g".
    const bu = liste === "varer" ? (pa.brug || {})[v.uid] : null;
    const brugTekst = bu
      ? `${(bu.dage || []).length > 1 ? `<span class="mdtag graa"><ha-icon icon="mdi:calendar-multiple"></ha-icon>${esc(bu.dage.join(" · "))}</span>` : ""}${
          bu.rest ? `<span class="mdtag graa"><ha-icon icon="mdi:fridge-outline"></ha-icon>Rest ca. ${esc(bu.rest)}</span>` : ""}`
      : "";
    const mdTekst = rest
      ? `<span class="mdtag graa"><ha-icon icon="mdi:cart-plus"></ha-icon>Resten – almindelig pris</span>`
      : byttet
      ? `<span class="mdtag ud"><ha-icon icon="mdi:swap-horizontal"></ha-icon>Madspild udsolgt – almindelig pris</span>`
      : md
      ? md.udsolgt
        ? `<span class="mdtag ud"><ha-icon icon="mdi:close-circle-outline"></ha-icon>Udsolgt – køb den almindelige</span>`
        : `<span class="mdtag"><ha-icon icon="mdi:clock-fast"></ha-icon>Madspild${md.pct ? ` −${esc(md.pct)} %` : ""}</span><span class="mdtag graa">${esc(md.stk)} stk${md.tjekket ? ` kl. ${esc(md.tjekket)}` : ""}</span>${
          Number(antal || 1) > Number(md.stk) ? `<span class="mdtag ud"><ha-icon icon="mdi:alert-outline"></ha-icon>Kun ${esc(md.stk)} stk – køb resten almindelig</span>` : ""
        }${this._mdBrug(md)}`
      : "";
    // På ekstra-listen vises antallet i knapperne i stedet for i navnet.
    const meta = [antal && liste !== "ekstra" ? `<b>${esc(antal)} ×</b>` : "", str ? esc(str) : ""].filter(Boolean).join(" ")
      + (butik ? ` <span class="butiktag">${esc(butik)}</span>` : "");
    return `<div class="vare ${t}" data-h="vare" data-liste="${liste}" data-uid="${esc(v.uid)}" data-tilstand="${t}">
      <span class="tjek">${t === "kurv" ? '<ha-icon icon="mdi:check"></ha-icon>' : t === "hjemme" ? '<ha-icon icon="mdi:home"></ha-icon>' : ""}</span>
      <span class="vtekst"><span class="vnavn">${esc(navn)}</span>
        ${meta || tilbud || butik ? `<span class="vmeta">${meta}${tilbud && !md ? `<span class="tag">Tilbud</span>` : ""}</span>` : ""}
        ${mdTekst || brugTekst ? `<span class="vmeta mdmeta">${mdTekst}${brugTekst}</span>` : ""}</span>
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
    const butRul = this.shadowRoot.querySelector(".butikker")?.scrollLeft || 0;
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
    const nyeButikker = this.shadowRoot.querySelector(".butikker");
    if (nyeButikker) nyeButikker.scrollLeft = butRul;
  }
}

const CSS = `
  :host { --radius: 16px; }
  ha-card { overflow: hidden; container-type: inline-size; }
  ha-icon { --mdc-icon-size: 18px; flex: none; }
  button { font: inherit; color: inherit; }
  small { color: var(--secondary-text-color); }

  /* Butiksvælger */
  .butikker { display: flex; gap: 8px; padding: 12px 12px 0; overflow-x: auto; scrollbar-width: none;
    overscroll-behavior-x: contain; }
  .uge { overscroll-behavior-x: contain; }
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
  .udf-knap { display: inline-flex; align-items: center; gap: 6px; margin-top: 10px; padding: 8px 14px; border-radius: 18px;
    border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); font: inherit; cursor: pointer; }
  .udf-knap.venter { cursor: default; color: var(--secondary-text-color); }
  .udf-knap.venter ha-icon { animation: udfspin 1s linear infinite; }
  @keyframes udfspin { to { transform: rotate(360deg); } }
  .udf-mark { display: flex; align-items: center; gap: 6px; margin-top: 8px; font-size: 13px; font-weight: 700; color: var(--brand); }
  .udf-tips { margin-top: 10px; padding: 10px 12px; border-radius: 12px; background: var(--secondary-background-color); font-size: 14px; }
  .udf-tips ul { margin: 6px 0 0; padding-left: 18px; }
  .udf-fejl { margin-top: 6px; font-size: 13px; color: var(--error-color, #c62828); }
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
  .mdmeta { flex-wrap: wrap; gap: 4px; margin-top: 2px; }
  .mdbutik { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 8px 0; padding: 10px 12px; border-radius: 12px;
    background: rgba(245, 158, 11, 0.12); font-size: 14px; }
  .mdbutik ha-icon { --mdc-icon-size: 20px; color: #b45309; }
  .mdbutik > span { flex: 1; min-width: 140px; }
  .mdskiftknap { border: 0; background: none; color: #b45309; font: inherit; font-weight: 700; cursor: pointer; padding: 6px 4px; }
  .mdliste { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
  .mdvalg { display: flex; justify-content: space-between; align-items: center; gap: 8px; text-align: left; min-height: 44px; padding: 8px 12px;
    border-radius: 10px; border: 1px solid var(--divider-color, #ddd); background: var(--card-background-color, #fff); color: var(--primary-text-color); font: inherit; cursor: pointer; }
  .mdvalg.valgt { border: 2px solid #f59e0b; font-weight: 700; }
  .mdvalg small { color: var(--secondary-text-color); font-weight: 400; }
  .mdtag { display: inline-flex; align-items: center; gap: 3px; font-size: 11px; font-weight: 700; padding: 1px 6px; border-radius: 6px;
    background: rgba(245, 158, 11, 0.16); color: #b45309; }
  .mdtag ha-icon { --mdc-icon-size: 13px; }
  .mdtag { white-space: nowrap; }
  .mdtag.graa { background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .mdtag.ud { background: rgba(217, 45, 32, 0.14); color: #b42318; }
  .mdtag.frys { background: rgba(56, 152, 214, 0.15); color: #0b5f8a; }
  .kontakt:disabled { opacity: 0.4; cursor: default; }
  .butiktag { font-size: 11px; font-weight: 700; padding: 1px 6px; border-radius: 6px; background: var(--secondary-background-color);
    color: var(--primary-text-color); border: 1px solid var(--divider-color); }
  .gruppe ha-icon { --mdc-icon-size: 16px; vertical-align: -3px; }
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
  .regnermed { margin: 10px 0; padding: 12px; border-radius: 14px; background: var(--secondary-background-color); }
  .rm-top { display: flex; gap: 8px; align-items: flex-start; font-size: 13.5px; line-height: 1.4; }
  .rm-top ha-icon { --mdc-icon-size: 20px; color: var(--primary-color); flex: none; }
  .rm-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .rm-chip { display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--divider-color); border-radius: 16px;
    padding: 6px 11px; background: var(--card-background-color); color: var(--primary-text-color); font: inherit; font-size: 13px; cursor: pointer; }
  .rm-chip.rm-tjek { border-color: var(--warning-color, #f59e0b); }
  .rm-chip.rm-tjek ha-icon { --mdc-icon-size: 16px; color: var(--warning-color, #f59e0b); }
  .rm-chip small { font-size: 11px; font-weight: 700; color: var(--warning-color, #f59e0b); }
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
      ${a.handl_senest ? `<div class="info"><ha-icon icon="mdi:calendar-clock"></ha-icon>${a.handledag ? `Handles ${esc(this._dato(a.handledag))} · ` : ""}tilbuddene gælder til ${esc(this._dato(a.handl_senest))}</div>` : ""}
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
        ${this._dageValg(a)}
        ${this._handlerValg(a)}
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
          <span class="rtekst"><span class="rnavn">${a.forbi ? "Før planen" : a.fjernet ? esc(d.state || "Ingen aftensmad") : esc(d.state)}</span>
            ${a.forbi ? `<span class="rinfo">Planen blev lavet senere</span>` : a.fjernet ? `<span class="rinfo">Spiser ude</span>` : a.rester_fra ? `<span class="rinfo">Rester fra ${esc(a.rester_fra.toLowerCase())} · intet at købe</span>` : `<span class="rinfo">${esc(a.tid ?? "?")} min · ${kr(a.pris)}${a.gaester ? ` · <b class="gaest"><ha-icon icon="mdi:account-group"></ha-icon>${esc(a.personer)}</b>` : ""}${a.dobbelt ? ` · <b class="gaest">2 dage</b>` : ""}</span>`}</span>
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
      ${a.min_ret ? `<span class="minmaerke"><ha-icon icon="mdi:heart"></ha-icon>Min ret</span>` : ""}
      <h1>${esc(d.state)}</h1>
      ${a.kort ? `<p class="kort">${esc(a.kort)}</p>` : ""}
      <div class="fakta">
        <span><ha-icon icon="mdi:timer-outline"></ha-icon>${esc(a.tid ?? "?")} min</span>
        <span><ha-icon icon="mdi:cash"></ha-icon>${kr(a.pris)}</span>
        <span><ha-icon icon="mdi:account"></ha-icon>${esc(String(a.pr_person ?? "?").replace(".", ","))} kr/pers.</span>
        ${a.kcal ? `<span title="AI'ens skøn pr. voksen portion"><ha-icon icon="mdi:fire"></ha-icon>ca. ${esc(a.kcal)} kcal</span>` : ""}
        ${a.protein ? `<span title="AI'ens skøn pr. voksen portion"><ha-icon icon="mdi:arm-flex-outline"></ha-icon>ca. ${esc(a.protein)} g protein</span>` : ""}
      </div>
      ${a.sundhed ? `<div class="sundhed"><ha-icon icon="mdi:leaf"></ha-icon>${esc(a.sundhed)}</div>` : ""}
      ${this._dagPersoner(a, i + 1)}
      <div class="kasse"><div class="overskrift"><ha-icon icon="mdi:basket-outline"></ha-icon>Ingredienser
          <small>${esc(a.personer ?? this._personer())} personer${a.dobbelt ? " · 2 dage" : ""}</small></div>
        <ul class="ing">${(a.ingredienser || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      ${
        a.noter || /^https?:\/\//i.test(a.link || "")
          ? `<div class="kasse"><div class="overskrift"><ha-icon icon="mdi:heart-outline"></ha-icon>Jeres noter</div>
            ${a.noter ? `<p class="mnoter">${esc(a.noter)}</p>` : ""}
            ${/^https?:\/\//i.test(a.link || "") ? `<a class="mlink" href="${esc(a.link)}" target="_blank" rel="noopener noreferrer"><ha-icon icon="mdi:open-in-new"></ha-icon>Åbn jeres opskrift</a>` : ""}</div>`
          : ""
      }
      <div class="kasse"><div class="overskrift"><ha-icon icon="mdi:chef-hat"></ha-icon>Sådan gør du</div>
        ${this._trin(a, i + 1)}</div>
      <div class="knapper">
        ${this._knap("byt", "Byt ret", "mdi:swap-horizontal", "", i + 1)}
        ${this._knap("fjern", "Spiser ude", "mdi:close", "graa", i + 1)}
        ${this._resterKnap(a, i, dage)}
        ${a.min_ret || a.rester_fra ? "" : this._knap("gemmin", "Gem som min ret", "mdi:heart-plus-outline", "graa", i + 1)}
        ${this._hass.states[this._valgt]?.attributes.har_mail ? this._knap("dagmail", "Send på mail", "mdi:email-outline", "graa", i + 1) : ""}
      </div>
    </article>`;
  }

  /** Mine retter: familiens egne opskrifter. Fælles for alle butikker; hver kan slås til og fra. */
  _mineSide(a) {
    const r = a.regler || {};
    const mine = a.mine_retter || [];
    const hyp = r.mine_hyppighed || "nogle";
    this._mineData = this._mineData || {};
    const felt = (titel, f, id, v, pladsholder, raekker, max) =>
      `<label class="mfelt"><span>${titel}</span><textarea name="m_${f}_${esc(id)}" rows="${raekker}" maxlength="${max}"
        placeholder="${pladsholder}">${esc(v)}</textarea></label>`;
    const rk = mine
      .map((m, i) => {
        const nr = i + 1;
        const aaben = this._mineAaben === m.id;
        const d = this._mineData[m.id];
        const inp = (f) => this._inputs[`m_${f}_${m.id}`] ?? d?.[f] ?? "";
        const info = [m.aktiv ? "" : "Slået fra", m.har_opskrift ? "Egen opskrift" : "", m.dage === 2 ? "2 dage" : "", m.link ? "Link" : ""]
          .filter(Boolean)
          .join(" · ");
        return `<section class="rkort mret ${m.aktiv ? "" : "fra"}">
          <div class="mrad"><button class="mnavn" data-h="maaben" data-id="${esc(m.id)}"><b>${esc(m.navn)}</b><small>${info || "Tryk for at skrive opskriften"}</small></button>
            <button class="kontakt ${m.aktiv ? "til" : ""}" data-h="maktiv" data-id="${esc(m.id)}" role="switch" aria-checked="${m.aktiv}" aria-label="${esc(m.navn)} med i planen"><span></span></button></div>
          ${
            !aaben
              ? ""
              : !d
                ? `<div class="mdetaljer"><small class="mhjaelp">Henter opskriften …</small></div>`
                : `<div class="mdetaljer">
                <div class="rlinje"><span class="rnavn2"><b>Portioner</b><small>Opskriften er til</small></span>
                  <div class="stepper"><button data-h="mport" data-id="${esc(m.id)}" data-d="-1" aria-label="Færre">−</button><span>${esc(d.portioner || 4)} pers.</span>
                  <button data-h="mport" data-id="${esc(m.id)}" data-d="1" aria-label="Flere">+</button></div></div>
                ${felt("Ingredienser", "ingredienser", m.id, inp("ingredienser"), "Én pr. linje, fx&#10;500 g hakket oksekød&#10;1 dåse hakkede tomater", 6, 2000)}
                ${felt("Fremgangsmåde", "fremgangsmaade", m.id, inp("fremgangsmaade"), "Ét trin pr. linje – vises præcis som I skriver det", 7, 4000)}
                ${felt("Noter til AI'en", "noter", m.id, inp("noter"), "Valgfrit, fx ingen chili, eller server med ris", 2, 400)}
                <input name="m_link_${esc(m.id)}" type="url" inputmode="url" autocomplete="off" placeholder="Link til opskriften (valgfrit)" value="${esc(inp("link"))}">
                <div class="rlinje"><span class="rnavn2"><b>Rækker til 2 dage</b><small>Dagen efter bliver rester</small></span>
                  <button class="kontakt ${m.dage === 2 ? "til" : ""}" data-h="mdage" data-id="${esc(m.id)}" role="switch" aria-checked="${m.dage === 2}" aria-label="Rækker til 2 dage"><span></span></button></div>
                <small class="mhjaelp">Gemmes, når du trykker udenfor feltet. AI'en finder varerne i tilbuddene og regner mængderne om til jer.</small>
                <div class="knapper">${/^https?:\/\//i.test(m.link || "") ? `<a class="knap graa" href="${esc(m.link)}" target="_blank" rel="noopener noreferrer"><ha-icon icon="mdi:open-in-new"></ha-icon><span>Åbn link</span></a>` : ""}
                  ${this._knap("mslet", "Slet opskriften", "mdi:delete-outline", "graa", nr)}</div></div>`
          }
        </section>`;
      })
      .join("");
    const aktive = mine.filter((m) => m.aktiv).length;
    return `<div class="rintro"><ha-icon icon="mdi:information-outline"></ha-icon>Jeres egne opskrifter. Dem, der er slået til, tager AI'en med i ugeplanen, når tilbuddene passer. De gælder alle butikker.</div>
      <section class="rkort">
        <div class="rlinje bred"><span class="rikon lyseroed"><ha-icon icon="mdi:heart-outline"></ha-icon></span><span class="rnavn2"><b>Hvor tit</b><small>${{ aldrig: "AI'en bruger dem ikke", nogle: "Cirka 1 om ugen", ofte: "2–3 om ugen" }[hyp]}${mine.length ? ` · ${aktive} af ${mine.length} slået til` : ""}</small></span>
          <div class="handler">${[["aldrig", "Aldrig"], ["nogle", "Nogle gange"], ["ofte", "Ofte"]]
            .map(([v, t]) => `<button class="${hyp === v ? "valgt" : ""}" data-h="rvalg" data-felt="mine_hyppighed" data-v="${v}">${t}</button>`)
            .join("")}</div></div>
        <form class="behov-form" data-form="mny"><input name="m_navn" autocomplete="off" enterkeyhint="done" maxlength="60"
          placeholder="Ny opskrift, fx lasagne" value="${esc(this._inputs.m_navn || "")}"><button type="submit" class="plusknap" aria-label="Tilføj"><ha-icon icon="mdi:plus"></ha-icon></button></form>
      </section>
      ${rk || `<div class="mtom"><ha-icon icon="mdi:heart-plus-outline"></ha-icon>Ingen opskrifter endnu. Skriv et navn ovenfor, eller tryk "Gem som min ret" under en opskrift i planen.</div>`}`;
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
        <div class="rtitel"><span class="rikon groen"><ha-icon icon="mdi:scale-balance"></ha-icon></span><span><b>Mål pr. portion</b><small>Valgfrit – AI'ens tal er et skøn</small></span></div>
        <div class="makro">
          <label class="budget"><input name="r_kcal" type="number" inputmode="numeric" min="200" max="2000" step="50" placeholder="Kcal"
            value="${esc(this._inputs.r_kcal ?? r.kcal ?? "")}"><span>kcal</span></label>
          <label class="budget"><input name="r_protein" type="number" inputmode="numeric" min="5" max="150" step="5" placeholder="Protein"
            value="${esc(this._inputs.r_protein ?? r.protein ?? "")}"><span>g protein</span></label>
        </div>
      </section>
      <section class="rkort">
        <div class="rlinje bred"><span class="rikon"><ha-icon icon="mdi:silverware-variant"></ha-icon></span><span class="rnavn2"><b>Niveau</b><small>${{ hverdag: "Billigt og nemt", hygge: "Lidt festligere", gourmet: "Spændende retter" }[r.niveau || "hverdag"]}</small></span>
          <div class="handler">${[["hverdag", "Hverdag"], ["hygge", "Hygge"], ["gourmet", "Gourmet"]]
            .map(([v, t]) => `<button class="${(r.niveau || "hverdag") === v ? "valgt" : ""}" data-h="rvalg" data-felt="niveau" data-v="${v}">${t}</button>`)
            .join("")}</div></div>
        <div class="rlinje"><span class="rikon"><ha-icon icon="mdi:account-group-outline"></ha-icon></span><span class="rnavn2"><b>Husstand</b><small>Børnevenlige retter?</small></span>
          <div class="handler">${[["boernefamilie", "Børn"], ["voksne", "Voksne"]]
            .map(([v, t]) => `<button class="${(r.husstand || "boernefamilie") === v ? "valgt" : ""}" data-h="rvalg" data-felt="husstand" data-v="${v}">${t}</button>`)
            .join("")}</div></div>
        <div class="rlinje"><span class="rikon"><ha-icon icon="mdi:timer-outline"></ha-icon></span><span class="rnavn2"><b>Maks tid</b><small>På hverdage</small></span>${stepper("max_tid", " min")}</div>
        <div class="rlinje"><span class="rikon"><ha-icon icon="mdi:pot-steam-outline"></ha-icon></span><span class="rnavn2"><b>Maks tid weekend</b><small>Plads til gryderetter</small></span>${stepper("max_tid_weekend", " min")}</div>
        <div class="rlinje"><span class="rikon groen"><ha-icon icon="mdi:sprout"></ha-icon></span><span class="rnavn2"><b>Vegetarretter</b><small>Mindst pr. uge</small></span>${stepper("vegetar", "")}</div>
        <div class="rlinje"><span class="rikon blaa"><ha-icon icon="mdi:fish"></ha-icon></span><span class="rnavn2"><b>Fiskeretter</b><small>Mindst pr. uge</small></span>${stepper("fisk", "")}</div>
        <div class="rlinje"><span class="rikon groen"><ha-icon icon="mdi:leaf"></ha-icon></span><span class="rnavn2"><b>Økologi</b><small>Når prisforskellen er lille</small></span>
          <button class="kontakt ${r.oeko ? "til" : ""}" data-h="rtoggle" data-felt="oeko" role="switch" aria-checked="${r.oeko ? "true" : "false"}" aria-label="Økologi"><span></span></button></div>
        <div class="rlinje"><span class="rikon"><ha-icon icon="mdi:clock-fast"></ha-icon></span><span class="rnavn2"><b>Madspild</b><small>${
          a.kan_madspild
            ? "Ekstra nedsatte varer i de første 2 dage – kan blive udsolgt, så der er altid en almindelig reserve"
            : 'Kun Netto, føtex og Bilka. Kræver gratis Salling-nøgle – se <a href="https://github.com/Clahen86/ha-madplan/blob/main/docs/guide-salling.md" target="_blank" rel="noopener">guiden</a>'
        }</small></span>
          <button class="kontakt ${r.madspild ? "til" : ""}" data-h="rtoggle" data-felt="madspild" role="switch" aria-checked="${r.madspild ? "true" : "false"}" aria-label="Madspild" ${a.kan_madspild ? "" : "disabled"}><span></span></button></div>
      </section>
      ${liste("allergier", "mdi:alert-octagon-outline", "Allergier", "Må aldrig indgå. Madplan fanger de fleste varer, men tjek altid varedeklarationen ved alvorlig allergi.", "Fx gluten, laktose, nødder", "roed")}
      ${liste("undgaa", "mdi:thumb-down-outline", "Undgå", "Det vil I ikke have", "Fx svampe eller lever")}
      ${liste("koekkener", "mdi:earth", "Yndlingskøkkener", "Ugen varieres mellem dem", "Fx italiensk, asiatisk")}
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
      ${this._butikkerKort(a)}
      ${this._profilKort(a)}
      ${this._udseendeKort(a)}`;
  }

  /** Profiler (kun administratorer): fx en datter, der bor ude, med egne regler, retter og planer. */
  _profilKort(a) {
    if (!this._hass.user?.is_admin) return "";
    if (this._brugere === undefined) {
      this._brugere = [];
      this._hass
        .callWS({ type: "config/auth/list" })
        .then((l) => {
          this._brugere = l.filter((u) => !u.system_generated && u.is_active).map((u) => ({ id: u.id, navn: u.name }));
          this._tegn();
        })
        .catch(() => {});
    }
    const profiler = a.profiler || [{ id: "hoved", navn: "Hjem", brugere: [] }];
    const nu = a.profil || "hoved";
    const navn = (id) => this._brugere.find((u) => u.id === id)?.navn || "?";
    const andre = new Set(profiler.flatMap((p) => p.brugere || []));
    const kaeder = [[a.butik_noegle, a.butik], ...(a.kaeder || [])].filter(([k]) => k);
    const vaelg = (navnAttr) => `<select name="${navnAttr}">${kaeder.map(([k, n]) => `<option value="${esc(k)}">${esc(n)}</option>`).join("")}</select>`;
    return `<section class="rkort">
        <div class="rtitel"><span class="rikon"><ha-icon icon="mdi:account-group-outline"></ha-icon></span>
          <span><b>Profiler</b><small>Hver profil har egne regler, retter og planer. Man ser den profil, ens bruger hører til.</small></span></div>
        ${profiler
          .map((p) => {
            const hoved = p.id === "hoved";
            const hvem = hoved
              ? "Alle andre brugere"
              : (p.brugere || []).length ? (p.brugere || []).map(navn).join(", ") : "Ingen brugere endnu";
            return `<div class="profil"><div class="rlinje"><span class="rnavn2"><b>${esc(p.navn)}</b><small>${esc(hvem)}</small></span>
                ${p.id === nu ? `<span class="pnu">Vises nu</span>` : `<button class="rchip" data-h="profilvis" data-id="${esc(p.id)}">Vis</button>`}
                ${hoved ? "" : `<button class="ikonknap" data-h="profilslet" data-id="${esc(p.id)}" aria-label="Slet profil"><ha-icon icon="mdi:delete-outline"></ha-icon></button>`}</div>
              ${hoved ? "" : `<div class="chips">${this._brugere
                .map((u) => {
                  const her = (p.brugere || []).includes(u.id);
                  return `<button class="rchip ${her ? "valgt" : "fra"}" data-h="profilbruger" data-id="${esc(p.id)}" data-u="${esc(u.id)}" ${!her && andre.has(u.id) ? 'title="Flyttes fra sin anden profil"' : ""}>${esc(u.navn)}${her ? '<ha-icon icon="mdi:check"></ha-icon>' : ""}</button>`;
                })
                .join("")}</div>
              ${p.id === nu ? "" : `<div class="pbutik">${vaelg(`pb_${p.id}`)}<button class="rchip" data-h="profilbutik" data-id="${esc(p.id)}">+ Butik</button></div>`}`}</div>`;
          })
          .join("")}
        <form class="behov-form pform" data-form="nyprofil">
          <input name="p_navn" autocomplete="off" enterkeyhint="done" placeholder="Ny profil, fx Datter" value="${esc(this._inputs.p_navn || "")}">
          ${vaelg("p_butik")}
          <button type="submit" class="plusknap" aria-label="Opret profil"><ha-icon icon="mdi:plus"></ha-icon></button></form>
        <small class="phjaelp">Den nye profil får sin egen plan i den valgte butik med samme AI som jeres – men ikke jeres mail, indkøbsliste eller REMA-login (sæt dem under Indstillinger → Madplan → Konfigurer).</small>
      </section>`;
  }

  /** Andre kæder, man også handler i - kun for den valgte butik. */
  _butikkerKort(a) {
    const valgt = a.ekstra_butikker || [];
    const min = (a.regler || {}).min_varer_ekstra ?? 3;
    return `<section class="rkort">
        <div class="rtitel"><span class="rikon"><ha-icon icon="mdi:calendar-sync-outline"></ha-icon></span>
          <span><b>Automatisk plan</b><small>Ny plan hver lørdag – hver butik koster ét AI-kald</small></span></div>
        ${(a.auto_planer || [])
          .map(([id, navn, til]) => `<div class="rlinje"><span class="rnavn2"><b>${esc(navn)}</b><small>${til ? "Laver plan lørdag" : "Kun når du trykker"}</small></span>
            <button class="kontakt ${til ? "til" : ""}" data-h="autoplan" data-id="${esc(id)}" data-til="${til ? 1 : 0}" role="switch" aria-checked="${til}" aria-label="Automatisk plan ${esc(navn)}"><span></span></button></div>`)
          .join("")}
      </section>
      <section class="rkort">
        <div class="rtitel"><span class="rikon"><ha-icon icon="mdi:store-plus-outline"></ha-icon></span>
          <span><b>Handler også i</b><small>Op til 2 kæder ud over ${esc(a.butik)} – kun deres tilbud bruges</small></span></div>
        <div class="chips">${(a.kaeder || [])
          .map(([k, navn]) => `<button class="rchip ${valgt.includes(k) ? "valgt" : "fra"}" data-h="ekstrabutik" data-k="${esc(k)}">${esc(navn)}${valgt.includes(k) ? '<ha-icon icon="mdi:check"></ha-icon>' : ""}</button>`)
          .join("")}</div>
        ${
          valgt.length
            ? `<div class="rlinje"><span class="rnavn2"><b>Mindst varer pr. butik</b><small>${min === 1 ? "Ingen grænse" : `Færre end ${min} købes i ${esc(a.butik)}`}</small></span>
                <div class="stepper"><button data-h="rstep" data-felt="min_varer_ekstra" data-d="-1" aria-label="Færre">−</button>
                <span>${esc(min)}</span><button data-h="rstep" data-felt="min_varer_ekstra" data-d="1" aria-label="Flere">+</button></div></div>`
            : ""
        }
      </section>`;
  }

  /** Én ret ud fra køleskabet - helt adskilt fra ugeplanen og dens indkøbsliste. */
  _enRetSide(a, n) {
    const liste = a.en_ret || [];
    const status = a.en_ret_status || "";
    const arbejder = status.endsWith("…");
    const valgt = liste.find((r) => r.id === this._enValgt) || liste[0];
    const pers = this._enPers ?? Math.round(Number(n || a.personer || 4));
    const har = this._har || [];
    let html = `<section class="rkort">
      <div class="rtitel"><span class="rikon"><ha-icon icon="mdi:fridge-outline"></ha-icon></span>
        <span><b>Hvad har I i køleskabet?</b><small>Én ret til i dag – påvirker ikke ugeplanen</small></span></div>
      ${har.length ? `<div class="chips">${har.map((h, i) => `<button class="chip-kladde" data-h="harfjern" data-i="${i}">${esc(h)}<ha-icon icon="mdi:close"></ha-icon></button>`).join("")}</div>` : ""}
      <form class="behov-form" data-form="har"><input name="har" autocomplete="off" enterkeyhint="done" placeholder="Fx kylling, ris, peberfrugt"
        value="${esc(this._inputs.har || "")}"><button type="submit" class="plusknap" aria-label="Tilføj"><ha-icon icon="mdi:plus"></ha-icon></button></form>
      <input class="enoenske" name="oenske" autocomplete="off" enterkeyhint="done" placeholder="Ønske (valgfrit), fx noget asiatisk" value="${esc(this._inputs.oenske || "")}">
      <div class="styring">
        <div class="stepper"><button data-h="enpers" data-d="-1" aria-label="Færre">−</button>
          <span><ha-icon icon="mdi:account-group"></ha-icon>${esc(pers)}</span><button data-h="enpers" data-d="1" aria-label="Flere">+</button></div>
        <button class="knap stor" data-h="findret" ${arbejder ? "disabled" : ""}><ha-icon icon="${arbejder ? "mdi:timer-sand" : "mdi:star-four-points"}"></ha-icon>${arbejder ? "Finder …" : "Find en ret"}</button>
      </div>
      ${status && !arbejder ? `<div class="statuspille ${status.startsWith("✅") ? "ok" : "fejl"}"><ha-icon icon="mdi:information-outline"></ha-icon>${esc(status)}</div>` : ""}
    </section>`;
    if (!valgt) return html + `<div class="velkommen"><ha-icon icon="mdi:chef-hat"></ha-icon><h2>Ingen ret endnu</h2><p>Skriv hvad I har, og tryk "Find en ret".</p></div>`;
    html += `<article class="ret">
      ${valgt.billede ? `<div class="retbillede"><img src="${esc(valgt.billede)}" alt=""></div>` : ""}
      <h1>${esc(valgt.navn)}</h1>
      ${valgt.kort ? `<p class="kort">${esc(valgt.kort)}</p>` : ""}
      <div class="fakta"><span><ha-icon icon="mdi:timer-outline"></ha-icon>${esc(valgt.tid ?? "?")} min</span>
        <span><ha-icon icon="mdi:account-group"></ha-icon>${esc(valgt.personer)} pers.</span>
        <span><ha-icon icon="mdi:cart-outline"></ha-icon>${valgt.koeb.length ? `${valgt.koeb_ca ? "ca. " : ""}${kr(valgt.koeb_total)}` : "Intet at købe"}</span></div>
      ${valgt.har.length ? `<div class="harliste"><ha-icon icon="mdi:fridge-outline"></ha-icon><span>${valgt.har.map(esc).join(", ")}</span></div>` : ""}
      ${
        valgt.koeb.length
          ? `<div class="kasse"><div class="overskrift"><ha-icon icon="mdi:cart-outline"></ha-icon>Skal købes<small>${valgt.koeb_ca ? "ca. " : ""}${kr(valgt.koeb_total)}</small></div>
              ${valgt.koeb.map((v) => `<div class="koebrad"><span>${esc(v.tekst.replace(/^🏷️\s*/, ""))}${v.tilbud ? ` <span class="tag">Tilbud</span>` : ""}</span><b>${esc(v.pris)}</b></div>`).join("")}
              <div class="enknapper">${a.har_indkobsliste ? this._knap("enliste", "Til listen", "mdi:playlist-plus", "lille") : ""}
                ${a.har_mail ? this._knap("enmail", "Send på mail", "mdi:email-outline", "lille") : ""}</div></div>`
          : ""
      }
      <div class="kasse"><div class="overskrift"><ha-icon icon="mdi:basket-outline"></ha-icon>Ingredienser<small>${esc(valgt.personer)} personer</small></div>
        <ul class="ing">${valgt.ingredienser.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div class="kasse"><div class="overskrift"><ha-icon icon="mdi:chef-hat"></ha-icon>Sådan gør du</div>
        <ol class="trin">${valgt.trin.map((x) => `<li><span>${esc(x)}</span></li>`).join("")}</ol></div>
      <div class="knapper">${this._knap("enslet", "Slet retten", "mdi:delete-outline", "graa")}</div>
    </article>`;
    const andre = liste.filter((r) => r !== valgt);
    if (andre.length)
      html += `<div class="afsnit">Tidligere retter</div><div class="dagliste">${andre
        .map((r) => `<button class="dagrad" data-h="envaelg" data-id="${esc(r.id)}">
            <span class="datoblok"><small>${esc((r.lavet || "").slice(8, 10))}/${esc(String(Number((r.lavet || "").slice(5, 7))))}</small><ha-icon icon="mdi:fridge-outline"></ha-icon></span>
            <span class="rtekst"><span class="rnavn">${esc(r.navn)}</span><span class="rinfo">${esc(r.tid ?? "?")} min · ${r.koeb.length} at købe</span></span></button>`)
        .join("")}</div>`;
    return html;
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
    // Butikslinjen og fanerne beholder deres vandrette position, når siden tegnes igen.
    const sidelaens = [".bchips", ".topfaner"].map((v) => this.shadowRoot.querySelector(v)?.scrollLeft || 0);
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
      under = `${esc(a.salling_butik || a.butik)}${a.uge ? ` · uge ${esc(a.uge)}` : ""}${a.periode ? ` · ${esc(a.periode)}` : ""}`;
      const n = this._hass.states[a.personer_entitet]?.state;
      const dage = (a.dag_entiteter || []).map((e) => this._hass.states[e]);
      if (this._dagValgt == null) {
        const i = dage.findIndex((d) => d?.attributes.dato === idagIso());
        this._dagValgt = i >= 0 ? i : 0;
      }
      const harPlan = a.antal_retter > 0 || dage.some((d) => d && d.state !== "–");
      if (this._side === "mine") {
        krop = this._mineSide(a);
      } else if (!harPlan && this._side === "regler") {
        krop = this._reglerSide(a);
      } else if (!harPlan && this._side === "enret") {
        krop = this._enRetSide(a, n);
      } else if (!harPlan) {
        krop = `${this._overblik(s, n)}<div class="velkommen"><ha-icon icon="mdi:chef-hat"></ha-icon><h2>Ingen madplan endnu</h2>
          <p>Tryk "Ny madplan" for at få ugens retter ud fra tilbuddene i ${esc(a.butik)}.</p></div>`;
      } else if (this._side === "ret") {
        krop = this._retSide(dage);
      } else if (this._side === "indkob") {
        krop = this._indkob(s);
      } else if (this._side === "regler") {
        krop = this._reglerSide(a);
      } else if (this._side === "enret") {
        krop = this._enRetSide(a, n);
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
                )}${this._fane("enret", "Én ret", "mdi:fridge-outline")}${this._fane("mine", "Mine retter", "mdi:heart-outline")}${this._fane(
                  "regler",
                  "Regler",
                  "mdi:tune-variant",
                )}</nav>`
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
    [".bchips", ".topfaner"].forEach((v, i) => {
      const e = this.shadowRoot.querySelector(v);
      if (e) e.scrollLeft = sidelaens[i];
    });
    // Den valgte fane ruller frem, og kanterne toner ud, når der er flere faner at rulle hen til.
    const tf = this.shadowRoot.querySelector(".topfaner");
    const b = tf?.querySelector("button.aktiv");
    // Kun når man skifter fane - ellers ville rækken hoppe tilbage, mens man selv ruller i den.
    if (b && this._centreret !== this._side) {
      this._centreret = this._side;
      tf.scrollLeft = b.offsetLeft - (tf.clientWidth - b.offsetWidth) / 2;
    }
    if (tf) {
      const kanter = () => {
        tf.classList.toggle("mere-v", tf.scrollLeft > 2);
        tf.classList.toggle("mere-h", tf.scrollLeft + tf.clientWidth < tf.scrollWidth - 2);
      };
      kanter();
      tf.addEventListener("scroll", kanter, { passive: true });
    }
    if (fokus) this._fokuser(fokus);
  }
}

const PANEL_CSS = `
  :host { display: block; height: 100%; background: var(--primary-background-color); color: var(--primary-text-color); }
  .app { display: flex; flex-direction: column; height: 100%; container-type: inline-size; overflow-x: clip; }
  /* Butikslinjen og fanerne ruller selv sidelæns, uden at bevægelsen skubber hele siden. */


  /* Top med kædens farver, butiksvalg og faner */
  .hero { flex: none; color: var(--brand-tekst); padding: 0 12px 14px; border-radius: 0 0 28px 28px;
    background:
      radial-gradient(circle at 85% -20%, rgba(255,255,255,.28), transparent 45%),
      radial-gradient(circle at 0% 120%, rgba(0,0,0,.25), transparent 50%),
      linear-gradient(140deg, var(--brand), color-mix(in srgb, var(--brand) 62%, #000));
    box-shadow: 0 6px 20px color-mix(in srgb, var(--brand) 35%, transparent); z-index: 1; }
  /* Toppen og alt i den holder sig inden for skærmens bredde. */
  .hero { box-sizing: border-box; min-width: 0; max-width: 100%; display: block; height: auto; overflow: visible; }
  .hero > * { min-width: 0; max-width: 100%; box-sizing: border-box; }
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
  /* Butikkerne bryder over på flere linjer i stedet for at skulle rulles sidelæns (virker på alle telefoner). */
  .bchips { display: flex; flex-wrap: wrap; gap: 8px; padding: 6px 0 10px; }
  .bchips::-webkit-scrollbar { display: none; }
  .bchip { position: relative; display: flex; align-items: center; gap: 6px; flex: none; padding: 6px 12px 6px 6px;
    border-radius: 20px; border: none; cursor: pointer; background: rgba(255,255,255,.18); color: inherit; }
  .bchip img { width: 28px; height: 28px; border-radius: 50%; background: #fff; object-fit: contain; padding: 2px; box-sizing: border-box; }
  .bchip span { font-weight: 600; }
  .bchip small { opacity: .8; color: inherit; }
  .bchip.valgt { background: #fff; color: #1c1c1c; box-shadow: 0 2px 8px rgba(0,0,0,.2); }
  .bchip em { position: absolute; top: -8px; right: 4px; font-style: normal; font-size: 9px; font-weight: 800; letter-spacing: .5px;
    text-transform: uppercase; background: #2e7d32; color: #fff; border-radius: 6px; padding: 1px 5px; }
  /* Fanerne deler bredden, når der er plads; på telefonen ruller rækken selv sidelæns (kun den - ikke siden).
     Ingen touch-action her: det låste rulningen i HA-appen. */
  .topfaner { position: relative; display: flex; width: 100%; box-sizing: border-box; gap: 6px; padding: 4px; border-radius: 18px;
    background: rgba(0,0,0,.2); overflow-x: auto; overflow-y: hidden; overscroll-behavior-x: contain; scrollbar-width: none;
    -webkit-overflow-scrolling: touch; }
  .topfaner::-webkit-scrollbar { display: none; }
  .topfaner.mere-h { -webkit-mask-image: linear-gradient(to right, #000 82%, transparent); mask-image: linear-gradient(to right, #000 82%, transparent); }
  .topfaner.mere-v { -webkit-mask-image: linear-gradient(to left, #000 82%, transparent); mask-image: linear-gradient(to left, #000 82%, transparent); }
  .topfaner.mere-v.mere-h { -webkit-mask-image: linear-gradient(to right, transparent, #000 14%, #000 86%, transparent);
    mask-image: linear-gradient(to right, transparent, #000 14%, #000 86%, transparent); }
  .topfaner button { position: relative; flex: 1 0 auto; min-width: 84px; display: flex; align-items: center; justify-content: center; gap: 6px;
    padding: 10px 14px; border: none; border-radius: 14px; background: none; color: inherit; opacity: .85; white-space: nowrap;
    font-weight: 600; font-size: 14px; cursor: pointer; transition: background .2s; }
  .topfaner button.aktiv { background: #fff; color: #1c1c1c; opacity: 1; box-shadow: 0 2px 8px rgba(0,0,0,.18); }
  .topfaner ha-icon { --mdc-icon-size: 20px; }
  .badge { background: #e53935; color: #fff; font-size: 11px; font-weight: 800; border-radius: 10px; padding: 1px 6px; }

  .indhold { flex: 1; overflow-y: auto; overflow-x: clip; -webkit-overflow-scrolling: touch; }
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
  /* Mine retter */
  .mret { padding: 10px 10px 10px 14px; }
  .mrad { display: flex; align-items: center; gap: 6px; }
  .mnavn { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left;
    border: none; background: none; color: inherit; font: inherit; padding: 4px 0; cursor: pointer; }
  .mnavn b { font-size: 16px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .mnavn small { color: var(--secondary-text-color); font-size: 12.5px; }
  .mret .ikonknap { width: 36px; height: 36px; flex: none; text-decoration: none; }
  .mret.fra .mnavn b { opacity: .55; }
  .mfelt { display: flex; flex-direction: column; gap: 4px; }
  .mfelt span { font-size: 13px; font-weight: 700; }
  .mfelt textarea { width: 100%; box-sizing: border-box; padding: 10px 14px; border-radius: 16px; border: 1px solid var(--divider-color);
    font: inherit; font-size: 14px; resize: vertical; outline: none; background: var(--card-background-color); color: var(--primary-text-color); }
  .mfelt textarea:focus { border-color: var(--brand); }
  .mdetaljer .knapper { margin-top: 2px; }
  .mdetaljer a.knap { text-decoration: none; }
  .mdetaljer { display: flex; flex-direction: column; gap: 10px; margin-top: 8px; padding-top: 10px; border-top: 1px solid var(--divider-color); }
  .mdetaljer input { width: 100%; box-sizing: border-box; padding: 10px 14px; border-radius: 22px; border: 1px solid var(--divider-color);
    font: inherit; outline: none; background: var(--card-background-color); color: var(--primary-text-color); }
  .mdetaljer input:focus { border-color: var(--brand); }
  .mhjaelp { color: var(--secondary-text-color); font-size: 12px; }
  .mtom { display: flex; flex-direction: column; align-items: center; gap: 8px; text-align: center; padding: 24px 16px;
    color: var(--secondary-text-color); font-size: 14px; }
  .mtom ha-icon { --mdc-icon-size: 40px; opacity: .6; }
  .minmaerke { display: inline-flex; align-items: center; gap: 4px; margin-top: 14px; padding: 3px 10px; border-radius: 12px;
    font-size: 12px; font-weight: 700; background: #fce4ec; color: #ad1457; }
  .minmaerke ha-icon { --mdc-icon-size: 14px; }
  .minmaerke + h1 { margin-top: 6px; }
  .mnoter { margin: 4px 0 8px; white-space: pre-line; }
  .mlink { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; color: color-mix(in srgb, var(--brand) 70%, var(--primary-text-color)); }
  .mlink ha-icon { --mdc-icon-size: 18px; }
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
  /* Niveau: knapperne på egen linje, så teksten ikke bliver klemt på en telefon. */
  .rlinje.bred { flex-wrap: wrap; }
  .rlinje.bred .handler { flex-basis: 100%; display: flex; }
  .rlinje.bred .handler button { flex: 1; }
  .rnavn2 { flex: 1; }
  .profil { padding: 4px 0 8px; } .profil + .profil { border-top: 1px solid var(--divider-color); }
  .pnu { font-size: 12px; font-weight: 600; color: var(--primary-color); white-space: nowrap; }
  .pbutik { display: flex; gap: 8px; align-items: center; } .pbutik select { flex: 1; min-width: 0; }
  .pform { flex-wrap: wrap; } .pform input { flex: 1 1 100%; } .pform select { flex: 1; min-width: 0; }
  .phjaelp { display: block; color: var(--secondary-text-color); font-size: 12px; margin-top: 6px; line-height: 1.4; }
  .rlinje .stepper span { min-width: 54px; justify-content: center; }
  .rchip { display: inline-flex; align-items: center; gap: 4px; padding: 7px 9px 7px 13px; border-radius: 18px; border: none; cursor: pointer;
    font: inherit; font-size: 14px; font-weight: 600; background: color-mix(in srgb, var(--brand) 14%, transparent); color: var(--primary-text-color); }
  .rchip.roed { background: rgba(198,40,40,.12); }
  .rchip.lyseroed { background: rgba(216,27,96,.12); }
  .rchip ha-icon { --mdc-icon-size: 15px; opacity: .6; }
  .rchip.fra { background: var(--secondary-background-color); color: var(--secondary-text-color); font-weight: 500; }
  .rchip.valgt { background: var(--brand); color: var(--brand-tekst); }
  .rchip.valgt ha-icon { opacity: 1; }
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
  .makro { display: flex; flex-wrap: wrap; gap: 10px; }
  .makro .budget input { width: 110px; }
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
    .topfaner button { flex-direction: column; gap: 3px; min-width: 74px; padding: 8px 12px; font-size: 12.5px; }
    .bchips { gap: 6px; }
    .bchip { padding: 4px 10px 4px 4px; gap: 5px; }
    .bchip img { width: 24px; height: 24px; }
    .bchip span { font-size: 14px; }
    .bchip small { font-size: 12px; }
    .topfaner ha-icon { --mdc-icon-size: 20px; }
    .topfaner .badge { position: absolute; top: 3px; right: calc(50% - 24px); font-size: 10px; padding: 0 5px; }
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

  /* Én ret */
  .enoenske { width: 100%; box-sizing: border-box; margin: 2px 0 4px; padding: 10px 14px; border-radius: 22px; font: inherit;
    border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); outline: none; }
  .enoenske:focus { border-color: var(--brand); }
  .rkort .styring .knap.stor[disabled] { opacity: .6; }
  @container (max-width: 420px) { .rkort .styring .knap.stor { flex: 1; justify-content: center; } }
  .harliste { display: flex; gap: 8px; align-items: flex-start; margin-top: 12px; padding: 10px 12px; border-radius: 16px;
    background: rgba(46,125,50,.12); color: var(--primary-text-color); font-size: 14px; }
  .harliste ha-icon { color: #2e7d32; --mdc-icon-size: 18px; flex: none; }
  .koebrad { display: flex; justify-content: space-between; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--divider-color); font-size: 14px; }
  .koebrad b { white-space: nowrap; font-weight: 600; }
  .enknapper { display: flex; gap: 8px; margin-top: 10px; }
  .dagevalg { flex-basis: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; font-size: 13px; }
  .dagevalg > span { color: var(--secondary-text-color); }
  .dagevalg > div { display: flex; gap: 4px; }
  .dagevalg button { width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--divider-color); cursor: pointer; font: inherit;
    font-size: 12px; font-weight: 700; background: var(--card-background-color); color: var(--secondary-text-color); text-decoration: line-through; }
  .dagevalg button.til { background: var(--brand); border-color: var(--brand); color: var(--brand-tekst); text-decoration: none; }
  .handler { display: inline-flex; align-items: center; gap: 2px; padding: 3px; border-radius: 20px; background: var(--secondary-background-color);
    font-size: 13px; }
  .handler span { padding: 0 8px 0 6px; color: var(--secondary-text-color); }
  .handler button { border: none; border-radius: 16px; padding: 6px 10px; background: none; cursor: pointer; font: inherit;
    font-weight: 600; color: var(--primary-text-color); }
  .handler button.valgt { background: var(--brand); color: var(--brand-tekst); }
  .enknapper .knap { flex: 1; justify-content: center; }
  .datoblok ha-icon { --mdc-icon-size: 18px; }

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
