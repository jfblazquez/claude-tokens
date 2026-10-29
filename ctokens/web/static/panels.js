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

// item: { key, title, tip (the full name, on hover), kind, conv, body, z, rect, min, onShow(), onClose() }
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

// What a person closes goes through here: a shell running a command asks first.
async function requestClose(item) {
  if (item.confirmClose && !(await item.confirmClose())) return;
  closePanel(item);
}

async function closeAll() {
  for (const item of dock.items.slice()) await requestClose(item);
}

// A middle click closes, as on browser tabs; held down it would otherwise start autoscroll or paste on Linux.
function middleCloses(el, item) {
  el.addEventListener("mousedown", (e) => { if (e.button === 1) e.preventDefault(); });
  el.addEventListener("auxclick", (e) => {
    if (e.button !== 1) return;
    e.preventDefault();
    requestClose(item);
  });
  return el;
}

function setDockMode(mode) {
  dock.mode = mode;
  store(DOCK_MODE_KEY, mode);
  drawDock();
  for (const item of dock.items) if (item.onShow) requestAnimationFrame(() => item.onShow());
}

const KIND_ICONS = { commit: "⎇", commits: "☰", file: "▤", dir: "▦", shell: "❯", pick: "≡" };
// Fonts seldom have a magnifying glass, so search draws its own.
const kindIcon = (kind) => (kind === "search" ? icon("search") : KIND_ICONS[kind]);

function panelTab(item) {
  return item.tabEl = middleCloses(h("div", { class: `dock-tab${item.changed ? " changed" : ""}`, role: "tab",
    "aria-selected": item === dock.active ? "true" : "false", title: item.tip || item.title, onclick: () => focusPanel(item) },
  h("span", { class: "dock-kind", "aria-hidden": "true" }, kindIcon(item.kind)), h("span", { class: "dock-title" }, item.title),
  h("button", { class: "dock-x", type: "button", title: "Close (middle click on the tab)", "aria-label": `Close ${item.title}`,
    onclick: (e) => { e.stopPropagation(); requestClose(item); } }, "×")), item);
}

// Tabs that do not fit stay reachable from here, next to the layout and closing them all.
function panelMenu(tabs) {
  const button = h("button", { class: "dock-menu-btn", type: "button", title: "Open panels and layout", "aria-haspopup": "menu" }, icon("chevron"));
  button.addEventListener("click", (e) => {
    e.stopPropagation();
    if (copyMenu && copyMenu.button === button) return closeCopyMenu(true);
    openPanelMenu(button);
  });
  if (tabs) {
    const count = () => {
      const box = tabs.getBoundingClientRect();
      const hidden = [...tabs.children].filter((t) => {
        const r = t.getBoundingClientRect();
        return r.right > box.right + 1 || r.left < box.left - 1;
      }).length;
      button.replaceChildren(...(hidden ? [`+${hidden}`] : []), icon("chevron"));
      button.title = hidden ? `${hidden} more panel${hidden === 1 ? "" : "s"}, the layout and closing them all` : "Open panels and layout";
    };
    tabs.addEventListener("scroll", count, { passive: true });
    new ResizeObserver(count).observe(tabs);
  }
  return button;
}

function openPanelMenu(button) {
  closeCopyMenu(false);
  const entry = (label, act, opts = {}) => h("button", { type: "button", role: opts.role || "menuitem", class: `copy-menu-item${opts.on ? " on" : ""}`,
    "aria-checked": opts.role ? String(!!opts.on) : null, title: opts.tip || null,
    onclick: () => { closeCopyMenu(false); act(); } }, label);
  const items = [
    ...dock.items.map((item) => entry([h("span", { class: "dock-kind", "aria-hidden": "true" }, kindIcon(item.kind)), " ",
      h("span", { class: "dock-title" }, item.title)], () => focusPanel(item), { on: item === dock.active, tip: item.tip || item.title })),
    ...DOCK_MODES.map(([mode, label]) => entry(label, () => setDockMode(mode), { role: "menuitemradio", on: mode === dock.mode })),
    entry("Close all panels", closeAll),
  ];
  const n = dock.items.length;
  const menu = h("div", { class: "copy-menu dock-menu", role: "menu", "aria-label": "Panels" },
    h("div", { class: "copy-menu-head" }, `${n} open panel${n === 1 ? "" : "s"}`), items.slice(0, n),
    h("div", { class: "copy-menu-head" }, "Layout"), items.slice(n, n + DOCK_MODES.length), h("hr"), items.slice(n + DOCK_MODES.length));
  document.body.append(menu);
  const r = button.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(r.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 8))}px`;
  menu.style.top = `${r.bottom + 4 + menu.offsetHeight > innerHeight ? Math.max(8, r.top - 4 - menu.offsetHeight) : r.bottom + 4}px`;
  const outside = (e) => { if (!menu.contains(e.target) && e.target !== button) closeCopyMenu(false); };
  const keys = (e) => {
    const i = items.indexOf(document.activeElement);
    if (e.key === "Escape" || e.key === "Tab") {
      e.stopPropagation();
      closeCopyMenu(e.key === "Escape");
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    }
  };
  document.addEventListener("pointerdown", outside, true);
  menu.addEventListener("keydown", keys);
  copyMenu = { menu, button, cleanup: () => document.removeEventListener("pointerdown", outside, true) };
  (items.find((b) => b.classList.contains("on")) || items[0]).focus();
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
  // Its button is about to be drawn anew.
  if (copyMenu && copyMenu.menu.classList.contains("dock-menu")) closeCopyMenu(false);
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
  // No scrollbar under the tabs: the wheel scrolls them sideways and the menu lists the ones out of view.
  tabs.addEventListener("wheel", (e) => {
    if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
    e.preventDefault();
    tabs.scrollLeft += e.deltaY;
  }, { passive: false });
  const head = h("div", { class: "dock-head" }, tabs, panelMenu(tabs),
    dock.mode === "modal" ? h("button", { class: "dock-x big", type: "button", title: "Close all panels",
      "aria-label": "Close all panels", onclick: closeAll }, "×") : null);
  requestAnimationFrame(() => {
    const current = tabs.querySelector('[aria-selected="true"]');
    if (current) tabs.scrollLeft = Math.max(0, Math.min(tabs.scrollLeft, current.offsetLeft - 8),
      current.offsetLeft + current.offsetWidth + 8 - tabs.clientWidth);
  });
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
    const backdrop = h("div", { class: "dock-backdrop", onclick: closeAll });
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
      tray.push(item.tabEl = middleCloses(h("button", { class: `tray-item${item.changed ? " changed" : ""}`, type: "button", title: item.title,
        onclick: () => focusPanel(item) }, kindIcon(item.kind), " ", h("span", {}, item.title)), item));
      return;
    }
    item.body.hidden = false;
    const title = item.tabEl = h("div", { class: `win-title${item.changed ? " changed" : ""}` }, h("span", { class: "dock-kind", "aria-hidden": "true" }, kindIcon(item.kind)),
      h("span", { class: "dock-title", title: item.tip || item.title }, item.tip || item.title), panelMenu(null),
      h("button", { class: "dock-x", type: "button", title: "Minimize", "aria-label": "Minimize",
        onclick: (e) => { e.stopPropagation(); item.min = true; drawDock(); } }, "–"),
      h("button", { class: "dock-x", type: "button", title: "Close (middle click on the title)", "aria-label": `Close ${item.title}`,
        onclick: (e) => { e.stopPropagation(); requestClose(item); } }, "×"));
    middleCloses(title, item);
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

// Ctrl+G with nothing focused goes to a line of the file panel in view, as it does with the focus in that panel.
function gotoActiveFile(e) {
  if (!isGotoKey(e) || e.defaultPrevented || (e.target !== document.body && e.target !== document.documentElement)) return;
  const item = dock.active;
  if (!item || item.kind !== "file" || !item.view || !shownPanel(item)) return;
  e.preventDefault();
  item.view.askLine();
}

function escapeClosesPanel(e) {
  if (e.key !== "Escape" || !dock.items.length || pick.el || e.target.closest(".xterm")) return;
  if (dock.mode === "modal" || (dock.el && dock.el.contains(e.target))) {
    const item = dock.mode === "modal" ? dock.active : dock.items.find((i) => i.body.contains(e.target));
    if (item) requestClose(item);
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

// ---------- open panels follow their file or folder on disk ----------
const RELOAD_KEY = "ctokens.panels.reload";
const WATCH_MS = 2000;
const reloadMode = () => (stored(RELOAD_KEY, "auto") === "ask" ? "ask" : "auto");
const watcher = { busy: false };

// item.watch: { path, stamp (as loaded), seen (last stamp on disk), due, gone, reload() }
function watch(item, path, stamp, reload) {
  item.watch = { path, stamp, seen: stamp, due: false, gone: false, reload };
  markChanged(item, false);
}

function markChanged(item, on) {
  item.changed = on;
  if (item.tabEl) item.tabEl.classList.toggle("changed", on);
  if (!on && item.banner) item.banner.remove();
  if (!on) item.banner = null;
}

const shownPanel = (item) => item.body.isConnected && item.body.getClientRects().length > 0;

// Reloading would drop what the reader is doing in the panel: a selection, or typing in its fields.
function busyPanel(item) {
  const selection = getSelection();
  if (!selection.isCollapsed && selection.anchorNode && item.body.contains(selection.anchorNode)) return true;
  return item.body.contains(document.activeElement) && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
}

function changeBanner(item, text, actions) {
  if (item.banner) item.banner.remove();
  item.banner = h("div", { class: "notice changed-notice", role: "status" }, h("span", {}, text), actions);
  const bar = item.body.querySelector(".panel-bar");
  if (bar) bar.after(item.banner);
  else item.body.prepend(item.banner);
}

// What a change seen on disk does: reloads the panel, or asks first when the settings say so.
function settle(item) {
  const w = item.watch;
  if (!w || !w.due) return;
  const what = item.kind === "dir" ? "folder" : "file";
  if (w.gone) {
    w.due = false;
    markChanged(item, true);
    changeBanner(item, `This ${what} is no longer on disk.`, []);
    return;
  }
  if (reloadMode() === "ask") {
    w.due = false;
    markChanged(item, true);
    const reload = () => { markChanged(item, false); w.reload(); };
    changeBanner(item, `This ${what} changed on disk.`, [
      h("button", { class: "btn small", type: "button", onclick: reload }, "Reload"),
      h("button", { class: "btn small", type: "button", title: "Reload open panels by themselves from now on (⚙ settings)",
        onclick: () => { store(RELOAD_KEY, "auto"); reload(); } }, "Always reload")]);
    return;
  }
  if (!shownPanel(item) || busyPanel(item)) return;
  w.due = false;
  w.reload();
}

async function checkPanels() {
  const items = dock.items.filter((i) => i.watch);
  if (watcher.busy || document.hidden || !items.length || !sendKey) return;
  watcher.busy = true;
  try {
    for (const conv of new Set(items.map((i) => i.conv))) {
      const mine = items.filter((i) => i.conv === conv);
      const { stats } = await postJson(convApi(conv, "/stat"), { paths: [...new Set(mine.map((i) => i.watch.path))] });
      for (const item of mine) {
        const w = item.watch;
        if (!w || !(w.path in stats)) continue;
        const now = stats[w.path], seen = now ? now.stamp : null;
        if (seen !== w.seen) {
          w.seen = seen;
          w.gone = seen === null;
          w.due = seen !== w.stamp;
          if (!w.due) markChanged(item, false);
        }
      }
    }
  } catch (_) { /* tried again on the next tick */ } finally {
    watcher.busy = false;
  }
  for (const item of items) if (dock.items.includes(item)) settle(item);
}

// ---------- file viewer ----------
const LINE_PX = 20;
const HIGHLIGHT_MAX = 400_000;
const MARKDOWN_RE = /\.(md|markdown|mdown|mkd|mdx)$/i;

function openFile(conv, match, at = {}) {
  const item = openPanel(`file:${match.path}`, `${baseName(match.display)}`, "file", conv, (it) => {
    it.tip = match.display;
    it.path = match.path;
    it.body.append(skeleton(8));
    it.ready = loadFile(it);
    it.onShow = () => {
      if (it.view && it === dock.active) it.view.focus();
      settle(it);
    };
    it.body.addEventListener("keydown", (e) => {
      if (isGotoKey(e) && it.view) {
        e.preventDefault();
        it.view.askLine();
      }
    });
  });
  item.ready.then(() => {
    if (!item.view) return;
    item.view.go(at.line, at.end);
    // As in an editor, keys go to the file just opened: Ctrl+G, the arrows, Page Down.
    if (item === dock.active) item.view.focus();
  });
}

const isGotoKey = (e) => e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey && e.key.toLowerCase() === "g";

// keep: what the reader had in view, so a file that changed on disk comes back where it was.
function loadFile(item, keep = null) {
  return api(`${convApi(item.conv, "/file")}?path=${encodeURIComponent(item.path)}`, { headers: sendHeaders() })
    .then((data) => {
      watch(item, data.path, data.stamp, () => loadFile(item, item.view ? item.view.state() : null));
      item.view = fileView(item.conv, item, data, keep);
    }, (err) => panelError(item, err));
}

// "42", "42:7" or "40-50", as the links take them.
function parseLines(text) {
  const m = String(text).trim().match(/^(\d+)(?:(?::\d+)|-(\d+))?$/);
  return m ? { line: Number(m[1]), end: m[2] ? Number(m[2]) : null } : null;
}

function fileView(conv, item, data, keep) {
  const lines = data.text.split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  const lang = highlighting() ? languageOfPath(hljs, data.path) : null;
  const code = h("code", { class: coloured(lang) ? `language-${lang}` : "" }, data.text);
  if (coloured(lang) && data.text.length <= HIGHLIGHT_MAX) hljs.highlightElement(code);
  const gutter = h("pre", { class: "fv-gutter", "aria-hidden": "true" }, lines.map((_, i) => `${i + 1}\n`).join(""));
  const mark = h("div", { class: "fv-mark", hidden: true });
  const text = h("pre", { class: "fv-text" }, code);
  const box = h("div", { class: "fv-code" }, gutter, text, mark);
  const scroller = h("div", { class: "fv-scroll", tabindex: "0" }, box);
  const note = h("span", { class: "muted fv-note", "aria-live": "polite" });
  const tell = (message) => {
    note.textContent = message;
    clearTimeout(note.timer);
    note.timer = setTimeout(() => { note.textContent = ""; }, 5000);
  };
  const goto = h("input", { class: "fv-goto", type: "text", inputmode: "numeric", placeholder: "Line", "aria-label": "Go to line",
    title: "Go to line (Ctrl+G): 42, or 40-50 to mark a range",
    onkeydown: (e) => {
      if (e.key === "Enter") {
        const at = parseLines(goto.value);
        if (at) go(at.line, at.end);
        scroller.focus({ preventScroll: true });
      } else if (e.key === "Escape") {
        e.stopPropagation();
        scroller.focus({ preventScroll: true });
      }
    } });
  let marked = null;
  gutter.addEventListener("click", (e) => go(Math.floor((e.offsetY - 8) / LINE_PX) + 1));
  const show = (line, end) => {
    marked = [line, end];
    mark.hidden = false;
    mark.style.top = `${8 + (line - 1) * LINE_PX}px`;
    mark.style.height = `${(end - line + 1) * LINE_PX}px`;
  };
  const markdown = !data.binary && MARKDOWN_RE.test(data.path);
  let mode = markdown ? (keep && keep.mode) || "preview" : "source", preview = null;
  const previewScroll = h("div", { class: "fv-scroll fv-preview", tabindex: "0" });
  const modes = markdown ? h("div", { class: "seg fv-modes", role: "group", "aria-label": "Show" },
    [["preview", "Preview"], ["source", "Source"]].map(([m, label]) => h("button", { type: "button", "data-mode": m,
      onclick: () => { setMode(m); current().focus({ preventScroll: true }); } }, label))) : null;
  const current = () => (mode === "preview" ? previewScroll : scroller);
  function setMode(m) {
    mode = m;
    if (mode === "preview" && !preview) {
      preview = markdownPreview(conv, data, previewScroll);
      previewScroll.append(preview);
    }
    previewScroll.hidden = mode !== "preview";
    scroller.hidden = mode === "preview";
    if (modes) for (const b of modes.children) b.setAttribute("aria-pressed", String(b.dataset.mode === mode));
  }
  function go(line, end) {
    if (!line || line < 1) return;
    if (mode === "preview") setMode("source");
    line = Math.min(line, lines.length || 1);
    end = Math.max(line, Math.min(end || line, lines.length || 1));
    show(line, end);
    scroller.scrollTop = Math.max(0, 8 + (line - 1) * LINE_PX - scroller.clientHeight / 3);
    goto.value = end > line ? `${line}-${end}` : line;
  }
  text.addEventListener("dblclick", (e) => {
    const line = Math.min(lines.length || 1, Math.max(1, Math.floor((e.clientY - box.getBoundingClientRect().top - 8) / LINE_PX) + 1));
    getSelection().removeAllRanges();
    const ref = `${data.path}:${line}`;
    pendingRef = ref;
    show(line, line);
    copyWith(() => writeText(ref), note, (ok) => {
      if (ok != null) tell(ok ? `Copied ${baseName(ref)} · double-click the message box to paste it there` : "Copy failed");
    });
  });
  // After the browser has settled the selection; the mouseup of a double-click belongs to the double-click.
  box.addEventListener("mouseup", (e) => {
    if (e.button === 0 && e.detail < 2) setTimeout(() => selectionMenu(e.clientX, e.clientY, conv, code, data, lang, tell), 0);
  });
  const notes = [data.binary ? "Binary file: not shown." : null,
    data.truncated ? `Only the first ${fmtBytes(data.text.length)} of ${fmtBytes(data.size)} are shown.` : null].filter(Boolean);
  const hadFocus = item.body.contains(document.activeElement);
  item.body.replaceChildren();
  append(item.body, [h("div", { class: "panel-bar" },
    copyable(h("span", { class: "mono path" }, breakable(data.display)), data.path),
    h("span", { class: "muted" }, `${fmt(lines.length)} lines · ${fmtBytes(data.size)}${lang && lang !== "plaintext" ? ` · ${languageName(lang)}` : ""}`),
    h("span", { class: "spacer" }), modes, goto,
    h("button", { class: "btn", type: "button", title: `Browse ${dirOf(data.path)}`, onclick: () => openDir(conv, dirOf(data.path), data.path) }, "▦ Folder"),
    h("button", { class: "btn", type: "button", title: `Open a shell in ${dirOf(data.path)}`, onclick: () => openShell(conv, dirOf(data.path)) }, "❯ Shell here")),
  notes.length ? h("div", { class: "notice" }, notes.join(" ")) : null, data.binary ? null : [scroller, markdown ? previewScroll : null], note]);
  setMode(mode);
  if (keep) {
    if (keep.marked) show(...keep.marked);
    goto.value = keep.goto;
    scroller.scrollTop = keep.top;
    scroller.scrollLeft = keep.left;
    previewScroll.scrollTop = keep.previewTop;
    tell("Reloaded: the file changed on disk");
  }
  if (hadFocus) current().focus({ preventScroll: true });
  return {
    go,
    focus: () => { if (!item.body.contains(document.activeElement)) current().focus({ preventScroll: true }); },
    // Ctrl+G: the line box, with the source in view.
    askLine: () => {
      if (mode === "preview") setMode("source");
      goto.focus();
      goto.select();
    },
    state: () => ({ mode, marked, goto: goto.value, top: scroller.scrollTop, left: scroller.scrollLeft, previewTop: previewScroll.scrollTop }),
  };
}

// GitHub's anchors: lower case, punctuation dropped, spaces as dashes, a count after repeats.
function headingAnchors(box) {
  const used = new Map();
  for (const heading of box.querySelectorAll("h1, h2, h3, h4, h5, h6")) {
    const slug = heading.textContent.trim().toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu, "").replace(/\s/g, "-");
    const n = used.get(slug) || 0;
    used.set(slug, n + 1);
    heading.dataset.anchor = n ? `${slug}-${n}` : slug;
  }
}

// A Markdown file read as it is meant to be: its links to other files and folders open them here, from its own folder.
function markdownPreview(conv, data, scroller) {
  const box = renderMarkdown(data.text, "md fv-md");
  headingAnchors(box);
  box.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a || /^[a-z][\w+.-]*:/i.test(a.getAttribute("href"))) return;
    e.preventDefault();
    const [where, hash = ""] = a.getAttribute("href").split("#");
    if (!where) {
      const target = box.querySelector(`[data-anchor="${CSS.escape(decodeURIComponent(hash).toLowerCase())}"]`);
      if (target) scroller.scrollTop += target.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 8;
      return;
    }
    let path = decodeURIComponent(where.split("?")[0]);
    // As on GitHub, a leading slash starts from the repository.
    path = path.startsWith("/") && data.root ? `${data.root}${path}` : path.startsWith("/") ? path : `${dirOf(data.path)}/${path}`;
    const lines = hash.match(/^L(\d+)(?:-L(\d+))?$/);
    openPath(conv, normalPath(path), lines ? { line: Number(lines[1]), end: lines[2] ? Number(lines[2]) : null } : {});
  });
  requestAnimationFrame(() => linkify([box], { conv, cwd: dirOf(data.path) }));
  return box;
}

function normalPath(path) {
  const parts = [];
  for (const part of path.split("/")) {
    if (part === "..") parts.pop();
    else if (part && part !== ".") parts.push(part);
  }
  return `/${parts.join("/")}`;
}

// A link that may name a folder or a file.
async function openPath(conv, path, at = {}) {
  let stat = null;
  try {
    stat = (await postJson(convApi(conv, "/stat"), { paths: [path] })).stats[path];
  } catch (_) { /* the panel says what went wrong */ }
  if (stat && stat.type === "dir") openDir(conv, path);
  else openFile(conv, { path, display: path }, at);
}

// ---------- folder browser ----------
const HIDDEN_KEY = "ctokens.dir.hidden";

// One panel per folder; going into another folder or up moves the panel there. from: the entry to select first.
function openDir(conv, path, from = null) {
  const problem = keyProblem();
  if (problem) return alert(problem);
  const open = dock.items.find((i) => i.kind === "dir" && i.path === path);
  if (open) {
    focusPanel(open);
    if (from) open.view.select(from);
    return;
  }
  const item = openPanel(`dir:${++dirCount}`, `${baseName(path) || path}/`, "dir", conv, (it) => {
    it.tip = path;
    it.path = path;
    it.body.append(skeleton(8));
    it.view = dirView(it);
    it.onShow = () => {
      if (it === dock.active) it.view.focus();
      settle(it);
    };
  });
  item.view.go(path, from);
}

let dirCount = 0;

function dirView(item) {
  const conv = item.conv;
  const state = { data: null, filter: "", hidden: stored(HIDDEN_KEY, "") === "1", selected: null };
  const list = h("div", { class: "dir-list", role: "listbox", "aria-label": "Folder entries", tabindex: "-1" });
  const note = h("span", { class: "muted fv-note", "aria-live": "polite" });
  const filter = h("input", { class: "fv-goto dir-filter", type: "search", placeholder: "Filter", "aria-label": "Filter the entries",
    spellcheck: "false", autocomplete: "off",
    oninput: () => { state.filter = filter.value; draw(); },
    onkeydown: (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        move(0);
      } else if (e.key === "Enter") {
        const first = list.querySelector(".dir-row");
        if (first) first.click();
      } else if (e.key === "Escape" && filter.value) {
        e.stopPropagation();
        filter.value = state.filter = "";
        draw();
      }
    } });
  const hidden = h("label", { class: "dir-hidden", title: "Show the entries whose name starts with a dot" },
    h("input", { type: "checkbox", checked: state.hidden, onchange: (e) => {
      state.hidden = e.target.checked;
      store(HIDDEN_KEY, state.hidden ? "1" : "");
      draw();
    } }), "Hidden");
  const crumbs = h("nav", { class: "dir-crumbs mono", "aria-label": "Folder path" });
  const up = h("button", { class: "btn small", type: "button", title: "Parent folder (Backspace)", "aria-label": "Parent folder",
    onclick: () => goUp() }, "↑");
  const shellHere = h("button", { class: "btn", type: "button", onclick: () => openShell(conv, item.path) }, "❯ Shell here");
  const searchHere = h("button", { class: "btn", type: "button", title: "Search the files of this folder",
    onclick: () => openSearch(conv, item.path) }, icon("search"), " Search");
  const scroll = h("div", { class: "dir-scroll" }, list);
  item.body.replaceChildren(h("div", { class: "panel-bar" }, up, crumbs, h("span", { class: "spacer" }), filter, hidden, searchHere,
    shellHere),
    scroll, note);
  item.body.addEventListener("keydown", (e) => {
    if (e.target === filter) return;
    if (e.key === "Backspace" || (e.altKey && e.key === "ArrowUp")) {
      e.preventDefault();
      goUp();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const rows = [...list.querySelectorAll(".dir-row")];
      move(rows.indexOf(document.activeElement) + (e.key === "ArrowDown" ? 1 : -1));
    } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && e.key !== " ") {
      filter.focus();
    }
  });

  function move(i) {
    const rows = [...list.querySelectorAll(".dir-row")];
    const row = rows[Math.max(0, Math.min(rows.length - 1, i))];
    if (row) row.focus();
  }

  function goUp() {
    if (state.data && state.data.parent) go(state.data.parent, state.data.path);
  }

  function crumbsOf(data) {
    const parts = data.path.split("/").filter(Boolean);
    const shown = data.root && data.path.startsWith(data.root) ? data.root.split("/").filter(Boolean).length - 1 : 0;
    const links = [];
    if (shown > 0) links.push(h("span", { class: "muted" }, "…/"));
    else links.push(h("button", { class: "crumb", type: "button", onclick: () => go("/") }, "/"));
    parts.forEach((part, i) => {
      if (i < shown) return;
      const to = `/${parts.slice(0, i + 1).join("/")}`;
      links.push(i === parts.length - 1 ? h("b", {}, part) : h("button", { class: "crumb", type: "button", onclick: () => go(to) }, part),
        i === parts.length - 1 ? null : h("span", { class: "muted" }, "/"));
    });
    return links;
  }

  function row(entry) {
    const full = `${state.data.path === "/" ? "" : state.data.path}/${entry.name}`;
    const open = (e) => {
      if (entry.type === "dir") return e && (e.ctrlKey || e.metaKey || e.button === 1) ? openDir(conv, full) : go(full);
      openFile(conv, { path: full, display: state.data.root && full.startsWith(`${state.data.root}/`) ? full.slice(state.data.root.length + 1) : full });
    };
    const el = h("button", { class: `dir-row ${entry.type}${entry.ignored ? " ignored" : ""}`, type: "button", role: "option",
      "data-name": entry.name, title: `${full}${entry.link ? " (link)" : ""}${entry.ignored ? " · ignored by git" : ""}`,
      onclick: open, onfocus: () => { state.selected = entry.name; } },
    h("span", { class: "dir-icon", "aria-hidden": "true" }, entry.type === "dir" ? "▸" : entry.type === "file" ? "·" : "?"),
    h("span", { class: "dir-name mono" }, entry.name, entry.type === "dir" ? "/" : "", entry.link ? h("span", { class: "muted" }, " →") : null),
    h("span", { class: "dir-size muted" }, entry.size == null ? "" : fmtBytes(entry.size)),
    h("span", { class: "dir-time muted" }, entry.mtime ? new Date(entry.mtime * 1000).toISOString().replace("T", " ").slice(0, 16) : ""));
    el.addEventListener("mousedown", (e) => { if (e.button === 1) e.preventDefault(); });
    el.addEventListener("auxclick", (e) => { if (e.button === 1 && entry.type === "dir") { e.preventDefault(); open(e); } });
    return el;
  }

  function draw() {
    const data = state.data;
    if (!data) return;
    const needle = state.filter.trim().toLowerCase();
    const entries = data.entries.filter((e) => (state.hidden || !e.name.startsWith(".") || needle.startsWith("."))
      && (!needle || e.name.toLowerCase().includes(needle)));
    const left = data.entries.length - entries.length;
    list.replaceChildren();
    append(list, [entries.map(row),
      entries.length ? null : h("div", { class: "muted pad" }, data.entries.length ? "Nothing matches." : "Empty folder."),
      left && !needle ? h("div", { class: "muted pad small" }, `${left} hidden entr${left === 1 ? "y" : "ies"}`) : null,
      data.truncated ? h("div", { class: "notice" }, `Only the first ${fmt(data.entries.length)} entries are shown.`) : null]);
    const chosen = state.selected && [...list.children].find((r) => r.dataset.name === state.selected);
    if (chosen) chosen.classList.add("selected");
  }

  async function go(path, from = null, keep = false) {
    let data;
    try {
      data = await api(`${convApi(conv, "/dir")}?path=${encodeURIComponent(path)}`, { headers: sendHeaders() });
    } catch (err) {
      if (!state.data) return panelError(item, err);
      note.textContent = err.message;
      return;
    }
    const top = scroll.scrollTop, focused = item.body.contains(document.activeElement);
    const same = state.data && state.data.path === data.path;
    state.data = data;
    item.path = data.path;
    item.tip = data.path;
    item.title = `${baseName(data.path) || "/"}/`;
    if (item.tabEl) {
      item.tabEl.title = item.tip;
      const label = item.tabEl.querySelector(".dock-title");
      if (label) label.textContent = dock.mode === "float" ? item.tip : item.title;
    }
    watch(item, data.path, data.stamp, () => go(data.path, null, true));
    if (!same) {
      state.selected = from ? baseName(from) : null;
      if (!keep) filter.value = state.filter = "";
    }
    crumbs.replaceChildren();
    append(crumbs, crumbsOf(data));
    up.disabled = !data.parent;
    shellHere.title = `Open a shell in ${data.path}`;
    draw();
    if (keep && same) scroll.scrollTop = top;
    else {
      const chosen = list.querySelector(".dir-row.selected");
      scroll.scrollTop = 0;
      if (chosen) chosen.scrollIntoView({ block: "center" });
    }
    if (keep) note.textContent = "";
    if (focused || !keep) focusList();
  }

  function focusList() {
    if (item !== dock.active && dock.mode !== "float") return;
    const target = list.querySelector(".dir-row.selected") || list.querySelector(".dir-row") || list;
    target.focus({ preventScroll: true });
  }

  return {
    go,
    select: (path) => {
      state.selected = baseName(path);
      draw();
      focusList();
    },
    focus: () => { if (!item.body.contains(document.activeElement)) focusList(); },
  };
}

// The lines a selection in a file spans, and what can be done with them: copied, with the path and lines as a header,
// or put into the message to the session.
function selectionMenu(x, y, conv, code, data, lang, tell) {
  const selection = getSelection();
  if (selection.isCollapsed || !selection.rangeCount) return;
  const range = selection.getRangeAt(0), chosen = selection.toString();
  if (!code.contains(range.startContainer) || !code.contains(range.endContainer) || !chosen.trim()) return;
  const before = document.createRange();
  before.setStart(code, 0);
  before.setEnd(range.startContainer, range.startOffset);
  const start = before.toString().split("\n").length, body = chosen.replace(/\n$/, "");
  const end = start + body.split("\n").length - 1;
  const ref = `${data.path}:${start}${end > start ? `-${end}` : ""}`;
  const copy = (value) => copyWith(() => writeText(value), tell, (ok) => { if (ok != null) tell(ok ? "Copied" : "Copy failed"); });
  const fence = "`".repeat(Math.max(3, ...[...body.matchAll(/`+/g)].map((m) => m[0].length + 1)));
  const ask = () => {
    if (!insertIntoComposer(`${ref}\n${fence}${coloured(lang) ? lang : ""}\n${body}\n${fence}`, true)) {
      tell("No message box: open the Conversation tab of a live session");
    }
  };
  pointMenu(x, y, "Selection", [
    ["Copy", () => copy(chosen)],
    [`Copy with ${baseName(ref)}`, () => copy(`${ref}\n${chosen}`)],
    ["Ask Claude", ask, composerReady() ? "Put it into the message box, where its cursor is, without sending it"
      : "Needs the Conversation tab of a live session open"],
    ...findEntry(conv, chosen, data.root || dirOf(data.path)),
    ...pasteEntries(chosen),
  ]);
}

// A selection in a conversation: copied, quoted into the message box, looked for in the files or typed into a shell.
const SELECTION_SKIP = "input, textarea, select, button, .composer, .xterm, #conv-head, .copy-menu";

function conversationSelection(e) {
  const main = $("main");
  if (e.button !== 0 || !app.route || !app.route.id || !main.contains(e.target) || e.target.closest(SELECTION_SKIP)) return;
  setTimeout(() => {
    const selection = getSelection();
    if (selection.isCollapsed || !selection.rangeCount) return;
    const range = selection.getRangeAt(0), chosen = selection.toString();
    const common = range.commonAncestorContainer;
    const el = common.nodeType === 1 ? common : common.parentElement;
    if (!chosen.trim() || !main.contains(el) || el.closest(SELECTION_SKIP)) return;
    const conv = app.route.id;
    const quote = () => {
      if (!insertIntoComposer(chosen.replace(/\n+$/, "").split("\n").map((line) => `> ${line}`.trimEnd()).join("\n"), true)) {
        flash("No message box: open the Conversation tab of a live session");
      }
    };
    pointMenu(e.clientX, e.clientY, "Selection", [
      ["Copy", () => copyWith(() => writeText(chosen), flasher, (ok) => { if (ok != null) flash(ok ? "Copied" : "Copy failed"); })],
      ["Ask Claude", quote, composerReady() ? "Quote it in the message box, where its cursor is, without sending it"
        : "Needs the Conversation tab of a live session open"],
      ...findEntry(conv, chosen, null),
      ...pasteEntries(chosen),
    ]);
  }, 0);
}

// Its first line, searched for in the files of a folder: the conversation's when there is none.
function findEntry(conv, text, cwd) {
  const query = text.split("\n").map((line) => line.trim()).find(Boolean) || "";
  if (!query || query.length > 1000) return [];
  return [[h("span", {}, icon("search"), " Find in files"), () => openSearch(conv, cwd, query),
    `Look for “${query.length > 60 ? `${query.slice(0, 60)}…` : query}” in the files of ${cwd || "the conversation's folder"}`]];
}

// A short message in a corner of the page, for what has no panel to say it in.
const flasher = { el: null, timer: null };

function flash(message) {
  if (!flasher.el) flasher.el = h("div", { class: "fv-note flash", "aria-live": "polite" });
  if (!flasher.el.isConnected) document.body.append(flasher.el);
  flasher.el.textContent = message;
  clearTimeout(flasher.timer);
  flasher.timer = setTimeout(() => { flasher.el.textContent = ""; }, 4000);
}

// A menu at a point of the page, closed like the copy menus: outside, Escape, scrolling.
function pointMenu(x, y, title, entries) {
  closeCopyMenu(false);
  const buttons = entries.map(([label, act, tip, off]) => h("button", { type: "button", role: "menuitem", class: "copy-menu-item",
    title: tip || null, disabled: !!off, onclick: () => { closeCopyMenu(false); act(); } }, label));
  const items = buttons.filter((b) => !b.disabled);
  const menu = h("div", { class: "copy-menu", role: "menu", "aria-label": title }, h("div", { class: "copy-menu-head" }, title), buttons);
  document.body.append(menu);
  menu.style.left = `${Math.max(8, Math.min(x, innerWidth - menu.offsetWidth - 8))}px`;
  menu.style.top = `${y + 12 + menu.offsetHeight > innerHeight ? Math.max(8, y - 12 - menu.offsetHeight) : y + 12}px`;
  const outside = (e) => { if (!menu.contains(e.target)) closeCopyMenu(false); };
  const away = () => closeCopyMenu(false);
  const keys = (e) => {
    const i = items.indexOf(document.activeElement);
    if (e.key === "Escape" || e.key === "Tab") {
      e.stopPropagation();
      closeCopyMenu(false);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    }
  };
  document.addEventListener("pointerdown", outside, true);
  document.addEventListener("keydown", keys, true);
  window.addEventListener("resize", away);
  copyMenu = { menu, button: { focus() {} }, cleanup: () => {
    document.removeEventListener("pointerdown", outside, true);
    document.removeEventListener("keydown", keys, true);
    window.removeEventListener("resize", away);
  } };
}

// ---------- commit viewer ----------
const DIFF_OPEN_LINES = 4000;
const DIFF_HIGHLIGHT_LINES = 1500;

// cwd: the repository's folder when it is not the conversation's, as for a commit a shell printed after a cd.
function openCommit(conv, sha, label, cwd) {
  openPanel(`commit:${sha}`, `${(label || sha).slice(0, 10)}`, "commit", conv, (item) => {
    item.body.append(skeleton(10));
    api(`${convApi(conv, "/commit")}?sha=${encodeURIComponent(sha)}${cwd ? `&cwd=${encodeURIComponent(cwd)}` : ""}`, { headers: sendHeaders() })
      .then((data) => {
        item.title = `${data.sha.slice(0, 7)} ${data.message.split("\n")[0]}`;
        item.tip = `${data.sha}\n${data.message.split("\n")[0]}`;
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
  const parents = data.parents.map((p) => h("span", { class: "ref ref-commit", role: "link", tabindex: "0", "data-sha": p, "data-cwd": data.root,
    title: `Parent ${p}` }, p.slice(0, 10)));
  item.body.replaceChildren(h("div", { class: "commit-head" },
    h("div", { class: "commit-subject" }, subject),
    body ? h("pre", { class: "commit-body" }, body) : null,
    h("div", { class: "meta" },
      copyable(h("span", { class: "mono" }, data.sha), data.sha),
      h("span", {}, `${data.author} · ${data.author_date.replace("T", " ").slice(0, 16)}`),
      parents.length ? h("span", {}, parents.length > 1 ? "Parents " : "Parent ", parents) : h("span", { class: "muted" }, "Root commit"),
      data.refs ? h("span", { class: "chip" }, data.refs) : null,
      h("button", { class: "btn small", type: "button", title: "The history of the repository, with this commit in it",
        onclick: () => openCommits(conv, data.root, data.sha) }, "☰ Commits")),
    h("div", { class: "meta" }, `${fmt(data.files.length)} file${data.files.length === 1 ? "" : "s"} changed`,
      h("span", { class: "plus" }, `+${fmt(data.files.reduce((n, f) => n + (f.added || 0), 0))}`),
      h("span", { class: "minus" }, `−${fmt(data.files.reduce((n, f) => n + (f.deleted || 0), 0))}`),
      h("button", { class: "btn small", type: "button", onclick: () => { for (const b of fileBoxes.values()) b.open = true; } }, "Expand all"),
      h("button", { class: "btn small", type: "button", onclick: () => { for (const b of fileBoxes.values()) b.open = false; } }, "Collapse all")),
    data.truncated ? h("div", { class: "notice" }, "The patch is too long; only its beginning is shown.") : null),
  h("div", { class: "commit-files" }, files));
}

// ---------- commit history ----------
// As editors put it: "3 hours ago", with the date itself in the title.
function ago(when) {
  const seconds = Math.max(0, (Date.now() - when) / 1000);
  for (const [unit, size] of [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (seconds >= size) {
      const n = Math.floor(seconds / size);
      return `${n} ${unit}${n === 1 ? "" : "s"} ago`;
    }
  }
  return "just now";
}

// One panel per folder, for the repository it is in; cwd null is the conversation's folder.
// sha: the commit to point at in the list, when it comes from that commit's view.
function openCommits(conv, cwd = null, sha = null) {
  const problem = keyProblem();
  if (problem) return alert(problem);
  const panel = openPanel(`commits:${cwd || conv}`, "Commits", "commits", conv, (item) => {
    item.body.append(skeleton(10));
    item.view = commitsView(item, cwd);
    // Pushes and commits made meanwhile show up when the panel comes back into view.
    item.onShow = () => { if (Date.now() - item.view.loaded > 5000) item.view.load(); };
  });
  if (sha) panel.view.point(sha);
}

function refChips(refs) {
  return refs ? refs.split(", ").map((ref) => {
    const head = ref.startsWith("HEAD -> ");
    const name = head ? ref.slice(8) : ref.replace(/^tag: /, "");
    return h("span", { class: `chip${head ? " main" : ref.startsWith("tag: ") ? " tag" : ""}`, title: head ? "The branch checked out" : ref }, name);
  }) : [];
}

function commitsView(item, cwd) {
  const conv = item.conv;
  const state = { data: null, commits: [], loading: false, point: null, scroll: false };
  const status = h("div", { class: "log-status" });
  const list = h("div", { class: "log-list", role: "list" });
  const more = h("button", { class: "btn small", type: "button", hidden: true, onclick: () => load(state.commits.length) }, "Load more");
  const refresh = h("button", { class: "btn small", type: "button", title: "Read the history again", onclick: () => load() }, "Refresh");
  const shellHere = h("button", { class: "btn small", type: "button", title: "A shell in the repository, to push or pull",
    onclick: () => openShell(conv, (state.data && state.data.root) || cwd) }, "❯ Shell");
  const view = { loaded: 0, load, point: (sha) => {
    Object.assign(state, { point: sha, scroll: true });
    if (state.data) pointAt();
  } };

  function pointAt() {
    for (const old of list.querySelectorAll(".log-row.here")) old.classList.remove("here");
    const el = state.point && list.querySelector(`.log-row[data-sha="${state.point}"]`);
    if (!el) return;
    el.classList.add("here");
    if (state.scroll) el.scrollIntoView({ block: "center" });
    state.scroll = false;
  }

  function row(c, mark) {
    const when = Date.parse(c.date);
    const marks = { out: ["↑", "Not pushed: no remote branch has it yet"], in: ["↓", "On the upstream branch, not here yet: pull it"],
      pushed: ["·", "Pushed"], none: ["", ""] };
    const [sign, tip] = marks[mark];
    return h("button", { class: `log-row ${mark}`, type: "button", role: "listitem", "data-sha": c.sha,
      title: `${c.sha}\n${c.subject}\n${c.author} · ${new Date(when).toISOString().replace("T", " ").slice(0, 16)} UTC${tip ? `\n${tip}` : ""}`,
      onclick: () => openCommit(conv, c.sha, null, state.data.root) },
    h("span", { class: "log-mark", "aria-label": tip || null }, sign),
    h("span", { class: "log-subject" }, c.parents.length > 1 ? h("span", { class: "muted" }, "⑂ ") : null, c.subject, refChips(c.refs)),
    h("span", { class: "log-meta muted" }, `${c.author} · ${ago(when)}`),
    h("span", { class: "log-sha mono muted" }, c.sha.slice(0, 7)));
  }

  function summary(data) {
    if (!data.remotes) return "No remote: nothing here is pushed anywhere.";
    if (!data.upstream) {
      const out = state.commits.filter((c) => c.pushed === false).length;
      return `${data.branch ? "No upstream branch" : "Detached HEAD"}${out ? ` · ${out}${data.more && out === state.commits.length ? "+" : ""} not on any remote` : ""}`;
    }
    if (!data.ahead && !data.behind) return `Up to date with ${data.upstream}`;
    return [data.ahead ? `↑ ${data.ahead} to push` : null, data.behind ? `↓ ${data.behind} to pull` : null].filter(Boolean).join(" · ")
      + ` · ${data.upstream}`;
  }

  function draw() {
    const data = state.data;
    item.title = `${data.branch || "HEAD"} · commits`;
    item.tip = `Commits of ${data.root}`;
    drawDock();
    status.replaceChildren(h("b", { class: "mono" }, `⎇ ${data.branch || "detached HEAD"}`), h("span", {}, summary(data)),
      data.fetched ? h("span", { class: "muted", title: new Date(data.fetched * 1000).toISOString() }, `fetched ${ago(data.fetched * 1000)}`) : null);
    const mark = (c) => (c.pushed === false ? "out" : c.pushed ? "pushed" : "none");
    list.replaceChildren(...(data.incoming.length ? [h("div", { class: "log-group" }, `Incoming from ${data.upstream}`),
      ...data.incoming.map((c) => row(c, "in")), h("div", { class: "log-group" }, "Commits")] : []),
    ...state.commits.map((c) => row(c, mark(c))),
    ...(state.commits.length ? [] : [h("div", { class: "muted pad" }, "No commits yet.")]));
    more.hidden = !data.more;
    pointAt();
  }

  async function load(skip = 0) {
    if (state.loading) return;
    state.loading = true;
    const params = new URLSearchParams();
    if (skip) params.set("skip", skip);
    if (cwd) params.set("cwd", cwd);
    try {
      const data = await api(`${convApi(conv, "/commits")}?${params}`, { headers: sendHeaders() });
      state.commits = skip ? state.commits.concat(data.commits) : data.commits;
      state.data = data;
      view.loaded = Date.now();
      if (!item.body.contains(list)) {
        item.body.replaceChildren(h("div", { class: "panel-bar" }, status, h("span", { class: "spacer" }), refresh, shellHere),
          h("div", { class: "dir-scroll" }, list, h("div", { class: "pad" }, more)));
      }
      draw();
    } catch (err) {
      if (!state.data) panelError(item, err);
      else flash(err.message);
    } finally {
      state.loading = false;
    }
  }
  load();
  return view;
}

// ---------- search in files ----------
const SEARCH_KEY = "ctokens.search";
const SEARCH_OPEN_FILES = 100;
// Long enough for a word typed at an ordinary pace to go as one search.
const SEARCH_DELAY_MS = 300;

// One panel per folder; a query from a selection runs in the panel already open.
function openSearch(conv, cwd = null, query = null) {
  const problem = keyProblem();
  if (problem) return alert(problem);
  const item = openPanel(`search:${cwd || conv}`, "Search", "search", conv, (it) => {
    it.view = searchView(it, cwd);
    it.onShow = () => it.view.focus();
  });
  if (query) item.view.run(query);
}

// The pattern as the browser reads it, to mark the matches; git's extended regular expressions mostly agree.
function searchPattern(query, opts) {
  let source = opts.regex ? query : query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  if (opts.word) source = `(?<![\\w])(?:${source})(?![\\w])`;
  try {
    return new RegExp(source, opts.case ? "g" : "gi");
  } catch (_) {
    return null;
  }
}

// The line from a little before its first match, with every match marked.
function searchLine(text, pattern) {
  const ranges = [];
  if (pattern) {
    pattern.lastIndex = 0;
    for (let m = pattern.exec(text); m && ranges.length < 50; m = pattern.exec(text)) {
      if (!m[0]) {
        pattern.lastIndex++;
        continue;
      }
      ranges.push([m.index, m.index + m[0].length]);
    }
  }
  const lead = text.length - text.trimStart().length;
  const from = ranges.length && ranges[0][0] - lead > 60 ? ranges[0][0] - 30 : lead;
  const parts = from > lead ? ["…"] : [];
  let at = from;
  for (const [a, b] of ranges) {
    if (b <= at) continue;
    parts.push(text.slice(at, Math.max(at, a)), h("mark", {}, text.slice(Math.max(at, a), b)));
    at = b;
  }
  parts.push(text.slice(at));
  return parts;
}

function searchView(item, cwd) {
  const conv = item.conv;
  let saved = {};
  try {
    saved = JSON.parse(stored(SEARCH_KEY, "{}")) || {};
  } catch (_) { /* defaults */ }
  const opts = { case: !!saved.case, word: !!saved.word, regex: !!saved.regex };
  const keep = () => store(SEARCH_KEY, JSON.stringify({ ...opts, include: include.value, exclude: exclude.value }));
  let timer = null;
  const later = () => {
    clearTimeout(timer);
    timer = setTimeout(() => run(), SEARCH_DELAY_MS);
  };
  const onEnter = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      run();
    }
  };
  const input = h("input", { class: "search-q", type: "search", placeholder: "Search", "aria-label": "Search in files", spellcheck: "false",
    autocomplete: "off", onkeydown: onEnter, oninput: later });
  const toggle = (name, label, tip) => {
    const b = h("button", { class: "search-opt", type: "button", title: tip, "aria-label": tip, "aria-pressed": String(opts[name]),
      onclick: () => {
        opts[name] = !opts[name];
        b.setAttribute("aria-pressed", String(opts[name]));
        keep();
        if (input.value) run();
      } }, label);
    return b;
  };
  const glob = (placeholder, label, value) => h("input", { class: "search-glob", type: "text", placeholder, "aria-label": label, value: value || "",
    spellcheck: "false", autocomplete: "off", onkeydown: onEnter, oninput: () => {
      keep();
      if (input.value) later();
    } });
  const include = glob("e.g. *.py, src/", "Files to include", saved.include);
  const exclude = glob("e.g. tests/, *.min.js", "Files to exclude", saved.exclude);
  const filters = h("details", { class: "search-filters", open: !!(saved.include || saved.exclude) },
    h("summary", { title: "Comma-separated globs: *.py anywhere, ./build/ from the folder searched" }, "Files to include and exclude"),
    h("label", {}, "Include", include), h("label", {}, "Exclude", exclude));
  const where = h("div", { class: "muted search-where mono" }, cwd || "");
  const summary = h("div", { class: "search-summary", "aria-live": "polite" });
  const results = h("div", { class: "search-results" });
  const collapse = h("button", { class: "btn small", type: "button", hidden: true,
    onclick: () => { for (const d of results.querySelectorAll("details")) d.open = false; } }, "Collapse all");
  item.body.replaceChildren(h("div", { class: "search-form" },
    h("div", { class: "search-row" }, input, toggle("case", "Aa", "Match case"), toggle("word", "ab", "Match whole word"),
      toggle("regex", ".*", "Use a regular expression")), filters, where),
  h("div", { class: "search-bar" }, summary, collapse), h("div", { class: "dir-scroll" }, results));
  let seq = 0, asking = null;

  async function run(query = input.value) {
    clearTimeout(timer);
    if (asking) asking.abort();
    asking = null;
    input.value = query;
    const n = ++seq;
    if (!query) {
      results.replaceChildren();
      summary.textContent = "";
      collapse.hidden = true;
      return;
    }
    const asked = { ...opts };
    const params = new URLSearchParams({ q: query, include: include.value, exclude: exclude.value });
    for (const name of ["case", "word", "regex"]) if (asked[name]) params.set(name, "1");
    if (cwd) params.set("cwd", cwd);
    summary.textContent = "Searching…";
    const controller = asking = new AbortController();
    let data;
    try {
      data = await api(`${convApi(conv, "/search")}?${params}`, { headers: sendHeaders(), signal: controller.signal });
    } catch (err) {
      if (n === seq) {
        summary.textContent = err.message;
        results.replaceChildren();
      }
      return;
    }
    if (n !== seq) return;
    item.title = query.length > 24 ? `${query.slice(0, 24)}…` : query;
    item.tip = `${query} in ${data.folder}`;
    drawDock();
    where.textContent = data.folder;
    draw(data, searchPattern(query, asked));
  }

  function draw(data, pattern) {
    const files = data.files.length;
    summary.replaceChildren();
    append(summary, [data.matches ? `${exact(data.matches)} result${data.matches === 1 ? "" : "s"} in ${exact(files)} file${files === 1 ? "" : "s"}`
      : "No results.",
    data.truncated ? h("div", { class: "notice" }, `Only the first ${exact(data.matches)} results: narrow the search to see the rest.`) : null,
    data.timed_out ? h("div", { class: "notice" }, "The search took too long and stopped; what it found is below.") : null]);
    collapse.hidden = !files;
    results.replaceChildren(...data.files.map((f, i) => {
      const slash = f.display.lastIndexOf("/");
      const rows = f.matches.map((m) => h("button", { class: "search-hit", type: "button", title: `${f.display}:${m.line}`,
        onclick: () => openFile(conv, { path: f.path, display: f.display }, { line: m.line }) },
      h("span", { class: "ln" }, m.line), h("span", { class: "search-text mono" }, searchLine(m.text, pattern))));
      return h("details", { class: "search-file", open: i < SEARCH_OPEN_FILES },
        h("summary", { title: f.path }, h("b", {}, f.display.slice(slash + 1)),
          slash > 0 ? h("span", { class: "muted mono" }, f.display.slice(0, slash)) : null, h("span", { class: "chip" }, f.matches.length)),
        rows);
    }));
  }

  return {
    run,
    focus: () => {
      if (item.body.contains(document.activeElement)) return;
      input.focus();
      input.select();
    },
  };
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
  const { fontFamily, fontSize, lineHeight } = term.options;
  const probe = h("span", { class: "xterm-probe", css: { fontFamily, fontSize: `${fontSize}px`, lineHeight: String(lineHeight) } },
    "W".repeat(50));
  el.append(probe);
  const box = { width: probe.offsetWidth / 50 || 8, height: probe.offsetHeight || 17 };
  probe.remove();
  return box;
}

// One Half Light and One Half Dark, the schemes of Windows Terminal.
const TERMINAL_THEMES = {
  light: { background: "#fafafa", foreground: "#383a42", cursor: "#4f525d", cursorAccent: "#fafafa", selectionBackground: "#383a4233",
    black: "#383a42", red: "#e45649", green: "#50a14f", yellow: "#c18301", blue: "#0184bc", magenta: "#a626a4", cyan: "#0997b3",
    white: "#fafafa", brightBlack: "#4f525d", brightRed: "#df6c75", brightGreen: "#98c379", brightYellow: "#e4c07a",
    brightBlue: "#61afef", brightMagenta: "#c577dd", brightCyan: "#56b5c1", brightWhite: "#ffffff" },
  dark: { background: "#282c34", foreground: "#dcdfe4", cursor: "#ffffff", cursorAccent: "#282c34", selectionBackground: "#ffffff40",
    black: "#282c34", red: "#e06c75", green: "#98c379", yellow: "#e5c07b", blue: "#61afef", magenta: "#c678dd", cyan: "#56b6c2",
    white: "#dcdfe4", brightBlack: "#5a6374", brightRed: "#e06c75", brightGreen: "#98c379", brightYellow: "#e5c07b",
    brightBlue: "#61afef", brightMagenta: "#c678dd", brightCyan: "#56b6c2", brightWhite: "#dcdfe4" },
};

// The size is in points, as in Windows Terminal; the generic monospace fonts stand in when the chosen one is missing.
function terminalOptions() {
  const s = themeSettings();
  return { theme: TERMINAL_THEMES[resolvedThemes().term], fontFamily: [s.font, cssVar("--mono") || "monospace"].filter(Boolean).join(", "),
    fontSize: Math.round(s.size * 4 / 3 * 100) / 100, lineHeight: s.lineHeight };
}

const terminals = new Set();

function restyleTerminals() {
  const options = terminalOptions();
  for (const t of terminals) {
    Object.assign(t.term.options, options);
    requestAnimationFrame(t.fit);
  }
}

function openShell(conv, cwd) {
  const problem = keyProblem();
  if (problem) return alert(problem);
  const n = ++shellCount;
  openPanel(`shell:${n}`, `Shell ${n} · ${baseName(cwd) || cwd}`, "shell", conv, (item) => {
    item.tip = `Shell ${n} in ${cwd}`;
    const screen = h("div", { class: "term" });
    const status = h("span", { class: "muted" }, "Starting…");
    const note = h("span", { class: "muted fv-note", "aria-live": "polite" });
    // Where the shell is now, after any cd.
    const browse = async () => {
      let folder = cwd;
      try {
        if (sh.id) folder = (await postJson(`/api/shells/${sh.id}/state`, {})).shell.current_cwd || cwd;
      } catch (_) { /* the folder it started in */ }
      openDir(conv, folder);
    };
    item.body.append(h("div", { class: "panel-bar" }, h("span", { class: "mono path" }, breakable(cwd)), status, h("span", { class: "spacer" }),
      h("button", { class: "btn small", type: "button", title: "Browse the folder the shell is in now", onclick: browse }, "▦ Folder")), screen, note);
    const term = new Terminal({ ...terminalOptions(), cursorBlink: true, scrollback: 5000, allowProposedApi: false });
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
      // After a command the shell may be somewhere else, so the names it prints are looked up again.
      if (sh.id && data.includes("\r")) refCache.delete(`shell:${sh.id}`);
      pump();
    });
    term.registerLinkProvider(shellLinks(term, conv, sh));
    // As in a terminal: a right-click copies the selection and Ctrl+V pastes, instead of sending ^V to the shell.
    screen.addEventListener("contextmenu", (e) => {
      if (!term.hasSelection()) return;
      e.preventDefault();
      const chosen = term.getSelection();
      term.clearSelection();
      copyWith(() => writeText(chosen), note, (ok) => { note.textContent = ok == null ? "" : ok ? "Copied" : "Copy failed"; });
      term.focus();
    });
    term.attachCustomKeyEventHandler((e) => !(e.type === "keydown" && e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey
      && e.key.toLowerCase() === "v"));
    // As a paste: the shell holds even several lines at its prompt, and the Enter that runs them is left to the user.
    item.shellName = `Shell ${n}`;
    item.pasteProblem = (text) => (!sh.id || sh.ended ? "The shell has ended"
      : pasteable(text).includes("\n") && !term.modes.bracketedPasteMode ? "What runs in it now would take each line as Enter" : null);
    item.paste = (text) => {
      term.paste(pasteable(text));
      term.focus();
    };
    const styled = { term, fit };
    terminals.add(styled);
    item.onShow = () => {
      fit();
      if (item === dock.active || dock.mode === "float") term.focus();
    };
    item.confirmClose = async () => {
      if (!sh.id || sh.ended) return true;
      let command = null;
      try {
        command = (await postJson(`/api/shells/${sh.id}/state`, {})).shell.command;
      } catch (_) { /* gone already: nothing to lose */ }
      return !command || confirm(`${command} is still running in ${item.title}. Close the shell and stop it?`);
    };
    item.onClose = () => {
      if (sh.id && shellStream.shells.delete(sh.id)) streamShells();
      if (sh.id && !sh.ended) postJson(`/api/shells/${sh.id}/close`, {}).catch(() => {});
      terminals.delete(styled);
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

// ---------- links in a terminal ----------
const URL_RE = /\bhttps?:\/\/[^\s"'<>`]+/g;
// A logical line longer than this many rows is not followed further.
const WRAP_ROWS = 50;

// The text of a buffer line with, for each character, the 1-based column it starts at: wide characters take two.
function bufferLineText(line) {
  let text = "";
  const cols = [];
  for (let x = 0; x < line.length; x++) {
    const cell = line.getCell(x);
    if (!cell || cell.getWidth() === 0) continue;
    const chars = cell.getChars() || " ";
    for (let i = 0; i < chars.length; i++) cols.push(x + 1);
    text += chars;
  }
  return { text, cols };
}

// The rows the terminal wrapped y (0-based) into, as one text, with where each character is: a URL or a path cut by the
// right edge still links whole.
function logicalLine(buffer, y) {
  let top = y;
  while (top > 0 && y - top < WRAP_ROWS && buffer.getLine(top) && buffer.getLine(top).isWrapped) top--;
  let text = "";
  const cells = [];
  for (let row = top; row - top < 2 * WRAP_ROWS; row++) {
    const line = buffer.getLine(row);
    if (!line || (row > top && !line.isWrapped)) break;
    const part = bufferLineText(line);
    for (const x of part.cols) cells.push({ x, y: row + 1 });
    text += part.text;
  }
  return { text, cells };
}

// URLs open in a new tab; commits and files open their panel, as on the conversation, from where the shell is now.
function shellLinks(term, conv, sh) {
  return {
    provideLinks(y, callback) {
      if (!sh.id) return callback(undefined);
      const { text, cells } = logicalLine(term.buffer.active, y - 1);
      const range = (c) => ({ start: cells[c.start], end: cells[c.end - 1] });
      const found = candidates(text).filter((c) => range(c).start.y <= y && y <= range(c).end.y);
      if (!found.length) return callback(undefined);
      const links = found.filter((c) => c.kind === "url").map((c) => ({ range: range(c), text: c.token,
        activate: () => window.open(c.token, "_blank", "noopener,noreferrer") }));
      const refs = found.filter((c) => c.kind !== "url");
      if (!refs.length) return callback(links);
      const scope = { shell: sh.id };
      resolveRefs(conv, refs.filter((c) => c.kind === "commit").map((c) => c.token),
        refs.filter((c) => c.kind === "file").map((c) => c.token), scope)
        .catch(() => null)
        .then(() => {
          const known = refsOf(refKey(conv, scope));
          for (const c of refs) {
            const info = c.kind === "commit" ? known.commits.get(c.token) : known.files.get(c.token);
            if (!info || (Array.isArray(info) && !info.length)) continue;
            const at = { line: c.line, end: c.end2 };
            links.push({ range: range(c), text: text.slice(c.start, c.end), activate: (e) => {
              if (c.kind === "commit") return openCommit(conv, info.sha, null, info.cwd);
              if (info.length === 1) return openFile(conv, info[0], at);
              choose(conv, info, at, { getBoundingClientRect: () => ({ left: e.clientX, right: e.clientX, top: e.clientY - 8, bottom: e.clientY + 8 }),
                focus: () => term.focus() });
            } });
          }
          callback(links.length ? links : undefined);
        });
    },
  };
}

const pasteable = (text) => text.replace(/\r\n?/g, "\n").replace(/\n+$/, "");

// The shells on screen, as [label, act, tip, off] menu entries that type the text at their prompt.
function pasteEntries(text) {
  if (!pasteable(text)) return [];
  return dock.items.filter((i) => i.kind === "shell" && i.paste && shownPanel(i)).map((item) => {
    const problem = item.pasteProblem(text);
    return [`❯ Paste into ${item.shellName}`, () => item.paste(text), problem || "Typed at its prompt without Enter, which is yours to press",
      !!problem];
  });
}

function shellButton(conv, cwd) {
  return h("button", { class: "btn", type: "button", title: `Open an interactive shell in ${cwd}`,
    onclick: () => openShell(conv, cwd) }, "❯ Shell");
}

function dirButton(conv, cwd) {
  return h("button", { class: "btn", type: "button", title: `Browse ${cwd}`, onclick: () => openDir(conv, cwd) }, "▦ Browse");
}

function commitsButton(conv, cwd) {
  return h("button", { class: "btn", type: "button", title: `Commits of the repository of ${cwd}, and which are pushed`,
    onclick: () => openCommits(conv, cwd) }, "☰ Commits");
}

function searchButton(conv, cwd) {
  return h("button", { class: "btn", type: "button", title: `Search the files of ${cwd}`, onclick: () => openSearch(conv, cwd) }, icon("search"), " Search");
}

// ---------- chooser for a name that matches several files ----------
const pick = { el: null, digits: "", timer: null };

function closePick() {
  if (!pick.el) return;
  pick.el.remove();
  pick.el = null;
  pick.cleanup();
}

// anchor: the element (or { getBoundingClientRect, focus }) the list opens under and gives the focus back to.
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

// ---------- links on URLs, commit hashes and file names ----------
const COMMIT_RE = /(?<![\w/.\-])[0-9a-f]{7,40}(?![\w/\-])/g;
const FILE_RE = /(?<![\w@./~\-])((?:~|\.{1,2})?\/?(?:[\w@+.\-]+\/)*(?:[\w@+\-][\w@+.\-]*\.[A-Za-z][\w\-]{0,11}|Makefile|Dockerfile|Jenkinsfile|README|LICENSE))(?:(?::|#L)(\d+)(?:([:\-])(\d+))?)?(?![\w/])/g;
const LINK_SKIP = "a, button, input, textarea, select, summary, kbd, .ref, #conv-head, .composer, .xterm, .msg-head, .pick";
const RESOLVE_BATCH = 400;

// conversation id, "shell:<id>" or "cwd:<folder>" -> { commits: Map(token -> info|null), files: Map(token -> matches|null) }
const refCache = new Map();
const linker = { observer: null, queue: new Set(), timer: null, off: false };

function refsOf(key) {
  if (!refCache.has(key)) refCache.set(key, { commits: new Map(), files: new Map() });
  return refCache.get(key);
}

// scope: { shell } to look names up from where that shell is now, { cwd } from a folder, {} from the conversation's.
const refKey = (conv, scope = {}) => (scope.shell ? `shell:${scope.shell}` : scope.cwd ? `cwd:${scope.cwd}` : conv);

function candidates(text) {
  const found = [];
  for (const m of text.matchAll(URL_RE)) {
    const url = m[0].replace(/[.,;:!?)\]}'"]+$/, "");
    found.push({ kind: "url", start: m.index, end: m.index + url.length, token: url });
  }
  for (const m of text.matchAll(COMMIT_RE)) {
    if (/\d/.test(m[0]) && /[a-f]/.test(m[0])) found.push({ kind: "commit", start: m.index, end: m.index + m[0].length, token: m[0] });
  }
  for (const m of text.matchAll(FILE_RE)) {
    if (/^\d+(\.\d+)+$/.test(m[1])) continue;
    found.push({ kind: "file", start: m.index, end: m.index + m[0].length, token: m[1],
      line: m[2] ? Number(m[2]) : null, end2: m[3] === "-" && m[4] ? Number(m[4]) : null });
  }
  let reach = 0;
  return found.sort((a, b) => a.start - b.start || b.end - a.end).filter((c) => c.start >= reach && (reach = c.end));
}

// Runs of text to look for names in: the text nodes of one code element go together, since highlighting splits a path
// or a URL across its spans; anything that is not linked breaks a run.
function textRuns(root) {
  const runs = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let last = null;
  while (walker.nextNode()) {
    const node = walker.currentNode, parent = node.parentElement;
    if (!parent || parent.closest(LINK_SKIP)) {
      last = null;
      continue;
    }
    const code = parent.closest("code");
    if (code && last && last.code === code) {
      last.nodes.push(node);
      last.text += node.data;
    } else runs.push(last = { code, nodes: [node], text: node.data });
  }
  return runs.filter((r) => r.text.length >= 3);
}

async function resolveRefs(conv, commits, files, scope = {}) {
  const refs = refsOf(refKey(conv, scope));
  commits = [...new Set(commits)].filter((c) => !refs.commits.has(c));
  files = [...new Set(files)].filter((f) => !refs.files.has(f));
  for (let i = 0; i < Math.max(commits.length, files.length); i += RESOLVE_BATCH) {
    const c = commits.slice(i, i + RESOLVE_BATCH), f = files.slice(i, i + RESOLVE_BATCH);
    for (const x of c) refs.commits.set(x, null);
    for (const x of f) refs.files.set(x, null);
    const data = await postJson(convApi(conv, "/resolve"), { commits: c, files: f, ...scope });
    for (const [k, v] of Object.entries(data.commits)) refs.commits.set(k, { ...v, cwd: data.cwd });
    for (const [k, v] of Object.entries(data.files)) refs.files.set(k, v);
  }
}

// What wraps each piece of a found name, or null when it names nothing here.
function refMaker(c, refs, key) {
  if (c.kind === "url") {
    return () => h("a", { class: "ref ref-url", href: c.token, target: "_blank", rel: "noopener noreferrer", title: c.token });
  }
  if (c.kind === "commit") {
    const info = refs.commits.get(c.token);
    if (!info) return null;
    return () => h("span", { class: "ref ref-commit", role: "link", tabindex: "0", "data-sha": info.sha, "data-cwd": info.cwd,
      title: [info.sha.slice(0, 12), info.subject, info.author && `${info.author}, ${info.date}`].filter(Boolean).join(" · ") });
  }
  const matches = refs.files.get(c.token);
  if (!matches) return null;
  return () => h("span", { class: `ref ref-file${matches.length > 1 ? " many" : ""}`, role: "link", tabindex: "0", "data-file": c.token,
    "data-line": c.line, "data-end": c.end2, "data-refs": key,
    title: matches.length > 1 ? `${matches.length} files match: ${matches.slice(0, 8).map((m) => m.display).join(", ")}${matches.length > 8 ? "…" : ""}`
      : `Open ${matches[0].display}${c.line ? ` at line ${c.line}` : ""}` });
}

// Wraps the characters start..end of a run, one element per text node they cross. Candidates go from the last, so the
// nodes before keep their offsets.
function wrapRun(run, starts, c, make) {
  for (let i = run.nodes.length - 1; i >= 0; i--) {
    const node = run.nodes[i], from = starts[i];
    if (from >= c.end || from + node.data.length <= c.start) continue;
    const s = Math.max(c.start - from, 0), e = Math.min(c.end - from, node.data.length);
    if (e < node.data.length) node.splitText(e);
    const piece = s > 0 ? node.splitText(s) : node;
    const el = make();
    piece.replaceWith(el);
    el.append(piece);
  }
}

// where: { conv, cwd } for a panel's text, looked up from that folder; the conversation on screen otherwise.
async function linkify(roots, where = null) {
  const conv = where ? where.conv : app.route && app.route.id;
  if (!conv) return;
  const work = [];
  for (const root of roots) {
    if (!root.isConnected) continue;
    for (const run of textRuns(root)) {
      const found = candidates(run.text);
      if (found.length) work.push({ run, found });
    }
  }
  if (!work.length) return;
  const scope = where && where.cwd ? { cwd: where.cwd } : {};
  // URLs need nothing from the server.
  if (sendKey && !linker.off) {
    try {
      await resolveRefs(conv, work.flatMap((w) => w.found.filter((c) => c.kind === "commit").map((c) => c.token)),
        work.flatMap((w) => w.found.filter((c) => c.kind === "file").map((c) => c.token)), scope);
    } catch (err) {
      if (err.status === 403) linker.off = true;
    }
  }
  if (!where && (!app.route || app.route.id !== conv)) return;
  const key = refKey(conv, scope), refs = refsOf(key);
  for (const { run, found } of work) {
    if (!run.nodes.every((n) => n.isConnected) || run.nodes.map((n) => n.data).join("") !== run.text) continue;
    let at = 0;
    const starts = run.nodes.map((n) => (at += n.data.length) - n.data.length);
    for (const c of found.slice().reverse()) {
      const make = refMaker(c, refs, key);
      if (make) wrapRun(run, starts, c, make);
    }
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
  document.addEventListener("keydown", gotoActiveFile);
  setInterval(checkPanels, WATCH_MS);
  // A hidden tab gives its connection back; the shells pick up from the byte they had reached.
  document.addEventListener("visibilitychange", streamShells);
  window.addEventListener("resize", () => { if (dock.items.length) drawDock(); });
  window.addEventListener("themechange", restyleTerminals);
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
  document.addEventListener("mouseup", conversationSelection);
  document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.classList && e.target.classList.contains("ref")) followRef(e); });
}

function followRef(e) {
  const ref = e.target.closest && e.target.closest(".ref");
  // A URL is a plain link.
  if (!ref || ref.tagName === "A") return;
  const item = dock.items.find((i) => i.body.contains(ref));
  const conv = item ? item.conv : app.route && app.route.id;
  if (!conv) return;
  e.preventDefault();
  if (ref.dataset.sha) return openCommit(conv, ref.dataset.sha, null, ref.dataset.cwd);
  const matches = refsOf(ref.dataset.refs || conv).files.get(ref.dataset.file) || [];
  const at = { line: ref.dataset.line ? Number(ref.dataset.line) : null, end: ref.dataset.end ? Number(ref.dataset.end) : null };
  if (matches.length === 1) openFile(conv, matches[0], at);
  else if (matches.length > 1) choose(conv, matches, at, ref);
}
