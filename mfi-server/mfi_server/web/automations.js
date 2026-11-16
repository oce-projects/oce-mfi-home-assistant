"use strict";

// Behaviour of the automations page of mFi Server: list, enable, run, delete, YAML editor and run history.
// Hand-written, no libraries. Every request uses a relative address, so it works under the ingress prefix.
// Translations and DOM helpers (t, el, loadStrings, detectLanguage, applyTranslations, setLang) come from common.js.

const HISTORY_LIMIT = 5;
const LIST_YAML_RE = /^-\s/m;
const PLAIN_YAML_RE = /^(?:true|false|null|on|off|yes|no|~|[-+]?[0-9][0-9.:_]*)$/i;
const SPECIAL_START_RE = /^[-?:,[\]{}&*!|>'"%@`#\s]/;
const EXAMPLE_YAML = [
  "id: example",
  "triggers:",
  "  - trigger: state",
  "    entity_id: switch.mfi_02aabbccdd01_1",
  "    to: \"on\"",
  "actions:",
  "  - delay: \"00:05:00\"",
  "  - action: switch.turn_off",
  "    target:",
  "      entity_id: switch.mfi_02aabbccdd01_1",
].join("\n") + "\n";

let versionEl;
let langSelect;
let yamlEl;
let messageEl;
let listEl;
let layoutEl;
let loginHintEl;
let newButton;
let checkButton;
let saveButton;
let historyPanel;
let historyFor;
let tracesEl;

let healthVersion = "";
let automations = [];
let editingId = "";
let historyId = "";
let historyAlias = "";
let traces = [];

function loadRefs() {
  versionEl = document.getElementById("version");
  langSelect = document.getElementById("lang");
  yamlEl = document.getElementById("yaml");
  messageEl = document.getElementById("auto-message");
  listEl = document.getElementById("automations");
  layoutEl = document.getElementById("auto-layout");
  loginHintEl = document.getElementById("auto-login");
  newButton = document.getElementById("auto-new");
  checkButton = document.getElementById("auto-check");
  saveButton = document.getElementById("auto-save");
  historyPanel = document.getElementById("auto-history");
  historyFor = document.getElementById("history-for");
  tracesEl = document.getElementById("traces");
}

function reportError(err) {
  console.error(err);
}

// ---------------------------------------------------------------- requests

function send(method, route, body) {
  const options = { method: method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  return fetch(route, options);
}

async function errorDetails(response) {
  const body = await response.json();
  return Array.isArray(body.details) ? body.details : [String(body.error)];
}

async function loadHealth() {
  const response = await fetch("api/v1/health");
  if (!response.ok) throw new Error("health request failed: " + response.status);
  const health = await response.json();
  healthVersion = String(health.version);
  renderVersion();
}

async function loadAutomations() {
  const response = await fetch("api/v1/automations");
  if (response.status === 401) {
    showLoginRequired();
    return;
  }
  if (!response.ok) {
    automations = [];
    listEl.replaceChildren(el("p", "message message--error", t("auto_load_error")));
    return;
  }
  loginHintEl.hidden = true;
  layoutEl.hidden = false;
  renderList(await response.json());
}

async function setEnabled(id, enabled) {
  const response = await send("POST", "api/v1/automations/" + encodeURIComponent(id) + "/enable", { enabled: enabled });
  if (!response.ok) throw new Error("enable request failed: " + response.status);
  await loadAutomations();
}

async function runAutomation(id) {
  const response = await send("POST", "api/v1/automations/" + encodeURIComponent(id) + "/trigger");
  if (!response.ok) throw new Error("trigger request failed: " + response.status);
}

async function deleteAutomation(id) {
  if (!window.confirm(t("auto_confirm_delete"))) return;
  const response = await send("DELETE", "api/v1/automations/" + encodeURIComponent(id));
  if (!response.ok) throw new Error("delete request failed: " + response.status);
  if (editingId === id) editingId = "";
  if (historyId === id) {
    historyId = "";
    traces = [];
  }
  await loadAutomations();
  renderHistory();
}

async function editAutomation(id) {
  const response = await fetch("api/v1/automations/" + encodeURIComponent(id));
  if (!response.ok) {
    notify("auto_load_error", "message--error");
    return;
  }
  const obj = await response.json();
  editingId = id;
  yamlEl.value = toYaml(obj);
  messageEl.replaceChildren();
  renderList(automations);
}

async function loadTraces(id, alias) {
  const response = await fetch("api/v1/automations/" + encodeURIComponent(id) + "/traces");
  if (!response.ok) throw new Error("traces request failed: " + response.status);
  const body = await response.json();
  historyId = id;
  historyAlias = alias;
  traces = Array.isArray(body.traces) ? body.traces.slice(0, HISTORY_LIMIT) : [];
  renderHistory();
}

async function checkYaml() {
  const response = await send("POST", "api/v1/automations/validate", { yaml: yamlEl.value });
  if (response.ok) {
    notify("auto_valid", "message--ok");
    return;
  }
  if (response.status === 400) {
    showErrors(await errorDetails(response));
    return;
  }
  throw new Error("validate request failed: " + response.status);
}

async function saveYaml() {
  const text = yamlEl.value;
  if (LIST_YAML_RE.test(text)) {
    const imported = await send("POST", "api/v1/automations/import", { yaml: text });
    if (imported.ok) {
      editingId = "";
      notify("auto_saved", "message--ok");
      await loadAutomations();
      return;
    }
    await showSaveProblem(imported);
    return;
  }
  const check = await send("POST", "api/v1/automations/validate", { yaml: text });
  if (!check.ok) {
    await showSaveProblem(check);
    return;
  }
  const body = await check.json();
  const obj = body.automations[0];
  const response = editingId
    ? await send("PUT", "api/v1/automations/" + encodeURIComponent(editingId), obj)
    : await send("POST", "api/v1/automations", obj);
  if (!response.ok) {
    await showSaveProblem(response);
    return;
  }
  const saved = await response.json();
  editingId = saved.id;
  notify("auto_saved", "message--ok");
  await loadAutomations();
}

async function showSaveProblem(response) {
  if (response.status === 400) {
    showErrors(await errorDetails(response));
    return;
  }
  notify("auto_save_error", "message--error");
}

// ---------------------------------------------------------------- messages

function notify(key, kind) {
  messageEl.replaceChildren(el("p", "message " + kind, t(key)));
}

function showErrors(details) {
  const list = el("ul", "message message--error errors");
  for (const detail of details) {
    list.appendChild(errorItem(String(detail)));
  }
  messageEl.replaceChildren(list);
}

function errorItem(text) {
  const item = el("li");
  const cut = text.indexOf(": ");
  if (cut > 0) {
    item.append(el("code", "", text.slice(0, cut)), document.createTextNode(" " + text.slice(cut + 2)));
  } else {
    item.textContent = text;
  }
  return item;
}

function showLoginRequired() {
  automations = [];
  listEl.replaceChildren();
  layoutEl.hidden = true;
  historyPanel.hidden = true;
  loginHintEl.hidden = false;
}

// ---------------------------------------------------------------- list

function renderVersion() {
  versionEl.textContent = healthVersion ? t("version", { v: healthVersion }) : "";
}

function renderList(items) {
  automations = items;
  listEl.replaceChildren();
  if (items.length === 0) {
    listEl.appendChild(el("p", "empty", t("no_automations")));
    return;
  }
  const list = el("ul", "autos");
  for (const automation of items) {
    list.appendChild(renderAutomation(automation));
  }
  listEl.appendChild(list);
}

function renderAutomation(a) {
  const item = el("li", "auto " + (a.enabled ? "auto--enabled" : "auto--disabled"));
  if (a.id === editingId) item.setAttribute("aria-current", "true");
  const head = el("div", "auto__head");
  head.append(el("h3", "auto__name", a.alias || a.id), toggleButton(a));
  const meta = el("p", "auto__meta");
  meta.append(el("span", "auto__id", a.id), document.createTextNode(" · " + t("auto_mode") + ": " + a.mode));
  const actions = el("div", "auto__actions");
  actions.append(
    actionButton("button", t("auto_edit"), () => editAutomation(a.id)),
    actionButton("button", t("auto_run"), () => runAutomation(a.id)),
    actionButton("button", t("auto_history"), () => loadTraces(a.id, a.alias || a.id)),
    actionButton("button button--danger", t("auto_delete"), () => deleteAutomation(a.id))
  );
  item.append(head, meta, actions);
  return item;
}

function toggleButton(a) {
  const button = el("button", "toggle", t(a.enabled ? "auto_enabled" : "auto_disabled"));
  button.type = "button";
  button.setAttribute("aria-pressed", a.enabled ? "true" : "false");
  button.addEventListener("click", () => {
    setEnabled(a.id, !a.enabled).catch(reportError);
  });
  return button;
}

function actionButton(className, label, handler) {
  const button = el("button", className, label);
  button.type = "button";
  button.addEventListener("click", () => {
    handler().catch(reportError);
  });
  return button;
}

function newAutomation() {
  editingId = "";
  yamlEl.value = EXAMPLE_YAML;
  messageEl.replaceChildren();
  renderList(automations);
}

// ---------------------------------------------------------------- history

function formatTime(sec) {
  if (typeof sec !== "number") return "";
  return new Date(sec * 1000).toLocaleString(lang);
}

function renderHistory() {
  historyPanel.hidden = historyId === "";
  historyFor.textContent = historyAlias;
  tracesEl.replaceChildren();
  if (traces.length === 0) {
    tracesEl.appendChild(el("p", "empty", t("auto_history_empty")));
    return;
  }
  const list = el("ol", "traces");
  for (const trace of traces) {
    list.appendChild(renderTrace(trace));
  }
  tracesEl.appendChild(list);
}

function renderTrace(trace) {
  const result = String(trace.result);
  const resultKey = "trace_" + result;
  const item = el("li", "trace trace--" + result);
  item.appendChild(el("p", "trace__result", t(resultKey)));
  const times = el("p", "trace__times");
  times.append(
    document.createTextNode(t("trace_start") + ": " + formatTime(trace.start) + " · "),
    document.createTextNode(t("trace_end") + ": " + formatTime(trace.end))
  );
  item.appendChild(times);
  if (result === "error" && typeof trace.message === "string") {
    item.appendChild(el("p", "message message--error", trace.message));
  }
  if (Array.isArray(trace.steps) && trace.steps.length > 0) {
    item.appendChild(el("p", "trace__label", t("trace_steps")));
    const steps = el("ol", "trace__steps");
    for (const step of trace.steps) {
      const line = el("li");
      line.append(
        el("code", "trace__path", String(step.path)),
        document.createTextNode(" — " + String(step.result))
      );
      steps.appendChild(line);
    }
    item.appendChild(steps);
  }
  return item;
}

// ---------------------------------------------------------------- YAML

function yamlScalar(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  const text = String(value);
  if (
    text === "" ||
    text.includes(":") ||
    text.includes("#") ||
    PLAIN_YAML_RE.test(text) ||
    SPECIAL_START_RE.test(text) ||
    text !== text.trim()
  ) {
    return JSON.stringify(text);
  }
  return text;
}

function yamlLines(value, indent) {
  const pad = "  ".repeat(indent);
  const lines = [];
  if (Array.isArray(value)) {
    for (const item of value) {
      if (item !== null && typeof item === "object") {
        const nested = yamlLines(item, indent + 1);
        lines.push(pad + "- " + (nested.length > 0 ? nested[0].trimStart() : ""));
        lines.push(...nested.slice(1));
      } else {
        lines.push(pad + "- " + yamlScalar(item));
      }
    }
    return lines;
  }
  for (const key of Object.keys(value)) {
    const item = value[key];
    if (Array.isArray(item) && item.length === 0) {
      lines.push(pad + key + ": []");
    } else if (item !== null && typeof item === "object") {
      lines.push(pad + key + ":");
      lines.push(...yamlLines(item, indent + 1));
    } else {
      const text = yamlScalar(item);
      lines.push(pad + key + (text ? ": " + text : ":"));
    }
  }
  return lines;
}

function toYaml(obj) {
  return yamlLines(obj, 0).join("\n") + "\n";
}

// ---------------------------------------------------------------- start

function render() {
  renderVersion();
  renderList(automations);
  renderHistory();
}

function bindEvents() {
  langSelect.addEventListener("change", () => {
    setLang(langSelect.value, render);
  });
  newButton.addEventListener("click", newAutomation);
  checkButton.addEventListener("click", () => {
    checkYaml().catch(reportError);
  });
  saveButton.addEventListener("click", () => {
    saveYaml().catch(reportError);
  });
}

async function start() {
  loadRefs();
  lang = detectLanguage();
  document.documentElement.lang = lang;
  bindEvents();
  await loadStrings();
  applyTranslations();
  loadHealth().catch(reportError);
  loadAutomations().catch(reportError);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    start().catch(reportError);
  });
} else {
  start().catch(reportError);
}
