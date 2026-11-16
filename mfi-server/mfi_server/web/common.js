"use strict";

// Shared helpers for the mFi Server pages: translations, language selector and DOM helpers.
// Loaded before app.js and automations.js on every page. No libraries, relative addresses only.

const LANG_KEY = "mfi_lang";
const strings = {};
let lang = "en";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

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
  const sel = document.getElementById("lang");
  if (sel) sel.value = lang;
}

function setLang(code, onChange) {
  lang = code;
  localStorage.setItem(LANG_KEY, code);
  document.documentElement.lang = code;
  applyTranslations();
  if (onChange) onChange();
}
