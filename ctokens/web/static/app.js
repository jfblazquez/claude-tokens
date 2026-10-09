"use strict";

// ---------- DOM helpers: every text value goes through text nodes (R2.7) ----------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "css") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  append(el, kids);
  return el;
}

function append(el, kids) {
  for (const kid of [kids].flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const $ = (id) => document.getElementById(id);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---------- formatting, as in the CLI (ctokens/text.py) ----------
function fmt(n) {
  if (n == null || Number.isNaN(n)) return "N/D";
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

function money(amount, estimated, digits = 4) {
  if (amount == null) return "N/D";
  return `${estimated ? "~" : ""}$${Number(amount).toFixed(digits)}`;
}

const pct = (x) => (x == null ? "N/D" : `${(x * 100).toFixed(1)}%`);

function utcTime(date) {
  return date.toISOString().slice(11, 19);
}

function utcMinute(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso || "") : d.toISOString().slice(0, 16).replace("T", " ");
}

// Long paths and tool names may wrap after a separator instead of widening their table.
const breakable = (text) => String(text == null ? "" : text).split(/(?<=\/|__|:)/).flatMap((part, i) => (i ? [h("wbr"), part] : [part]));

// ---------- copy to clipboard ----------
const COPY_FEEDBACK_MS = 1500;

const SVG_NS = "http://www.w3.org/2000/svg";
const ICON_PATHS = {
  clipboard: ["M9 2h6a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z",
    "M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"],
  check: ["M20 6 9 17l-5-5"],
  failed: ["M18 6 6 18", "m6 6 12 12"],
};

function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  for (const [k, v] of [["viewBox", "0 0 24 24"], ["class", "icon"], ["aria-hidden", "true"]]) svg.setAttribute(k, v);
  for (const d of ICON_PATHS[name]) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

// show(true | false) right after the copy, show(null) once the feedback expires.
function copyText(text, el, show) {
  const done = (ok) => {
    show(ok);
    clearTimeout(el.copyTimer);
    el.copyTimer = setTimeout(() => show(null), COPY_FEEDBACK_MS);
  };
  const write = navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject(new Error("no clipboard"));
  write.then(() => done(true), () => done(false));
}

// Copies the original value, not the rendered text, which may be truncated or carry <wbr> breaks.
function copyable(el, value) {
  el.classList.add("copyable");
  el.title = "Double-click to copy";
  el.addEventListener("dblclick", () => {
    getSelection().removeAllRanges();
    copyText(value, el, (ok) => {
      if (ok == null) delete el.dataset.copied;
      else el.dataset.copied = ok ? "Copied" : "Copy failed";
    });
  });
  return el;
}

// Without a label the button shows only the clipboard icon, so the title doubles as its accessible name.
function copyButton(text, title, label = null) {
  const idle = () => label || icon("clipboard");
  const button = h("button", { class: label ? "btn copy-btn" : "btn copy-btn icon-btn", type: "button", title,
    "aria-label": label ? null : title }, idle());
  button.addEventListener("click", () => copyText(text, button, (ok) => {
    if (ok == null) button.replaceChildren(idle());
    else button.replaceChildren(label ? (ok ? "Copied" : "Copy failed") : icon(ok ? "check" : "failed"));
  }));
  return button;
}

const shellQuote = (s) => (/^[\w@%+=:,./-]+$/.test(s) ? s : `'${s.replace(/'/g, "'\\''")}'`);

const pathCell = (text, copy) => {
  const cell = h("span", { class: "mono" }, breakable(text));
  return copy ? copyable(cell, String(text)) : cell;
};
const pathCol = (key, label, copy = false) => ({ key, label, cls: "path", render: (r) => pathCell(r[key], copy) });

function guessedNotice(models) {
  return `~ estimated price: no published rate for ${models.join(", ")}; priced from the newest known model of the same `
    + "family. Use --pricing to set the real rate.";
}

function pricingNotices(data) {
  const out = [];
  if ((data.guessed_price_models || []).length) {
    out.push(h("div", { class: "notice", role: "note" }, guessedNotice(data.guessed_price_models)));
  }
  if ((data.unknown_price_models || []).length) {
    out.push(h("div", { class: "notice", role: "note" }, `Models without pricing: ${data.unknown_price_models.join(", ")}. `
      + "Their tokens are counted but their cost shows as N/D."));
  }
  return out;
}

// ---------- sorting ----------
function compareValues(x, y) {
  if (typeof x === "number" && typeof y === "number") return x - y;
  return String(x).localeCompare(String(y), undefined, { numeric: true, sensitivity: "base" });
}

// Missing values sort last in both directions.
function sortRows(rows, value, dir) {
  return [...rows].sort((a, b) => {
    const x = value(a), y = value(b);
    const xn = x == null || x === "", yn = y == null || y === "";
    if (xn || yn) return xn === yn ? 0 : xn ? 1 : -1;
    return compareValues(x, y) * dir;
  });
}

// ---------- generic table with click-to-sort (R3.4, R11.4) ----------
const sortMemory = new Map();

function countBy(rows, key) {
  const counts = new Map();
  for (const r of rows) counts.set(key(r), (counts.get(key(r)) || 0) + 1);
  return counts;
}

// opts.group = { key, label(row) } adds a header row per label while the table is sorted by that key;
// opts.pageSize/page/onPage show one page of the sorted rows at a time.
function renderTable(columns, rows, opts = {}) {
  const remembered = opts.id && sortMemory.get(opts.id);
  let sortKey = remembered ? remembered.key : opts.sortKey || null;
  let dir = remembered ? remembered.dir : opts.dir || -1;
  let page = opts.page || 0;
  const wrap = h("div", { class: "card scroll" });
  const pager = opts.pageSize ? h("nav", { class: "pager", "aria-label": "Pages" }) : null;
  const cls = (...names) => names.filter(Boolean).join(" ") || null;
  const setPage = (n) => {
    page = n;
    if (opts.onPage) opts.onPage(page);
  };

  function drawPager(total) {
    const pages = Math.max(1, Math.ceil(total / opts.pageSize));
    const first = page * opts.pageSize;
    const go = (n) => () => {
      setPage(n);
      draw();
      window.scrollTo(0, 0);
    };
    const button = (label, n, title) => h("button", { class: "btn", type: "button", title, disabled: n === page || n < 0 || n >= pages, onclick: go(n) }, label);
    pager.hidden = pages < 2;
    pager.replaceChildren(button("«", 0, "First page"), button("‹ Previous", page - 1, "Previous page"),
      h("span", { class: "count" }, `${fmt(first + 1)}–${fmt(Math.min(first + opts.pageSize, total))} of ${fmt(total)} · page ${fmt(page + 1)} of ${fmt(pages)}`),
      button("Next ›", page + 1, "Next page"), button("»", pages - 1, "Last page"));
  }

  function draw() {
    const col = columns.find((c) => c.key === sortKey);
    const data = col ? sortRows(rows, col.sortValue || ((r) => r[col.key]), dir) : rows;
    if (pager) setPage(Math.min(page, Math.max(0, Math.ceil(data.length / opts.pageSize) - 1)));
    const shown = pager ? data.slice(page * opts.pageSize, (page + 1) * opts.pageSize) : data;
    const head = h("tr", {}, columns.map((c) => {
      const active = sortKey === c.key;
      const button = h("button", {
        class: "sort", type: "button", title: `Sort by ${c.label}`,
        onclick: () => {
          if (active) dir = -dir;
          else { sortKey = c.key; dir = c.num ? -1 : 1; }
          if (opts.id) sortMemory.set(opts.id, { key: sortKey, dir });
          setPage(0);
          draw();
        },
      }, c.label, h("span", { class: "ind", "aria-hidden": "true" }, active ? (dir > 0 ? "▲" : "▼") : ""));
      return h("th", { class: cls(c.num && "num"), scope: "col",
        "aria-sort": active ? (dir > 0 ? "ascending" : "descending") : null }, button);
    }));
    const group = opts.group && opts.group.key === sortKey ? opts.group.label : null;
    // Group sizes count every row, not only this page, so a group cut by a page break still shows its full size.
    const sizes = group ? countBy(data, group) : null;
    const body = [];
    let current = null;
    for (const r of shown) {
      if (group && group(r) !== current) {
        current = group(r);
        body.push(h("tr", { class: "group" }, h("th", { colspan: columns.length, scope: "colgroup" }, current,
          h("span", { class: "n" }, fmt(sizes.get(current))))));
      }
      body.push(h("tr", {
        class: cls(opts.onRow && "link"),
        onclick: opts.onRow ? (e) => { if (!e.target.closest("a")) opts.onRow(r); } : null,
      }, columns.map((c) => h("td", { class: cls(c.num && "num", c.cls) }, c.render ? c.render(r) : r[c.key]))));
    }
    const foot = opts.footer
      ? h("tfoot", {}, h("tr", { class: "total" }, opts.footer.map((cell, i) => h("td", { class: cls(columns[i] && columns[i].num && "num") }, cell))))
      : null;
    wrap.replaceChildren(h("table", {}, h("thead", {}, head), h("tbody", {}, body), foot));
    if (pager) drawPager(data.length);
  }

  draw();
  return pager ? h("div", { class: "paged" }, wrap, pager) : wrap;
}

// ---------- states (R11.5) ----------
function skeleton(lines = 6, note = null) {
  return h("div", { class: "card", "aria-busy": "true" },
    note ? h("div", { class: "state loading" }, h("div", { class: "spinner", role: "status", "aria-label": "Loading" }),
      h("div", { class: "body" }, note)) : null,
    h("div", { class: "skel", role: note ? null : "status", "aria-label": note ? null : "Loading" },
      Array.from({ length: lines }, () => h("i"))));
}

function emptyState(title, body) {
  return h("div", { class: "card state" }, h("div", { class: "title" }, title), h("div", { class: "body" }, body));
}

function errorState(err, retry) {
  const projects = err && err.body && Array.isArray(err.body.projects) ? err.body.projects : null;
  return h("div", { class: "card state error", role: "alert" },
    h("div", { class: "title" }, "Couldn't load this view"),
    h("div", { class: "body" }, err && err.message ? err.message : String(err)),
    projects ? h("div", { class: "body" }, "This conversation id exists in more than one project, so the server cannot tell which "
      + "one to show. Matching projects: ", projects.map((p, i) => [i ? ", " : "", h("span", { class: "mono" }, p)])) : null,
    h("button", { class: "btn", type: "button", onclick: retry }, "Retry"));
}

// ---------- API ----------
class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function api(path) {
  let response;
  try {
    response = await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store" });
  } catch (_) {
    throw new ApiError("Could not reach the server. Check that claude_tokens.py --serve is still running, then retry.", 0, null);
  }
  let body = null;
  try {
    body = await response.json();
  } catch (_) {
    body = null;
  }
  if (!response.ok) {
    const message = body && typeof body.error === "string" ? body.error : `The server answered ${response.status} ${response.statusText}`;
    throw new ApiError(message.trim(), response.status, body);
  }
  if (body == null) throw new ApiError("The server sent a response that is not valid JSON.", response.status, null);
  return body;
}

const withProject = (path, project) => (project ? `${path}?project=${encodeURIComponent(project)}` : path);

// ---------- router (design §8.1) ----------
function parseRoute(hash) {
  const path = String(hash || "").replace(/^#/, "") || "/";
  if (path === "/") return { view: "list" };
  if (path === "/totals") return { view: "totals" };
  const m = path.match(/^\/c\/([^/]+)(?:\/(messages|response|bash|files))?\/?$/);
  if (m) {
    try {
      return { view: m[2] || "report", id: decodeURIComponent(m[1]) };
    } catch (_) {
      return { view: "notfound" };
    }
  }
  return { view: "notfound" };
}

const convHref = (id, tab) => `#/c/${encodeURIComponent(id)}${tab && tab !== "report" ? `/${tab}` : ""}`;

// A view is { title(route), load(route) -> Promise<data>, render(data, route) -> nodes, head?, loading?, after? }.
const VIEWS = {
  notfound: {
    title: () => "Not found",
    load: async () => null,
    render: () => [h("div", { class: "page-head" }, h("h1", {}, "Page not found")),
      h("div", { class: "card state" }, h("div", { class: "body" }, "This address does not match any view."),
        h("a", { href: "#/" }, "Go to the conversation list"))],
  },
};

// ---------- model colours (R11.1, design §8.4) ----------
const FAMILY_SLOT = { opus: 0, sonnet: 1, haiku: 2, fable: 3, mythos: 4 };
const FIRST_FREE_SLOT = 5, LAST_SLOT = 7;

const familyOf = (model) => Object.keys(FAMILY_SLOT).find((f) => String(model).toLowerCase().includes(f)) || null;
const versionOf = (model) => String(model).split("-").filter((p) => /^\d+$/.test(p)).map(Number);

function compareVersionsDesc(a, b) {
  const va = versionOf(a), vb = versionOf(b);
  for (let i = 0; i < Math.max(va.length, vb.length); i++) {
    const d = (vb[i] || 0) - (va[i] || 0);
    if (d) return d;
  }
  return 0;
}

function mixHex(a, b, weight) {
  const parse = (x) => [1, 3, 5].map((i) => parseInt(x.slice(i, i + 2), 16));
  const [p, q] = [parse(a), parse(b)];
  return `#${p.map((v, i) => Math.round(v * (1 - weight) + q[i] * weight).toString(16).padStart(2, "0")).join("")}`;
}

// models: every model seen this session, in order of first appearance; palette: the 8 --mN colours.
function assignColors(models, palette, surface) {
  const colors = {}, perFamily = {};
  for (const m of models.filter(familyOf).sort(compareVersionsDesc)) {
    const fam = familyOf(m), n = (perFamily[fam] = (perFamily[fam] || 0) + 1);
    const base = palette[FAMILY_SLOT[fam]];
    colors[m] = n === 1 ? base : mixHex(base, surface, n === 2 ? 0.38 : 0.55);
  }
  let slot = FIRST_FREE_SLOT;
  for (const m of models) if (!familyOf(m)) colors[m] = palette[Math.min(slot++, LAST_SLOT)];
  return colors;
}

const seenModels = [];
const colorState = { palette: null, surface: null, size: -1, colors: {} };

// Registers every model of a response before rendering, so one render never sees the assignment change midway.
function noteModels(value) {
  const add = (m) => { if (!seenModels.includes(m)) seenModels.push(m); };
  const visit = (v) => {
    if (!v || typeof v !== "object") return;
    if (Array.isArray(v)) { v.forEach(visit); return; }
    if (typeof v.model === "string") add(v.model);
    if (v.models && typeof v.models === "object" && !Array.isArray(v.models)) Object.keys(v.models).forEach(add);
    Object.values(v).forEach(visit);
  };
  visit(value);
}

function readPalette() {
  colorState.palette = Array.from({ length: LAST_SLOT + 1 }, (_, i) => cssVar(`--m${i}`));
  colorState.surface = cssVar("--surface");
  colorState.size = -1;
}

function colorOf(model) {
  if (!seenModels.includes(model)) seenModels.push(model);
  if (!colorState.palette) readPalette();
  if (colorState.size !== seenModels.length) {
    colorState.colors = assignColors(seenModels, colorState.palette, colorState.surface);
    colorState.size = seenModels.length;
  }
  return colorState.colors[model];
}

const swatch = (model) => h("span", { class: "sw", "aria-hidden": "true", css: { background: colorOf(model) } });
const modelCell = (model) => [swatch(model), model];

// ---------- conversation list (R3) ----------
const convRows = new Map();
const convTasks = new Map();
const convCounts = new Map();

let projectsDir = null;

function listRows(body) {
  const rows = Array.isArray(body) ? body : (body && body.conversations) || [];
  if (body && typeof body.projects_dir === "string") projectsDir = body.projects_dir;
  for (const row of [...rows].reverse()) convRows.set(row.id, row);
  return rows;
}

const folderLabel = () => (projectsDir ? copyable(h("b", { class: "mono" }, projectsDir), projectsDir) : "the projects folder");
const folderText = () => projectsDir || "the projects folder";

const pathTail = (path) => String(path || "").split(/[\\/]/).filter(Boolean).slice(-2).join("/");
// The last two levels of a path, so a deep project folder does not widen the list.
const shortPath = (path) => (String(path || "").split(/[\\/]/).filter(Boolean).length > 2 ? `…/${pathTail(path)}` : String(path || ""));

const projectMatches = (row, filter) => !filter || String(row.project || "").toLowerCase().includes(filter.toLowerCase());

let listFilter = "";
let listSearch = "";
let listSearchDraft = "";
let listSearchTimer = null;
// Long enough to skip the requests of a word still being typed; a cached search answers in ~30 ms.
const SEARCH_DEBOUNCE_MS = 300;
const LIST_PAGE_SIZE = 50;
// The last list shown, its page and scroll, so coming back from a conversation redraws it at once.
const listState = { data: null, at: null, page: 0, scrollY: 0 };

function applyListSearch(value) {
  clearTimeout(listSearchTimer);
  const next = value.trim();
  if (next === listSearch) return;
  listSearch = next;
  listState.page = 0;
  show({ keepScroll: true });
  load({ refresh: true });
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// UTC days, like every time in the UI; weeks start on Monday.
function dateGroup(iso, now) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "No date";
  const day = Math.floor(t / DAY_MS), today = Math.floor(now / DAY_MS);
  const weekStart = today - ((new Date(now).getUTCDay() + 6) % 7);
  if (day >= today) return "Today";
  if (day === today - 1) return "Yesterday";
  if (day >= weekStart) return "This week";
  if (day >= weekStart - 7) return "Last week";
  const date = new Date(t), current = new Date(now);
  if (date.getUTCFullYear() === current.getUTCFullYear() && date.getUTCMonth() === current.getUTCMonth()) return "Earlier this month";
  return `${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

function listCount(data) {
  if (data && data.search !== listSearch) return [h("span", { class: "spinner small", "aria-hidden": "true" }), "Searching…"];
  if (!data) return "";
  const shown = data.rows.filter((r) => projectMatches(r, listFilter)).length;
  return data.search ? `${fmt(shown)} conversations containing “${data.search}”` : `${fmt(shown)} of ${fmt(data.rows.length)} conversations`;
}

VIEWS.list = {
  title: () => "Conversations",
  async load() {
    const search = listSearch;
    const data = { search, rows: listRows(await api(search ? `/api/conversations?q=${encodeURIComponent(search)}` : "/api/conversations")) };
    Object.assign(listState, { data, at: new Date() });
    return data;
  },
  // Shown at once and reloaded behind it, since new conversations may have appeared meanwhile.
  cached: () => (listState.data && listState.data.search === listSearch
    ? { data: listState.data, at: listState.at, stale: true, scrollY: listState.scrollY } : null),
  leave: () => { listState.scrollY = window.scrollY; },
  head(route, data) {
    const count = h("span", { class: "count", "aria-live": "polite" }, listCount(app.phase === "ready" ? data : null));
    const project = h("input", { id: "list-filter", type: "search", placeholder: "Filter by project path", value: listFilter, "aria-label": "Filter by project",
      oninput: (e) => { listFilter = e.target.value; listState.page = 0; show({ keepScroll: true }); } });
    const search = h("input", { id: "list-search", type: "search", placeholder: "Word or phrase in the title or messages", value: listSearchDraft,
      "aria-label": "Search conversations",
      oninput: (e) => {
        listSearchDraft = e.target.value;
        clearTimeout(listSearchTimer);
        listSearchTimer = setTimeout(() => applyListSearch(listSearchDraft), SEARCH_DEBOUNCE_MS);
      },
      onchange: (e) => applyListSearch(e.target.value),
      onsearch: (e) => applyListSearch(e.target.value) });
    return [h("div", { class: "page-head" }, h("h1", {}, "Conversations"),
      h("div", { class: "meta" }, projectsDir ? h("span", {}, "Projects folder ", folderLabel()) : null,
        h("span", {}, "Most recent first · times in UTC"))),
    h("div", { class: "toolbar" }, h("div", { class: "filters" }, h("label", { class: "field" }, "Project", project),
      h("label", { class: "field" }, "Search", search)), count)];
  },
  render({ search, rows }) {
    if (!rows.length && !search) {
      return emptyState("No conversations found", `No conversations were found in ${folderText()}. `
        + "Conversations appear here after you use Claude Code.");
    }
    const shown = rows.filter((r) => projectMatches(r, listFilter));
    if (!shown.length) {
      const why = [listFilter && `a project matching “${listFilter}”`, search && `“${search}” in its title or messages`];
      return emptyState("No matching conversations", `No conversation has ${why.filter(Boolean).join(" and ")}.`);
    }
    const now = Date.now();
    return h("div", { class: "section" }, renderTable([
      { key: "modified", label: "Modified (UTC)", render: (r) => h("span", { class: "mono" }, utcMinute(r.modified)) },
      { key: "title", label: "Title", cls: "wrap",
        render: (r) => h("a", { href: convHref(r.id) }, r.title ? r.title : h("span", { class: "muted" }, "Untitled")) },
      { key: "project", label: "Project", cls: "path", sortValue: (r) => pathTail(r.project),
        render: (r) => h("span", { class: "mono", title: r.project }, breakable(shortPath(r.project))) },
      { key: "size_kb", label: "Size KB", num: true, render: (r) => fmt(r.size_kb) },
      { key: "subagents", label: "Subagents", num: true, render: (r) => fmt(r.subagents) },
      { key: "id", label: "Conversation id", render: (r) => h("span", { class: "mono muted" }, r.id) },
    ], shown, { id: "list", sortKey: "modified", dir: -1, onRow: (r) => { location.hash = convHref(r.id); },
      group: { key: "modified", label: (r) => dateGroup(r.modified, now) },
      pageSize: LIST_PAGE_SIZE, page: listState.page, onPage: (page) => { listState.page = page; } }));
  },
};

// ---------- conversation header and tabs (R4.5) ----------
const TABS = [["report", "Usage"], ["messages", "Conversation"], ["response", "Last response"], ["bash", "Bash commands"], ["files", "Files"]];

async function refreshList() {
  try {
    listRows(await api("/api/conversations"));
  } catch (_) {
    // The header falls back to the id; the view itself reports its own errors.
  }
}

// ---------- conversation cache: every tab of the open conversation, kept until the list is shown again ----------
// path (API suffix) -> { promise, data, at, stale }; data stays undefined until the first answer.
const convCache = { id: null, entries: new Map() };
const PREFETCHED = ["", "/messages", "/last-response", "/bash", "/files"];

function convEntries(id) {
  if (convCache.id !== id) Object.assign(convCache, { id, entries: new Map() });
  return convCache.entries;
}

function clearConvCache() {
  Object.assign(convCache, { id: null, entries: new Map() });
  messagesState.anchor = null;
}

// Tab counts and the fallback title come from whichever answer arrives first, prefetched or not; true when one changed.
function noteConvData(id, path, data) {
  if (path === "") {
    const main = (data.conversations || []).find((c) => c.kind === "main");
    if (!main || !main.task || convTasks.get(id) === main.task) return false;
    convTasks.set(id, main.task);
    return true;
  }
  if (path === "/messages") return setCount(id, "messages", visibleMessages(data.messages || []).length);
  if (path === "/bash") return setCount(id, "bash", (data.bash_commands || []).length);
  if (path === "/files") return setCount(id, "files", Object.keys(data.files || {}).length);
  return false;
}

function fetchConv(id, path, force) {
  const entries = convEntries(id);
  const old = entries.get(path);
  if (old && !force && !old.stale) return old.promise;
  const entry = { data: old ? old.data : undefined, at: old ? old.at : null, stale: false };
  entry.promise = api(`/api/conversations/${encodeURIComponent(id)}${path}`).then((data) => {
    if (entries.get(path) === entry) Object.assign(entry, { data, at: new Date() });
    if (noteConvData(id, path, data)) redrawConvHead(id);
    return data;
  }, (err) => {
    if (entries.get(path) === entry) entries.delete(path);
    throw err;
  });
  entries.set(path, entry);
  return entry.promise;
}

function peekConv(id, path) {
  const entry = convCache.id === id ? convCache.entries.get(path) : null;
  return entry && entry.data !== undefined ? { data: entry.data, at: entry.at, stale: entry.stale } : null;
}

// Failures stay silent here: the tab that needs the data asks again and shows the error.
function prefetchConv(id) {
  for (const path of PREFETCHED) {
    if (!convEntries(id).has(path)) fetchConv(id, path, false).catch(() => {});
  }
}

// A refresh reloads the current tab and marks the others stale; they redraw at once and reload behind when opened.
async function loadConversation(route, path, { refresh = false, revalidate = false } = {}) {
  const entries = convEntries(route.id);
  if (refresh && !revalidate) for (const [key, entry] of entries) if (key !== path) entry.stale = true;
  const [data] = await Promise.all([fetchConv(route.id, path, refresh),
    (refresh && !revalidate) || !convRows.has(route.id) ? refreshList() : null]);
  prefetchConv(route.id);
  return data;
}

function convView(path, spec) {
  const pathOf = typeof path === "function" ? path : () => path;
  return {
    head: convHead,
    load: (route, opts) => loadConversation(route, pathOf(route), opts),
    cached: (route) => peekConv(route.id, pathOf(route)),
    keepNodes: true,
    ...spec,
  };
}

function redrawConvHead(id) {
  const route = app.route;
  if (!route || route.id !== id || !$("conv-head")) return;
  $("conv-head").replaceWith(convHead(route));
  drawConvNav();
  document.title = `${VIEWS[route.view].title(route, app.data)} · claude-tokens`;
}

function convHead(route) {
  const row = convRows.get(route.id), counts = convCounts.get(route.id) || {};
  const title = (row && row.title) || convTasks.get(route.id) || "Untitled conversation";
  const resume = row ? `cd ${shellQuote(row.project)} && claude --resume ${shellQuote(route.id)}` : null;
  const meta = [h("span", { class: "conv-id" }, copyable(h("span", { class: "mono" }, route.id), route.id),
    resume ? copyButton(resume, resume, "Copy resume") : null)];
  if (row) {
    meta.push(h("span", {}, copyable(h("b", { class: "mono" }, row.project), row.project)), h("span", {}, `Modified ${utcMinute(row.modified)} UTC`),
      h("span", {}, `${fmt(row.size_kb)} KB · ${fmt(row.subagents)} subagent${row.subagents === 1 ? "" : "s"}`));
  }
  return h("div", { class: "page-head", id: "conv-head" },
    h("h1", {}, title),
    h("div", { class: "meta" }, meta));
}

// The tabs live in the app bar, so they stay on screen however far the page scrolls;
// inside a conversation a back button takes the place of the main nav.
const SHORT_TABS = { response: "Response", bash: "Bash" };

function drawConvNav() {
  const nav = $("conv-nav"), route = app.route;
  nav.hidden = !route || !route.id;
  $("nav-back").hidden = nav.hidden;
  $("nav-main").hidden = !nav.hidden;
  if (nav.hidden) {
    nav.replaceChildren();
    return;
  }
  const counts = convCounts.get(route.id) || {};
  nav.replaceChildren(...TABS.map(([key, label]) => h("a", {
    href: convHref(route.id, key), title: label, "aria-current": route.view === key ? "page" : null,
  }, SHORT_TABS[key] || label, counts[key] != null ? h("span", { class: "n" }, fmt(counts[key])) : null)));
  // On a phone the tabs scroll sideways; keep the current one in view.
  const current = nav.querySelector("[aria-current]");
  if (current && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = current.offsetLeft - nav.offsetLeft - 24;
}

const convTitle = (route) => (convRows.get(route.id) || {}).title || convTasks.get(route.id) || "Conversation";

// ---------- usage report (R4) ----------
const cacheWrite = (r) => `${fmt(r.cache_write_5m)}/${fmt(r.cache_write_1h)}`;
const sumBy = (rows, key) => rows.reduce((s, r) => s + (r[key] || 0), 0);

function stat(label, value, detail) {
  return h("div", { class: "stat" }, h("div", { class: "k" }, label), h("div", { class: "v" }, value), detail ? h("div", { class: "d" }, detail) : null);
}

function sectionHead(title, hint) {
  return h("div", { class: "section-head" }, h("h2", {}, title), hint ? h("span", { class: "hint" }, hint) : null);
}

function tokenColumns() {
  return [
    { key: "total_tokens", label: "Total", num: true, render: (r) => fmt(r.total_tokens) },
    { key: "input", label: "Input", num: true, render: (r) => fmt(r.input) },
    { key: "output", label: "Output", num: true, render: (r) => fmt(r.output) },
  ];
}

VIEWS.report = convView("", {
  title: convTitle,
  render(data) {
    const scopes = data.conversations || [];
    const byModel = data.by_model || [];
    if (!byModel.length) {
      return emptyState("No usage recorded yet", "This conversation has no assistant responses with token usage. "
        + "It may have just started; refresh in a moment.");
    }
    const guessed = (data.guessed_price_models || []).length > 0;
    const unknown = (data.unknown_price_models || []).length > 0;
    const scopeRows = [];
    for (const s of [...scopes].sort((a, b) => (b.kind === "main") - (a.kind === "main"))) {
      for (const model of Object.keys(s.models || {}).sort()) scopeRows.push({ ...s.models[model], kind: s.kind, id: s.id, task: s.task, model });
    }
    const tokens = sumBy(byModel, "total_tokens");
    const subagents = scopes.filter((s) => s.kind !== "main").length;
    const stats = h("div", { class: "stats" },
      stat("Estimated cost", money(data.estimated_total_cost_usd, guessed),
        [guessed ? "~ includes a guessed price" : "", unknown ? "excludes models without pricing" : ""].filter(Boolean).join(" · ")
          || "main + subagents"),
      stat("Total tokens", compact(tokens), `${fmt(tokens)} total · ${fmt(sumBy(byModel, "output"))} output`),
      stat("Scopes", `1 + ${subagents}`, "main + subagents"),
      stat("Served from cache", pct(tokens ? sumBy(byModel, "cache_read") / tokens : null), "of all tokens"));

    const dupScopes = scopes.filter((s) => s.skipped_duplicates);
    const dupNote = dupScopes.length
      ? h("details", { class: "footnote" },
        h("summary", {}, `Duplicates skipped: ${fmt(sumBy(dupScopes, "skipped_duplicates"))} in ${fmt(dupScopes.length)} `
          + `scope${dupScopes.length === 1 ? "" : "s"}`),
        h("div", {}, dupScopes.map((s) => `${s.id}=${s.skipped_duplicates}`).join(", ")))
      : h("p", { class: "footnote" }, "Duplicates skipped: none");
    const usage = h("section", { class: "section" }, sectionHead("Usage per scope", "Main conversation and each subagent"),
      renderTable([
        { key: "id", label: "Scope", render: (r) => (r.kind === "main" ? h("span", { class: "chip main" }, "main") : h("span", { class: "mono" }, r.id)) },
        { key: "task", label: "Task", cls: "wrap" },
        { key: "model", label: "Model", render: (r) => modelCell(r.model) },
        ...tokenColumns(),
        { key: "cache_read", label: "Cache read", num: true, render: (r) => fmt(r.cache_read) },
        { key: "cache_write", label: "Cache write 5m/1h", num: true, render: cacheWrite, sortValue: (r) => r.cache_write_5m + r.cache_write_1h },
        { key: "estimated_cost_usd", label: "Cost", num: true, render: (r) => money(r.estimated_cost_usd, r.price_estimated) },
      ], scopeRows, { id: "report-scopes" }),
      dupNote);

    const showRaw = byModel.some((r) => r.raw_output_tokens != null && r.raw_output_tokens !== r.output);
    const modelColumns = [
      { key: "model", label: "Model", render: (r) => modelCell(r.model) },
      ...tokenColumns(),
      showRaw ? { key: "raw_output_tokens", label: "Raw output*", num: true,
        render: (r) => (r.raw_output_tokens === r.output ? "" : fmt(r.raw_output_tokens)) } : null,
      { key: "cache_read", label: "Cache read", num: true, render: (r) => fmt(r.cache_read) },
      { key: "cache_write", label: "Cache write 5m/1h", num: true, render: cacheWrite, sortValue: (r) => r.cache_write_5m + r.cache_write_1h },
      { key: "estimated_cost_usd", label: "Cost", num: true, render: (r) => money(r.estimated_cost_usd, r.price_estimated) },
    ].filter(Boolean);
    const footer = ["Total", fmt(tokens), fmt(sumBy(byModel, "input")), fmt(sumBy(byModel, "output")), showRaw ? "" : null,
      fmt(sumBy(byModel, "cache_read")), `${fmt(sumBy(byModel, "cache_write_5m"))}/${fmt(sumBy(byModel, "cache_write_1h"))}`,
      money(data.estimated_total_cost_usd, guessed)].filter((c) => c !== null);
    const models = h("section", { class: "section" }, sectionHead("Summary by model"),
      renderTable(modelColumns, byModel, { id: "report-models", footer }),
      showRaw ? h("p", { class: "footnote" }, "* Raw output is shown only when persisted stream events differ from de-duplicated API responses.") : null);

    const ratio = (r) => (r.context_window_tokens ? r.context_tokens / r.context_window_tokens : null);
    const context = h("section", { class: "section" },
      sectionHead("Last observed context", "Main conversation · window inferred from the largest context seen (200k/1M tier); pass --context-window to set it"),
      renderTable([
        { key: "model", label: "Model", render: (r) => modelCell(r.model) },
        { key: "context_tokens", label: "Context / window", render: (r) => [
          ratio(r) == null ? null : h("span", { class: "meter", "aria-hidden": "true" }, h("i", { css: { width: `${Math.min(100, ratio(r) * 100)}%` } })),
          h("span", { class: "mono" }, `${fmt(r.context_tokens)} / ${r.context_window_tokens ? fmt(r.context_window_tokens) : "N/D"}`)] },
        { key: "used", label: "Used", num: true, sortValue: ratio, render: (r) => pct(ratio(r)) },
        { key: "input_tokens", label: "New input", num: true, render: (r) => fmt(r.input_tokens) },
        { key: "cache_read_tokens", label: "Cache read", num: true, render: (r) => fmt(r.cache_read_tokens) },
        { key: "cache_write_tokens", label: "Cache write", num: true, render: (r) => fmt(r.cache_write_tokens) },
        { key: "last_output_tokens", label: "Last output", num: true, render: (r) => fmt(r.last_output_tokens) },
      ], data.main_context_snapshot || [], { id: "report-context" }),
      h("p", { class: "footnote" }, "System prompt, tools, memory, skills and messages are not broken down in the JSONL."));

    const cold = h("section", { class: "section" }, sectionHead("Cold-summary estimate", "What summarizing this context would cost without cache"),
      renderTable([
        { key: "model", label: "Model", render: (r) => modelCell(r.model) },
        { key: "context_tokens", label: "Cold input", num: true, render: (r) => fmt(r.context_tokens) },
        { key: "assumed_summary_output_tokens", label: "Assumed output", num: true, render: (r) => fmt(r.assumed_summary_output_tokens) },
        { key: "estimated_cold_summary_cost_usd", label: "Cost", num: true, render: (r) => money(r.estimated_cold_summary_cost_usd, r.price_estimated) },
      ], data.cold_summary_estimate || [], { id: "report-cold" }));

    return [stats, ...pricingNotices(data), usage, models, context, cold];
  },
});

// ---------- content views (R7) ----------
function setCount(id, key, n) {
  const counts = convCounts.get(id) || {};
  convCounts.set(id, { ...counts, [key]: n });
  return counts[key] !== n;
}

// Tags and attributes that the 'self'-only CSP would block anyway (inline styles, remote media) are dropped up front.
const SANITIZE = {
  FORBID_TAGS: ["style", "img", "picture", "video", "audio", "source", "track", "form", "input", "button", "textarea", "select"],
  FORBID_ATTR: ["style"],
};

function renderMarkdown(markdown, cls = "card md") {
  const box = h("article", { class: cls });
  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
    box.append(h("pre", {}, markdown));
    return box;
  }
  box.innerHTML = DOMPurify.sanitize(marked.parse(markdown), SANITIZE);
  for (const a of box.querySelectorAll("a[href]")) {
    if (/^(https?:|mailto:)/i.test(a.getAttribute("href"))) {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    }
  }
  if (typeof hljs !== "undefined") {
    for (const code of box.querySelectorAll("pre code")) {
      const lang = [...code.classList].find((c) => c.startsWith("language-"));
      if (lang && !hljs.getLanguage(lang.slice(9))) {
        code.classList.remove(lang);
        code.classList.add("language-plaintext");
      }
      hljs.highlightElement(code);
    }
  }
  for (const pre of box.querySelectorAll("pre")) copyable(pre, pre.textContent.replace(/\n$/, ""));
  return box;
}

VIEWS.response = convView("/last-response", {
  title: (route) => `Last response · ${convTitle(route)}`,
  render(data) {
    if (!data.last_response) {
      return emptyState("No text response", "The main conversation has no assistant text response yet. "
        + "Responses from subagents are not shown here.");
    }
    const box = renderMarkdown(data.last_response);
    box.prepend(copyButton(data.last_response, "Copy the response as Markdown"));
    return [h("div", { class: "meta" }, "Last assistant text response of the main conversation · rendered Markdown"), box];
  },
});

const sourceLabel = (source) => (source === "main" ? "main" : `subagent ${source.slice(0, 8)}`);
const sourceChip = (source) => h("span", { class: source === "main" ? "chip main" : "chip", title: source === "main" ? "Main conversation" : `Subagent ${source}` },
  sourceLabel(source));

function parseStamp(stamp) {
  const d = stamp ? new Date(stamp) : null;
  return d && !Number.isNaN(d.getTime()) ? d : null;
}

const bashFilter = { id: null, source: "", text: "" };

function bashItems(commands) {
  const items = [];
  let day = null;
  for (const c of commands) {
    const today = c.when ? c.when.toISOString().slice(0, 10) : "undated";
    if (today !== day) {
      items.push(h("li", { class: "day" }, today === "undated" ? "No timestamp" : `${today} (UTC)`));
      day = today;
    }
    items.push(h("li", {},
      c.when ? h("time", { datetime: c.when.toISOString(), title: `${c.when.toISOString().slice(0, 19).replace("T", " ")} UTC` }, utcTime(c.when))
        : h("span", { class: "notime" }, "—"),
      h("div", { class: "desc" }, sourceChip(c.source), c.description ? c.description : h("span", { class: "muted" }, "No description")),
      h("div", { class: "cmd" }, h("pre", {}, c.command), copyButton(c.command, "Copy the command"))));
  }
  return items;
}

VIEWS.bash = convView("/bash", {
  title: (route) => `Bash commands · ${convTitle(route)}`,
  render(data, route) {
    const commands = (data.bash_commands || []).map((c) => ({ ...c, source: c.source || "main", when: parseStamp(c.timestamp) }));
    if (!commands.length) return emptyState("No Bash commands", "Neither the main conversation nor its subagents ran any Bash command.");
    const perSource = new Map();
    for (const c of commands) perSource.set(c.source, (perSource.get(c.source) || 0) + 1);
    if (bashFilter.id !== route.id) Object.assign(bashFilter, { id: route.id, source: "", text: "" });
    if (!perSource.has(bashFilter.source)) bashFilter.source = "";
    const fromMain = perSource.get("main") || 0;
    const list = h("ol", { class: "cmds card" });
    const count = h("span", { class: "count" });
    const draw = () => {
      const q = bashFilter.text.trim().toLowerCase();
      const shown = commands.filter((c) => (!bashFilter.source || c.source === bashFilter.source)
        && (!q || c.command.toLowerCase().includes(q) || String(c.description || "").toLowerCase().includes(q)));
      list.replaceChildren(...(shown.length ? bashItems(shown) : [h("li", { class: "day" }, "No command matches the filter")]));
      count.textContent = shown.length === commands.length
        ? `${fmt(commands.length)} Bash commands · ${fmt(fromMain)} from main, ${fmt(commands.length - fromMain)} from subagents`
        : `${fmt(shown.length)} of ${fmt(commands.length)} Bash commands`;
    };
    const source = h("select", { id: "bash-source", "aria-label": "Filter by source", onchange: (e) => { bashFilter.source = e.target.value; draw(); } },
      h("option", { value: "" }, `All sources (${fmt(commands.length)})`),
      [...perSource].map(([s, n]) => h("option", { value: s, selected: s === bashFilter.source }, `${sourceLabel(s)} (${fmt(n)})`)));
    const text = h("input", { id: "bash-filter", type: "search", placeholder: "Command or description", value: bashFilter.text, "aria-label": "Filter commands",
      oninput: (e) => { bashFilter.text = e.target.value; draw(); } });
    draw();
    return [h("div", { class: "meta" }, "Chronological across the main conversation and its subagents · times in UTC"),
      h("div", { class: "toolbar" }, h("div", { class: "filters" }, h("label", { class: "field" }, "Source", source), h("label", { class: "field" }, "Search", text)), count),
      list];
  },
});

VIEWS.files = convView("/files", {
  title: (route) => `Files · ${convTitle(route)}`,
  render(data) {
    const rows = Object.entries(data.files || {}).map(([file, t]) => ({
      file, Read: t.Read || 0, Write: t.Write || 0, Edit: t.Edit || 0, sources: Array.isArray(t.sources) ? t.sources : [],
    }));
    if (!rows.length) return emptyState("No files touched", "Neither the main conversation nor its subagents read, wrote or edited a file.");
    return [h("div", { class: "meta" }, "One row per file · counts add up every source that touched it"),
      renderTable([
        pathCol("file", "File", true),
        { key: "Read", label: "Read", num: true, render: (r) => fmt(r.Read) },
        { key: "Write", label: "Write", num: true, render: (r) => fmt(r.Write) },
        { key: "Edit", label: "Edit", num: true, render: (r) => fmt(r.Edit) },
        { key: "sources", label: "Sources", cls: "chips", sortValue: (r) => r.sources.length, render: (r) => r.sources.map(sourceChip) },
      ], rows, { id: "files", sortKey: "file", dir: 1 }),
      h("div", { class: "count" }, `${fmt(rows.length)} distinct file${rows.length === 1 ? "" : "s"}`)];
  },
});

// ---------- conversation messages ----------
// anchor: the message at the top of the screen when the tab was left, to come back to the same place.
const messagesState = { id: null, source: "main", toBottom: false, restore: false, anchor: null };
const KIND_LABELS = { prompt: "User", meta: "Injected context", summary: "Compaction summary", tool_result: "Tool results" };

const withSource = (path, source) => (source === "main" ? path : `${path}?source=${encodeURIComponent(source)}`);

// Tool inputs and results can be long, so a block is only built the first time it is opened.
function lazyDetails(cls, summary, build, title = null) {
  const body = h("div", { class: "blk-body" });
  const box = h("details", { class: cls }, h("summary", { title }, summary), body);
  box.addEventListener("toggle", () => { if (box.open && !body.firstChild) append(body, build()); });
  return box;
}

const clippedPre = (item) => [h("pre", {}, item.text), item.size > item.text.length
  ? h("div", { class: "footnote" }, `Showing the first ${fmt(item.text.length)} of ${fmt(item.size)} characters`) : null];

const labelled = (label, item) => h("div", {}, h("div", { class: "lbl" }, label), clippedPre(item));

// The figures that change from one response to the next stand out; the rest stay small and muted.
function usageStats(m) {
  const u = m.usage;
  const items = [
    ["Context", fmt(u.context), "key"],
    ["Output", u.thinking ? `${fmt(u.output)} (${fmt(u.thinking)} thinking)` : fmt(u.output), "key"],
    ["Cost", money(m.estimated_cost_usd, m.price_estimated), "key"],
    ["Input", fmt(u.input)],
    ["Cache read", fmt(u.cache_read)],
    ["Cache write 5m/1h", `${fmt(u.cache_write_5m)}/${fmt(u.cache_write_1h)}`],
    u.web_search_requests ? ["Web searches", fmt(u.web_search_requests)] : null,
    u.web_fetch_requests ? ["Web fetches", fmt(u.web_fetch_requests)] : null,
    u.speed && u.speed !== "standard" ? ["Speed", u.speed] : null,
    u.service_tier && u.service_tier !== "standard" ? ["Tier", u.service_tier] : null,
  ].filter(Boolean);
  return h("dl", { class: "ustats" }, items.map(([k, v, cls]) => h("div", { class: cls }, h("dt", {}, k), h("dd", {}, v))));
}

const ROUTINE_STOPS = new Set(["tool_use", "end_turn", "stop_sequence"]);
const cacheMiss = (u) => u.cache_read === 0 && u.cache_write_5m + u.cache_write_1h > 0;

function toolBlock(block, result) {
  const failed = !!(result && result.is_error);
  return lazyDetails(failed ? "blk failed" : "blk",
    [h("span", { class: "chip" }, block.name), failed ? h("span", { class: "badge" }, "error") : null,
      result ? null : h("span", { class: "muted" }, "no result"), block.summary ? h("span", { class: "mono sum" }, block.summary) : null],
    () => [block.input.map((f) => labelled(f.name, f)), result ? labelled(failed ? "result (error)" : "result", result) : null],
    block.summary || null);
}

// tools: tool_use id -> its result, plus the ids of every tool_use, so results render under the call that made them.
function messageBlocks(m, tools) {
  return m.blocks.map((b) => {
    if (b.type === "text") return m.role === "assistant" ? renderMarkdown(b.text, "md") : h("pre", { class: "prompt" }, b.text);
    if (b.type === "thinking") return lazyDetails("think", "Thinking", () => h("pre", {}, b.text));
    if (b.type === "tool_use") return toolBlock(b, tools.results.get(b.id));
    if (b.type === "tool_result" && !tools.calls.has(b.tool_use_id)) {
      return lazyDetails(b.is_error ? "blk failed" : "blk", "Tool result", () => clippedPre(b));
    }
    return null;
  });
}

// showModel: the model name is written only when it differs from the previous response; the swatch is always there.
function messageItem(m, tools, showModel) {
  const time = m.when ? h("time", { datetime: m.when.toISOString(), title: `${m.when.toISOString().slice(0, 19).replace("T", " ")} UTC` }, utcTime(m.when))
    : h("span", { class: "notime" }, "—");
  const num = m.n ? h("span", { class: "n" }, `#${m.n}`) : null;
  if (m.role === "assistant") {
    const item = h("li", { class: m.kind === "error" ? "msg failed" : "msg" },
      h("div", { class: "msg-head" }, num, time, h("span", { class: "model", title: m.model }, swatch(m.model), showModel ? m.model : null),
        m.kind === "error" ? h("span", { class: "badge" }, "API error") : null,
        m.stop_reason && !ROUTINE_STOPS.has(m.stop_reason) ? h("span", { class: "badge warn" }, m.stop_reason) : null,
        cacheMiss(m.usage) ? h("span", { class: "badge warn", title: "Nothing was read from cache: the whole context was written again" },
          "cache miss") : null,
        usageStats(m)),
      h("div", { class: "msg-body" }, messageBlocks(m, tools)));
    item.style.borderLeftColor = colorOf(m.model);
    return item;
  }
  const collapsed = m.kind === "meta" || m.kind === "summary";
  return h("li", { class: collapsed ? "msg aside" : "msg user" },
    h("div", { class: "msg-head" }, num, time, h("b", {}, KIND_LABELS[m.kind])),
    h("div", { class: "msg-body" }, collapsed ? lazyDetails("blk", "Show", () => messageBlocks(m, tools)) : messageBlocks(m, tools)));
}

function messageItems(messages, tools) {
  const items = [];
  let day = null, model = null;
  for (const m of messages) {
    const today = m.when ? m.when.toISOString().slice(0, 10) : "undated";
    if (today !== day) {
      items.push(h("li", { class: "day" }, today === "undated" ? "No timestamp" : `${today} (UTC)`));
      day = today;
      model = null;
    }
    items.push(messageItem(m, tools, m.role === "assistant" && m.model !== model));
    if (m.role === "assistant") model = m.model;
  }
  return items;
}

const ellipsis = (text, n) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);
const sourceOption = (s) => `${s.id === "main" ? "main" : `subagent ${s.id.slice(0, 8)}`} · ${ellipsis(String(s.task || ""), 60)}`;
const visibleMessages = (messages) => messages.filter((m) => m.kind !== "tool_result");

// Off-screen messages have an estimated height (content-visibility), so positions move as the ones in view get laid out;
// the target is applied again until the page height settles.
function settleScroll(target) {
  let last = -1, stable = 0, frames = 0;
  const step = () => {
    const end = document.documentElement.scrollHeight;
    window.scrollTo(0, target());
    stable = end === last ? stable + 1 : 0;
    last = end;
    if (stable < 2 && ++frames < 30) requestAnimationFrame(step);
  };
  step();
}

const scrollToEnd = () => settleScroll(() => document.documentElement.scrollHeight);

function topMessage() {
  const top = Math.max(0, document.querySelector(".appbar").getBoundingClientRect().bottom);
  for (const el of document.querySelectorAll(".msgs > li")) {
    const box = el.getBoundingClientRect();
    if (box.bottom > top) return { el, offset: box.top };
  }
  return null;
}

function messagesPath(route) {
  if (messagesState.id !== route.id) Object.assign(messagesState, { id: route.id, source: "main", anchor: null });
  return withSource("/messages", messagesState.source);
}

VIEWS.messages = convView(messagesPath, {
  title: (route) => `Conversation · ${convTitle(route)}`,
  load: (route, opts) => {
    // A fresh open starts at the latest message; a refresh keeps the reader where they are.
    if (!opts.refresh) Object.assign(messagesState, { toBottom: true, restore: false });
    return loadConversation(route, messagesPath(route), opts);
  },
  // Coming back from another tab reattaches the same nodes, so the anchor is still in the page; otherwise start at the end.
  enter: () => Object.assign(messagesState, { toBottom: true, restore: true }),
  leave: () => { messagesState.anchor = topMessage(); },
  render(data) {
    let n = 0;
    // Same numbering as the CLI: tool results are not counted, since they render under their call.
    const messages = (data.messages || []).map((m) => ({ ...m, n: m.kind === "tool_result" ? null : ++n, when: parseStamp(m.timestamp) }));
    const tools = { results: new Map(), calls: new Set() };
    for (const m of messages) {
      for (const b of m.blocks) {
        if (b.type === "tool_result") tools.results.set(b.tool_use_id, b);
        if (b.type === "tool_use") tools.calls.add(b.id);
      }
    }
    const shown = messages.filter((m) => !(m.kind === "tool_result" && m.blocks.every((b) => tools.calls.has(b.tool_use_id))));
    const responses = messages.filter((m) => m.role === "assistant");
    const cost = responses.reduce((sum, m) => sum + (m.estimated_cost_usd || 0), 0);
    const source = h("select", { id: "messages-source", "aria-label": "Source",
      onchange: (e) => { messagesState.source = e.target.value; load({ refresh: false }); } },
    (data.sources || []).map((s) => h("option", { value: s.id, selected: s.id === data.source }, sourceOption(s))));
    const toolbar = h("div", { class: "toolbar" },
      h("div", { class: "filters" }, h("label", { class: "field" }, "Source", source),
        h("button", { class: "btn", type: "button", onclick: () => window.scrollTo(0, 0) }, "↑ First"),
        h("button", { class: "btn", type: "button", onclick: scrollToEnd }, "↓ Last")),
      h("span", { class: "count" }, `${fmt(visibleMessages(messages).length)} messages · ${fmt(responses.length)} responses · `
        + money(cost, responses.some((m) => m.price_estimated))));
    const meta = h("div", { class: "meta" }, "Every message in log order · token usage of each assistant response · times in UTC");
    if (!shown.length) return [meta, toolbar, emptyState("No messages", "This log has no user or assistant messages yet.")];
    return [meta, toolbar, h("ol", { class: "msgs" }, messageItems(shown, tools))];
  },
  after: () => {
    const { anchor, restore, toBottom } = messagesState;
    Object.assign(messagesState, { anchor: null, restore: false, toBottom: false });
    if (restore && anchor && anchor.el.isConnected) settleScroll(() => anchor.el.getBoundingClientRect().top + window.scrollY - anchor.offset);
    else if (toBottom) scrollToEnd();
  },
});

// ---------- totals (R5, R8) ----------
let totalsFilter = "";
let totalsDraft = "";

function compact(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} M`;
  return fmt(n);
}

const hasGuessed = (T, day) => Object.keys(day.models || {}).some((m) => (T.guessed_price_models || []).includes(m));
const moneyShort = (v, estimated) => money(v, estimated, v && Math.abs(v) < 0.01 ? 4 : 2);
const DAY_MS = 864e5, MAX_FILLED_DAYS = 1000;

// Days without usage are added as zeros so the day axis keeps its real spacing.
function fillDays(daily) {
  const dated = (daily || []).filter((d) => d.day).sort((a, b) => compareValues(a.day, b.day));
  if (!dated.length) return [];
  const start = Date.parse(`${dated[0].day}T00:00:00Z`), end = Date.parse(`${dated[dated.length - 1].day}T00:00:00Z`);
  if (Number.isNaN(start) || Number.isNaN(end) || (end - start) / DAY_MS > MAX_FILLED_DAYS) return dated;
  const byDay = new Map(dated.map((d) => [d.day, d]));
  const out = [];
  for (let t = start; t <= end; t += DAY_MS) {
    const day = new Date(t).toISOString().slice(0, 10);
    out.push(byDay.get(day) || { day, responses: 0, total_tokens: 0, estimated_cost_usd: 0, models: {} });
  }
  return out;
}

function topEntries(counts, n = 15) {
  return Object.entries(counts || {}).sort((a, b) => b[1] - a[1] || compareValues(a[0], b[0])).slice(0, n);
}

function applyTotalsFilter(value) {
  const next = value.trim();
  if (next === totalsFilter) return;
  totalsFilter = next;
  totalsDraft = next;
  load({ refresh: false });
}

function chartBox(id, label, cls) {
  return h("div", { class: cls ? `chart-box ${cls}` : "chart-box" }, h("canvas", { id, role: "img", "aria-label": label }));
}

function chartCard(title, sub, body, wide) {
  return h("div", { class: wide ? "card chart-card chart-wide" : "card chart-card" }, h("h3", {}, title), sub ? h("div", { class: "sub" }, sub) : null, body);
}

VIEWS.totals = {
  title: () => "Totals",
  load: async () => (await Promise.all([api(withProject("/api/totals", totalsFilter)), projectsDir ? null : refreshList()]))[0],
  head() {
    const hint = h("span", { class: "count" });
    const setHint = () => {
      hint.textContent = totalsDraft.trim() !== totalsFilter ? "Press Enter to apply the filter"
        : totalsFilter ? `Filtered by project “${totalsFilter}”` : "All projects";
    };
    const input = h("input", {
      id: "totals-filter", type: "search", placeholder: "Filter by project path", value: totalsDraft, "aria-label": "Filter by project",
      oninput: (e) => { totalsDraft = e.target.value; setHint(); },
      onchange: (e) => applyTotalsFilter(e.target.value),
      onsearch: (e) => applyTotalsFilter(e.target.value),
    });
    setHint();
    return [h("div", { class: "page-head" }, h("h1", {}, "Overall usage"),
      h("div", { class: "meta" }, h("span", {}, "Every conversation and subagent in ", folderLabel()), h("span", {}, "Days are UTC"))),
    h("div", { class: "toolbar" }, h("label", { class: "field" }, "Project", input), hint)];
  },
  loading: () => skeleton(10, "Scanning the conversation logs. The first load after start-up takes a few seconds; "
    + "later loads only re-read logs that changed."),
  render(T) {
    if (!T.conversations) {
      return emptyState("Nothing to total yet", totalsFilter ? `No conversation has a project matching “${totalsFilter}”.`
        : `There are no conversation logs in ${folderText()}, so there is no usage to aggregate.`);
    }
    const guessed = (T.guessed_price_models || []).length > 0;
    const w = T.window || {};
    const stats = h("div", { class: "stats" },
      stat("Total cost", money(T.estimated_total_cost_usd, guessed, 2), `${money(T.cost_per_conversation_usd, false, 4)} per conversation`),
      stat("Tokens", compact(T.total_tokens), `${fmt(T.total_tokens)} total · ${fmt(T.output_tokens)} generated`),
      stat("Volume", fmt(T.conversations), `conversations · ${fmt(T.subagents)} subagents · ${fmt(T.projects_count)} projects`),
      stat("Cache hits", pct(T.cache_hit_ratio), "of input tokens served from cache"),
      stat("Time window", w.start ? `${fmt(w.span_days)} days` : "—", w.start
        ? `${w.start.slice(0, 10)} → ${w.end.slice(0, 10)} · ${fmt(w.active_days)} active · busiest ${w.busiest_day} (${fmt(w.busiest_day_responses)} responses)`
        : "no dated usage"));

    const undated = (T.daily || []).find((d) => d.day == null);
    const models = (T.by_model || []).map((r) => r.model);
    const legend = h("div", { class: "legend" }, models.map((m) => h("span", {}, swatch(m), m)));
    const charts = h("div", { class: "charts" },
      chartCard("Daily cost by model", undated
        ? `Undated records (no timestamp, not plotted): ${moneyShort(undated.estimated_cost_usd, hasGuessed(T, undated))} · ${fmt(undated.total_tokens)} tokens`
        : "Stacked by model · days in UTC",
      h("div", { class: "chart-stack" }, legend, chartBox("c-daily", "Daily cost by model", "tall")), true),
      chartCard("Model share", "Percentage of cost and of tokens per model",
        h("div", { class: "pair" }, chartBox("c-share-cost", "Percentage of cost per model"), chartBox("c-share-tok", "Percentage of tokens per model"))),
      chartCard("Projects by cost", "Top 15", chartBox("c-projects", "Projects by cost", "tall")),
      chartCard("Daily activity", "Assistant responses per day (UTC)", chartBox("c-activity", "Assistant responses per day"), true),
      chartCard("Tools and skills", "Top 15 tool calls (log scale) · skill invocations",
        h("div", { class: "pair" }, chartBox("c-tools", "Tool calls", "tall"), chartBox("c-skills", "Skill invocations", "tall")), true));

    const modelTable = h("section", { class: "section" }, sectionHead("Usage by model"), renderTable([
      { key: "model", label: "Model", render: (r) => modelCell(r.model) },
      { key: "total_tokens", label: "Total tokens", num: true, render: (r) => fmt(r.total_tokens) },
      { key: "pct_tokens", label: "% tokens", num: true, render: (r) => pct(r.pct_tokens) },
      { key: "estimated_cost_usd", label: "Cost", num: true, render: (r) => money(r.estimated_cost_usd, r.price_estimated, 2) },
      { key: "pct_cost", label: "% cost", num: true, render: (r) => pct(r.pct_cost) },
    ], T.by_model || [], { id: "totals-models", sortKey: "estimated_cost_usd" }));
    const projectTable = h("section", { class: "section" }, sectionHead("Projects by cost"), renderTable([
      pathCol("project", "Project", true),
      { key: "conversations", label: "Conversations", num: true, render: (r) => fmt(r.conversations) },
      { key: "total_tokens", label: "Total tokens", num: true, render: (r) => fmt(r.total_tokens) },
      { key: "estimated_cost_usd", label: "Cost", num: true, render: (r) => money(r.estimated_cost_usd, false, 2) },
    ], T.projects || [], { id: "totals-projects", sortKey: "estimated_cost_usd" }));
    const toolRows = topEntries(T.tools, Infinity).map(([tool, calls]) => ({ tool, calls, share: T.tool_calls ? calls / T.tool_calls : 0 }));
    const skillRows = topEntries(T.skills, Infinity).map(([skill, n]) => ({ skill, n }));
    const usageTables = h("div", { class: "charts" },
      h("section", { class: "section" }, sectionHead("Top tools"), toolRows.length ? renderTable([
        { key: "tool", label: "Tool", cls: "wrap", render: (r) => copyable(h("span", {}, breakable(r.tool)), r.tool) },
        { key: "calls", label: "Calls", num: true, render: (r) => fmt(r.calls) },
        { key: "share", label: "% of calls", num: true, render: (r) => pct(r.share) },
      ], toolRows, { id: "totals-tools", sortKey: "calls" }) : emptyState("No tool calls", "No conversation called a tool.")),
      h("section", { class: "section" }, sectionHead("Skills used"), skillRows.length ? renderTable([
        { key: "skill", label: "Skill", render: (r) => h("span", { class: "mono" }, r.skill) },
        { key: "n", label: "Invocations", num: true, render: (r) => fmt(r.n) },
      ], skillRows, { id: "totals-skills", sortKey: "n" }) : emptyState("No skills used", "No conversation invoked a skill.")));

    return [stats, ...pricingNotices(T), charts, modelTable, projectTable, usageTables];
  },
  after: (T) => (T.conversations ? drawCharts(T) : null),
};

function drawCharts(T) {
  if (typeof Chart === "undefined") return null;
  const fg = cssVar("--muted"), grid = cssVar("--grid"), accent = cssVar("--accent"), surface = cssVar("--surface");
  Chart.defaults.font.family = cssVar("--font");
  Chart.defaults.font.size = 12;
  Chart.defaults.color = fg;
  const charts = [];
  const guessed = new Set(T.guessed_price_models || []);
  // Chart.js groups thousands by browser locale; ticks use the same separator as the tables instead.
  const tickNum = (v) => (Number.isInteger(v) ? fmt(v) : String(v));
  const axis = (title, extra = {}, ticks = {}) => ({
    grid: { color: grid, drawTicks: false }, border: { color: grid },
    ticks: { color: fg, padding: 6, maxRotation: 0, autoSkipPadding: 10, ...ticks },
    title: { display: !!title, text: title, color: fg }, ...extra,
  });
  const base = { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false } } };
  const place = (id, config, empty) => {
    const canvas = $(id);
    if (!canvas) return;
    if (empty) {
      canvas.replaceWith(h("div", { class: "empty" }, empty));
      return;
    }
    charts.push(new Chart(canvas, config));
  };

  const days = fillDays(T.daily);
  const multiYear = days.length && days[0].day.slice(0, 4) !== days[days.length - 1].day.slice(0, 4);
  const labels = days.map((d) => (multiYear ? d.day : d.day.slice(5)));
  const dayTitle = (items) => `${days[items[0].dataIndex].day} (UTC)`;
  const models = (T.by_model || []).map((r) => r.model);

  place("c-daily", {
    type: "bar",
    data: { labels, datasets: models.map((m) => ({
      label: m, data: days.map((d) => (d.models[m] ? d.models[m].estimated_cost_usd || 0 : 0)),
      backgroundColor: colorOf(m), borderRadius: 2, maxBarThickness: 22,
    })) },
    options: { ...base,
      scales: { x: axis("Day (UTC)", { stacked: true }),
        y: axis(null, { stacked: true, border: { display: false } }, { callback: (v) => `$${tickNum(v)}` }) },
      plugins: { legend: { display: false }, tooltip: { mode: "index", filter: (i) => i.raw > 0, callbacks: {
        title: dayTitle,
        label: (i) => {
          const entry = days[i.dataIndex].models[i.dataset.label];
          return ` ${i.dataset.label}: ${entry && entry.estimated_cost_usd == null ? "N/D" : moneyShort(i.raw, guessed.has(i.dataset.label))}`;
        },
        footer: (items) => `Day total: ${moneyShort(days[items[0].dataIndex].estimated_cost_usd, hasGuessed(T, days[items[0].dataIndex]))}`,
      } } } },
  }, days.length ? null : "No dated usage");

  const share = (id, key, title) => place(id, {
    type: "bar",
    data: { labels: models.map((m) => m.replace(/^claude-/, "")), datasets: [{
      data: (T.by_model || []).map((r) => (r[key] == null ? null : r[key] * 100)),
      backgroundColor: models.map((m) => colorOf(m)), borderRadius: 3, maxBarThickness: 18,
    }] },
    options: { ...base, indexAxis: "y",
      scales: { x: axis(title, { min: 0, max: 100 }, { callback: (v) => `${v}%` }),
        y: { grid: { display: false }, border: { display: false }, ticks: { color: fg } } },
      plugins: { legend: { display: false }, tooltip: { callbacks: { title: (items) => models[items[0].dataIndex], label: (i) => ` ${i.raw.toFixed(1)}%` } } } },
  }, models.length ? null : "No usage");
  share("c-share-cost", "pct_cost", "% of cost");
  share("c-share-tok", "pct_tokens", "% of tokens");

  // Chart.js clips y labels that do not fit, so long names are shortened in the middle; tooltips keep the full name.
  const shortLabel = (name) => (name.length > 26 ? `${name.slice(0, 10)}…${name.slice(-15)}` : name);
  const logTick = (v) => (Number.isInteger(Math.log10(v)) ? fmt(v) : "");
  const hbar = (id, { names, values, color, format, title, fullNames = names, empty, log = false }) => place(id, {
    type: "bar",
    data: { labels: names.map(shortLabel), datasets: [{ data: values, backgroundColor: color, borderRadius: 3, maxBarThickness: 16 }] },
    options: { ...base, indexAxis: "y",
      scales: { x: axis(title, log ? { type: "logarithmic" } : {}, { callback: log ? logTick : tickNum }),
        y: { grid: { display: false }, border: { display: false }, ticks: { color: fg, autoSkip: false } } },
      plugins: { legend: { display: false }, tooltip: { callbacks: {
        title: (items) => fullNames[items[0].dataIndex], label: (i) => ` ${format(i.raw)}` } } } },
  }, values.length ? null : empty);

  const projects = [...(T.projects || [])].sort((a, b) => b.estimated_cost_usd - a.estimated_cost_usd).slice(0, 15);
  hbar("c-projects", { names: projects.map((p) => String(p.project).split("/").filter(Boolean).pop() || p.project),
    values: projects.map((p) => p.estimated_cost_usd), color: accent, format: (v) => moneyShort(v, false), title: "Cost (USD)",
    fullNames: projects.map((p) => p.project), empty: "No projects" });
  const tools = topEntries(T.tools), skills = topEntries(T.skills);
  hbar("c-tools", { names: tools.map((t) => t[0]), values: tools.map((t) => t[1]), color: accent, format: fmt,
    title: "Tool calls (log scale)", empty: "No tool calls", log: true });
  hbar("c-skills", { names: skills.map((t) => t[0]), values: skills.map((t) => t[1]), color: cssVar("--m5"), format: fmt,
    title: "Invocations", empty: "No skills used" });

  place("c-activity", {
    type: "line",
    data: { labels, datasets: [{
      data: days.map((d) => d.responses || 0), borderColor: accent, backgroundColor: mixHex(accent, surface, 0.82), fill: true,
      tension: 0.3, pointRadius: days.map((_, i) => (i === days.length - 1 ? 4 : 0)), pointBackgroundColor: accent, borderWidth: 2,
    }] },
    options: { ...base,
      scales: { x: axis("Day (UTC)"),
        y: axis(null, { beginAtZero: true, border: { display: false } }, { precision: 0, callback: tickNum }) },
      plugins: { legend: { display: false }, tooltip: { callbacks: { title: dayTitle, label: (i) => ` ${fmt(i.raw)} responses` } } } },
  }, days.length ? null : "No dated usage");

  return () => charts.forEach((c) => c.destroy());
}

// ---------- shell: app bar, loading, refresh (R9.4, R9.5) ----------
const app = { route: null, seq: 0, busy: false, phase: "loading", data: null, error: null, loadedAt: null, failedAt: null, timer: null, after: [] };

function updateBar() {
  const loaded = $("loaded");
  if (app.busy) loaded.textContent = "Loading…";
  else if (app.failedAt) loaded.textContent = `Failed at ${utcTime(app.failedAt)} UTC`;
  else loaded.textContent = app.loadedAt ? `${utcTime(app.loadedAt)} UTC` : "--:--:-- UTC";
  $("refresh").disabled = app.busy;
  const totals = !!app.route && app.route.view === "totals";
  for (const [id, on] of [["nav-list", !totals], ["nav-totals", totals]]) {
    if (on) $(id).setAttribute("aria-current", "page");
    else $(id).removeAttribute("aria-current");
  }
  drawConvNav();
}

function runCleanups() {
  for (const fn of app.after.splice(0)) {
    try { fn(); } catch (e) { console.error(e); }
  }
}

// Body nodes per data object of a keepNodes view: going back to a tab reattaches them instead of rendering again.
let renderedBodies = new WeakMap();

function show({ keepScroll = false } = {}) {
  const route = app.route, view = VIEWS[route.view];
  const y = window.scrollY;
  const focused = document.activeElement && document.activeElement.id ? document.activeElement : null;
  runCleanups();
  readPalette();
  if (app.phase === "ready") noteModels(app.data);
  const head = view.head ? view.head(route, app.data) : [];
  let body;
  if (app.phase === "loading") body = view.loading ? view.loading(route) : skeleton(8);
  else if (app.phase === "error") body = errorState(app.error, () => load({ refresh: false }));
  else if (!view.keepNodes) body = view.render(app.data, route);
  else {
    body = renderedBodies.get(app.data) || view.render(app.data, route);
    renderedBodies.set(app.data, body);
  }
  $("main").replaceChildren(...[head, body].flat(Infinity).filter(Boolean));
  document.title = `${view.title(route, app.data)} · claude-tokens`;
  if (app.phase === "ready" && view.after) {
    const cleanup = view.after(app.data, route);
    if (typeof cleanup === "function") app.after.push(cleanup);
  }
  if (keepScroll) window.scrollTo(0, y);
  const again = focused && focused.tagName === "INPUT" && !$("main").contains(focused) ? $(focused.id) : null;
  if (again) {
    again.focus();
    if (typeof focused.selectionStart === "number") again.setSelectionRange(focused.selectionStart, focused.selectionEnd);
  }
  updateBar();
}

// revalidate: reload a view drawn from cache, without marking the other tabs stale as a refresh does.
async function load({ refresh, revalidate = false }) {
  const route = app.route, view = VIEWS[route.view], seq = ++app.seq;
  app.busy = true;
  if (!refresh || app.phase !== "ready") {
    app.phase = "loading";
    show();
  } else {
    updateBar();
  }
  try {
    const data = await view.load(route, { refresh, revalidate });
    if (seq !== app.seq) return;
    Object.assign(app, { phase: "ready", data, error: null, loadedAt: new Date(), failedAt: null, busy: false });
    show({ keepScroll: refresh });
  } catch (err) {
    if (seq !== app.seq) return;
    if (!(err instanceof ApiError)) console.error(err);
    Object.assign(app, { phase: "error", data: null, error: err, failedAt: new Date(), busy: false });
    show({ keepScroll: refresh });
  }
}

function navigate() {
  const leaving = app.route && VIEWS[app.route.view];
  if (leaving && leaving.leave) leaving.leave();
  const route = parseRoute(location.hash);
  if (route.view === "list") clearConvCache();
  app.route = route;
  const view = VIEWS[route.view];
  const hit = view.cached ? view.cached(route) : null;
  if (!hit) {
    app.data = null;
    load({ refresh: false });
    window.scrollTo(0, 0);
    return;
  }
  app.seq++;
  Object.assign(app, { phase: "ready", data: hit.data, error: null, loadedAt: hit.at, failedAt: null, busy: false });
  if (view.enter) view.enter(route);
  window.scrollTo(0, 0);
  show();
  if (hit.scrollY) window.scrollTo(0, hit.scrollY);
  if (hit.stale) load({ refresh: true, revalidate: true });
  else if (route.id) prefetchConv(route.id);
}

function setAutoRefresh(on) {
  clearInterval(app.timer);
  app.timer = on ? setInterval(() => { if (!app.busy) load({ refresh: true }); }, 30000) : null;
}

function updateToTop() {
  $("to-top").hidden = window.scrollY < window.innerHeight;
}

function boot() {
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  document.body.append(h("button", { class: "btn to-top", id: "to-top", type: "button", title: "Back to top", "aria-label": "Back to top", hidden: true,
    onclick: () => window.scrollTo({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" }) }, "↑"));
  window.addEventListener("scroll", updateToTop, { passive: true });
  const auto = $("auto");
  auto.checked = false;
  auto.addEventListener("change", () => setAutoRefresh(auto.checked));
  $("refresh").addEventListener("click", () => load({ refresh: true }));
  window.addEventListener("hashchange", navigate);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    renderedBodies = new WeakMap();
    if (app.route) show({ keepScroll: true });
  });
  navigate();
}

if (typeof document !== "undefined" && document.getElementById("main")) boot();
