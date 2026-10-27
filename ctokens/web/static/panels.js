"use strict";
// Panels next to a conversation: a commit's diff, a file of its folder and interactive shells, plus the links that
// open them on the hashes and file names the conversation mentions. Loaded before app.js and used by it, so this file
// only declares; everything runs once app.js has booted.

// ---------- dock: where panels live ----------
const DOCK_MODES = [["side", "Side panel"], ["bottom", "Bottom panel"], ["float", "Floating windows"], ["modal", "Overlay"]];
const DOCK_MODE_KEY = "ctokens.dock.mode";
const DOCK_SIZE_KEY = "ctokens.dock.size";
const DOCK_MIN = 260;

function stored(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch (e) {
    return fallback;
  }
}

function store(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (e) { /* kept for this page only */ }
}

// item: { key, title, kind, conv, body, z, rect, min, onShow(), onClose() }
function storedSize() {
  try {
    const size = JSON.parse(stored(DOCK_SIZE_KEY, "{}"));
    return size && typeof size === "object" ? size : {};
  } catch (e) {
    return {};
  }
}

const dock = { mode: DOCK_MODES.some(([m]) => m === stored(DOCK_MODE_KEY, "side")) ? stored(DOCK_MODE_KEY, "side") : "side",
  items: [], active: null, el: null, z: 30, size: storedSize() };

function openPanel(key, title, kind, conv, build) {
  let item = dock.items.find((i) => i.key === key);
  if (!item) {
    item = { key, title, kind, conv, body: h("div", { class: `panel-body ${kind}` }), min: false, onShow: null, onClose: null };
    dock.items.push(item);
    build(item);
  }
  focusPanel(item);
  return item;
}

function focusPanel(item) {
  dock.active = item;
  item.min = false;
  item.z = ++dock.z;
  drawDock();
  if (item.onShow) requestAnimationFrame(() => item.onShow());
}

function closePanel(item) {
  const i = dock.items.indexOf(item);
  if (i < 0) return;
  dock.items.splice(i, 1);
  if (item.onClose) item.onClose();
  if (dock.active === item) dock.active = dock.items[Math.min(i, dock.items.length - 1)] || null;
  drawDock();
  if (dock.active && dock.active.onShow) requestAnimationFrame(() => dock.active.onShow());
}

function setDockMode(mode) {
  dock.mode = mode;
  store(DOCK_MODE_KEY, mode);
  drawDock();
  for (const item of dock.items) if (item.onShow) requestAnimationFrame(() => item.onShow());
}

const KIND_ICONS = { commit: "⎇", file: "▤", shell: "❯", pick: "≡" };

function panelTab(item) {
  return h("div", { class: "dock-tab", role: "tab", "aria-selected": item === dock.active ? "true" : "false", title: item.title,
    onclick: () => focusPanel(item), onauxclick: (e) => { if (e.button === 1) closePanel(item); } },
  h("span", { class: "dock-kind", "aria-hidden": "true" }, KIND_ICONS[item.kind]), h("span", { class: "dock-title" }, item.title),
  h("button", { class: "dock-x", type: "button", title: "Close", "aria-label": `Close ${item.title}`,
    onclick: (e) => { e.stopPropagation(); closePanel(item); } }, "×"));
}

function modeSwitch() {
  return h("select", { class: "dock-mode", "aria-label": "Panel layout", title: "Panel layout",
    onchange: (e) => setDockMode(e.target.value) },
  DOCK_MODES.map(([value, label]) => h("option", { value, selected: value === dock.mode }, label)));
}

function dragResize(handle, axis, read, write) {
  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    const start = axis === "x" ? e.clientX : e.clientY, from = read();
    const move = (ev) => write(from + start - (axis === "x" ? ev.clientX : ev.clientY));
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      store(DOCK_SIZE_KEY, JSON.stringify(dock.size));
      for (const item of dock.items) if (item.onShow) item.onShow();
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
}

function barHeight() {
  const bar = document.querySelector(".appbar");
  return bar ? bar.getBoundingClientRect().height : 0;
}

function drawDock() {
  if (!dock.el) {
    dock.el = h("div", { id: "dock" });
    document.body.append(dock.el);
  }
  const root = document.documentElement;
  root.style.setProperty("--bar-h", `${barHeight()}px`);
  const shown = dock.items.length > 0;
  document.body.classList.toggle("dock-side", shown && dock.mode === "side");
  document.body.classList.toggle("dock-bottom", shown && dock.mode === "bottom");
  if (!shown) {
    dock.el.replaceChildren();
    dock.el.className = "";
    return;
  }
  if (dock.mode === "float") return drawFloating();
  const active = dock.active || dock.items[0];
  const tabs = h("div", { class: "dock-tabs", role: "tablist" }, dock.items.map(panelTab));
  const head = h("div", { class: "dock-head" }, tabs, modeSwitch(),
    dock.mode === "modal" ? h("button", { class: "dock-x big", type: "button", title: "Close all panels",
      "aria-label": "Close all panels", onclick: () => { dock.items.slice().forEach(closePanel); } }, "×") : null);
  const bodies = dock.items.map((item) => {
    item.body.hidden = item !== active;
    return item.body;
  });
  if (dock.mode === "side") {
    const width = Math.max(DOCK_MIN, Math.min(innerWidth - 320, dock.size.side || Math.round(innerWidth * 0.45)));
    root.style.setProperty("--dock-w", `${width}px`);
    const grip = h("div", { class: "dock-grip x", title: "Drag to resize" });
    dragResize(grip, "x", () => dock.size.side || width, (w) => {
      dock.size.side = Math.max(DOCK_MIN, Math.min(innerWidth - 320, w));
      root.style.setProperty("--dock-w", `${dock.size.side}px`);
    });
    dock.el.className = "dock side";
    dock.el.replaceChildren(grip, head, h("div", { class: "dock-bodies" }, bodies));
  } else if (dock.mode === "bottom") {
    const height = Math.max(160, Math.min(innerHeight - 160, dock.size.bottom || Math.round(innerHeight * 0.45)));
    root.style.setProperty("--dock-h", `${height}px`);
    const grip = h("div", { class: "dock-grip y", title: "Drag to resize" });
    dragResize(grip, "y", () => dock.size.bottom || height, (v) => {
      dock.size.bottom = Math.max(160, Math.min(innerHeight - 160, v));
      root.style.setProperty("--dock-h", `${dock.size.bottom}px`);
    });
    dock.el.className = "dock bottom";
    dock.el.replaceChildren(grip, head, h("div", { class: "dock-bodies" }, bodies));
  } else {
    dock.el.className = "dock modal";
    const box = h("div", { class: "dock-box", role: "dialog", "aria-modal": "true", "aria-label": active.title },
      head, h("div", { class: "dock-bodies" }, bodies));
    const backdrop = h("div", { class: "dock-backdrop", onclick: () => dock.items.slice().forEach(closePanel) });
    dock.el.replaceChildren(backdrop, box);
  }
}

// Floating: one window per panel, dragged by its title and resized from its corner; minimized ones wait in a tray.
function drawFloating() {
  dock.el.className = "dock float";
  const wins = [], tray = [];
  dock.items.forEach((item, n) => {
    if (!item.rect) {
      const w = Math.min(760, innerWidth - 40), hgt = Math.min(560, innerHeight - barHeight() - 60);
      item.rect = { x: Math.max(8, innerWidth - w - 24 - (n % 6) * 28), y: barHeight() + 16 + (n % 6) * 28, w, h: hgt };
    }
    if (item.min) {
      tray.push(h("button", { class: "tray-item", type: "button", title: item.title, onclick: () => focusPanel(item) },
        KIND_ICONS[item.kind], " ", h("span", {}, item.title)));
      return;
    }
    item.body.hidden = false;
    const title = h("div", { class: "win-title" }, h("span", { class: "dock-kind", "aria-hidden": "true" }, KIND_ICONS[item.kind]),
      h("span", { class: "dock-title" }, item.title), modeSwitch(),
      h("button", { class: "dock-x", type: "button", title: "Minimize", "aria-label": "Minimize",
        onclick: (e) => { e.stopPropagation(); item.min = true; drawDock(); } }, "–"),
      h("button", { class: "dock-x", type: "button", title: "Close", "aria-label": `Close ${item.title}`,
        onclick: (e) => { e.stopPropagation(); closePanel(item); } }, "×"));
    const win = h("section", { class: `dock-win${item === dock.active ? " active" : ""}`, role: "dialog", "aria-label": item.title,
      css: { left: `${item.rect.x}px`, top: `${item.rect.y}px`, width: `${item.rect.w}px`, height: `${item.rect.h}px`, zIndex: item.z || 30 } },
    title, item.body);
    win.addEventListener("pointerdown", () => {
      if (dock.active !== item) {
        dock.active = item;
        item.z = ++dock.z;
        win.style.zIndex = item.z;
        for (const other of dock.el.querySelectorAll(".dock-win")) other.classList.toggle("active", other === win);
      }
    });
    title.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button, select")) return;
      e.preventDefault();
      title.setPointerCapture(e.pointerId);
      const dx = e.clientX - item.rect.x, dy = e.clientY - item.rect.y;
      const move = (ev) => {
        item.rect.x = Math.max(0, Math.min(innerWidth - 80, ev.clientX - dx));
        item.rect.y = Math.max(0, Math.min(innerHeight - 40, ev.clientY - dy));
        win.style.left = `${item.rect.x}px`;
        win.style.top = `${item.rect.y}px`;
      };
      const up = () => {
        title.removeEventListener("pointermove", move);
        title.removeEventListener("pointerup", up);
      };
      title.addEventListener("pointermove", move);
      title.addEventListener("pointerup", up);
    });
    new ResizeObserver(() => {
      if (!win.isConnected || !win.offsetWidth) return;
      item.rect.w = win.offsetWidth;
      item.rect.h = win.offsetHeight;
      if (item.onShow) item.onShow();
    }).observe(win);
    wins.push(win);
  });
  dock.el.replaceChildren(...wins);
  if (tray.length) dock.el.append(h("div", { class: "dock-tray" }, tray));
}

function escapeClosesPanel(e) {
  if (e.key !== "Escape" || !dock.items.length || pick.el || e.target.closest(".xterm")) return;
  if (dock.mode === "modal" || (dock.el && dock.el.contains(e.target))) {
    const item = dock.mode === "modal" ? dock.active : dock.items.find((i) => i.body.contains(e.target));
    if (item) closePanel(item);
  }
}

// ---------- requests ----------
const convApi = (conv, path) => `/api/conversations/${encodeURIComponent(conv)}${path}`;
const postJson = (path, data) => api(path, { method: "POST", headers: { ...sendHeaders(), "Content-Type": "application/json" },
  body: JSON.stringify(data) });
const keyProblem = () => (!sendKey ? "These panels need the send key: open the link that claude_tokens.py --serve prints." : null);

function panelError(item, err) {
  item.body.replaceChildren(h("div", { class: "card state error", role: "alert" },
    h("div", { class: "title" }, "Couldn't open this panel"), h("div", { class: "body" }, err.message || String(err))));
}

const dirOf = (path) => path.replace(/\/[^/]*$/, "") || "/";
const baseName = (path) => path.split("/").pop();

// ---------- file viewer ----------
const LINE_PX = 20;
const HIGHLIGHT_MAX = 400_000;

function openFile(conv, match, at = {}) {
  const item = openPanel(`file:${match.path}`, `${baseName(match.display)}`, "file", conv, (it) => {
    it.title = match.display;
    it.body.append(skeleton(8));
    it.ready = api(`${convApi(conv, "/file")}?path=${encodeURIComponent(match.path)}`, { headers: sendHeaders() })
      .then((data) => { it.view = fileView(conv, it, data); }, (err) => panelError(it, err));
  });
  item.ready.then(() => { if (item.view) item.view.go(at.line, at.end); });
}

function fileView(conv, item, data) {
  const lines = data.text.split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  const lang = highlighting() ? languageOfPath(hljs, data.path) : null;
  const code = h("code", { class: coloured(lang) ? `language-${lang}` : "" }, data.text);
  if (coloured(lang) && data.text.length <= HIGHLIGHT_MAX) hljs.highlightElement(code);
  const gutter = h("pre", { class: "fv-gutter", "aria-hidden": "true" }, lines.map((_, i) => `${i + 1}\n`).join(""));
  const mark = h("div", { class: "fv-mark", hidden: true });
  const scroller = h("div", { class: "fv-scroll", tabindex: "0" }, h("div", { class: "fv-code" }, gutter, h("pre", { class: "fv-text" }, code), mark));
  const goto = h("input", { class: "fv-goto", type: "number", min: 1, max: lines.length, placeholder: "Line", "aria-label": "Go to line",
    onkeydown: (e) => { if (e.key === "Enter") go(Number(goto.value)); } });
  gutter.addEventListener("click", (e) => go(Math.floor((e.offsetY - 8) / LINE_PX) + 1));
  const go = (line, end) => {
    if (!line || line < 1) return;
    line = Math.min(line, lines.length || 1);
    end = Math.max(line, Math.min(end || line, lines.length || 1));
    mark.hidden = false;
    mark.style.top = `${8 + (line - 1) * LINE_PX}px`;
    mark.style.height = `${(end - line + 1) * LINE_PX}px`;
    scroller.scrollTop = Math.max(0, 8 + (line - 1) * LINE_PX - scroller.clientHeight / 3);
    goto.value = line;
  };
  const notes = [data.binary ? "Binary file: not shown." : null,
    data.truncated ? `Only the first ${fmtBytes(data.text.length)} of ${fmtBytes(data.size)} are shown.` : null].filter(Boolean);
  item.body.replaceChildren();
  append(item.body, [h("div", { class: "panel-bar" },
    copyable(h("span", { class: "mono path" }, breakable(data.display)), data.path),
    h("span", { class: "muted" }, `${fmt(lines.length)} lines · ${fmtBytes(data.size)}${lang && lang !== "plaintext" ? ` · ${languageName(lang)}` : ""}`),
    h("span", { class: "spacer" }), goto,
    h("button", { class: "btn", type: "button", title: `Open a shell in ${dirOf(data.path)}`, onclick: () => openShell(conv, dirOf(data.path)) }, "❯ Shell here")),
  notes.length ? h("div", { class: "notice" }, notes.join(" ")) : null, data.binary ? null : scroller]);
  return { go };
}

// ---------- commit viewer ----------
const DIFF_OPEN_LINES = 4000;
const DIFF_HIGHLIGHT_LINES = 1500;

function openCommit(conv, sha, label) {
  openPanel(`commit:${sha}`, `${(label || sha).slice(0, 10)}`, "commit", conv, (item) => {
    item.body.append(skeleton(10));
    api(`${convApi(conv, "/commit")}?sha=${encodeURIComponent(sha)}`, { headers: sendHeaders() })
      .then((data) => {
        item.title = `${data.sha.slice(0, 10)} ${data.message.split("\n")[0]}`;
        drawDock();
        commitView(conv, item, data);
      }, (err) => panelError(item, err));
  });
}

function diffSections(patch) {
  return patch.split(/^(?=diff --git )/m).filter((s) => s.startsWith("diff --git "));
}

function diffRows(section, path, lang) {
  const rows = [];
  let oldN = 0, newN = 0, inHunk = false;
  const highlight = coloured(lang) && section.length < 400_000;
  for (const line of section.replace(/\n$/, "").split("\n")) {
    const hunk = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) {
      oldN = Number(hunk[1]);
      newN = Number(hunk[2]);
      inHunk = true;
      rows.push(h("div", { class: "dl hunk" }, h("span", { class: "ln" }), h("span", { class: "ln" }), h("span", { class: "dc" }, line)));
      continue;
    }
    if (!inHunk) continue;
    const sign = line[0];
    const cls = sign === "+" ? "add" : sign === "-" ? "del" : sign === "\\" ? "meta" : "ctx";
    const a = cls === "add" || cls === "meta" ? "" : oldN++, b = cls === "del" || cls === "meta" ? "" : newN++;
    const text = h("code", { class: highlight ? `language-${lang}` : "" }, line.slice(1));
    rows.push(h("div", { class: `dl ${cls}`, "data-new": b === "" ? null : b }, h("span", { class: "ln" }, a), h("span", { class: "ln" }, b),
      h("span", { class: "dc" }, h("span", { class: "sign" }, sign || " "), text)));
  }
  if (highlight && rows.length <= DIFF_HIGHLIGHT_LINES) for (const code of rows.flatMap((r) => [...r.querySelectorAll("code[class]")])) hljs.highlightElement(code);
  return rows;
}

function commitView(conv, item, data) {
  const [subject, ...rest] = data.message.split("\n");
  const body = rest.join("\n").trim();
  const sections = new Map(diffSections(data.patch).map((s) => {
    const m = s.match(/^diff --git a\/(.*?) b\/(.*)$/m);
    return [m ? m[2] : s.slice(11, 80), s];
  }));
  const total = data.files.reduce((n, f) => n + (f.added || 0) + (f.deleted || 0), 0);
  const fileBoxes = new Map();
  const files = data.files.map((f) => {
    const section = sections.get(f.path) || "";
    const lang = highlighting() ? languageOfPath(hljs, f.path) : null;
    const open = () => openFile(conv, { path: `${data.root}/${f.path}`, display: f.path });
    const box = lazyDetails("diff-file", [h("span", { class: "mono path" }, f.old_path ? `${f.old_path} → ${f.path}` : f.path),
      h("span", { class: "diff-stat" }, f.added == null ? h("span", { class: "muted" }, "binary") : [h("span", { class: "plus" }, `+${f.added}`), " ",
        h("span", { class: "minus" }, `−${f.deleted}`)]),
      h("button", { class: "btn small", type: "button", title: "Open the file as it is now in the working tree",
        onclick: (e) => { e.preventDefault(); open(); } }, "Open file")],
    () => {
      const rows = diffRows(section, f.path, lang);
      const grid = h("div", { class: "diff" }, rows.length ? rows : h("div", { class: "muted pad" }, "No textual change."));
      grid.addEventListener("click", (e) => {
        const row = e.target.closest(".ln") && e.target.closest(".dl[data-new]");
        if (row) openFile(conv, { path: `${data.root}/${f.path}`, display: f.path }, { line: Number(row.dataset.new) });
      });
      return grid;
    });
    fileBoxes.set(f.path, box);
    return box;
  });
  if (total <= DIFF_OPEN_LINES) for (const box of fileBoxes.values()) box.open = true;
  const parents = data.parents.map((p) => h("span", { class: "ref ref-commit", role: "link", tabindex: "0", "data-sha": p, title: `Parent ${p}` }, p.slice(0, 10)));
  item.body.replaceChildren(h("div", { class: "commit-head" },
    h("div", { class: "commit-subject" }, subject),
    body ? h("pre", { class: "commit-body" }, body) : null,
    h("div", { class: "meta" },
      copyable(h("span", { class: "mono" }, data.sha), data.sha),
      h("span", {}, `${data.author} · ${data.author_date.replace("T", " ").slice(0, 16)}`),
      parents.length ? h("span", {}, parents.length > 1 ? "Parents " : "Parent ", parents) : h("span", { class: "muted" }, "Root commit"),
      data.refs ? h("span", { class: "chip" }, data.refs) : null),
    h("div", { class: "meta" }, `${fmt(data.files.length)} file${data.files.length === 1 ? "" : "s"} changed`,
      h("span", { class: "plus" }, `+${fmt(data.files.reduce((n, f) => n + (f.added || 0), 0))}`),
      h("span", { class: "minus" }, `−${fmt(data.files.reduce((n, f) => n + (f.deleted || 0), 0))}`),
      h("button", { class: "btn small", type: "button", onclick: () => { for (const b of fileBoxes.values()) b.open = true; } }, "Expand all"),
      h("button", { class: "btn small", type: "button", onclick: () => { for (const b of fileBoxes.values()) b.open = false; } }, "Collapse all")),
    data.truncated ? h("div", { class: "notice" }, "The patch is too long; only its beginning is shown.") : null),
  h("div", { class: "commit-files" }, files));
}

// ---------- shells ----------
let shellCount = 0;
// One event stream carries every shell of the page: the browser opens at most six connections to a host, shared by
// all its tabs, and each stream holds one. id -> { offset, write(bytes), exit(code) }.
const shellStream = { es: null, shells: new Map() };

function streamShells() {
  if (shellStream.es) shellStream.es.close();
  shellStream.es = null;
  const shells = [...shellStream.shells];
  if (!shells.length || document.hidden) return;
  const es = new EventSource(`/api/shells/stream?from=${shells.map(([id, sh]) => `${id}:${sh.offset}`).join(",")}`);
  shellStream.es = es;
  const shellOf = (e) => {
    const data = JSON.parse(e.data);
    return [shellStream.shells.get(data.id), data];
  };
  es.addEventListener("data", (e) => {
    const [sh, data] = shellOf(e);
    if (!sh) return;
    sh.offset = data.at;
    sh.write(Uint8Array.from(atob(data.data), (c) => c.charCodeAt(0)));
  });
  es.addEventListener("exit", (e) => {
    const [sh, data] = shellOf(e);
    if (!sh) return;
    shellStream.shells.delete(data.id);
    sh.exit(data.code);
  });
  es.addEventListener("end", () => {
    es.close();
    if (shellStream.es === es) shellStream.es = null;
  });
}

function measureCell(term, el) {
  const dims = term._core && term._core._renderService && term._core._renderService.dimensions;
  if (dims && dims.css && dims.css.cell && dims.css.cell.width) return dims.css.cell;
  const probe = h("span", { class: "xterm-probe" }, "W".repeat(50));
  el.append(probe);
  const box = { width: probe.offsetWidth / 50 || 8, height: probe.offsetHeight || 17 };
  probe.remove();
  return box;
}

function terminalTheme() {
  return { background: cssVar("--term-bg"), foreground: cssVar("--term-fg"), cursor: cssVar("--accent"),
    selectionBackground: cssVar("--accent-soft") };
}

function openShell(conv, cwd) {
  const problem = keyProblem();
  if (problem) return alert(problem);
  const n = ++shellCount;
  openPanel(`shell:${n}`, `Shell ${n} · ${baseName(cwd) || cwd}`, "shell", conv, (item) => {
    const screen = h("div", { class: "term" });
    const status = h("span", { class: "muted" }, "Starting…");
    item.body.append(h("div", { class: "panel-bar" }, h("span", { class: "mono path" }, breakable(cwd)), status), screen);
    const term = new Terminal({ fontFamily: cssVar("--mono") || "monospace", fontSize: 13, cursorBlink: true, scrollback: 5000,
      theme: terminalTheme(), allowProposedApi: false });
    const sh = { id: null, queue: "", sending: false, cols: 80, rows: 24, ended: false };
    let opened = false;
    const fit = () => {
      if (!screen.isConnected || !screen.clientWidth || !screen.clientHeight) return;
      if (!opened) {
        term.open(screen);
        opened = true;
      }
      const cell = measureCell(term, screen);
      const cols = Math.max(20, Math.floor((screen.clientWidth - 14) / cell.width));
      const rows = Math.max(5, Math.floor(screen.clientHeight / cell.height));
      if (cols !== term.cols || rows !== term.rows) term.resize(cols, rows);
      if (sh.id && (cols !== sh.cols || rows !== sh.rows)) postJson(`/api/shells/${sh.id}/resize`, { cols, rows }).catch(() => {});
      Object.assign(sh, { cols, rows });
    };
    const pump = async () => {
      if (sh.sending || !sh.queue || !sh.id || sh.ended) return;
      sh.sending = true;
      const data = sh.queue;
      sh.queue = "";
      try {
        await postJson(`/api/shells/${sh.id}/input`, { data });
      } catch (err) {
        status.textContent = `Input lost: ${err.message}`;
      }
      sh.sending = false;
      pump();
    };
    term.onData((data) => {
      sh.queue += data;
      pump();
    });
    item.onShow = () => {
      fit();
      if (item === dock.active || dock.mode === "float") term.focus();
    };
    item.onClose = () => {
      if (sh.id && shellStream.shells.delete(sh.id)) streamShells();
      if (sh.id && !sh.ended) postJson(`/api/shells/${sh.id}/close`, {}).catch(() => {});
      term.dispose();
    };
    new ResizeObserver(() => fit()).observe(screen);
    requestAnimationFrame(async () => {
      fit();
      try {
        const data = await postJson(convApi(conv, "/shell"), { cwd, cols: sh.cols, rows: sh.rows });
        sh.id = data.shell.id;
      } catch (err) {
        status.textContent = `Not started: ${err.message}`;
        return;
      }
      status.textContent = "Running";
      shellStream.shells.set(sh.id, { offset: 0, write: (bytes) => term.write(bytes), exit: (code) => {
        sh.ended = true;
        status.textContent = code == null ? "Ended" : `Ended (exit code ${code})`;
        term.write(`\r\n\x1b[2m[${code == null ? "the shell is gone" : `process exited with code ${code}`}]\x1b[0m\r\n`);
      } });
      streamShells();
      pump();
      item.onShow();
    });
  });
}

function shellButton(conv, cwd) {
  return h("button", { class: "btn", type: "button", title: `Open an interactive shell in ${cwd}`,
    onclick: () => openShell(conv, cwd) }, "❯ Shell");
}

// ---------- chooser for a name that matches several files ----------
const pick = { el: null, digits: "", timer: null };

function closePick() {
  if (!pick.el) return;
  pick.el.remove();
  pick.el = null;
  pick.cleanup();
}

function choose(conv, matches, at, anchor) {
  closePick();
  const open = (i) => {
    if (!matches[i]) return;
    closePick();
    openFile(conv, matches[i], at);
  };
  const items = matches.map((m, i) => h("button", { type: "button", class: "pick-item", onclick: () => open(i) },
    h("kbd", {}, String(i + 1)), h("span", { class: "mono" }, breakable(m.display))));
  const menu = h("div", { class: "pick", role: "menu", "aria-label": "Open which file?" },
    h("div", { class: "copy-menu-head" }, `${matches.length} files match · press a number`), items);
  document.body.append(menu);
  const r = anchor.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(r.left, innerWidth - menu.offsetWidth - 8))}px`;
  menu.style.top = `${r.bottom + 4 + menu.offsetHeight > innerHeight ? Math.max(8, r.top - 4 - menu.offsetHeight) : r.bottom + 4}px`;
  const keys = (e) => {
    if (/^[0-9]$/.test(e.key)) {
      e.preventDefault();
      pick.digits += e.key;
      clearTimeout(pick.timer);
      const n = Number(pick.digits);
      // 1 opens at once with fewer than 10 matches; with more, a second digit may follow.
      if (n * 10 > matches.length) open(n - 1);
      else pick.timer = setTimeout(() => open(n - 1), 600);
      return;
    }
    const i = items.indexOf(document.activeElement);
    if (e.key === "Escape") {
      e.preventDefault();
      closePick();
      anchor.focus();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    }
  };
  const outside = (e) => { if (!menu.contains(e.target)) closePick(); };
  menu.addEventListener("keydown", keys);
  document.addEventListener("pointerdown", outside, true);
  window.addEventListener("hashchange", closePick);
  pick.el = menu;
  pick.digits = "";
  pick.cleanup = () => {
    clearTimeout(pick.timer);
    document.removeEventListener("pointerdown", outside, true);
    window.removeEventListener("hashchange", closePick);
  };
  items[0].focus();
}

// ---------- links on commit hashes and file names ----------
const COMMIT_RE = /(?<![\w/.\-])[0-9a-f]{7,40}(?![\w/\-])/g;
const FILE_RE = /(?<![\w@./~\-])((?:~|\.{1,2})?\/?(?:[\w@+.\-]+\/)*(?:[\w@+\-][\w@+.\-]*\.[A-Za-z][\w\-]{0,11}|Makefile|Dockerfile|Jenkinsfile|README|LICENSE))(?:(?::|#L)(\d+)(?:([:\-])(\d+))?)?(?![\w/])/g;
const LINK_SKIP = "a, button, input, textarea, select, summary, kbd, .ref, #conv-head, .composer, .xterm, .msg-head, .dock, .pick";
const RESOLVE_BATCH = 400;

// conversation id -> { commits: Map(token -> info|null), files: Map(token -> matches|null) }
const refCache = new Map();
const linker = { observer: null, queue: new Set(), timer: null, off: false };

function refsOf(conv) {
  if (!refCache.has(conv)) refCache.set(conv, { commits: new Map(), files: new Map() });
  return refCache.get(conv);
}

function candidates(text) {
  const found = [];
  for (const m of text.matchAll(COMMIT_RE)) {
    if (/\d/.test(m[0]) && /[a-f]/.test(m[0])) found.push({ kind: "commit", start: m.index, end: m.index + m[0].length, token: m[0] });
  }
  for (const m of text.matchAll(FILE_RE)) {
    if (/^\d+(\.\d+)+$/.test(m[1])) continue;
    found.push({ kind: "file", start: m.index, end: m.index + m[0].length, token: m[1],
      line: m[2] ? Number(m[2]) : null, end2: m[3] === "-" && m[4] ? Number(m[4]) : null });
  }
  return found.sort((a, b) => a.start - b.start || b.end - a.end)
    .filter((c, i, all) => !all.slice(0, i).some((o) => c.start < o.end && o.start < c.end));
}

function textNodes(root) {
  const nodes = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.data.length < 7 || !n.parentElement || n.parentElement.closest(LINK_SKIP)
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  while (walker.nextNode()) nodes.push(walker.currentNode);
  return nodes;
}

async function resolveRefs(conv, commits, files) {
  const refs = refsOf(conv);
  commits = [...new Set(commits)].filter((c) => !refs.commits.has(c));
  files = [...new Set(files)].filter((f) => !refs.files.has(f));
  for (let i = 0; i < Math.max(commits.length, files.length); i += RESOLVE_BATCH) {
    const c = commits.slice(i, i + RESOLVE_BATCH), f = files.slice(i, i + RESOLVE_BATCH);
    for (const x of c) refs.commits.set(x, null);
    for (const x of f) refs.files.set(x, null);
    const data = await postJson(convApi(conv, "/resolve"), { commits: c, files: f });
    for (const [k, v] of Object.entries(data.commits)) refs.commits.set(k, v);
    for (const [k, v] of Object.entries(data.files)) refs.files.set(k, v);
  }
}

function refSpan(c, text, refs) {
  if (c.kind === "commit") {
    const info = refs.commits.get(c.token);
    if (!info) return null;
    return h("span", { class: "ref ref-commit", role: "link", tabindex: "0", "data-sha": info.sha,
      title: [info.sha.slice(0, 12), info.subject, info.author && `${info.author}, ${info.date}`].filter(Boolean).join(" · ") }, text);
  }
  const matches = refs.files.get(c.token);
  if (!matches) return null;
  return h("span", { class: `ref ref-file${matches.length > 1 ? " many" : ""}`, role: "link", tabindex: "0", "data-file": c.token,
    "data-line": c.line, "data-end": c.end2,
    title: matches.length > 1 ? `${matches.length} files match: ${matches.slice(0, 8).map((m) => m.display).join(", ")}${matches.length > 8 ? "…" : ""}`
      : `Open ${matches[0].display}${c.line ? ` at line ${c.line}` : ""}` }, text);
}

async function linkify(roots) {
  const conv = app.route && app.route.id;
  if (!conv || linker.off || !sendKey) return;
  const work = [];
  for (const root of roots) {
    if (!root.isConnected) continue;
    for (const node of textNodes(root)) {
      const found = candidates(node.data);
      if (found.length) work.push({ node, found });
    }
  }
  if (!work.length) return;
  try {
    await resolveRefs(conv, work.flatMap((w) => w.found.filter((c) => c.kind === "commit").map((c) => c.token)),
      work.flatMap((w) => w.found.filter((c) => c.kind === "file").map((c) => c.token)));
  } catch (err) {
    if (err.status === 403) linker.off = true;
    return;
  }
  if (!app.route || app.route.id !== conv) return;
  const refs = refsOf(conv);
  for (const { node, found } of work) {
    if (!node.isConnected) continue;
    const text = node.data, parts = [];
    let at = 0;
    for (const c of found) {
      const span = refSpan(c, text.slice(c.start, c.end), refs);
      if (!span) continue;
      parts.push(text.slice(at, c.start), span);
      at = c.end;
    }
    if (!parts.length) continue;
    parts.push(text.slice(at));
    node.replaceWith(...parts.filter((p) => p !== ""));
  }
}

function startPanels() {
  // xterm.js adds <style> elements; the CSP accepts them with the nonce the server wrote into this page.
  const nonce = document.querySelector('meta[name="style-nonce"]');
  const create = Document.prototype.createElement;
  if (nonce) {
    Document.prototype.createElement = function createElement(tag, options) {
      const el = create.call(this, tag, options);
      if (String(tag).toLowerCase() === "style") el.setAttribute("nonce", nonce.content);
      return el;
    };
  }
  document.addEventListener("keydown", escapeClosesPanel);
  // A hidden tab gives its connection back; the shells pick up from the byte they had reached.
  document.addEventListener("visibilitychange", streamShells);
  window.addEventListener("resize", () => { if (dock.items.length) drawDock(); });
  const main = $("main");
  linker.observer = new MutationObserver((records) => {
    for (const r of records) for (const n of r.addedNodes) if (n.nodeType === 1 && !n.classList.contains("ref")) linker.queue.add(n);
    clearTimeout(linker.timer);
    linker.timer = setTimeout(() => {
      const roots = [...linker.queue].filter((n) => ![...linker.queue].some((o) => o !== n && o.contains(n)));
      linker.queue.clear();
      linkify(roots);
    }, 60);
  });
  linker.observer.observe(main, { childList: true, subtree: true });
  linker.queue.add(main);
  document.addEventListener("click", followRef);
  document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.classList && e.target.classList.contains("ref")) followRef(e); });
}

function followRef(e) {
  const ref = e.target.closest && e.target.closest(".ref");
  if (!ref) return;
  const item = dock.items.find((i) => i.body.contains(ref));
  const conv = item ? item.conv : app.route && app.route.id;
  if (!conv) return;
  e.preventDefault();
  if (ref.dataset.sha) return openCommit(conv, ref.dataset.sha);
  const matches = refsOf(conv).files.get(ref.dataset.file) || [];
  const at = { line: ref.dataset.line ? Number(ref.dataset.line) : null, end: ref.dataset.end ? Number(ref.dataset.end) : null };
  if (matches.length === 1) openFile(conv, matches[0], at);
  else if (matches.length > 1) choose(conv, matches, at, ref);
}
