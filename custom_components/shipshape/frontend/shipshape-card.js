/* Shipshape dashboard card. Vanilla custom element, no build step. */
const SHIPSHAPE_VERSION = "0.1.1";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ZONE_ICONS = [
  "mdi:home", "mdi:silverware-fork-knife", "mdi:sofa", "mdi:bed-king", "mdi:bed", "mdi:teddy-bear",
  "mdi:shower", "mdi:bathtub", "mdi:toilet", "mdi:washing-machine", "mdi:door", "mdi:garage",
  "mdi:tree", "mdi:tools", "mdi:wrench", "mdi:dog", "mdi:cat", "mdi:car", "mdi:desk", "mdi:stairs",
];

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function meterColor(ratio) {
  const clamped = Math.max(0, Math.min(ratio, 1.25)) / 1.25;
  const hue = Math.round(130 - clamped * 130);
  return `hsl(${hue}, 68%, 44%)`;
}

function dueText(chore) {
  if (chore.state === "paused") return "Paused";
  const d = chore.days_left;
  if (chore.snoozed) return `Snoozed, back in ${plural(d, "day")}`;
  if (d < 0) return `${plural(-d, "day")} overdue`;
  if (d === 0) return "Due today";
  if (d === 1) return "Due tomorrow";
  if (d < 14) return `Due in ${d} days`;
  if (d < 70) return `Due in ${Math.round(d / 7)} weeks`;
  return `Due in ${Math.round(d / 30.4)} months`;
}

const STYLES = `
  :host { display: block; }
  ha-card { overflow: hidden; }
  .wrap { max-width: 860px; margin: 0 auto; padding: 16px; box-sizing: border-box; }
  .head { display: flex; align-items: center; gap: 12px; }
  .title { font-size: 1.4rem; font-weight: 500; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chips { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
  .chip { border-radius: 999px; padding: 4px 12px; font-size: 0.85rem; background: var(--secondary-background-color); color: var(--primary-text-color); border: 1px solid transparent; }
  .chip.bad { background: color-mix(in srgb, var(--error-color) 16%, transparent); }
  .chip.good { background: color-mix(in srgb, var(--success-color, #43a047) 18%, transparent); }
  button { font: inherit; color: inherit; cursor: pointer; }
  button.chip { cursor: pointer; }
  button.chip.on { border-color: var(--primary-color); color: var(--primary-color); font-weight: 500; }
  .icon-btn { background: none; border: none; width: 40px; height: 40px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; color: var(--secondary-text-color); flex: none; }
  .icon-btn:hover { background: var(--secondary-background-color); }
  .tabs { display: flex; gap: 4px; margin: 14px 0 6px; border-bottom: 1px solid var(--divider-color); }
  .tab { background: none; border: none; padding: 10px 14px; border-bottom: 2px solid transparent; color: var(--secondary-text-color); font-weight: 500; }
  .tab.on { color: var(--primary-color); border-bottom-color: var(--primary-color); }
  .banner { margin-top: 12px; padding: 10px 12px; border-radius: 10px; background: color-mix(in srgb, var(--warning-color, #ffa600) 20%, transparent); display: flex; align-items: center; gap: 10px; }
  .banner span { flex: 1; }
  .section { margin: 16px 0 6px; font-size: 0.8rem; letter-spacing: 0.04em; text-transform: uppercase; color: var(--secondary-text-color); display: flex; align-items: center; gap: 8px; }
  .section .count { font-weight: 600; }
  .row { position: relative; display: flex; align-items: center; gap: 12px; padding: 10px 8px 12px 12px; border-radius: 10px; cursor: pointer; }
  .row:hover { background: var(--secondary-background-color); }
  .row .text { flex: 1; min-width: 0; }
  .row .name { font-size: 1rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row .sub { font-size: 0.82rem; color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row .sub .late { color: var(--error-color); font-weight: 500; }
  .meter { position: absolute; left: 12px; right: 60px; bottom: 4px; height: 4px; border-radius: 2px; background: var(--divider-color); overflow: hidden; }
  .meter i { display: block; height: 100%; border-radius: 2px; }
  .dot { width: 12px; height: 12px; border-radius: 50%; flex: none; }
  .check { flex: none; width: 40px; height: 40px; border-radius: 50%; border: 2px solid var(--divider-color); background: none; display: inline-flex; align-items: center; justify-content: center; color: var(--secondary-text-color); }
  .check:hover { border-color: var(--success-color, #43a047); color: var(--success-color, #43a047); }
  .who { flex: none; font-size: 0.72rem; padding: 2px 8px; border-radius: 999px; background: var(--secondary-background-color); color: var(--secondary-text-color); max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .empty { text-align: center; padding: 28px 12px; color: var(--secondary-text-color); }
  .empty ha-icon { --mdc-icon-size: 40px; color: var(--success-color, #43a047); display: block; margin: 0 auto 8px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; margin-top: 12px; }
  .zone { text-align: left; border: 1px solid var(--divider-color); border-radius: 12px; padding: 12px; background: var(--card-background-color); display: flex; flex-direction: column; gap: 6px; min-height: 96px; }
  .zone:hover { border-color: var(--primary-color); }
  .zone .zhead { display: flex; align-items: center; gap: 8px; }
  .zone .zname { flex: 1; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .zone .badge { font-size: 0.75rem; border-radius: 999px; padding: 1px 8px; background: var(--error-color); color: #fff; }
  .zone .zsub { font-size: 0.8rem; color: var(--secondary-text-color); }
  .zone .bar, .pbar { height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; margin-top: auto; }
  .zone .bar i, .pbar i { display: block; height: 100%; }
  .zone.add { align-items: center; justify-content: center; border-style: dashed; color: var(--secondary-text-color); }
  .back { display: flex; align-items: center; gap: 6px; margin-top: 12px; }
  .back .zname { flex: 1; font-size: 1.15rem; font-weight: 500; }
  .link { background: none; border: none; color: var(--primary-color); padding: 8px 4px; font-weight: 500; }
  .person { display: flex; align-items: center; gap: 12px; padding: 10px 4px; }
  .avatar { width: 40px; height: 40px; border-radius: 50%; background: var(--primary-color); color: var(--text-primary-color, #fff); display: flex; align-items: center; justify-content: center; font-weight: 600; flex: none; background-size: cover; background-position: center; }
  .person .pmain { flex: 1; min-width: 0; }
  .person .pts { font-weight: 600; font-size: 1.1rem; }
  .act { display: flex; align-items: center; gap: 8px; padding: 6px 4px; font-size: 0.9rem; }
  .act .atext { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .act .awhen { color: var(--secondary-text-color); font-size: 0.8rem; flex: none; }
  .err { margin-top: 12px; padding: 10px 12px; border-radius: 10px; background: color-mix(in srgb, var(--error-color) 16%, transparent); }

  .scrim { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 8; display: flex; align-items: flex-end; justify-content: center; }
  @media (min-width: 600px) { .scrim { align-items: center; } }
  .dialog { background: var(--card-background-color); color: var(--primary-text-color); width: 100%; max-width: 480px; max-height: 92vh; overflow-y: auto; border-radius: 16px 16px 0 0; padding: 18px 18px 14px; box-sizing: border-box; box-shadow: 0 8px 30px rgba(0,0,0,0.35); }
  @media (min-width: 600px) { .dialog { border-radius: 16px; } }
  .dialog h2 { margin: 0 0 4px; font-size: 1.2rem; font-weight: 500; display: flex; align-items: center; gap: 8px; }
  .dialog h2 span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .dialog .dsub { color: var(--secondary-text-color); font-size: 0.9rem; margin-bottom: 10px; }
  .dialog .bigmeter { height: 8px; border-radius: 4px; background: var(--divider-color); overflow: hidden; margin: 8px 0 14px; }
  .dialog .bigmeter i { display: block; height: 100%; }
  label { display: block; font-size: 0.8rem; color: var(--secondary-text-color); margin: 12px 0 4px; }
  input[type=text], input[type=number], input[type=date], select, textarea { width: 100%; box-sizing: border-box; padding: 10px; border-radius: 8px; border: 1px solid var(--divider-color); background: var(--secondary-background-color); color: var(--primary-text-color); font: inherit; }
  textarea { min-height: 60px; resize: vertical; }
  .two { display: flex; gap: 8px; }
  .two > * { flex: 1; min-width: 0; }
  .opts { display: flex; flex-wrap: wrap; gap: 6px; }
  .opt { border: 1px solid var(--divider-color); border-radius: 999px; padding: 6px 12px; background: none; font-size: 0.9rem; }
  .opt.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .checkline { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 0.95rem; color: var(--primary-text-color); }
  .checkline input { width: 18px; height: 18px; }
  .btns { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
  .btn { border: 1px solid var(--divider-color); background: none; border-radius: 10px; padding: 10px 14px; font-weight: 500; }
  .btn.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn.danger { color: var(--error-color); }
  .btn.grow { flex: 1; }
  .spacer { flex: 1; }
  details { margin-top: 14px; }
  summary { cursor: pointer; color: var(--secondary-text-color); font-size: 0.9rem; }
  .hint { font-size: 0.8rem; color: var(--secondary-text-color); margin-top: 4px; }
  .derr { color: var(--error-color); margin-top: 10px; font-size: 0.9rem; }
  .toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 9; background: var(--primary-text-color); color: var(--card-background-color); border-radius: 10px; padding: 10px 8px 10px 16px; display: flex; align-items: center; gap: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.3); max-width: 92vw; }
  .toast span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .toast button { background: none; border: none; color: var(--primary-color); font-weight: 600; padding: 6px 10px; filter: brightness(1.4); }
`;

class ShipshapeCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._snap = null;
    this._error = null;
    this._tab = "todo";
    this._zone = null;
    this._filter = "all";
    this._showSoon = false;
    this._dialog = null;
    this._toast = null;
    this._library = null;
    this._unsub = null;
    this._subscribing = false;
    this.shadowRoot.innerHTML = `<style>${STYLES}</style><ha-card><div class="wrap" id="main"></div></ha-card><div id="dialog"></div><div id="toast"></div>`;
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
  }

  static getStubConfig() {
    return { title: "Chores" };
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "title", selector: { text: {} } },
        {
          name: "default_tab",
          selector: { select: { options: [
            { value: "todo", label: "To-do" },
            { value: "rooms", label: "Rooms" },
            { value: "scores", label: "Scores" },
          ] } },
        },
        { name: "zone", selector: { text: {} } },
        { name: "person", selector: { entity: { domain: "person" } } },
      ],
      computeLabel: (schema) =>
        ({ title: "Title", default_tab: "Tab to open on", zone: "Only show this zone (name)", person: "Only show this person's chores" }[schema.name]),
    };
  }

  setConfig(config) {
    this._config = { title: "Chores", ...config };
    this._tab = this._config.default_tab || "todo";
    if (this._config.person) this._filter = this._config.person;
    this._render();
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first || !this._unsub) this._subscribe();
  }

  connectedCallback() {
    this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
    clearTimeout(this._toastTimer);
  }

  async _subscribe() {
    if (this._unsub || this._subscribing || !this._hass || !this.isConnected) return;
    this._subscribing = true;
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (snap) => {
          this._snap = snap;
          this._error = null;
          this._render();
        },
        { type: "shipshape/subscribe" }
      );
    } catch (err) {
      this._error = (err && err.message) || "Shipshape is not available";
      this._render();
    } finally {
      this._subscribing = false;
    }
    if (!this.isConnected && this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  async _ws(type, payload = {}) {
    return this._hass.callWS({ type, ...payload });
  }

  // ---------------------------------------------------------------- data
  _chore(id) {
    return (this._snap?.chores || []).find((c) => c.id === id);
  }

  _zoneById(id) {
    return (this._snap?.zones || []).find((z) => z.id === id);
  }

  _personName(id) {
    const p = (this._snap?.people || []).find((x) => x.id === id);
    return p ? p.name : id ? id.split(".").pop() : "";
  }

  _visible(chore) {
    if (this._fixedZone() && chore.zone_id !== this._fixedZone().id) return false;
    if (this._filter === "all") return true;
    return !chore.responsible.length || chore.responsible.includes(this._filter);
  }

  _fixedZone() {
    const name = (this._config.zone || "").trim().toLowerCase();
    if (!name) return null;
    return (this._snap?.zones || []).find((z) => z.name.toLowerCase() === name) || null;
  }

  // -------------------------------------------------------------- render
  _render() {
    const main = this.shadowRoot.getElementById("main");
    if (!main) return;
    if (this._error) {
      main.innerHTML = `<div class="head"><div class="title">${esc(this._config.title)}</div></div><div class="err">${esc(this._error)}</div>`;
      return;
    }
    if (!this._snap) {
      main.innerHTML = `<div class="head"><div class="title">${esc(this._config.title)}</div></div><div class="empty">Loading…</div>`;
      return;
    }
    const s = this._snap;
    const fixed = this._fixedZone();
    let body = "";
    if (fixed) body = this._renderZone(fixed, false);
    else if (this._tab === "rooms") body = this._zone && this._zoneById(this._zone) ? this._renderZone(this._zoneById(this._zone), true) : this._renderRooms();
    else if (this._tab === "scores") body = this._renderScores();
    else body = this._renderTodo();

    const vac = s.vacation && s.vacation.active;
    main.innerHTML = `
      <div class="head">
        <div class="title">${esc(this._config.title)}</div>
        <button class="icon-btn" data-action="new-chore" title="Add chore" aria-label="Add chore"><ha-icon icon="mdi:plus"></ha-icon></button>
        <button class="icon-btn" data-action="menu" title="More" aria-label="More"><ha-icon icon="mdi:dots-vertical"></ha-icon></button>
      </div>
      <div class="chips">
        <span class="chip ${s.summary.due ? "bad" : "good"}">${s.summary.due ? `${s.summary.due} due` : "Nothing due"}</span>
        ${s.summary.overdue ? `<span class="chip bad">${s.summary.overdue} overdue</span>` : ""}
        <span class="chip">${s.summary.on_track}% on track</span>
      </div>
      ${vac ? `<div class="banner"><ha-icon icon="mdi:beach"></ha-icon><span>Vacation mode is on. Every chore is frozen.</span><button class="link" data-action="vacation-off">Resume</button></div>` : ""}
      ${fixed ? "" : `<div class="tabs">
        ${[["todo", "To-do"], ["rooms", "Rooms"], ["scores", "Scores"]].map(([k, l]) => `<button class="tab ${this._tab === k ? "on" : ""}" data-action="tab" data-tab="${k}">${l}</button>`).join("")}
      </div>`}
      ${body}`;
  }

  _renderFilter() {
    const people = this._snap.people || [];
    if (people.length < 2 || this._config.person) return "";
    const chip = (id, label) => `<button class="chip ${this._filter === id ? "on" : ""}" data-action="filter" data-filter="${esc(id)}">${esc(label)}</button>`;
    return `<div class="chips">${chip("all", "Everyone")}${people.map((p) => chip(p.id, p.name)).join("")}</div>`;
  }

  _renderRow(c, showZone = true) {
    const pct = Math.max(3, Math.min(100, Math.round(c.ratio * 100)));
    const late = c.state === "overdue" || c.state === "due";
    const bits = [];
    if (showZone) bits.push(esc(c.zone));
    bits.push(late ? `<span class="late">${esc(dueText(c))}</span>` : esc(dueText(c)));
    bits.push(esc(c.schedule_label));
    const who = c.responsible.length ? `<span class="who">${esc(c.responsible.map((p) => this._personName(p)).join(", "))}</span>` : "";
    return `
      <div class="row" data-action="open" data-id="${esc(c.id)}">
        <div class="text">
          <div class="name">${esc(c.name)}</div>
          <div class="sub">${bits.join(" · ")}</div>
        </div>
        ${who}
        <button class="check" data-action="complete" data-id="${esc(c.id)}" title="Mark done" aria-label="Mark ${esc(c.name)} done"><ha-icon icon="mdi:check"></ha-icon></button>
        <div class="meter"><i style="width:${pct}%;background:${c.state === "paused" ? "var(--disabled-text-color, #999)" : meterColor(c.ratio)}"></i></div>
      </div>`;
  }

  _renderTodo() {
    const chores = this._snap.chores.filter((c) => this._visible(c));
    const overdue = chores.filter((c) => c.state === "overdue");
    const due = chores.filter((c) => c.state === "due");
    const soon = chores.filter((c) => c.state === "soon").sort((a, b) => a.days_left - b.days_left);
    let html = this._renderFilter();
    if (!this._snap.chores.length) {
      return `${html}<div class="empty"><ha-icon icon="mdi:broom"></ha-icon>No chores yet.<br><button class="link" data-action="new-chore">Add your first chore</button></div>`;
    }
    if (!overdue.length && !due.length) {
      html += `<div class="empty"><ha-icon icon="mdi:check-decagram"></ha-icon>All caught up.</div>`;
    }
    if (overdue.length) html += `<div class="section">Overdue <span class="count">${overdue.length}</span></div>${overdue.map((c) => this._renderRow(c)).join("")}`;
    if (due.length) html += `<div class="section">Due <span class="count">${due.length}</span></div>${due.map((c) => this._renderRow(c)).join("")}`;
    if (soon.length) {
      const shown = this._showSoon ? soon : soon.slice(0, 5);
      html += `<div class="section">Coming up <span class="count">${soon.length}</span></div>${shown.map((c) => this._renderRow(c)).join("")}`;
      if (soon.length > 5) html += `<button class="link" data-action="toggle-soon">${this._showSoon ? "Show fewer" : `Show all ${soon.length}`}</button>`;
    }
    return html;
  }

  _renderRooms() {
    const tiles = this._snap.zones.map((z) => {
      const color = meterColor((100 - z.on_track) / 100 * 1.25);
      return `
        <button class="zone" data-action="zone" data-id="${esc(z.id)}">
          <div class="zhead"><ha-icon icon="${esc(z.icon || "mdi:home")}"></ha-icon><span class="zname">${esc(z.name)}</span>${z.due ? `<span class="badge">${z.due}</span>` : ""}</div>
          <div class="zsub">${z.total ? `${plural(z.total, "chore")}${z.due ? `, ${z.due} due` : ", all on track"}` : "No chores yet"}</div>
          <div class="bar"><i style="width:${z.total ? z.on_track : 0}%;background:${color}"></i></div>
        </button>`;
    });
    tiles.push(`<button class="zone add" data-action="new-zone"><ha-icon icon="mdi:plus"></ha-icon><span>Add zone</span></button>`);
    return `<div class="grid">${tiles.join("")}</div>`;
  }

  _renderZone(zone, withBack) {
    const chores = this._snap.chores.filter((c) => c.zone_id === zone.id && (this._filter === "all" || !c.responsible.length || c.responsible.includes(this._filter)));
    const head = `
      <div class="back">
        ${withBack ? `<button class="icon-btn" data-action="rooms" title="Back" aria-label="Back to rooms"><ha-icon icon="mdi:arrow-left"></ha-icon></button>` : ""}
        <ha-icon icon="${esc(zone.icon || "mdi:home")}"></ha-icon>
        <span class="zname">${esc(zone.name)}</span>
        <button class="icon-btn" data-action="edit-zone" data-id="${esc(zone.id)}" title="Edit zone" aria-label="Edit zone"><ha-icon icon="mdi:pencil"></ha-icon></button>
      </div>`;
    const list = chores.length
      ? chores.map((c) => this._renderRow(c, false)).join("")
      : `<div class="empty">No chores in ${esc(zone.name)} yet.</div>`;
    return `${head}${list}<button class="link" data-action="new-chore" data-zone="${esc(zone.id)}">+ Add chore to ${esc(zone.name)}</button>`;
  }

  _renderScores() {
    const people = [...(this._snap.people || [])].sort((a, b) => b.points_7d - a.points_7d);
    const top = Math.max(1, ...people.map((p) => p.points_7d));
    const rows = people.map((p) => {
      const initial = (p.name || "?").trim().charAt(0).toUpperCase();
      const pic = p.picture ? ` style="background-image:url('${esc(p.picture)}')"` : "";
      return `
        <div class="person">
          <div class="avatar"${pic}>${p.picture ? "" : esc(initial)}</div>
          <div class="pmain">
            <div>${esc(p.name)}</div>
            <div class="sub" style="font-size:0.82rem;color:var(--secondary-text-color)">${plural(p.done_7d, "chore")} this week · ${p.points_30d} points in 30 days · ${p.due} due now</div>
            <div class="pbar"><i style="width:${Math.round((p.points_7d / top) * 100)}%;background:var(--primary-color)"></i></div>
          </div>
          <div class="pts">${p.points_7d}</div>
        </div>`;
    });
    const recent = (this._snap.recent || []).map((h) => `
        <div class="act">
          <ha-icon icon="mdi:check-circle-outline"></ha-icon>
          <span class="atext">${esc(h.zone)}: ${esc(h.chore)}${h.by_name ? ` · ${esc(h.by_name)}` : ""}</span>
          <span class="awhen">${esc(this._ago(h.at))}</span>
          <button class="link" data-action="undo" data-id="${esc(h.id)}">Undo</button>
        </div>`);
    return `
      <div class="section">Points, last 7 days</div>
      ${rows.join("") || `<div class="empty">No people set up.</div>`}
      <div class="section">Recently done</div>
      ${recent.join("") || `<div class="empty">Nothing completed yet.</div>`}`;
  }

  _ago(iso) {
    const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins} min ago`;
    if (mins < 1440) return `${Math.round(mins / 60)} h ago`;
    return `${Math.round(mins / 1440)} d ago`;
  }

  // ------------------------------------------------------------- dialogs
  _openDialog(dialog) {
    this._dialog = dialog;
    this._renderDialog();
  }

  _closeDialog() {
    this._dialog = null;
    this._renderDialog();
  }

  _renderDialog() {
    const host = this.shadowRoot.getElementById("dialog");
    const d = this._dialog;
    if (!d) {
      host.innerHTML = "";
      return;
    }
    let inner = "";
    if (d.type === "chore") inner = this._dialogChore(d);
    else if (d.type === "zone") inner = this._dialogZone(d);
    else if (d.type === "menu") inner = this._dialogMenu();
    else if (d.type === "confirm") inner = this._dialogConfirm(d);
    host.innerHTML = `<div class="scrim" data-action="scrim"><div class="dialog" role="dialog" aria-modal="true">${inner}${d.error ? `<div class="derr">${esc(d.error)}</div>` : ""}</div></div>`;
  }

  _dialogMenu() {
    const vac = this._snap?.vacation?.active;
    return `
      <h2><span>Shipshape</span><button class="icon-btn" data-action="close" aria-label="Close"><ha-icon icon="mdi:close"></ha-icon></button></h2>
      <div class="btns" style="flex-direction:column">
        <button class="btn" data-action="new-chore">Add a chore</button>
        <button class="btn" data-action="new-zone">Add a zone</button>
        <button class="btn" data-action="${vac ? "vacation-off" : "vacation-on"}">${vac ? "Turn vacation mode off" : "Turn vacation mode on"}</button>
      </div>
      <div class="hint" style="margin-top:12px">Vacation mode freezes every chore so nothing piles up while you are away. Reminders, calendar and Skylight settings are under Settings → Devices &amp; services → Shipshape → Configure.</div>
      <div class="hint">Shipshape ${SHIPSHAPE_VERSION}</div>`;
  }

  _dialogConfirm(d) {
    return `
      <h2><span>${esc(d.title)}</span></h2>
      <div class="dsub">${esc(d.text)}</div>
      <div class="btns"><span class="spacer"></span><button class="btn" data-action="close">Cancel</button><button class="btn danger" data-action="confirm-yes">${esc(d.yes || "Delete")}</button></div>`;
  }

  _dialogZone(d) {
    const z = d.draft;
    return `
      <h2><span>${z.id ? "Edit zone" : "New zone"}</span><button class="icon-btn" data-action="close" aria-label="Close"><ha-icon icon="mdi:close"></ha-icon></button></h2>
      <label for="z-name">Name</label>
      <input type="text" id="z-name" value="${esc(z.name)}" maxlength="60" placeholder="e.g. Guest Room">
      <label>Icon</label>
      <div class="opts">${ZONE_ICONS.map((i) => `<button class="opt ${z.icon === i ? "on" : ""}" data-action="zone-icon" data-icon="${i}" aria-label="${i.slice(4)}"><ha-icon icon="${i}"></ha-icon></button>`).join("")}</div>
      <label for="z-icon">Or any icon name</label>
      <input type="text" id="z-icon" value="${esc(z.icon)}" placeholder="mdi:home">
      <div class="btns">
        ${z.id ? `<button class="btn danger" data-action="delete-zone">Delete zone</button>` : ""}
        <span class="spacer"></span>
        <button class="btn" data-action="close">Cancel</button>
        <button class="btn primary" data-action="save-zone">Save</button>
      </div>`;
  }

  _dialogChore(d) {
    const c = d.draft;
    const existing = d.id ? this._chore(d.id) : null;
    const people = this._snap.people || [];
    const isMonths = c.schedule.kind === "months";
    const zones = this._snap.zones;
    let top = "";
    if (existing) {
      const pct = Math.max(3, Math.min(100, Math.round(existing.ratio * 100)));
      const doneBy = people.length > 1
        ? people.map((p) => `<button class="btn primary grow" data-action="complete-as" data-person="${esc(p.id)}">Done by ${esc(p.name)}</button>`).join("")
        : `<button class="btn primary grow" data-action="complete-as" data-person="">Mark done</button>`;
      top = `
        <div class="dsub">${esc(existing.zone)} · ${esc(dueText(existing))}${existing.last_done ? ` · last done ${esc(this._ago(existing.last_done))}${existing.last_done_by ? ` by ${esc(this._personName(existing.last_done_by))}` : ""}` : " · never done"}</div>
        <div class="bigmeter"><i style="width:${pct}%;background:${meterColor(existing.ratio)}"></i></div>
        <div class="btns" style="margin-top:0">${doneBy}</div>
        <div class="btns">
          <button class="btn grow" data-action="snooze" data-days="1">Snooze 1 day</button>
          <button class="btn grow" data-action="snooze" data-days="3">3 days</button>
          <button class="btn grow" data-action="snooze" data-days="7">1 week</button>
        </div>
        <details ${d.editing ? "open" : ""}><summary>Edit chore</summary>`;
    }
    const lib = !existing && d.suggestions && d.suggestions.length
      ? `<label>Suggestions</label><div class="opts">${d.suggestions.slice(0, 14).map((sug, i) => `<button class="opt" data-action="suggest" data-index="${i}">${esc(sug.name)}</button>`).join("")}</div>`
      : "";
    const form = `
      ${lib}
      <label for="c-name">Name</label>
      <input type="text" id="c-name" value="${esc(c.name)}" maxlength="120" placeholder="e.g. Wipe counters">
      <label for="c-zone">Zone</label>
      <select id="c-zone">${zones.map((z) => `<option value="${esc(z.id)}" ${z.id === c.zone_id ? "selected" : ""}>${esc(z.name)}</option>`).join("")}</select>
      <label>Repeat</label>
      <div class="opts">
        <button class="opt ${isMonths ? "" : "on"}" data-action="kind" data-kind="interval">Every…</button>
        <button class="opt ${isMonths ? "on" : ""}" data-action="kind" data-kind="months">In fixed months</button>
      </div>
      ${isMonths
        ? `<div class="opts" style="margin-top:8px">${MONTHS.map((m, i) => `<button class="opt ${c.schedule.months.includes(i + 1) ? "on" : ""}" data-action="month" data-month="${i + 1}">${m}</button>`).join("")}</div>`
        : `<div class="two" style="margin-top:8px">
            <input type="number" id="c-every" min="1" max="3650" value="${esc(c.schedule.every)}" aria-label="Every">
            <select id="c-unit" aria-label="Unit">${["days", "weeks", "months"].map((u) => `<option value="${u}" ${c.schedule.unit === u ? "selected" : ""}>${u}</option>`).join("")}</select>
          </div>`}
      ${people.length ? `<label>Who does it (none selected means anyone)</label>
      <div class="opts">${people.map((p) => `<button class="opt ${c.assignees.includes(p.id) ? "on" : ""}" data-action="assignee" data-person="${esc(p.id)}">${esc(p.name)}</button>`).join("")}</div>
      ${c.assignees.length > 1 ? `<label class="checkline"><input type="checkbox" id="c-rotate" ${c.rotate ? "checked" : ""}> Take turns instead of sharing</label>` : ""}` : ""}
      <label>Effort (points earned)</label>
      <div class="opts">${[1, 2, 3].map((n) => `<button class="opt ${c.effort === n ? "on" : ""}" data-action="effort" data-effort="${n}">${["Quick", "Medium", "Big"][n - 1]} · ${n}</button>`).join("")}</div>
      ${existing ? `<label for="c-last">Last done</label><input type="date" id="c-last" value="${esc((c.last_done || "").slice(0, 10))}" max="${new Date().toISOString().slice(0, 10)}">
      <label class="checkline"><input type="checkbox" id="c-paused" ${c.paused ? "checked" : ""}> Paused</label>`
        : `<label for="c-cond">How is it right now?</label>
      <select id="c-cond"><option value="0">Just done</option><option value="0.5" selected>About halfway</option><option value="0.9">Nearly due</option><option value="due">Due now</option></select>`}
      <label for="c-notes">Notes</label>
      <textarea id="c-notes" maxlength="500">${esc(c.notes)}</textarea>
      <details><summary>Automatic trigger</summary>
        <div class="hint">Let a device update this chore. Example: entity vacuum.robot, state docked, to mark vacuuming done when the robot returns.</div>
        <label for="c-tent">Entity</label>
        <input type="text" id="c-tent" value="${esc(c.trigger?.entity_id || "")}" placeholder="vacuum.robot">
        <div class="two">
          <div><label for="c-tfrom">From state (optional)</label><input type="text" id="c-tfrom" value="${esc(c.trigger?.from || "")}"></div>
          <div><label for="c-tto">To state</label><input type="text" id="c-tto" value="${esc(c.trigger?.to || "")}"></div>
        </div>
        <label for="c-tact">Then</label>
        <select id="c-tact"><option value="complete" ${c.trigger?.action !== "make_due" ? "selected" : ""}>Mark the chore done</option><option value="make_due" ${c.trigger?.action === "make_due" ? "selected" : ""}>Make the chore due</option></select>
      </details>
      <div class="btns">
        ${existing ? `<button class="btn danger" data-action="delete-chore">Delete</button>` : ""}
        <span class="spacer"></span>
        <button class="btn" data-action="close">Cancel</button>
        <button class="btn primary" data-action="save-chore">${existing ? "Save" : "Add chore"}</button>
      </div>`;
    return `
      <h2><span>${existing ? esc(existing.name) : "New chore"}</span><button class="icon-btn" data-action="close" aria-label="Close"><ha-icon icon="mdi:close"></ha-icon></button></h2>
      ${top}${form}${existing ? "</details>" : ""}`;
  }

  /** Copy what is typed in the open chore form back into the draft. */
  _readChoreForm() {
    const d = this._dialog;
    if (!d || d.type !== "chore") return;
    const $ = (id) => this.shadowRoot.getElementById(id);
    const c = d.draft;
    if ($("c-name")) c.name = $("c-name").value;
    if ($("c-zone")) c.zone_id = $("c-zone").value;
    if ($("c-every")) c.schedule.every = parseInt($("c-every").value, 10) || 1;
    if ($("c-unit")) c.schedule.unit = $("c-unit").value;
    if ($("c-rotate")) c.rotate = $("c-rotate").checked;
    if ($("c-last")) c.last_done = $("c-last").value;
    if ($("c-paused")) c.paused = $("c-paused").checked;
    if ($("c-cond")) c.condition = $("c-cond").value;
    if ($("c-notes")) c.notes = $("c-notes").value;
    if ($("c-tent")) {
      const entity = $("c-tent").value.trim();
      c.trigger = entity ? { entity_id: entity, from: $("c-tfrom").value.trim(), to: $("c-tto").value.trim(), action: $("c-tact").value } : null;
    }
    const details = this.shadowRoot.querySelector(".dialog > details");
    if (details) d.editing = details.open;
  }

  _readZoneForm() {
    const d = this._dialog;
    if (!d || d.type !== "zone") return;
    const name = this.shadowRoot.getElementById("z-name");
    const icon = this.shadowRoot.getElementById("z-icon");
    if (name) d.draft.name = name.value;
    if (icon && icon.value.trim()) d.draft.icon = icon.value.trim();
  }

  async _newChore(zoneId) {
    const zones = this._snap?.zones || [];
    if (!zones.length) {
      this._openDialog({ type: "zone", draft: { name: "", icon: "mdi:home" } });
      return;
    }
    const zone = zoneId || (this._fixedZone() && this._fixedZone().id) || (this._tab === "rooms" && this._zone) || zones[0].id;
    const dialog = {
      type: "chore",
      id: null,
      draft: { name: "", zone_id: zone, schedule: { kind: "interval", every: 1, unit: "weeks", months: [] }, assignees: [], rotate: false, effort: 1, notes: "", trigger: null, condition: "0.5" },
      suggestions: [],
    };
    this._openDialog(dialog);
    try {
      if (!this._library) this._library = await this._ws("shipshape/library");
      if (this._dialog === dialog) {
        dialog.suggestions = this._suggestionsFor(zone);
        this._readChoreForm();
        this._renderDialog();
      }
    } catch (err) {
      /* suggestions are optional */
    }
  }

  _suggestionsFor(zoneId) {
    if (!this._library) return [];
    const zone = this._zoneById(zoneId);
    if (!zone) return [];
    const have = new Set(this._snap.chores.filter((c) => c.zone_id === zoneId).map((c) => c.name.toLowerCase()));
    const name = zone.name.toLowerCase();
    const libZones = this._library.zones || [];
    const match = libZones.find((z) => z.name.toLowerCase() === name)
      || libZones.find((z) => name.includes(z.name.toLowerCase().split(" ")[0]))
      || (name.includes("bath") ? libZones.find((z) => z.name === "Bathroom") : null)
      || (name.includes("room") ? libZones.find((z) => z.name === "Bedroom") : null);
    return (match ? match.chores : []).filter((c) => !have.has(c.name.toLowerCase()));
  }

  _editChore(id) {
    const c = this._chore(id);
    if (!c) return;
    this._openDialog({
      type: "chore",
      id,
      editing: false,
      draft: {
        name: c.name,
        zone_id: c.zone_id,
        schedule: { kind: c.schedule.kind, every: c.schedule.every || 1, unit: c.schedule.unit || "weeks", months: [...(c.schedule.months || [])] },
        assignees: [...(c.assignees || [])],
        rotate: !!c.rotate,
        effort: c.effort || 1,
        paused: !!c.paused,
        last_done: c.last_done || "",
        notes: c.notes || "",
        trigger: c.trigger ? { ...c.trigger } : null,
      },
    });
  }

  // -------------------------------------------------------------- events
  _onChange(ev) {
    if (ev.target && ev.target.id === "c-zone" && this._dialog && this._dialog.type === "chore" && !this._dialog.id) {
      this._readChoreForm();
      this._dialog.suggestions = this._suggestionsFor(this._dialog.draft.zone_id);
      this._renderDialog();
    }
  }

  async _onClick(ev) {
    const el = ev.composedPath().find((n) => n instanceof HTMLElement && n.dataset && n.dataset.action);
    if (!el) return;
    const action = el.dataset.action;
    if (action === "scrim") {
      if (ev.composedPath()[0] === el) this._closeDialog();
      return;
    }
    ev.stopPropagation();
    try {
      await this._act(action, el.dataset);
    } catch (err) {
      const message = (err && err.message) || String(err);
      if (this._dialog) {
        this._dialog.error = message;
        this._renderDialog();
      } else {
        this._showToast(message);
      }
    }
  }

  async _act(action, data) {
    const d = this._dialog;
    switch (action) {
      case "tab":
        this._tab = data.tab;
        this._zone = null;
        return this._render();
      case "filter":
        this._filter = data.filter;
        return this._render();
      case "toggle-soon":
        this._showSoon = !this._showSoon;
        return this._render();
      case "zone":
        this._tab = "rooms";
        this._zone = data.id;
        return this._render();
      case "rooms":
        this._zone = null;
        return this._render();
      case "menu":
        return this._openDialog({ type: "menu" });
      case "close":
        return this._closeDialog();
      case "open":
        return this._editChore(data.id);
      case "complete":
        return this._complete(data.id, null);
      case "complete-as": {
        const id = d.id;
        this._closeDialog();
        return this._complete(id, data.person || null);
      }
      case "snooze": {
        const id = d.id;
        await this._ws("shipshape/chore/snooze", { chore_id: id, days: parseInt(data.days, 10) });
        this._closeDialog();
        return this._showToast(`Snoozed for ${plural(parseInt(data.days, 10), "day")}`);
      }
      case "undo":
        await this._ws("shipshape/undo", { history_id: data.id || null });
        return this._showToast("Undone");
      case "vacation-on":
      case "vacation-off":
        await this._ws("shipshape/vacation", { active: action === "vacation-on" });
        return this._closeDialog();
      case "new-chore":
        return this._newChore(data.zone);
      case "new-zone":
        return this._openDialog({ type: "zone", draft: { name: "", icon: "mdi:home" } });
      case "edit-zone": {
        const z = this._zoneById(data.id);
        return z ? this._openDialog({ type: "zone", draft: { id: z.id, name: z.name, icon: z.icon || "mdi:home" } }) : null;
      }
      case "zone-icon":
        this._readZoneForm();
        d.draft.icon = data.icon;
        return this._renderDialog();
      case "save-zone": {
        this._readZoneForm();
        const res = await this._ws("shipshape/zone/save", { zone: d.draft });
        this._closeDialog();
        this._tab = "rooms";
        this._zone = res.id;
        return this._render();
      }
      case "delete-zone": {
        const z = this._zoneById(d.draft.id);
        return this._openDialog({ type: "confirm", title: `Delete ${z ? z.name : "zone"}?`, text: `This also deletes its ${plural(z ? z.total : 0, "chore")}. This cannot be undone.`, run: async () => { await this._ws("shipshape/zone/delete", { zone_id: d.draft.id }); this._zone = null; } });
      }
      case "kind":
        this._readChoreForm();
        d.draft.schedule.kind = data.kind;
        return this._renderDialog();
      case "month": {
        this._readChoreForm();
        const m = parseInt(data.month, 10);
        const months = d.draft.schedule.months;
        d.draft.schedule.months = months.includes(m) ? months.filter((x) => x !== m) : [...months, m].sort((a, b) => a - b);
        return this._renderDialog();
      }
      case "assignee": {
        this._readChoreForm();
        const list = d.draft.assignees;
        d.draft.assignees = list.includes(data.person) ? list.filter((x) => x !== data.person) : [...list, data.person];
        return this._renderDialog();
      }
      case "effort":
        this._readChoreForm();
        d.draft.effort = parseInt(data.effort, 10);
        return this._renderDialog();
      case "suggest": {
        this._readChoreForm();
        const sug = d.suggestions[parseInt(data.index, 10)];
        if (!sug) return null;
        d.draft.name = sug.name;
        d.draft.effort = sug.effort || 1;
        d.draft.schedule = sug.months
          ? { kind: "months", every: 1, unit: "weeks", months: [...sug.months] }
          : { kind: "interval", every: sug.every, unit: sug.unit, months: [] };
        return this._renderDialog();
      }
      case "save-chore":
        return this._saveChore();
      case "delete-chore": {
        const id = d.id;
        const c = this._chore(id);
        return this._openDialog({ type: "confirm", title: `Delete ${c ? c.name : "chore"}?`, text: "Its history stays in the scores. This cannot be undone.", run: async () => { await this._ws("shipshape/chore/delete", { chore_id: id }); } });
      }
      case "confirm-yes": {
        const run = d.run;
        await run();
        this._closeDialog();
        return this._render();
      }
      default:
        return null;
    }
  }

  async _saveChore() {
    this._readChoreForm();
    const d = this._dialog;
    const c = d.draft;
    const schedule = c.schedule.kind === "months" ? { kind: "months", months: c.schedule.months } : { kind: "interval", every: c.schedule.every, unit: c.schedule.unit };
    if (schedule.kind === "months" && !schedule.months.length) throw new Error("Pick at least one month");
    const payload = {
      name: c.name,
      zone_id: c.zone_id,
      schedule,
      assignees: c.assignees,
      rotate: c.assignees.length > 1 && !!c.rotate,
      effort: c.effort,
      notes: c.notes,
      trigger: c.trigger,
    };
    if (d.id) {
      payload.id = d.id;
      payload.paused = !!c.paused;
      const before = this._chore(d.id);
      const beforeDay = before && before.last_done ? before.last_done.slice(0, 10) : "";
      if ((c.last_done || "").slice(0, 10) !== beforeDay) payload.last_done = c.last_done || null;
    } else if (c.condition === "due") {
      payload.last_done = null;
    } else {
      payload.condition = parseFloat(c.condition || "0.5");
    }
    await this._ws("shipshape/chore/save", { chore: payload });
    this._closeDialog();
  }

  async _complete(id, person) {
    const c = this._chore(id);
    const res = await this._ws("shipshape/chore/complete", { chore_id: id, by: person });
    this._showToast(`Done: ${c ? c.name : "chore"}`, res.history_id);
  }

  _showToast(text, undoId) {
    const host = this.shadowRoot.getElementById("toast");
    clearTimeout(this._toastTimer);
    host.innerHTML = `<div class="toast" role="status"><span>${esc(text)}</span>${undoId ? `<button data-action="undo" data-id="${esc(undoId)}">Undo</button>` : ""}</div>`;
    this._toastTimer = setTimeout(() => { host.innerHTML = ""; }, undoId ? 7000 : 3500);
  }
}

if (!customElements.get("shipshape-card")) {
  customElements.define("shipshape-card", ShipshapeCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "shipshape-card",
    name: "Shipshape",
    description: "Condition-based household chores: to-do list, rooms and scores.",
    preview: false,
    documentationURL: "https://github.com/WileCyot/ha-shipshape",
  });
  console.info(`%c SHIPSHAPE %c ${SHIPSHAPE_VERSION} `, "background:#1976d2;color:#fff;border-radius:3px 0 0 3px", "background:#444;color:#fff;border-radius:0 3px 3px 0");
}
