"use strict";
// The interface and console themes and the console font, kept in this browser. Loaded without defer, before the body,
// so the page paints in its theme from the start; app.js and panels.js read the settings from here.

const THEME_KEY = "ctokens.theme";
const THEME_DEFAULTS = { ui: "system", console: "ui", font: '"Ubuntu Mono derivative Powerline", "Ubuntu Mono"', size: 11,
  lineHeight: 1.2 };
const THEME_CHOICES = { ui: ["system", "light", "dark"], console: ["ui", "light", "dark"] };
const systemDark = matchMedia("(prefers-color-scheme: dark)");
let themeSaved = readThemeSaved();

function readThemeSaved() {
  try {
    const saved = JSON.parse(localStorage.getItem(THEME_KEY) || "{}");
    return saved && typeof saved === "object" ? saved : {};
  } catch (e) {
    return {};
  }
}

function themeSettings() {
  const saved = themeSaved, s = { ...THEME_DEFAULTS };
  for (const k of ["ui", "console"]) if (THEME_CHOICES[k].includes(saved[k])) s[k] = saved[k];
  if (typeof saved.font === "string") s.font = saved.font.trim().slice(0, 300);
  if (Number(saved.size) >= 6 && Number(saved.size) <= 40) s.size = Number(saved.size);
  if (Number(saved.lineHeight) >= 1 && Number(saved.lineHeight) <= 3) s.lineHeight = Number(saved.lineHeight);
  return s;
}

function resolvedThemes() {
  const s = themeSettings(), ui = s.ui === "system" ? (systemDark.matches ? "dark" : "light") : s.ui;
  return { ui, term: s.console === "ui" ? ui : s.console };
}

// themechange tells the page to draw again: charts and model colours read the CSS variables of the interface theme.
function applyTheme(always) {
  const root = document.documentElement, { ui, term } = resolvedThemes();
  const detail = { ui: root.dataset.theme !== ui, term: root.dataset.console !== term };
  root.dataset.theme = ui;
  root.dataset.console = term;
  for (const link of document.querySelectorAll("link[data-hljs]")) link.media = link.dataset.hljs === ui ? "all" : "not all";
  if (always || detail.ui || detail.term) window.dispatchEvent(new CustomEvent("themechange", { detail }));
}

function saveThemeSettings(patch) {
  themeSaved = patch ? { ...themeSettings(), ...patch } : {};
  try {
    if (patch) localStorage.setItem(THEME_KEY, JSON.stringify(themeSaved));
    else localStorage.removeItem(THEME_KEY);
  } catch (e) { /* kept for this page only */ }
  applyTheme(true);
}

applyTheme();
systemDark.addEventListener("change", () => applyTheme());
// Another tab of the app changed them.
window.addEventListener("storage", (e) => {
  if (e.key !== THEME_KEY && e.key !== null) return;
  themeSaved = readThemeSaved();
  applyTheme(true);
});
