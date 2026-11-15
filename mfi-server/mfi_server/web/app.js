"use strict";

// Behaviour of the mFi Server web page: translations, login, devices, outlet switches and history chart.
// Hand-written, no libraries. Every request uses a relative address, so it works under the ingress prefix.

const REFRESH_MS = 10000;
const HISTORY_MS = 86400000;
const LANG_KEY = "mfi_lang";
const SVG_NS = "http://www.w3.org/2000/svg";
const CHART_WIDTH = 600;
const CHART_HEIGHT = 200;
const CHART_MARGIN = 1;
const GRID_Y = [1, 100, 199];
const STATE_KEYS = { connected: "state_connected", lost: "state_lost", unknown: "state_unknown" };
const METRICS = [
  { key: "active_pwr", label: "metric_active_pwr", unit: "W", digits: 1 },
  { key: "v_rms", label: "metric_v_rms", unit: "V", digits: 1 },
  { key: "i_rms", label: "metric_i_rms", unit: "A", digits: 2 },
  { key: "pf", label: "metric_pf", unit: "", digits: 2 },
  { key: "energy_sum", label: "metric_energy_sum", unit: "Wh", digits: 0 },
];

const strings = {};
let lang = "en";
let healthVersion = "";
let loggedIn = false;
let devices = [];
let devicesLoaded = false;
let loginMessageKey = "";
let chartState = null;
const busyOutputs = new Set();
const outputErrors = new Set();

let versionEl;
let langSelect;
let logoutButton;
let loginSection;
let passwordInput;
let loginButton;
let loginMessage;
let devicesHeading;
let devicesEl;
let chartPanel;
let chartTitle;
let chartSvg;
let chartMin;
let chartMax;
let chartClose;

function loadRefs() {
  versionEl = document.getElementById("version");
  langSelect = document.getElementById("lang");
  logoutButton = document.getElementById("logout-button");
  loginSection = document.getElementById("login");
  passwordInput = document.getElementById("password");
  loginButton = document.getElementById("login-button");
  loginMessage = document.getElementById("login-message");
  devicesHeading = document.querySelector('[data-i18n="devices_heading"]');
  devicesEl = document.getElementById("devices");
  chartPanel = document.getElementById("chart");
  chartTitle = document.getElementById("chart-title");
  chartSvg = document.getElementById("chart-svg");
  chartMin = document.getElementById("chart-min");
  chartMax = document.getElementById("chart-max");
  chartClose = document.getElementById("chart-close");
}

function reportError(err) {
  console.error(err);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svgNode(name, attributes) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    node.setAttribute(key, String(value));
  }
  return node;
}

// ---------------------------------------------------------------- i18n

async function loadStrings() {
  const enResponse = await fetch("i18n/en.json");
  const itResponse = await fetch("i18n/it.json");
  if (!enResponse.ok || !itResponse.ok) {
    throw new Error("translations not loaded: " + enResponse.status + " " + itResponse.status);
  }
  strings.en = await enResponse.json();
  strings.it = await itResponse.json();
}

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
  document.querySelectorAll("[data-i18n-title]").forEach((node) => {
    node.title = t(node.dataset.i18nTitle);
  });
  document.title = t("app_title");
  langSelect.value = lang;
}

function setLanguage(code) {
  lang = code;
  localStorage.setItem(LANG_KEY, code);
  document.documentElement.lang = code;
  applyTranslations();
  renderVersion();
  setLoginMessage(loginMessageKey);
  renderDevices();
  renderChart();
}

// ---------------------------------------------------------------- header and login

function renderVersion() {
  versionEl.textContent = healthVersion ? t("version", { v: healthVersion }) : "";
}

async function loadHealth() {
  const response = await fetch("api/v1/health");
  if (!response.ok) throw new Error("health request failed: " + response.status);
  const health = await response.json();
  healthVersion = String(health.version);
  renderVersion();
}

function setLoginMessage(key) {
  loginMessageKey = key || "";
  loginMessage.textContent = key ? t(key) : "";
  loginMessage.className = key ? "message message--error" : "";
}

function showLogin(key) {
  loggedIn = false;
  loginSection.hidden = false;
  devicesHeading.hidden = true;
  devicesEl.hidden = true;
  logoutButton.hidden = true;
  if (key !== undefined) setLoginMessage(key);
}

function showDevices() {
  loginSection.hidden = true;
  devicesHeading.hidden = false;
  devicesEl.hidden = false;
}

async function login() {
  const response = await fetch("api/v1/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: passwordInput.value }),
  });
  if (response.status === 204) {
    loggedIn = true;
    passwordInput.value = "";
    setLoginMessage("");
    await refreshDevices();
    return;
  }
  if (response.status === 401) {
    setLoginMessage("msg_login_failed");
    return;
  }
  if (response.status === 429) {
    setLoginMessage("msg_too_many");
    return;
  }
  if (response.status === 503) {
    setLoginMessage("msg_password_not_set");
    return;
  }
  throw new Error("login failed: " + response.status);
}

async function logout() {
  const response = await fetch("api/v1/logout", { method: "POST" });
  if (response.status !== 204) throw new Error("logout failed: " + response.status);
  loggedIn = false;
  await refreshDevices();
}

// ---------------------------------------------------------------- devices

async function refreshDevices() {
  const response = await fetch("api/v1/devices");
  if (response.status === 200) {
    devices = await response.json();
    devicesLoaded = true;
    showDevices();
    // Without a login (Home Assistant ingress) there is nothing to log out from.
    logoutButton.hidden = !loggedIn;
    renderDevices();
    return;
  }
  if (response.status === 401) {
    showLogin();
    return;
  }
  if (response.status === 503) {
    const body = await response.json();
    if (body.error === "password_not_set") {
      showLogin("msg_password_not_set");
      return;
    }
  }
  throw new Error("devices request failed: " + response.status);
}

function stateName(state) {
  return Object.prototype.hasOwnProperty.call(STATE_KEYS, state) ? state : "unknown";
}

function formatTime(ms) {
  if (typeof ms !== "number") return t("never");
  return new Intl.DateTimeFormat(lang, { dateStyle: "short", timeStyle: "medium" }).format(new Date(ms));
}

function formatNumber(value, metric) {
  return new Intl.NumberFormat(lang, { maximumFractionDigits: metric.digits }).format(Number(value));
}

function withUnit(value, metric) {
  return formatNumber(value, metric) + (metric.unit ? " " + metric.unit : "");
}

function renderDevices() {
  devicesEl.replaceChildren();
  if (!devicesLoaded) {
    devicesEl.appendChild(el("p", "empty", t("loading")));
    return;
  }
  if (devices.length === 0) {
    devicesEl.appendChild(el("p", "empty", t("no_devices")));
    return;
  }
  for (const device of devices) {
    devicesEl.appendChild(renderDevice(device));
  }
}

function renderDevice(device) {
  const state = stateName(device.state);
  const card = el("article", "device device--" + state);
  const head = el("div", "device__head");
  head.appendChild(el("h3", "device__name", device.name));
  head.appendChild(renderState(state));
  const meta = el("p", "device__meta");
  meta.append(
    document.createTextNode(t("model_label") + ": " + device.model + " · "),
    el("span", "device__mac", device.mac),
    document.createTextNode(" · " + t("last_seen", { time: formatTime(device.last_seen_ms) }))
  );
  const ports = el("div", "ports");
  for (const port of device.ports) {
    ports.appendChild(renderPort(device.mac, port));
  }
  card.append(head, meta, ports);
  return card;
}

function renderState(state) {
  const node = el("span", "state");
  node.append(el("span", "state__dot"), document.createTextNode(t(STATE_KEYS[state])));
  return node;
}

function renderPort(mac, port) {
  const key = mac + "/" + port.port;
  const values = port.values || {};
  const label = port.label || t("port_label") + " " + port.port;
  const block = el("div", "port");
  const portHead = el("div", "port__head");
  portHead.appendChild(el("span", "port__label", label));
  if (values.output !== undefined && values.output !== null) {
    portHead.appendChild(renderToggle(mac, port.port, values.output, key));
  }
  block.appendChild(portHead);
  if (outputErrors.has(key)) {
    block.appendChild(el("p", "port__error", t("output_error")));
  }
  block.appendChild(renderMetrics(port, label, values));
  return block;
}

function renderToggle(mac, portNumber, output, key) {
  const on = Number(output) === 1;
  const toggle = el("button", "toggle", t(on ? "output_on" : "output_off"));
  toggle.type = "button";
  toggle.setAttribute("aria-pressed", on ? "true" : "false");
  toggle.disabled = busyOutputs.has(key);
  toggle.addEventListener("click", () => {
    setOutput(mac, portNumber, on ? 0 : 1).catch(reportError);
  });
  return toggle;
}

function renderMetrics(port, portLabel, values) {
  const group = el("div", "metrics");
  for (const metric of METRICS) {
    const raw = values[metric.key];
    if (raw === undefined || raw === null) continue;
    const button = el("button", "metric");
    button.type = "button";
    button.append(
      el("span", "metric__label", t(metric.label)),
      el("span", "metric__value", formatNumber(raw, metric)),
      el("span", "metric__unit", metric.unit)
    );
    button.addEventListener("click", () => {
      openChart(port.sensor_id, portLabel, metric).catch(reportError);
    });
    group.appendChild(button);
  }
  return group;
}

async function setOutput(mac, portNumber, value) {
  const key = mac + "/" + portNumber;
  busyOutputs.add(key);
  renderDevices();
  let ok = false;
  try {
    const response = await fetch(
      "api/v1/devices/" + encodeURIComponent(mac) + "/ports/" + encodeURIComponent(portNumber) + "/output",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: value }),
      }
    );
    ok = response.status === 202;
    if (!ok) reportError(new Error("output request failed: " + response.status));
  } catch (err) {
    reportError(err);
  }
  busyOutputs.delete(key);
  if (ok) {
    outputErrors.delete(key);
  } else {
    outputErrors.add(key);
  }
  await refreshDevices();
}

// ---------------------------------------------------------------- chart

function isPoint(point) {
  return Array.isArray(point) && point.length === 2 && typeof point[0] === "number" && typeof point[1] === "number";
}

async function openChart(sensorId, portLabel, metric) {
  const now = Date.now();
  const mac = devices.find((device) => device.ports.some((port) => port.sensor_id === sensorId)).mac;
  const params = new URLSearchParams({
    mac: mac,
    sensor_id: String(sensorId),
    // The history tag is the measurement name, the same as the key in the values of the API.
    tag: metric.key,
    from: String(now - HISTORY_MS),
    to: String(now),
  });
  const response = await fetch("api/v1/history?" + params.toString());
  if (!response.ok) throw new Error("history request failed: " + response.status);
  const body = await response.json();
  if (!Array.isArray(body.points)) throw new Error("history reply has no points");
  chartState = { portLabel: portLabel, metric: metric, points: body.points.filter(isPoint) };
  renderChart();
  chartPanel.hidden = false;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  chartPanel.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
}

function renderChart() {
  if (!chartState) return;
  const metric = chartState.metric;
  const points = chartState.points;
  chartTitle.textContent = chartState.portLabel + " · " + t(metric.label) + " · " + t("chart_title");
  const nodes = GRID_Y.map((y) => svgNode("line", { class: "chart__grid", x1: 0, x2: CHART_WIDTH, y1: y, y2: y }));
  if (points.length === 0) {
    chartMin.textContent = t("never");
    chartMax.textContent = t("never");
  } else {
    let minTime = points[0][0];
    let maxTime = minTime;
    let minValue = points[0][1];
    let maxValue = minValue;
    for (const [time, value] of points) {
      minTime = Math.min(minTime, time);
      maxTime = Math.max(maxTime, time);
      minValue = Math.min(minValue, value);
      maxValue = Math.max(maxValue, value);
    }
    const timeSpan = maxTime - minTime || 1;
    const valueSpan = maxValue - minValue;
    const coords = points.map(([time, value]) => {
      const x = CHART_MARGIN + ((time - minTime) / timeSpan) * (CHART_WIDTH - 2 * CHART_MARGIN);
      const ratio = valueSpan > 0 ? (value - minValue) / valueSpan : 0.5;
      const y = CHART_HEIGHT - CHART_MARGIN - ratio * (CHART_HEIGHT - 2 * CHART_MARGIN);
      return x.toFixed(1) + "," + y.toFixed(1);
    });
    nodes.push(svgNode("polyline", { class: "chart__line", points: coords.join(" ") }));
    chartMin.textContent = t("chart_min", { value: withUnit(minValue, metric) });
    chartMax.textContent = t("chart_max", { value: withUnit(maxValue, metric) });
  }
  chartSvg.replaceChildren(...nodes);
}

function closeChart() {
  chartState = null;
  chartSvg.replaceChildren();
  chartPanel.hidden = true;
}

// ---------------------------------------------------------------- start

function bindEvents() {
  langSelect.addEventListener("change", () => {
    setLanguage(langSelect.value);
  });
  loginButton.addEventListener("click", () => {
    login().catch(reportError);
  });
  passwordInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") login().catch(reportError);
  });
  logoutButton.addEventListener("click", () => {
    logout().catch(reportError);
  });
  chartClose.addEventListener("click", closeChart);
}

async function start() {
  loadRefs();
  lang = detectLanguage();
  document.documentElement.lang = lang;
  bindEvents();
  await loadStrings();
  applyTranslations();
  renderVersion();
  renderDevices();
  loadHealth().catch(reportError);
  refreshDevices().catch(reportError);
  window.setInterval(() => {
    refreshDevices().catch(reportError);
  }, REFRESH_MS);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    start().catch(reportError);
  });
} else {
  start().catch(reportError);
}
