"use strict";

// Automation editor of the Rules tab: list, form (When / And if / Then), YAML switch, save and traces.
// Hand-written, no libraries. Every address is relative. The DOM is built with createElement and textContent only.
// The file is one closure, so its names do not clash with app.js, which provides t(key) for the translations.
// Two hooks come from the page, not from this file: window.mfiDevices (a list of {mac, name, ports}) fills the
// device and port selects, and the element #editor with data-script-enabled="true" offers the script action.
// The keys trace_time, trace_trigger, trace_result and editor_remove are not in the editor contract yet.

(function () {
  const TRIGGER_TYPES = ["state", "numeric_state", "time", "time_pattern", "calendar"];
  const CONDITION_TYPES = ["state", "numeric_state", "time", "and", "or", "not"];
  const ACTION_TYPES = [
    "switch.turn_on", "switch.turn_off", "switch.toggle", "light.turn_on", "scene.turn_on",
    "automation.trigger", "automation.turn_on", "automation.turn_off",
    "http_post", "notify.email", "mfi.event", "delay", "if", "choose",
  ];
  const NESTED_CONDITIONS = ["and", "or", "not"];
  const ENTITY_ACTIONS = ["switch.turn_on", "switch.turn_off", "switch.toggle", "light.turn_on"];
  const TARGET_ACTIONS = ["scene.turn_on", "automation.trigger", "automation.turn_on", "automation.turn_off"];
  const DATA_ACTIONS = ["http_post", "notify.email", "mfi.event", "script"];
  const SECTION_IDS = { trigger: "editor-when", condition: "editor-and-if", action: "editor-then" };
  const LIST_KEYS = { trigger: "triggers", condition: "conditions", action: "actions" };
  // Editable fields per item: [path, kind]. kind is text, number, list (comma separated) or entity (device and port).
  const FIELDS = {
    "trigger:state": [[["entity_id"], "text"], [["to"], "text"], [["for"], "text"]],
    "trigger:numeric_state": [[["entity_id"], "text"], [["above"], "number"], [["below"], "number"], [["for"], "text"]],
    "trigger:time": [[["at"], "text"], [["weekday"], "list"]],
    "trigger:time_pattern": [[["hours"], "text"], [["minutes"], "text"], [["seconds"], "text"]],
    "trigger:calendar": [[["entity_id"], "text"], [["event"], "text"]],
    "condition:state": [[["entity_id"], "text"], [["state"], "text"]],
    "condition:numeric_state": [[["entity_id"], "text"], [["above"], "number"], [["below"], "number"]],
    "condition:time": [[["after"], "text"], [["before"], "text"], [["weekday"], "list"]],
    "action:switch.turn_on": [[["target", "entity_id"], "entity"], [["for"], "text"]],
    "action:switch.turn_off": [[["target", "entity_id"], "entity"], [["for"], "text"]],
    "action:switch.toggle": [[["target", "entity_id"], "entity"], [["for"], "text"]],
    "action:light.turn_on": [[["target", "entity_id"], "entity"], [["data", "brightness"], "number"]],
    "action:scene.turn_on": [[["target", "entity_id"], "text"]],
    "action:automation.trigger": [[["target", "entity_id"], "text"]],
    "action:automation.turn_on": [[["target", "entity_id"], "text"]],
    "action:automation.turn_off": [[["target", "entity_id"], "text"]],
    "action:http_post": [[["data", "url"], "text"]],
    "action:notify.email": [[["data", "addr"], "list"], [["data", "subject"], "text"], [["data", "body"], "text"]],
    "action:mfi.event": [[["data", "key"], "text"], [["data", "msg"], "text"]],
    "action:delay": [[["delay"], "text"]],
    "action:script": [[["data", "entity_id"], "text"], [["data", "text"], "text"]],
  };

  const $ = (id) => document.getElementById(id);
  let draft = null;
  let yamlMode = false;
  let listItems = [];
  let listNotice = "";
  let errorNotes = [];
  const fieldNodes = new Map();

  // ---------------------------------------------------------------- helpers

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function option(value, text) {
    const node = el("option", "", text);
    node.value = value;
    return node;
  }

  function reportError(err) {
    console.error(err);
  }

  function postJson(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function ensureList(obj, key) {
    if (!Array.isArray(obj[key])) obj[key] = [];
    return obj[key];
  }

  function scriptEnabled() {
    const host = $("editor");
    return Boolean(host) && host.dataset.scriptEnabled === "true";
  }

  function knownDevices() {
    return Array.isArray(window.mfiDevices) ? window.mfiDevices : [];
  }

  function newId(base) {
    const stem = String(base).slice(0, 40).replace(/[^a-z0-9_]/g, "_");
    return stem + "_" + Date.now().toString(36);
  }

  function emptyDraft() {
    return { id: newId("auto"), alias: "", enabled: true, mode: "single", max: 10, triggers: [], conditions: [], actions: [] };
  }

  function getPath(obj, path) {
    return path.reduce((node, key) => (node && typeof node === "object" ? node[key] : undefined), obj);
  }

  function setPath(obj, path, value) {
    let node = obj;
    for (const key of path.slice(0, -1)) {
      if (!node[key] || typeof node[key] !== "object") node[key] = {};
      node = node[key];
    }
    const last = path[path.length - 1];
    if (value === undefined) delete node[last];
    else node[last] = value;
  }

  function displayValue(value, kind) {
    if (value === undefined || value === null) return "";
    if (kind === "list" && Array.isArray(value)) return value.join(", ");
    return String(value);
  }

  function parseValue(raw, kind) {
    const text = raw.trim();
    if (text === "") return undefined;
    if (kind === "number") {
      const number = Number(text);
      return Number.isFinite(number) ? number : text;
    }
    if (kind === "list") {
      const names = text.split(",").map((name) => name.trim()).filter((name) => name !== "");
      return names.length > 0 ? names : undefined;
    }
    return raw;
  }

  // ---------------------------------------------------------------- messages

  function showMessage(kind, text) {
    const node = $("editor-message");
    node.className = "message " + kind;
    node.textContent = text;
    node.hidden = false;
  }

  function clearMessage() {
    const node = $("editor-message");
    node.textContent = "";
    node.hidden = true;
  }

  function showYamlError(body) {
    showMessage("message--error", typeof body.detail === "string" ? body.detail : t("editor_invalid"));
  }

  function clearFieldErrors() {
    for (const node of fieldNodes.values()) {
      node.removeAttribute("aria-invalid");
      node.removeAttribute("aria-describedby");
    }
    for (const note of errorNotes) note.remove();
    errorNotes = [];
  }

  // Each detail is "<path>: <reason>"; a detail with a known field is shown under that field, the others in the message.
  function showProblems(details) {
    clearFieldErrors();
    const general = [];
    for (const detail of details) {
      const text = String(detail);
      const cut = text.indexOf(": ");
      const field = cut > 0 ? fieldNodes.get(text.slice(0, cut)) : undefined;
      if (!field) {
        general.push(text);
        continue;
      }
      const note = el("p", "errors", text.slice(cut + 2));
      note.id = "editor-error-" + errorNotes.length;
      field.setAttribute("aria-invalid", "true");
      field.setAttribute("aria-describedby", note.id);
      field.parentNode.appendChild(note);
      errorNotes.push(note);
    }
    const text = general.length > 0 ? t("editor_invalid") + ": " + general.join("; ") : t("editor_invalid");
    showMessage("message--error", text);
  }

  // ---------------------------------------------------------------- item model

  function typeName(section, item) {
    if (!item || typeof item !== "object") return "";
    if (section === "trigger") return String(item.trigger || "");
    if (section === "condition") return String(item.condition || "");
    if ("action" in item) return String(item.action);
    if ("delay" in item) return "delay";
    if ("if" in item) return "if";
    if ("choose" in item) return "choose";
    return "";
  }

  function newItem(section, type) {
    if (section === "trigger") return { trigger: type };
    if (section === "condition") {
      return NESTED_CONDITIONS.includes(type) ? { condition: type, conditions: [] } : { condition: type };
    }
    if (type === "if") return { if: [], then: [] };
    if (type === "choose") return { choose: [{ conditions: [], sequence: [] }] };
    if (type === "delay") return { delay: "00:00:00" };
    const item = { action: type };
    if (ENTITY_ACTIONS.includes(type) || TARGET_ACTIONS.includes(type)) item.target = {};
    if (DATA_ACTIONS.includes(type)) item.data = {};
    return item;
  }

  function typesFor(section) {
    if (section === "trigger") return TRIGGER_TYPES;
    if (section === "condition") return CONDITION_TYPES;
    return scriptEnabled() ? ACTION_TYPES.concat(["script"]) : ACTION_TYPES;
  }

  function entityDomain(item) {
    return item.action === "light.turn_on" ? "light" : "switch";
  }

  function entityName(domain, mac, port) {
    return domain + ".mfi_" + String(mac).replace(/:/g, "").toLowerCase() + "_" + port;
  }

  // ---------------------------------------------------------------- fields

  function labelled(text, control) {
    const label = el("label", "editor__field");
    label.append(el("span", "", text), control);
    return label;
  }

  function buildFields(item, spec, itemPath) {
    const path = spec[0];
    const kind = spec[1];
    const fieldPath = itemPath + "." + path.join(".");
    if (kind === "entity") return entityFields(item, path, fieldPath);
    const input = el("input");
    input.type = kind === "number" ? "number" : "text";
    input.value = displayValue(getPath(item, path), kind);
    input.addEventListener("input", () => setPath(item, path, parseValue(input.value, kind)));
    fieldNodes.set(fieldPath, input);
    return [labelled(path.join("."), input)];
  }

  function fillPorts(select, devices, mac, selected) {
    select.replaceChildren(option("", ""));
    const device = devices.find((candidate) => candidate.mac === mac);
    if (device) {
      for (const port of device.ports || []) select.appendChild(option(String(port), String(port)));
    }
    select.value = selected;
    select.disabled = !device;
  }

  function entityFields(item, path, fieldPath) {
    const domain = entityDomain(item);
    const devices = knownDevices();
    const current = getPath(item, path);
    const deviceSelect = el("select");
    const portSelect = el("select");
    let mac = "";
    let port = "";
    deviceSelect.appendChild(option("", ""));
    for (const device of devices) {
      deviceSelect.appendChild(option(device.mac, String(device.name || device.mac)));
      for (const number of device.ports || []) {
        if (entityName(domain, device.mac, number) === current) {
          mac = device.mac;
          port = String(number);
        }
      }
    }
    deviceSelect.value = mac;
    fillPorts(portSelect, devices, mac, port);
    deviceSelect.addEventListener("change", () => {
      fillPorts(portSelect, devices, deviceSelect.value, "");
      setPath(item, path, undefined);
    });
    portSelect.addEventListener("change", () => {
      const value = portSelect.value === "" ? undefined : entityName(domain, deviceSelect.value, portSelect.value);
      setPath(item, path, value);
    });
    fieldNodes.set(fieldPath, portSelect);
    return [labelled(t("editor_device"), deviceSelect), labelled(t("editor_port"), portSelect)];
  }

  // ---------------------------------------------------------------- nested lists

  function addChooser(section, list, host) {
    const old = host.querySelector(".editor__chooser");
    if (old) old.remove();
    const select = el("select", "editor__chooser");
    const placeholder = option("", t("editor_select_type"));
    placeholder.disabled = true;
    placeholder.selected = true;
    select.appendChild(placeholder);
    for (const type of typesFor(section)) select.appendChild(option(type, type));
    select.addEventListener("change", () => {
      if (select.value === "") return;
      list.push(newItem(section, select.value));
      renderForm();
    });
    host.appendChild(select);
    select.focus();
  }

  function addButton(section, list, host) {
    const button = el("button", "button", t("editor_add"));
    button.type = "button";
    button.addEventListener("click", () => addChooser(section, list, host));
    return button;
  }

  function nestedBlock(parent, key, parentPath, section) {
    const list = ensureList(parent, key);
    const wrap = el("div", "editor__nested");
    const host = el("div", "editor__list");
    renderItems(list, section, parentPath + "." + key, host);
    wrap.append(host, addButton(section, list, host));
    return wrap;
  }

  function branchesBlock(item, itemPath) {
    const branches = ensureList(item, "choose");
    const wrap = el("div", "editor__nested");
    const host = el("div", "editor__list");
    branches.forEach((branch, index) => {
      if (!branch || typeof branch !== "object") return;
      const branchPath = itemPath + ".choose[" + index + "]";
      const card = el("div", "editor__item");
      card.appendChild(el("span", "tag tag--other editor__type", "#" + (index + 1)));
      card.append(
        nestedBlock(branch, "conditions", branchPath, "condition"),
        nestedBlock(branch, "sequence", branchPath, "action")
      );
      host.appendChild(card);
    });
    const add = el("button", "button", t("editor_add"));
    add.type = "button";
    add.addEventListener("click", () => {
      branches.push({ conditions: [], sequence: [] });
      renderForm();
    });
    wrap.append(host, add);
    return wrap;
  }

  function appendNested(card, item, section, type, itemPath) {
    if (section === "condition" && NESTED_CONDITIONS.includes(type)) {
      card.appendChild(nestedBlock(item, "conditions", itemPath, "condition"));
    } else if (type === "if") {
      card.appendChild(nestedBlock(item, "if", itemPath, "condition"));
      card.appendChild(nestedBlock(item, "then", itemPath, "action"));
      if (Array.isArray(item.else)) card.appendChild(nestedBlock(item, "else", itemPath, "action"));
    } else if (type === "choose") {
      card.appendChild(branchesBlock(item, itemPath));
      if (Array.isArray(item.default)) card.appendChild(nestedBlock(item, "default", itemPath, "action"));
    }
  }

  // ---------------------------------------------------------------- form

  function renderCard(list, index, section, itemPath) {
    const item = list[index];
    const type = typeName(section, item);
    const card = el("div", "editor__item");
    const remove = el("button", "button button--danger", t("editor_remove"));
    remove.type = "button";
    remove.addEventListener("click", () => {
      list.splice(index, 1);
      renderForm();
    });
    const head = el("div", "editor__head");
    head.append(el("span", "tag tag--known editor__type", type), remove);
    card.appendChild(head);
    if (type === "script") card.appendChild(el("p", "message editor__warning", t("editor_script_warning")));
    const fields = el("div", "editor__fields");
    for (const spec of FIELDS[section + ":" + type] || []) {
      fields.append(...buildFields(item, spec, itemPath));
    }
    card.appendChild(fields);
    appendNested(card, item, section, type, itemPath);
    return card;
  }

  function renderItems(list, section, basePath, host) {
    host.replaceChildren();
    list.forEach((item, index) => {
      host.appendChild(renderCard(list, index, section, basePath + "[" + index + "]"));
    });
  }

  function renderForm() {
    clearFieldErrors();
    fieldNodes.clear();
    if (!draft) return;
    renderItems(ensureList(draft, "triggers"), "trigger", "triggers", $(SECTION_IDS.trigger));
    renderItems(ensureList(draft, "conditions"), "condition", "conditions", $(SECTION_IDS.condition));
    renderItems(ensureList(draft, "actions"), "action", "actions", $(SECTION_IDS.action));
  }

  function addTop(section) {
    if (!draft) return;
    addChooser(section, ensureList(draft, LIST_KEYS[section]), $(SECTION_IDS[section]));
  }

  function syncAlias() {
    if (!draft) return;
    const value = $("editor-alias").value.trim();
    if (value) draft.alias = value;
    else delete draft.alias;
  }

  function showDraft() {
    $("editor-alias").value = draft.alias || "";
    renderForm();
  }

  function setYamlMode(on) {
    yamlMode = on;
    $("editor-yaml").hidden = !on;
    for (const id of Object.values(SECTION_IDS)) {
      $(id).closest(".editor__section").hidden = on;
    }
    $("editor-toggle-yaml").textContent = t(on ? "editor_switch_form" : "editor_switch_yaml");
  }

  function openEditor(automation) {
    draft = automation ? clone(automation) : emptyDraft();
    clearMessage();
    setYamlMode(false);
    $("editor-form").hidden = false;
    showDraft();
    loadTraces(automation ? automation.id : "").catch(reportError);
  }

  function closeEditor() {
    draft = null;
    clearMessage();
    clearFieldErrors();
    fieldNodes.clear();
    $("editor-form").hidden = true;
  }

  async function toggleYaml() {
    if (!draft) return;
    clearMessage();
    if (!yamlMode) {
      syncAlias();
      const response = await postJson("api/v1/editor/to_yaml", { automation: draft });
      if (!response.ok) {
        showMessage("message--error", t("editor_invalid"));
        return;
      }
      const body = await response.json();
      $("editor-yaml").value = body.yaml;
      setYamlMode(true);
      return;
    }
    const response = await postJson("api/v1/editor/from_yaml", { yaml: $("editor-yaml").value });
    const body = await response.json();
    if (!response.ok) {
      showYamlError(body);
      return;
    }
    draft = body.automation;
    setYamlMode(false);
    showDraft();
  }

  async function saveDraft() {
    if (!draft) return;
    clearMessage();
    let automation = draft;
    if (yamlMode) {
      const parsed = await postJson("api/v1/editor/from_yaml", { yaml: $("editor-yaml").value });
      const parsedBody = await parsed.json();
      if (!parsed.ok) {
        showYamlError(parsedBody);
        return;
      }
      automation = parsedBody.automation;
    } else {
      syncAlias();
    }
    const response = await postJson("api/v1/editor/save", { automation: automation });
    if (response.status === 400) {
      const body = await response.json();
      showProblems(Array.isArray(body.details) ? body.details : []);
      return;
    }
    if (!response.ok) {
      showMessage("message--error", t("editor_invalid"));
      return;
    }
    const saved = await response.json();
    draft = saved.automation;
    if (!yamlMode) showDraft();
    await loadList();
    showMessage("message--ok", t("editor_saved"));
  }

  // ---------------------------------------------------------------- list

  function listRow(automation) {
    const row = el("div", "panel editor__row");
    const enabled = automation.enabled === true;
    const name = el("span", "editor__name", String(automation.alias || automation.id || ""));
    const toggle = el("button", "switch", t(enabled ? "editor_disable" : "editor_enable"));
    toggle.type = "button";
    toggle.setAttribute("aria-pressed", enabled ? "true" : "false");
    toggle.addEventListener("click", () => {
      setEnabled(automation).catch(reportError);
    });
    const edit = el("button", "button", t("editor_edit"));
    edit.type = "button";
    edit.addEventListener("click", () => openEditor(automation));
    const copy = el("button", "button", t("editor_copy"));
    copy.type = "button";
    copy.addEventListener("click", () => {
      copyAutomation(automation).catch(reportError);
    });
    row.append(name, toggle, edit, copy);
    return row;
  }

  function renderList() {
    const host = $("editor-list");
    host.replaceChildren();
    if (listNotice) host.appendChild(el("p", "message message--error", listNotice));
    for (const automation of listItems) host.appendChild(listRow(automation));
  }

  async function loadList() {
    const response = await fetch("api/v1/rules");
    if (response.status === 401) {
      listItems = [];
      renderList();
      return;
    }
    if (!response.ok) throw new Error("rules request failed: " + response.status);
    const body = await response.json();
    listItems = Array.isArray(body.automations) ? body.automations : [];
    renderList();
  }

  // Enable and copy both go through the save route: the automation is sent with enabled changed, or with a new id.
  async function saveFromList(automation) {
    const response = await postJson("api/v1/editor/save", { automation: automation });
    if (!response.ok) {
      listNotice = t("editor_invalid");
      renderList();
      return;
    }
    listNotice = "";
    if (draft && draft.id === automation.id) draft.enabled = automation.enabled;
    await loadList();
  }

  async function setEnabled(automation) {
    const copy = clone(automation);
    copy.enabled = !automation.enabled;
    await saveFromList(copy);
  }

  async function copyAutomation(automation) {
    const copy = clone(automation);
    copy.id = newId(automation.id);
    await saveFromList(copy);
  }

  // ---------------------------------------------------------------- traces

  function formatTraceTime(seconds) {
    if (typeof seconds !== "number") return "";
    return new Date(seconds * 1000).toLocaleString(document.documentElement.lang || undefined);
  }

  function traceRow(trace) {
    const result = String(trace.result);
    const resultCell = el("td");
    resultCell.appendChild(el("span", result === "finished" ? "tag tag--known" : "tag tag--other", result));
    const row = el("tr");
    row.append(
      el("td", "editor__time", formatTraceTime(trace.start)),
      el("td", "", String(trace.trigger || "")),
      resultCell
    );
    return row;
  }

  function traceTable(traces) {
    const wrap = el("div", "table-wrap");
    const table = el("table", "table");
    const head = el("tr");
    for (const key of ["trace_time", "trace_trigger", "trace_result"]) head.appendChild(el("th", "", t(key)));
    const thead = el("thead");
    thead.appendChild(head);
    const tbody = el("tbody");
    for (const trace of traces) tbody.appendChild(traceRow(trace));
    table.append(thead, tbody);
    wrap.appendChild(table);
    return wrap;
  }

  async function loadTraces(id) {
    const host = $("editor-traces");
    host.replaceChildren();
    if (!id) {
      host.appendChild(el("p", "empty", t("editor_no_traces")));
      return;
    }
    const response = await fetch("api/v1/editor/traces/" + encodeURIComponent(id));
    const body = response.ok ? await response.json() : {};
    const traces = Array.isArray(body.traces) ? body.traces : [];
    if (traces.length === 0) {
      host.appendChild(el("p", "empty", t("editor_no_traces")));
      return;
    }
    host.appendChild(traceTable(traces));
  }

  // ---------------------------------------------------------------- start

  function refreshIfVisible() {
    if (location.hash === "#view-rules") loadList().catch(reportError);
  }

  function bindEvents() {
    $("editor-open").addEventListener("click", () => openEditor(null));
    $("editor-cancel").addEventListener("click", closeEditor);
    $("editor-save").addEventListener("click", () => {
      saveDraft().catch(reportError);
    });
    $("editor-toggle-yaml").addEventListener("click", () => {
      toggleYaml().catch(reportError);
    });
    $("editor-add-trigger").addEventListener("click", () => addTop("trigger"));
    $("editor-add-condition").addEventListener("click", () => addTop("condition"));
    $("editor-add-action").addEventListener("click", () => addTop("action"));
    window.addEventListener("hashchange", refreshIfVisible);
    const lang = $("lang");
    if (lang) {
      // app.js translates the page on the same change; the editor texts are redrawn after it.
      lang.addEventListener("change", () => {
        renderList();
        if (draft) renderForm();
        setYamlMode(yamlMode);
      });
    }
  }

  function start() {
    if (!$("editor")) return;
    bindEvents();
    refreshIfVisible();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
