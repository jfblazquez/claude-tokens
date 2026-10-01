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

function renderTable(columns, rows, opts = {}) {
  const remembered = opts.id && sortMemory.get(opts.id);
  let sortKey = remembered ? remembered.key : opts.sortKey || null;
  let dir = remembered ? remembered.dir : opts.dir || -1;
  const wrap = h("div", { class: "card scroll" });
  const cls = (...names) => names.filter(Boolean).join(" ") || null;

  function draw() {
    const col = columns.find((c) => c.key === sortKey);
    const data = col ? sortRows(rows, col.sortValue || ((r) => r[col.key]), dir) : rows;
    const head = h("tr", {}, columns.map((c) => {
      const active = sortKey === c.key;
      const button = h("button", {
        class: "sort", type: "button", title: `Sort by ${c.label}`,
        onclick: () => {
          if (active) dir = -dir;
          else { sortKey = c.key; dir = c.num ? -1 : 1; }
          if (opts.id) sortMemory.set(opts.id, { key: sortKey, dir });
          draw();
        },
      }, c.label, h("span", { class: "ind", "aria-hidden": "true" }, active ? (dir > 0 ? "▲" : "▼") : ""));
      return h("th", { class: cls(c.num && "num"), scope: "col",
        "aria-sort": active ? (dir > 0 ? "ascending" : "descending") : null }, button);
    }));
    const body = data.map((r) => h("tr", {
      class: cls(opts.onRow && "link"),
      onclick: opts.onRow ? (e) => { if (!e.target.closest("a")) opts.onRow(r); } : null,
    }, columns.map((c) => h("td", { class: cls(c.num && "num", c.wrap && "wrap") }, c.render ? c.render(r) : r[c.key]))));
    const foot = opts.footer
      ? h("tfoot", {}, h("tr", { class: "total" }, opts.footer.map((cell, i) => h("td", { class: cls(columns[i] && columns[i].num && "num") }, cell))))
      : null;
    wrap.replaceChildren(h("table", {}, h("thead", {}, head), h("tbody", {}, body), foot));
  }

  draw();
  return wrap;
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
    projects ? h("div", { class: "body" }, "Matching projects: ", projects.map((p, i) => [i ? ", " : "", h("span", { class: "mono" }, p)])) : null,
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
  const m = path.match(/^\/c\/([^/]+)(?:\/(response|bash|files))?\/?$/);
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

const modelCell = (model) => model;

// ---------- conversation list (R3) ----------
const convRows = new Map();
const convTasks = new Map();
const convCounts = new Map();

function listRows(body) {
  const rows = Array.isArray(body) ? body : (body && body.conversations) || [];
  for (const row of [...rows].reverse()) convRows.set(row.id, row);
  return rows;
}

const projectMatches = (row, filter) => !filter || String(row.project || "").toLowerCase().includes(filter.toLowerCase());

let listFilter = "";

VIEWS.list = {
  title: () => "Conversations",
  load: async () => listRows(await api("/api/conversations")),
  head: () => h("div", { class: "page-head" }, h("h1", {}, "Conversations"),
    h("div", { class: "meta" }, h("span", {}, "Most recent first · times in UTC"))),
  render(rows) {
    if (!rows.length) {
      return emptyState("No conversations found", "There are no conversation logs in the projects folder yet (the one given "
        + "by --projects-dir, ~/.claude/projects by default). Conversations appear here after you use Claude Code.");
    }
    const count = h("span", { class: "count" });
    const holder = h("div", { class: "section" });
    const draw = () => {
      const shown = rows.filter((r) => projectMatches(r, listFilter));
      count.textContent = `${fmt(shown.length)} of ${fmt(rows.length)} conversations`;
      holder.replaceChildren(shown.length ? renderTable([
        { key: "modified", label: "Modified (UTC)", render: (r) => h("span", { class: "mono" }, utcMinute(r.modified)) },
        { key: "title", label: "Title", wrap: true,
          render: (r) => h("a", { href: convHref(r.id) }, r.title ? r.title : h("span", { class: "muted" }, "Untitled")) },
        { key: "project", label: "Project", render: (r) => h("span", { class: "mono" }, r.project) },
        { key: "size_kb", label: "Size KB", num: true, render: (r) => fmt(r.size_kb) },
        { key: "subagents", label: "Subagents", num: true, render: (r) => fmt(r.subagents) },
        { key: "id", label: "Conversation id", render: (r) => h("span", { class: "mono muted" }, r.id) },
      ], shown, { id: "list", sortKey: "modified", dir: -1, onRow: (r) => { location.hash = convHref(r.id); } })
        : emptyState("No matching conversations", `No conversation has a project matching “${listFilter}”.`));
    };
    const input = h("input", { id: "list-filter", type: "search", placeholder: "Filter by project path", value: listFilter, "aria-label": "Filter by project",
      oninput: (e) => { listFilter = e.target.value; draw(); } });
    draw();
    return [h("div", { class: "toolbar" }, h("label", { class: "field" }, "Project", input), count), holder];
  },
};

// ---------- conversation header and tabs (R4.5) ----------
const TABS = [["report", "Usage"], ["response", "Last response"], ["bash", "Bash commands"], ["files", "Files"]];

async function refreshConvRow(id) {
  try {
    listRows(await api("/api/conversations"));
  } catch (_) {
    // The header falls back to the id; the view itself reports its own errors.
  }
}

async function loadConversation(route, path) {
  const [data] = await Promise.all([api(`/api/conversations/${encodeURIComponent(route.id)}${path}`), refreshConvRow(route.id)]);
  return data;
}

function convHead(route) {
  const row = convRows.get(route.id), counts = convCounts.get(route.id) || {};
  const title = (row && row.title) || convTasks.get(route.id) || "Untitled conversation";
  const meta = [h("span", { class: "mono" }, route.id)];
  if (row) {
    meta.push(h("span", {}, h("b", { class: "mono" }, row.project)), h("span", {}, `Modified ${utcMinute(row.modified)} UTC`),
      h("span", {}, `${fmt(row.size_kb)} KB · ${fmt(row.subagents)} subagent${row.subagents === 1 ? "" : "s"}`));
  }
  return [h("div", { class: "page-head" },
    h("div", { class: "crumb" }, h("a", { href: "#/" }, "← Conversations")),
    h("h1", {}, title),
    h("div", { class: "meta" }, meta)),
  h("nav", { class: "tabs", "aria-label": "Conversation views" }, TABS.map(([key, label]) => h("a", {
    href: convHref(route.id, key), "aria-current": route.view === key ? "page" : null,
  }, label, counts[key] != null ? h("span", { class: "n" }, fmt(counts[key])) : null)))];
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

VIEWS.report = {
  title: convTitle,
  load: async (route) => {
    const data = await loadConversation(route, "");
    const main = (data.conversations || []).find((c) => c.kind === "main");
    if (main && main.task) convTasks.set(route.id, main.task);
    return data;
  },
  head: convHead,
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
    for (const s of scopes) {
      for (const model of Object.keys(s.models || {}).sort()) scopeRows.push({ ...s.models[model], kind: s.kind, id: s.id, task: s.task, model });
    }
    const tokens = sumBy(byModel, "total_tokens");
    const subagents = scopes.filter((s) => s.kind !== "main").length;
    const stats = h("div", { class: "stats" },
      stat("Estimated cost", money(data.estimated_total_cost_usd, guessed),
        [guessed ? "~ includes a guessed price" : "", unknown ? "excludes models without pricing" : ""].filter(Boolean).join(" · ")
          || "main + subagents"),
      stat("Total tokens", fmt(tokens), `${fmt(sumBy(byModel, "output"))} output`),
      stat("Scopes", `1 + ${subagents}`, "main + subagents"),
      stat("Served from cache", pct(tokens ? sumBy(byModel, "cache_read") / tokens : null), "of all tokens"));

    const duplicates = scopes.filter((s) => s.skipped_duplicates).map((s) => `${s.id}=${s.skipped_duplicates}`).join(", ");
    const usage = h("section", { class: "section" }, sectionHead("Usage per scope", "Main conversation and each subagent"),
      renderTable([
        { key: "kind", label: "Scope", render: (r) => h("span", { class: r.kind === "main" ? "chip main" : "chip" }, r.kind) },
        { key: "id", label: "ID", render: (r) => h("span", { class: "mono" }, r.id) },
        { key: "task", label: "Task", wrap: true },
        { key: "model", label: "Model", render: (r) => modelCell(r.model) },
        ...tokenColumns(),
        { key: "cache_read", label: "Cache read", num: true, render: (r) => fmt(r.cache_read) },
        { key: "cache_write", label: "Cache write 5m/1h", num: true, render: cacheWrite, sortValue: (r) => r.cache_write_5m + r.cache_write_1h },
        { key: "estimated_cost_usd", label: "Cost", num: true, render: (r) => money(r.estimated_cost_usd, r.price_estimated) },
      ], scopeRows, { id: "report-scopes" }),
      h("p", { class: "footnote" }, `Duplicates skipped: ${duplicates || "none"}`));

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
};

// ---------- content views (R7) ----------
function setCount(id, key, n) {
  convCounts.set(id, { ...(convCounts.get(id) || {}), [key]: n });
}

// Tags and attributes that the 'self'-only CSP would block anyway (inline styles, remote media) are dropped up front.
const SANITIZE = {
  FORBID_TAGS: ["style", "img", "picture", "video", "audio", "source", "track", "form", "input", "button", "textarea", "select"],
  FORBID_ATTR: ["style"],
};

function renderMarkdown(markdown) {
  const box = h("article", { class: "card md" });
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
  return box;
}

VIEWS.response = {
  title: (route) => `Last response · ${convTitle(route)}`,
  load: (route) => loadConversation(route, "/last-response"),
  head: convHead,
  render(data) {
    if (!data.last_response) {
      return emptyState("No text response", "The main conversation has no assistant text response yet. "
        + "Responses from subagents are not shown here.");
    }
    return [h("div", { class: "meta" }, "Last assistant text response of the main conversation · rendered Markdown"),
      renderMarkdown(data.last_response)];
  },
};

const sourceChip = (source) => h("span", { class: source === "main" ? "chip main" : "chip", title: source === "main" ? "Main conversation" : `Subagent ${source}` },
  source === "main" ? "main" : `subagent ${source.slice(0, 8)}`);

function parseStamp(stamp) {
  const d = stamp ? new Date(stamp) : null;
  return d && !Number.isNaN(d.getTime()) ? d : null;
}

VIEWS.bash = {
  title: (route) => `Bash commands · ${convTitle(route)}`,
  load: async (route) => {
    const data = await loadConversation(route, "/bash");
    setCount(route.id, "bash", (data.bash_commands || []).length);
    return data;
  },
  head: convHead,
  render(data) {
    const commands = (data.bash_commands || []).map((c) => ({ ...c, source: c.source || "main", when: parseStamp(c.timestamp) }));
    if (!commands.length) return emptyState("No Bash commands", "Neither the main conversation nor its subagents ran any Bash command.");
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
        h("pre", {}, c.command)));
    }
    const sources = [...new Set(commands.map((c) => c.source))];
    const fromMain = commands.filter((c) => c.source === "main").length;
    return [h("div", { class: "toolbar" }, h("div", { class: "meta" }, "Chronological across the main conversation and its subagents · times in UTC"),
      h("div", { class: "legend" }, sources.map((s) => h("span", {}, sourceChip(s))))),
    h("ol", { class: "cmds card" }, items),
    h("div", { class: "count" }, `${fmt(commands.length)} Bash commands · ${fmt(fromMain)} from main, ${fmt(commands.length - fromMain)} from subagents`)];
  },
};

VIEWS.files = {
  title: (route) => `Files · ${convTitle(route)}`,
  load: async (route) => {
    const data = await loadConversation(route, "/files");
    setCount(route.id, "files", Object.keys(data.files || {}).length);
    return data;
  },
  head: convHead,
  render(data) {
    const rows = Object.entries(data.files || {}).map(([file, t]) => ({
      file, Read: t.Read || 0, Write: t.Write || 0, Edit: t.Edit || 0, sources: Array.isArray(t.sources) ? t.sources : [],
    }));
    if (!rows.length) return emptyState("No files touched", "Neither the main conversation nor its subagents read, wrote or edited a file.");
    return [h("div", { class: "meta" }, "One row per file · counts add up every source that touched it"),
      renderTable([
        { key: "file", label: "File", render: (r) => h("span", { class: "mono" }, r.file) },
        { key: "Read", label: "Read", num: true, render: (r) => fmt(r.Read) },
        { key: "Write", label: "Write", num: true, render: (r) => fmt(r.Write) },
        { key: "Edit", label: "Edit", num: true, render: (r) => fmt(r.Edit) },
        { key: "sources", label: "Sources", sortValue: (r) => r.sources.length, render: (r) => r.sources.map(sourceChip) },
      ], rows, { id: "files", sortKey: "file", dir: 1 }),
      h("div", { class: "count" }, `${fmt(rows.length)} distinct file${rows.length === 1 ? "" : "s"}`)];
  },
};

// ---------- shell: app bar, loading, refresh (R9.4, R9.5) ----------
const app = { route: null, seq: 0, busy: false, phase: "loading", data: null, error: null, loadedAt: null, failedAt: null, timer: null, after: [] };

function updateBar() {
  const loaded = $("loaded");
  if (app.busy) loaded.textContent = "Loading…";
  else if (app.failedAt) loaded.textContent = `Load failed at ${utcTime(app.failedAt)} UTC`;
  else loaded.textContent = app.loadedAt ? `Loaded at ${utcTime(app.loadedAt)} UTC` : "Loaded at --:--:-- UTC";
  $("refresh").disabled = app.busy;
  const totals = app.route && app.route.view === "totals";
  $("nav-list").toggleAttribute("aria-current", !totals);
  $("nav-totals").toggleAttribute("aria-current", !!totals);
  if (!totals) $("nav-list").setAttribute("aria-current", "page");
  else $("nav-totals").setAttribute("aria-current", "page");
}

function runCleanups() {
  for (const fn of app.after.splice(0)) {
    try { fn(); } catch (e) { console.error(e); }
  }
}

function show({ keepScroll = false } = {}) {
  const route = app.route, view = VIEWS[route.view];
  const y = window.scrollY;
  const focused = document.activeElement && document.activeElement.id ? document.activeElement : null;
  runCleanups();
  const head = view.head ? view.head(route, app.data) : [];
  let body;
  if (app.phase === "loading") body = view.loading ? view.loading(route) : skeleton(8);
  else if (app.phase === "error") body = errorState(app.error, () => load({ refresh: false }));
  else body = view.render(app.data, route);
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

async function load({ refresh }) {
  const route = app.route, view = VIEWS[route.view], seq = ++app.seq;
  app.busy = true;
  if (!refresh || app.phase !== "ready") {
    app.phase = "loading";
    show();
  } else {
    updateBar();
  }
  try {
    const data = await view.load(route);
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
  app.route = parseRoute(location.hash);
  app.data = null;
  load({ refresh: false });
  window.scrollTo(0, 0);
}

function setAutoRefresh(on) {
  clearInterval(app.timer);
  app.timer = on ? setInterval(() => { if (!app.busy) load({ refresh: true }); }, 30000) : null;
}

function boot() {
  const auto = $("auto");
  auto.checked = false;
  auto.addEventListener("change", () => setAutoRefresh(auto.checked));
  $("refresh").addEventListener("click", () => load({ refresh: true }));
  window.addEventListener("hashchange", navigate);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (app.route) show({ keepScroll: true }); });
  navigate();
}

if (typeof document !== "undefined" && document.getElementById("main")) boot();
