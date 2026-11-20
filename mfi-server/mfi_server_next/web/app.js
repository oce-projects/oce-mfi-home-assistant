"use strict";

// Behaviour of the mFi Server web page (new server): translations, tabs, login, live updates and the views.
// Hand-written, no libraries. Every address is relative. The DOM is built with createElement and textContent only.

const LANG_KEY = "mfi_next_lang";
const VIEW_IDS = ["view-devices", "view-ports", "view-measures", "view-rules", "view-events", "view-users", "view-maps", "view-system"];
const INTERVALS = ["hour", "day", "week", "month"];
const INTERVAL_KEYS = { hour: "interval_hour", day: "interval_day", week: "interval_week", month: "interval_month" };
const STATE_KEYS = { connected: "state_connected", lost: "state_lost", unknown: "state_unknown" };
const STATES = ["connected", "lost", "unknown"];
const DEVICE_ACTIONS = [
  { name: "adopt", labelKey: "action_adopt", className: "button button--primary" },
  { name: "locate", labelKey: "action_locate", className: "button" },
  { name: "reboot", labelKey: "action_reboot", className: "button button--danger" },
  { name: "forget", labelKey: "action_forget", className: "button button--danger" },
];
// Keys of the port values sent by the server (active power, voltage, current, power factor, energy sum).
const METRICS = [
  { key: "active_pwr", label: "metric_power", unit: "W", digits: 1 },
  { key: "v_rms", label: "metric_voltage", unit: "V", digits: 1 },
  { key: "i_rms", label: "metric_current", unit: "A", digits: 2 },
  { key: "pf", label: "metric_pf", unit: "", digits: 2 },
  { key: "energy_sum", label: "metric_energy", unit: "Wh", digits: 0 },
];
const VIEW_LOADERS = {
  "view-measures": loadMeasures,
  "view-rules": loadRules,
  "view-events": loadEventsAndAlarms,
  "view-maps": loadMaps,
};
const COMET_RETRY_MS = 3000;
const DAY_MS = 86400000;
const BAR_COUNT = 12;
const CHART_BASE = 180;
const CHART_PLOT = 160;
const CHART_SLOT = 50;
const PIE_RADIUS = 15.9155;
const CURRENCY_PATTERN = /^[A-Z]{3}$/;

const strings = {};
let lang = "en";
let cursor = 0;
let cometGeneration = 0;
let loggedIn = false;
let versionText = "";
let loginMessageKey = "";
let riskyEnabled = false;
let interval = "day";
let measures = null;
let rules = [];
let events = [];
let alarms = [];
let maps = [];
let filterFrom = "";
let filterTo = "";
const devices = new Map();

// ---------------------------------------------------------------- helpers

function $(id) {
  return document.getElementById(id);
}

function isObject(value) {
  return typeof value === "object" && value !== null;
}

function arrayOf(value) {
  return Array.isArray(value) ? value.filter(isObject) : [];
}

function listOf(body, key) {
  return isObject(body) ? arrayOf(body[key]) : [];
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// The SVG namespace is read from an svg element of the page, so no address is written in this file.
function svgNamespace() {
  const node = document.querySelector("svg");
  return node ? node.namespaceURI : null;
}

function svgEl(ns, tag, attributes) {
  const node = document.createElementNS(ns, tag);
  for (const [key, value] of Object.entries(attributes || {})) {
    node.setAttribute(key, String(value));
  }
  return node;
}

function reportError(err) {
  console.error(err);
}

function setHidden(id, hidden) {
  const node = $(id);
  if (node) node.hidden = hidden;
}

function inputValue(id) {
  const node = $(id);
  return node ? node.value : "";
}

function clearInput(id) {
  const node = $(id);
  if (node) node.value = "";
}

function emptyState(key) {
  return el("p", "empty", t(key));
}

function postJson(path, body) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function getJson(path) {
  const response = await fetch(path);
  if (response.status === 401) {
    showLogin();
    return null;
  }
  if (!response.ok) throw new Error(path + " failed: " + response.status);
  return response.json();
}

// ---------------------------------------------------------------- i18n

function t(key, params) {
  const table = strings[lang] || {};
  let text = Object.prototype.hasOwnProperty.call(table, key) ? table[key] : key;
  if (params) {
    text = text.replace(/\{([a-z0-9_]+)\}/g, (match, name) =>
      Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
    );
  }
  return text;
}

async function loadStrings() {
  const [en, it] = await Promise.all([fetch("i18n/en.json"), fetch("i18n/it.json")]);
  if (!en.ok || !it.ok) throw new Error("translations not loaded: " + en.status + " " + it.status);
  strings.en = await en.json();
  strings.it = await it.json();
}

function detectLanguage() {
  const saved = localStorage.getItem(LANG_KEY);
  if (saved === "en" || saved === "it") return saved;
  return String(navigator.language || "").toLowerCase().startsWith("it") ? "it" : "en";
}

function applyTranslations() {
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
  document.title = t("app_title");
  const select = $("lang");
  if (select) select.value = lang;
}

function setLang(code) {
  lang = code;
  localStorage.setItem(LANG_KEY, code);
  document.documentElement.lang = code;
  applyTranslations();
  renderAll();
}

function formatTime(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return t("never");
  return new Intl.DateTimeFormat(lang, { dateStyle: "short", timeStyle: "medium" }).format(new Date(ms));
}

function formatNumber(value, digits) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return new Intl.NumberFormat(lang, { maximumFractionDigits: digits }).format(number);
}

// ---------------------------------------------------------------- tabs

function currentView() {
  const id = location.hash.slice(1);
  return VIEW_IDS.includes(id) ? id : "view-devices";
}

// One view is shown at a time, and no view while logged out. The tab of the active view gets aria-current.
function showView() {
  const active = currentView();
  for (const id of VIEW_IDS) {
    setHidden(id, !loggedIn || id !== active);
  }
  for (const link of document.querySelectorAll(".tab")) {
    if (link.getAttribute("href") === "#" + active) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  }
  const loader = VIEW_LOADERS[active];
  if (loggedIn && loader) loader().catch(reportError);
}

// ---------------------------------------------------------------- login

function setLoginMessage(key) {
  loginMessageKey = key;
  const node = $("login-message");
  if (!node) return;
  node.textContent = key ? t(key) : "";
  node.className = key ? "message message--error" : "message";
}

function showLogin() {
  loggedIn = false;
  setHidden("login", false);
  showView();
}

function showApp() {
  loggedIn = true;
  setHidden("login", true);
  showView();
}

async function login() {
  const response = await postJson("api/v1/login", {
    username: inputValue("username"),
    password: inputValue("password"),
  });
  if (response.status === 200) {
    clearInput("username");
    clearInput("password");
    setLoginMessage("");
    cursor = 0;
    showApp();
    startComet();
    return;
  }
  if (response.status === 401) {
    setLoginMessage("login_failed");
    return;
  }
  if (response.status === 429) {
    setLoginMessage("login_too_many");
    return;
  }
  throw new Error("login failed: " + response.status);
}

async function logout() {
  const response = await fetch("api/v1/logout", { method: "POST" });
  if (response.status !== 204 && response.status !== 401) {
    throw new Error("logout failed: " + response.status);
  }
  cometGeneration += 1;
  showLogin();
}

// ---------------------------------------------------------------- live updates (comet)

// Starting a new loop bumps the generation, so an older loop that is still waiting stops at its next step.
function startComet() {
  cometGeneration += 1;
  pollComet(cometGeneration).catch(reportError);
}

function applyMessage(message) {
  if (typeof message.version === "string") versionText = message.version;
  if (typeof message.risky_enabled === "boolean") riskyEnabled = message.risky_enabled;
  if (typeof message.mac !== "string") return;
  if (!/^[0-9a-fA-F:-]+$/.test(message.mac)) return;
  if (message.removed === true) {
    devices.delete(message.mac);
    return;
  }
  devices.set(message.mac, Object.assign({}, devices.get(message.mac), message));
}

async function pollComet(generation) {
  if (generation !== cometGeneration) return;
  try {
    const response = await fetch("api/v1/comet?cursor=" + cursor);
    if (generation !== cometGeneration) return;
    if (response.status === 401) {
      showLogin();
      return;
    }
    if (!response.ok) throw new Error("comet failed: " + response.status);
    const body = await response.json();
    if (isObject(body) && typeof body.cursor === "number") cursor = body.cursor;
    listOf(body, "messages").forEach(applyMessage);
    if (!loggedIn) showApp();
    renderAll();
  } catch (err) {
    reportError(err);
    await new Promise((resolve) => setTimeout(resolve, COMET_RETRY_MS));
  }
  pollComet(generation).catch(reportError);
}

// ---------------------------------------------------------------- shared rendering pieces

function stateOf(device) {
  return Object.prototype.hasOwnProperty.call(STATE_KEYS, device.state) ? device.state : "unknown";
}

function tile(labelKey, value) {
  const node = el("div", "tile");
  node.append(el("span", "tile__label", t(labelKey)), el("span", "tile__value", value));
  return node;
}

function tableWrap(headKeys, rows) {
  const wrap = el("div", "table-wrap");
  const table = el("table", "table");
  const tbody = el("tbody");
  tbody.append(...rows);
  if (headKeys.length > 0) {
    const thead = el("thead");
    const head = el("tr");
    for (const key of headKeys) head.appendChild(el("th", "", t(key)));
    thead.appendChild(head);
    table.append(thead, tbody);
  } else {
    table.appendChild(tbody);
  }
  wrap.appendChild(table);
  return wrap;
}

function deviceIcon() {
  const ns = svgNamespace();
  if (!ns) return el("span", "device-card__icon");
  const svg = svgEl(ns, "svg", { class: "device-card__icon", viewBox: "0 0 24 24", "aria-hidden": "true" });
  svg.appendChild(svgEl(ns, "rect", { x: 3, y: 3, width: 18, height: 18, rx: 4 }));
  svg.appendChild(svgEl(ns, "path", { d: "M9 12h6" }));
  return svg;
}

// ---------------------------------------------------------------- devices

function renderDevices() {
  const host = $("devices-list");
  if (!host) return;
  const list = Array.from(devices.values());
  const counts = { connected: 0, lost: 0, unknown: 0 };
  for (const device of list) counts[stateOf(device)] += 1;
  const row = el("div", "tiles");
  for (const state of STATES) row.appendChild(tile(STATE_KEYS[state], String(counts[state])));
  row.appendChild(pieTile(counts, list.length));
  if (list.length === 0) {
    host.replaceChildren(row, emptyState("no_devices"));
    return;
  }
  const grid = el("div", "card-grid");
  grid.append(...list.map(renderDeviceCard));
  host.replaceChildren(row, grid);
}

function pieTile(counts, total) {
  const node = el("div", "tile tile--pie");
  node.appendChild(el("span", "tile__label", t("devices_heading")));
  const ns = svgNamespace();
  if (ns) {
    const svg = svgEl(ns, "svg", { class: "pie__svg", viewBox: "0 0 42 42" });
    if (total === 0) {
      svg.appendChild(svgEl(ns, "circle", { class: "pie__ring", cx: 21, cy: 21, r: PIE_RADIUS }));
    }
    let offset = 25;
    for (const state of STATES) {
      const share = total > 0 ? (counts[state] / total) * 100 : 0;
      if (share === 0) continue;
      svg.appendChild(svgEl(ns, "circle", {
        class: "pie__segment pie__segment--" + state,
        cx: 21,
        cy: 21,
        r: PIE_RADIUS,
        "stroke-dasharray": share.toFixed(2) + " " + (100 - share).toFixed(2),
        "stroke-dashoffset": offset.toFixed(2),
      }));
      offset -= share;
    }
    node.appendChild(svg);
  }
  const legend = el("ul", "pie__legend");
  for (const state of STATES) {
    const item = el("li", "pie__item");
    item.append(
      el("span", "pie__dot pie__dot--" + state),
      document.createTextNode(t(STATE_KEYS[state]) + ": " + counts[state])
    );
    legend.appendChild(item);
  }
  node.appendChild(legend);
  return node;
}

function renderDeviceCard(device) {
  const state = stateOf(device);
  const card = el("article", "device-card device-card--" + state);
  const head = el("div", "device-card__head");
  const chip = el("span", "state");
  chip.append(el("span", "state__dot"), document.createTextNode(t(STATE_KEYS[state])));
  head.append(deviceIcon(), el("h3", "device-card__name", String(device.name || device.mac || "")), chip);
  const mac = el("p", "device-card__meta");
  mac.append(document.createTextNode(t("device_mac") + ": "), el("span", "mono", String(device.mac || "")));
  const actions = el("div", "device-card__actions");
  for (const action of DEVICE_ACTIONS) actions.appendChild(actionButton(device, action));
  card.append(
    head,
    el("p", "device-card__meta", t("device_model") + ": " + String(device.model || "-")),
    mac,
    el("p", "device-card__meta", t("device_last_seen") + ": " + formatTime(device.last_seen_ms)),
    actions
  );
  return card;
}

function actionButton(device, action) {
  const button = el("button", action.className, t(action.labelKey));
  button.type = "button";
  button.addEventListener("click", () => {
    deviceAction(device.mac, action.name, button).catch(reportError);
  });
  return button;
}

async function deviceAction(mac, name, button) {
  button.disabled = true;
  try {
    const response = await postJson("api/v1/devices/" + encodeURIComponent(mac) + "/" + name, {});
    if (response.status === 401) {
      showLogin();
      return;
    }
    if (!response.ok) throw new Error(name + " failed: " + response.status);
  } finally {
    button.disabled = false;
  }
}

// ---------------------------------------------------------------- ports

function renderPorts() {
  const host = $("ports-list");
  if (!host) return;
  const withPorts = Array.from(devices.values()).filter((device) => arrayOf(device.ports).length > 0);
  if (withPorts.length === 0) {
    host.replaceChildren(emptyState("no_ports"));
    return;
  }
  host.replaceChildren(...withPorts.map(renderPortPanel));
}

function renderPortPanel(device) {
  const panel = el("section", "panel");
  panel.appendChild(el("h3", "", String(device.name || device.mac || "")));
  for (const port of arrayOf(device.ports)) {
    panel.appendChild(renderPort(device.mac, port));
  }
  return panel;
}

function renderPort(mac, port) {
  const values = isObject(port.values) ? port.values : {};
  const label = port.label ? String(port.label) : t("port_label") + " " + String(port.port);
  const block = el("div", "port");
  const head = el("div", "port__head");
  head.appendChild(el("span", "port__label", label));
  if (values.output === 0 || values.output === 1) {
    head.appendChild(outputSwitch(mac, port.port, values.output === 1));
  }
  block.append(head, renderMetrics(values));
  return block;
}

function outputSwitch(mac, portNumber, on) {
  const toggle = el("button", "switch", t(on ? "output_on" : "output_off"));
  toggle.type = "button";
  toggle.setAttribute("aria-pressed", on ? "true" : "false");
  toggle.addEventListener("click", () => {
    setOutput(mac, portNumber, on ? 0 : 1, toggle).catch(reportError);
  });
  return toggle;
}

async function setOutput(mac, portNumber, value, control) {
  control.disabled = true;
  try {
    const path = "api/v1/devices/" + encodeURIComponent(mac) + "/ports/" + encodeURIComponent(portNumber) + "/output";
    const response = await postJson(path, { value: value });
    if (response.status === 401) {
      showLogin();
      return;
    }
    if (!response.ok) throw new Error("output failed: " + response.status);
  } finally {
    control.disabled = false;
  }
}

function renderMetrics(values) {
  const group = el("div", "metrics");
  for (const metric of METRICS) {
    const raw = values[metric.key];
    if (typeof raw !== "number") continue;
    const cell = el("div", "metric");
    cell.append(
      el("span", "metric__label", t(metric.label)),
      el("span", "metric__value", formatNumber(raw, metric.digits)),
      el("span", "metric__unit", metric.unit)
    );
    group.appendChild(cell);
  }
  return group;
}

// ---------------------------------------------------------------- measures

async function loadMeasures() {
  const body = await getJson("api/v1/stat/" + encodeURIComponent(interval));
  if (body === null) return;
  measures = isObject(body) ? body : null;
  renderMeasures();
}

function valueOfAggregate(item) {
  if (typeof item === "number") return item;
  if (isObject(item) && typeof item.value === "number") return item.value;
  return 0;
}

function renderMeasures() {
  const host = $("measures-chart");
  if (!host) return;
  const aggregates = measures && Array.isArray(measures.aggregates) ? measures.aggregates : [];
  const nodes = [intervalButtons()];
  if (aggregates.length === 0) {
    nodes.push(emptyState("no_measures"));
  } else {
    nodes.push(barChart(aggregates.slice(0, BAR_COUNT).map(valueOfAggregate)));
  }
  if (measures && typeof measures.cost === "number") {
    nodes.push(costTile(measures.cost, measures.currency));
  }
  host.replaceChildren(...nodes);
}

function intervalButtons() {
  const row = el("div", "intervals");
  for (const name of INTERVALS) {
    const button = el("button", "metric", t(INTERVAL_KEYS[name]));
    button.type = "button";
    button.setAttribute("aria-pressed", name === interval ? "true" : "false");
    button.addEventListener("click", () => {
      interval = name;
      loadMeasures().catch(reportError);
    });
    row.appendChild(button);
  }
  return row;
}

function barChart(values) {
  const panel = el("div", "panel");
  const ns = svgNamespace();
  if (!ns) return panel;
  const svg = svgEl(ns, "svg", { class: "chart", viewBox: "0 0 600 200" });
  for (const y of [1, 100, 199]) {
    svg.appendChild(svgEl(ns, "line", { class: "chart__grid", x1: 0, x2: 600, y1: y, y2: y }));
  }
  const max = Math.max(0, ...values);
  values.forEach((value, index) => {
    const height = max > 0 ? (Math.max(value, 0) / max) * CHART_PLOT : 0;
    svg.appendChild(svgEl(ns, "rect", {
      class: "chart__bar",
      x: index * CHART_SLOT + 4,
      y: CHART_BASE - height,
      width: CHART_SLOT - 8,
      height: height,
    }));
  });
  const top = svgEl(ns, "text", { class: "chart__label", x: 0, y: 12 });
  top.textContent = formatNumber(max, 0);
  svg.appendChild(top);
  panel.appendChild(svg);
  return panel;
}

function costTile(cost, currency) {
  const text = typeof currency === "string" && CURRENCY_PATTERN.test(currency)
    ? new Intl.NumberFormat(lang, { style: "currency", currency: currency }).format(cost)
    : formatNumber(cost, 2);
  return tile("energy_cost", text);
}

// ---------------------------------------------------------------- rules

async function loadRules() {
  const body = await getJson("api/v1/rules");
  if (body === null) return;
  rules = listOf(body, "automations");
  renderRules();
}

function renderRules() {
  const host = $("rules-list");
  if (!host) return;
  if (rules.length === 0) {
    host.replaceChildren(emptyState("no_rules"));
    return;
  }
  host.replaceChildren(tableWrap([], rules.map(renderRuleRow)));
}

function renderRuleRow(rule) {
  const enabled = rule.enabled === true;
  const nameCell = el("td", "", String(rule.name || rule.id || ""));
  const stateCell = el("td");
  stateCell.appendChild(el("span", enabled ? "tag tag--known" : "tag tag--other", t(enabled ? "rule_enabled" : "rule_disabled")));
  const actionCell = el("td");
  const copyButton = el("button", "button", t("copy"));
  copyButton.type = "button";
  copyButton.addEventListener("click", () => {
    copyRule(rule, copyButton).catch(reportError);
  });
  actionCell.appendChild(copyButton);
  const row = el("tr");
  row.append(nameCell, stateCell, actionCell);
  return row;
}

async function copyRule(rule, button) {
  const copy = Object.assign({}, rule, { name: String(rule.name || "") + " (" + t("copy") + ")", enabled: false });
  delete copy.id;
  button.disabled = true;
  try {
    const response = await postJson("api/v1/rules", copy);
    if (response.status === 401) {
      showLogin();
      return;
    }
    if (!response.ok) throw new Error("rule copy failed: " + response.status);
  } finally {
    button.disabled = false;
  }
  await loadRules();
}

// ---------------------------------------------------------------- events and alarms

function inFilter(time) {
  if (typeof time !== "number") return true;
  const from = Date.parse(filterFrom);
  const to = Date.parse(filterTo);
  if (!Number.isNaN(from) && time < from) return false;
  if (!Number.isNaN(to) && time >= to + DAY_MS) return false;
  return true;
}

async function loadEventsAndAlarms() {
  const eventsBody = await getJson("api/v1/events");
  if (eventsBody === null) return;
  const alarmsBody = await getJson("api/v1/alarms");
  if (alarmsBody === null) return;
  events = listOf(eventsBody, "events");
  alarms = listOf(alarmsBody, "alarms");
  renderEvents();
}

function timeRows(list) {
  return list.map((item) => {
    const row = el("tr");
    row.append(el("td", "", formatTime(item.time)), el("td", "", String(item.message || "")));
    return row;
  });
}

function renderEvents() {
  const eventsHost = $("events-list");
  if (eventsHost) {
    const shown = events.filter((event) => inFilter(event.time));
    eventsHost.replaceChildren(
      shown.length === 0 ? emptyState("no_events") : tableWrap(["event_time", "event_message"], timeRows(shown))
    );
  }
  const alarmsHost = $("alarms-list");
  if (alarmsHost) {
    alarmsHost.replaceChildren(
      alarms.length === 0 ? emptyState("no_alarms") : tableWrap(["event_time", "event_message"], timeRows(alarms))
    );
  }
}

// The filter bar is built once; it sits before the events list inside the events view.
function buildEventFilter() {
  const view = $("view-events");
  const list = $("events-list");
  if (!view || !list) return;
  const fromInput = el("input", "filter__input");
  fromInput.type = "date";
  const toInput = el("input", "filter__input");
  toInput.type = "date";
  const apply = el("button", "button button--primary", t("apply"));
  apply.type = "button";
  apply.dataset.i18n = "apply";
  apply.addEventListener("click", () => {
    filterFrom = fromInput.value;
    filterTo = toInput.value;
    renderEvents();
  });
  const panel = el("div", "panel filter");
  panel.append(filterField("filter_from", fromInput), filterField("filter_to", toInput), apply);
  view.insertBefore(panel, list);
}

function filterField(key, input) {
  const label = el("label", "filter__field");
  const text = el("span", "", t(key));
  text.dataset.i18n = key;
  label.append(text, input);
  return label;
}

// ---------------------------------------------------------------- maps, users, system, risky

async function loadMaps() {
  const body = await getJson("api/v1/maps");
  if (body === null) return;
  maps = listOf(body, "maps");
  renderMaps();
}

function renderMaps() {
  const host = $("maps-list");
  if (!host) return;
  if (maps.length === 0) {
    host.replaceChildren(emptyState("no_maps"));
    return;
  }
  const grid = el("div", "card-grid");
  grid.append(...maps.map((map) => {
    const card = el("article", "panel");
    card.appendChild(el("h3", "", String(map.name || map.id || "")));
    return card;
  }));
  host.replaceChildren(grid);
}

function renderUsers() {
  const host = $("users-list");
  if (host) host.replaceChildren(emptyState("no_users"));
}

function renderSystem() {
  const host = $("system-info");
  if (!host) return;
  const rows = [el("div", "panel", versionText ? t("version", { v: versionText }) : "")];
  for (const key of ["ntp_label", "timezone_label", "energy_price", "backup_import", "support_info"]) {
    const row = el("div", "panel info");
    row.appendChild(el("span", "info__label", t(key)));
    rows.push(row);
  }
  rows.push(renderRulesImport());
  host.replaceChildren(...rows);
}

// The import card is built once and kept, so a comet re-render keeps the chosen file and the busy button.
let rulesImport = null;
let rulesImportResult = null;
let rulesImportBusy = false;

function buildRulesImport() {
  const card = el("section", "panel info import-rules");
  const title = el("h3", "");
  title.dataset.i18n = "import_rules_action";
  const file = el("input");
  file.type = "file";
  file.accept = ".unf";
  const picker = el("label");
  const pickerText = el("span", "info__label");
  picker.append(pickerText, file);
  const send = el("button", "button button--primary");
  send.type = "button";
  const message = el("p", "message");
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");
  const result = el("div");
  card.append(title, picker, send, message, result);
  file.addEventListener("change", () => renderSystem());
  send.addEventListener("click", () => {
    if (file.files.length > 0) sendRulesImport(file.files[0]).catch(reportError);
  });
  return { card, title, pickerText, file, send, message, result };
}

function renderSkippedRow(item) {
  const row = el("tr");
  row.append(el("td", "mono", String(item.id || "")), el("td", "", String(item.reason || "")));
  return row;
}

function renderRulesImport() {
  if (rulesImport === null) rulesImport = buildRulesImport();
  const view = rulesImport;
  view.title.textContent = t("import_rules_action");
  view.pickerText.textContent = t("backup_import");
  view.send.textContent = t("import_rules_action");
  view.send.disabled = rulesImportBusy || view.file.files.length === 0;
  view.message.className = "message";
  view.message.textContent = "";
  view.result.replaceChildren();
  if (rulesImportResult === null) return view.card;
  if (!rulesImportResult.ok) {
    view.message.className = "message message--error";
    view.message.textContent = t("import_rules_error");
    return view.card;
  }
  const skipped = arrayOf(rulesImportResult.report.skipped);
  view.message.className = "message message--ok";
  view.message.textContent = t("import_rules_report", {
    converted: rulesImportResult.report.converted,
    skipped: skipped.length,
  });
  if (skipped.length > 0) view.result.appendChild(tableWrap([], skipped.map(renderSkippedRow)));
  return view.card;
}

async function sendRulesImport(chosen) {
  rulesImportBusy = true;
  renderSystem();
  try {
    const response = await fetch("api/v1/upload/rules", {
      method: "POST",
      body: await chosen.arrayBuffer(),
    });
    if (response.status === 401) {
      showLogin();
      return;
    }
    if (!response.ok) throw new Error("import failed: " + response.status);
    const body = await response.json();
    if (!isObject(body) || !isObject(body.report)) throw new Error("import report missing");
    rulesImportResult = { ok: true, report: body.report };
  } catch (err) {
    rulesImportResult = { ok: false };
    reportError(err);
  } finally {
    rulesImportBusy = false;
    renderSystem();
  }
}

function renderRisky() {
  setHidden("risky", !riskyEnabled);
}

function renderVersion() {
  const node = $("version");
  if (node) node.textContent = versionText ? t("version", { v: versionText }) : "";
}

function renderAll() {
  renderVersion();
  setLoginMessage(loginMessageKey);
  renderDevices();
  renderPorts();
  renderMeasures();
  renderRules();
  renderEvents();
  renderMaps();
  renderUsers();
  renderSystem();
  renderRisky();
}

// ---------------------------------------------------------------- start

function bindEvents() {
  const select = $("lang");
  if (select) select.addEventListener("change", () => setLang(select.value));
  const loginButton = $("login-button");
  if (loginButton) {
    loginButton.addEventListener("click", () => {
      login().catch(reportError);
    });
  }
  const password = $("password");
  if (password) {
    password.addEventListener("keydown", (event) => {
      if (event.key === "Enter") login().catch(reportError);
    });
  }
  const logoutButton = $("logout-button");
  if (logoutButton) {
    logoutButton.addEventListener("click", () => {
      logout().catch(reportError);
    });
  }
  window.addEventListener("hashchange", showView);
}

async function start() {
  lang = detectLanguage();
  document.documentElement.lang = lang;
  bindEvents();
  await loadStrings();
  applyTranslations();
  buildEventFilter();
  renderAll();
  // Nothing is shown until the first protected request decides between login and app.
  setHidden("login", true);
  showView();
  startComet();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    start().catch(reportError);
  });
} else {
  start().catch(reportError);
}
