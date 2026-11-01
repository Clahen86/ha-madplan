/* Madplan-kort: ugens retter, opskrifter og indkøbsliste i ét kort. */

const DAGE = ["Søndag", "Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag"];

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

class MadplanCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._cfg = {
      sensor: "sensor.madplan",
      personer: "number.madplan_personer",
      varer: "todo.madplan_varer",
      titel: "Ugens madplan",
      vis_indkob: true,
      ...config,
    };
    this._aaben = this._aaben || {};
    this._bekraeft = null;
    this._varer = this._varer || [];
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (ev) => this._klik(ev));
    }
    this._sidst = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (this._cfg.vis_indkob && !this._unsub && hass.states[this._cfg.varer]) this._abonner();
    // Tegn kun igen, når madplanens egne enheder ændrer sig.
    const ids = [this._cfg.sensor, this._cfg.personer, ...DAGE.map((_, i) => `sensor.madplan_dag_${i + 1}`)];
    const noegle = ids.map((id) => hass.states[id]).filter(Boolean);
    if (this._sidst && noegle.length === this._sidst.length && noegle.every((s, i) => s === this._sidst[i])) return;
    this._sidst = noegle;
    this._tegn();
  }

  connectedCallback() {
    if (this._hass && this._cfg?.vis_indkob && !this._unsub) this._abonner();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((u) => u()).catch(() => {});
      this._unsub = null;
    }
  }

  getCardSize() {
    return 12;
  }

  getGridOptions() {
    return { columns: "full" };
  }

  _abonner() {
    this._unsub = this._hass.connection
      .subscribeMessage(
        (msg) => {
          this._varer = msg.items || [];
          this._tegn();
        },
        { type: "todo/item/subscribe", entity_id: this._cfg.varer },
      )
      .catch(() => {
        this._unsub = null;
      });
  }

  _kald(domain, service, data = {}) {
    return this._hass.callService(domain, service, data);
  }

  _klik(ev) {
    const el = ev.target.closest("[data-handling]");
    if (!el) return;
    const h = el.dataset.handling;
    const dag = Number(el.dataset.dag || 0);
    const kraeverBekraeft = ["ny", "byt", "fjern", "send"].includes(h);
    const id = `${h}-${dag}`;
    if (kraeverBekraeft && this._bekraeft !== id) {
      this._bekraeft = id;
      clearTimeout(this._bekraeftTimer);
      this._bekraeftTimer = setTimeout(() => {
        this._bekraeft = null;
        this._tegn();
      }, 4000);
      this._tegn();
      return;
    }
    this._bekraeft = null;
    const p = this._cfg.personer;
    const n = Number(this._hass.states[p]?.state || 0);
    switch (h) {
      case "ny":
        this._kald("madplan", "ny_plan");
        break;
      case "byt":
        this._kald("madplan", "byt_ret", { dag });
        break;
      case "fjern":
        this._kald("madplan", "fjern_ret", { dag });
        break;
      case "send":
        this._kald("madplan", "overfoer");
        break;
      case "plus":
        this._kald("number", "set_value", { entity_id: p, value: Math.min(n + 1, 12) });
        break;
      case "minus":
        this._kald("number", "set_value", { entity_id: p, value: Math.max(n - 1, 1) });
        break;
      case "aaben":
        this._aaben[el.dataset.noegle] = !this._aaben[el.dataset.noegle];
        break;
      case "vare": {
        const v = this._varer.find((x) => x.uid === el.dataset.uid);
        if (v)
          this._kald("todo", "update_item", {
            entity_id: this._cfg.varer,
            item: v.uid,
            status: v.status === "completed" ? "needs_action" : "completed",
          });
        break;
      }
    }
    this._tegn();
  }

  _knap(handling, tekst, ikon, ekstra = "", dag = 0) {
    const bekraeft = this._bekraeft === `${handling}-${dag}`;
    return `<button class="knap ${ekstra} ${bekraeft ? "bekraeft" : ""}" data-handling="${handling}" data-dag="${dag}">
      <ha-icon icon="${bekraeft ? "mdi:check" : ikon}"></ha-icon><span>${bekraeft ? "Tryk igen" : tekst}</span></button>`;
  }

  _dag(i) {
    const s = this._hass.states[`sensor.madplan_dag_${i + 1}`];
    if (!s) return "";
    const a = s.attributes;
    const idag = new Date();
    const iso = `${idag.getFullYear()}-${String(idag.getMonth() + 1).padStart(2, "0")}-${String(idag.getDate()).padStart(2, "0")}`;
    const iAften = a.dato === iso;
    const dag = i + 1;
    let indhold;
    if (a.fjernet) {
      indhold = `<div class="fjernet"><ha-icon icon="mdi:silverware-variant"></ha-icon><div>Ingen aftensmad<br><small>Tryk "Byt ret" for at få en ret igen.</small></div></div>`;
    } else if (s.state === "–") {
      indhold = `<div class="fjernet"><div>Ingen ret endnu</div></div>`;
    } else {
      const ing = `ing-${dag}`;
      const trin = `trin-${dag}`;
      indhold = `
        ${a.billede ? `<div class="billede"><img src="${esc(a.billede)}" loading="lazy" alt=""></div>` : ""}
        <div class="navn">${esc(s.state)}</div>
        ${a.kort ? `<div class="kort">${esc(a.kort)}</div>` : ""}
        <div class="fakta">
          <span><ha-icon icon="mdi:timer-outline"></ha-icon>${esc(a.tid ?? "?")} min</span>
          <span><ha-icon icon="mdi:cash"></ha-icon>${esc(a.pris ?? "?")} kr</span>
          <span><ha-icon icon="mdi:account"></ha-icon>${esc(a.pr_person ?? "?")} kr/pers.</span>
        </div>
        ${a.sundhed ? `<div class="sundhed"><ha-icon icon="mdi:leaf"></ha-icon>${esc(a.sundhed)}</div>` : ""}
        <div class="fold" data-handling="aaben" data-noegle="${ing}">
          <ha-icon icon="${this._aaben[ing] ? "mdi:chevron-down" : "mdi:chevron-right"}"></ha-icon>Ingredienser</div>
        ${this._aaben[ing] ? `<ul>${(a.ingredienser || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
        <div class="fold" data-handling="aaben" data-noegle="${trin}">
          <ha-icon icon="${this._aaben[trin] ? "mdi:chevron-down" : "mdi:chevron-right"}"></ha-icon>Sådan gør du</div>
        ${this._aaben[trin] ? `<ol>${(a.trin || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ol>` : ""}`;
    }
    return `<div class="dag ${iAften ? "i-aften" : ""} ${a.fjernet ? "er-fjernet" : ""}">
      <div class="dag-top"><span class="dagnavn">${DAGE[i]}</span>
        ${iAften ? `<span class="chip groen">I aften</span>` : ""}
        <span class="chip">${esc(a.dato_kort || "")}</span></div>
      ${indhold}
      <div class="knapper">${this._knap("byt", "Byt ret", "mdi:swap-horizontal", "", dag)}${
        a.fjernet ? "" : this._knap("fjern", "Fjern", "mdi:close-circle-outline", "graa", dag)
      }</div>
    </div>`;
  }

  _indkob() {
    if (!this._cfg.vis_indkob || !this._hass.states[this._cfg.varer]) return "";
    const s = this._hass.states[this._cfg.sensor];
    const varer = this._varer;
    const linje = (v) => {
      const hjemme = v.status === "completed";
      return `<div class="vare ${hjemme ? "hjemme" : ""}" data-handling="vare" data-uid="${esc(v.uid)}">
        <ha-icon icon="${hjemme ? "mdi:home-check" : "mdi:checkbox-blank-outline"}"></ha-icon>
        <span class="vnavn">${esc(v.summary)}</span><span class="vpris">${esc((v.description || "").replace(".00", ""))}</span></div>`;
    };
    const mangler = varer.filter((v) => v.status !== "completed");
    const hjemme = varer.filter((v) => v.status === "completed");
    return `<div class="indkob">
      <div class="sektion"><ha-icon icon="mdi:cart"></ha-icon>Indkøb
        <span class="chip groen">${esc(s?.state ?? 0)} kr</span></div>
      <div class="hjaelp">Tryk på det, I har hjemme, så trækkes det fra prisen. 🏷️ = på tilbud.</div>
      ${mangler.map(linje).join("")}
      ${hjemme.length ? `<div class="undertitel">Har hjemme (${hjemme.length})</div>${hjemme.map(linje).join("")}` : ""}
      <div class="knapper">${this._knap("send", "Send indkøbsliste", "mdi:cart-arrow-right", "groen")}</div>
    </div>`;
  }

  _tegn() {
    if (!this._hass || !this.shadowRoot) return;
    const s = this._hass.states[this._cfg.sensor];
    if (!s) {
      this.shadowRoot.innerHTML = `<ha-card><div class="tom">Madplan er ikke sat op (${esc(this._cfg.sensor)} findes ikke).</div></ha-card>`;
      return;
    }
    const a = s.attributes;
    const status = a.status && a.status !== "Klar" ? a.status : "";
    const arbejder = status.endsWith("…");
    const n = this._hass.states[this._cfg.personer]?.state;
    this.shadowRoot.innerHTML = `<style>${CSS}</style><ha-card>
      <div class="top">
        <div class="titel">${esc(this._cfg.titel)}</div>
        <div class="under">${a.uge ? `Uge ${esc(a.uge)} · ` : ""}${esc(a.periode || "")}</div>
        <div class="tal">
          <div><b>${esc(s.state)} kr</b><small>at købe</small></div>
          <div><b>${esc(a.pr_kuvert || 0)} kr</b><small>pr. kuvert</small></div>
          ${a.sparet ? `<div><b>${esc(a.sparet)} kr</b><small>har I hjemme</small></div>` : ""}
        </div>
        ${status ? `<div class="status ${arbejder ? "" : "fejl"}">${arbejder ? '<ha-circular-progress indeterminate size="small"></ha-circular-progress>' : ""}${esc(status)}</div>` : ""}
        <div class="knapper">
          ${
            n !== undefined
              ? `<div class="personer"><button class="rund" data-handling="minus">−</button>
                 <span><ha-icon icon="mdi:account-group"></ha-icon>${esc(Math.round(Number(n)))} personer</span>
                 <button class="rund" data-handling="plus">+</button></div>`
              : ""
          }
          ${this._knap("ny", "Ny madplan", "mdi:auto-fix", "lilla")}
        </div>
      </div>
      <div class="dage">${DAGE.map((_, i) => this._dag(i)).join("")}</div>
      ${this._indkob()}
    </ha-card>`;
  }
}

const CSS = `
  ha-card { padding: 16px; }
  .top .titel { font-size: 24px; font-weight: 500; }
  .under, .hjaelp, small { color: var(--secondary-text-color); }
  .tal { display: flex; gap: 20px; margin: 12px 0; flex-wrap: wrap; }
  .tal div { display: flex; flex-direction: column; }
  .tal b { font-size: 20px; }
  .status { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 8px;
    background: rgba(var(--rgb-primary-color, 3,169,244), .12); margin-bottom: 12px; }
  .status.fejl { background: rgba(var(--rgb-error-color, 219,68,55), .12); }
  .knapper { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 12px; }
  .knap { display: inline-flex; align-items: center; gap: 6px; border: none; border-radius: 18px; padding: 8px 14px;
    font: inherit; cursor: pointer; color: #fff; background: var(--primary-color); }
  .knap ha-icon { --mdc-icon-size: 18px; }
  .knap.lilla { background: #673ab7; } .knap.groen { background: #2e7d32; }
  .knap.graa { background: var(--secondary-background-color); color: var(--primary-text-color); }
  .knap.bekraeft { background: #ef6c00; color: #fff; }
  .personer { display: inline-flex; align-items: center; gap: 8px; }
  .personer span { display: inline-flex; align-items: center; gap: 4px; }
  .rund { width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--divider-color);
    background: none; color: var(--primary-text-color); font-size: 18px; cursor: pointer; }
  .dage { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; margin-top: 16px; }
  .dag { border: 1px solid var(--divider-color); border-radius: 12px; padding: 12px; display: flex; flex-direction: column; }
  .dag.i-aften { border: 2px solid #2e7d32; }
  .dag.er-fjernet { opacity: .7; }
  .dag-top { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
  .dagnavn { font-weight: 600; font-size: 16px; flex: 1; }
  .chip { font-size: 12px; padding: 2px 8px; border-radius: 10px; background: var(--secondary-background-color); }
  .chip.groen { background: #2e7d32; color: #fff; }
  .billede { text-align: center; margin-bottom: 6px; }
  .billede img { max-height: 120px; max-width: 100%; object-fit: contain; }
  .navn { font-size: 17px; font-weight: 500; }
  .kort { color: var(--secondary-text-color); margin: 4px 0; }
  .fakta { display: flex; gap: 12px; flex-wrap: wrap; margin: 6px 0; font-size: 14px; }
  .fakta span, .sundhed, .fold, .sektion { display: inline-flex; align-items: center; gap: 4px; }
  ha-icon { --mdc-icon-size: 18px; }
  .sundhed { font-style: italic; color: var(--secondary-text-color); font-size: 14px; }
  .fold { cursor: pointer; font-weight: 500; margin-top: 6px; user-select: none; }
  ul, ol { margin: 4px 0 4px; padding-left: 22px; }
  li { margin: 2px 0; }
  .dag .knapper { margin-top: auto; padding-top: 10px; }
  .fjernet { display: flex; gap: 10px; align-items: center; padding: 16px 0; }
  .indkob { margin-top: 20px; }
  .sektion { font-size: 20px; font-weight: 500; gap: 8px; margin-bottom: 4px; }
  .undertitel { margin: 12px 0 4px; color: var(--secondary-text-color); font-weight: 500; }
  .vare { display: flex; align-items: center; gap: 10px; padding: 8px 4px; border-bottom: 1px solid var(--divider-color);
    cursor: pointer; }
  .vare .vnavn { flex: 1; }
  .vare .vpris { color: var(--secondary-text-color); white-space: nowrap; }
  .vare.hjemme .vnavn { text-decoration: line-through; color: var(--secondary-text-color); }
  .tom { padding: 8px; }
`;

customElements.define("madplan-card", MadplanCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "madplan-card",
  name: "Madplan",
  description: "Ugens madplan med opskrifter og indkøbsliste.",
  preview: false,
});
