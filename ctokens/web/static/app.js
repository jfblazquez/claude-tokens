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
function exact(n) {
  if (n == null || Number.isNaN(n)) return "N/D";
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

// The largest unit that keeps n under base, with at most two decimals: 950, 1.5K, 12.35M.
function scaled(n, base, units) {
  if (n == null || Number.isNaN(n)) return "N/D";
  let value = Number(n), unit = 0;
  while (Math.abs(Number(value.toFixed(2))) >= base && unit < units.length - 1) { value /= base; unit += 1; }
  return String(Number(value.toFixed(2))) + units[unit];
}

const fmt = (n) => scaled(n, 1000, ["", "K", "M", "B"]);
const fmtBytes = (n) => scaled(n, 1024, [" B", " KB", " MB", " GB", " TB"]);

// Two decimals from $1 up; under $1, rounded at the first non-zero decimal ($0.086 → $0.09).
function money(amount, estimated) {
  if (amount == null) return "N/D";
  const value = Number(amount);
  let text = value.toFixed(2);
  if (value && Math.abs(value) < 1) {
    const digits = Math.min(8, -Math.floor(Math.log10(Math.abs(value))));
    const rounded = Number(value.toFixed(digits));
    text = rounded && Math.abs(rounded) < 1 ? rounded.toFixed(digits).replace(/0+$/, "") : rounded.toFixed(2);
  }
  return `${estimated ? "~" : ""}$${text}`;
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
  folder: ["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"],
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

// write() copies and may return a promise; show(true | false) right after the copy, show(null) once the feedback expires.
function copyWith(write, el, show) {
  const done = (ok) => {
    show(ok);
    clearTimeout(el.copyTimer);
    el.copyTimer = setTimeout(() => show(null), COPY_FEEDBACK_MS);
  };
  let pending;
  try {
    pending = Promise.resolve(write());
  } catch (err) {
    pending = Promise.reject(err);
  }
  pending.then(() => done(true), () => done(false));
}

// The copy event takes HTML as it is, while the async API sanitises it inside the page, where the CSP refuses every style
// attribute; it also works over plain HTTP. The async API is left for browsers that do not fire the event.
function copyEvent(data) {
  let done = false;
  const listener = (e) => {
    for (const [type, value] of Object.entries(data)) e.clipboardData.setData(type, value);
    e.preventDefault();
    done = true;
  };
  document.addEventListener("copy", listener, true);
  try {
    document.execCommand("copy");
  } finally {
    document.removeEventListener("copy", listener, true);
  }
  return done;
}

function writeData(data) {
  if (copyEvent(data)) return null;
  const types = Object.keys(data);
  if (types.length === 1) return navigator.clipboard.writeText(data["text/plain"]);
  return navigator.clipboard.write([new ClipboardItem(Object.fromEntries(types.map((t) => [t, new Blob([data[t]], { type: t })])))]);
}

const writeText = (text) => writeData({ "text/plain": text });
// Pasted into an editor it is the plain text; into a document, a chat or a spreadsheet, the HTML.
const writeRich = (plain, html) => writeData({ "text/plain": plain, "text/html": html });
const copyText = (text, el, show) => copyWith(() => writeText(text), el, show);

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

const asWrite = (content) => (typeof content === "function" ? content : () => writeText(content));

// content: the text to copy, or a write() function for anything else; formats: [label, content] pairs offered on
// right-click. Without a label the button shows only the clipboard icon, so the title doubles as its accessible name.
function copyButton(content, title, label = null, formats = null) {
  const idle = () => label || icon("clipboard");
  const button = h("button", { class: label ? "btn copy-btn" : "btn copy-btn icon-btn", type: "button", title,
    "aria-label": label ? null : title }, idle());
  const copy = (c) => copyWith(asWrite(c), button, (ok) => {
    if (ok == null) button.replaceChildren(idle());
    else button.replaceChildren(label ? (ok ? "Copied" : "Copy failed") : icon(ok ? "check" : "failed"));
  });
  button.addEventListener("click", () => copy(content));
  if (formats) {
    button.setAttribute("aria-haspopup", "menu");
    button.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      openCopyMenu(button, formats, copy);
    });
  }
  return button;
}

// A click copies the first format.
const copyMenuButton = (title, formats) => copyButton(formats[0][1], `${title} · right-click for other formats`, null, formats);

let copyMenu = null;

function closeCopyMenu(refocus) {
  if (!copyMenu) return;
  const { menu, button, cleanup } = copyMenu;
  copyMenu = null;
  menu.remove();
  cleanup();
  if (refocus) button.focus();
}

function openCopyMenu(button, formats, copy) {
  closeCopyMenu(false);
  const items = formats.map(([label, content], i) => h("button", { type: "button", role: "menuitem", class: "copy-menu-item",
    onclick: () => { closeCopyMenu(true); copy(content); } }, label, i ? null : h("span", { class: "muted" }, "click")));
  const menu = h("div", { class: "copy-menu", role: "menu", "aria-label": "Copy as" }, h("div", { class: "copy-menu-head" }, "Copy as"), items);
  document.body.append(menu);
  const r = button.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(r.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 8))}px`;
  menu.style.top = `${r.bottom + 4 + menu.offsetHeight > innerHeight ? Math.max(8, r.top - 4 - menu.offsetHeight) : r.bottom + 4}px`;
  const outside = (e) => { if (!menu.contains(e.target)) closeCopyMenu(false); };
  const away = () => closeCopyMenu(false);
  const keys = (e) => {
    const i = items.indexOf(document.activeElement);
    if (e.key === "Escape" || e.key === "Tab") closeCopyMenu(e.key === "Escape");
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    }
  };
  document.addEventListener("pointerdown", outside, true);
  menu.addEventListener("keydown", keys);
  for (const type of ["scroll", "resize", "hashchange"]) window.addEventListener(type, away, true);
  copyMenu = { menu, button, cleanup: () => {
    document.removeEventListener("pointerdown", outside, true);
    for (const type of ["scroll", "resize", "hashchange"]) window.removeEventListener(type, away, true);
  } };
  items[0].focus();
}

// ---------- copy formats ----------
// Pasted HTML keeps only inline styles, and editors such as Word, Outlook or Teams show it on a light page, so the
// light theme's colours are written out rather than read from the page, which may be dark.
const EXPORT_MONO = "Consolas, 'Cascadia Mono', Menlo, 'Liberation Mono', monospace";
const EXPORT_ROOT = "font-family: 'Segoe UI', system-ui, -apple-system, Roboto, Arial, sans-serif; font-size: 14px; line-height: 1.5; "
  + "color: #17202b";
const EXPORT_STYLES = {
  pre: `margin: 8px 0; padding: 8px 12px; background: #fafafa; border: 1px solid #dce1e8; border-radius: 6px; font-family: ${EXPORT_MONO}; `
    + "font-size: 13px; line-height: 1.45; color: #383a42; white-space: pre-wrap",
  code: `font-family: ${EXPORT_MONO}; font-size: 0.92em; background: #f2f4f8; padding: 1px 4px; border-radius: 4px`,
  table: "border-collapse: collapse; margin: 8px 0",
  th: "border: 1px solid #dce1e8; padding: 4px 10px; background: #eef1f5; font-weight: 600; text-align: left",
  td: "border: 1px solid #dce1e8; padding: 4px 10px",
  blockquote: "margin: 8px 0; padding-left: 12px; border-left: 3px solid #dce1e8; color: #5a6575",
  a: "color: #2253b8",
  hr: "border: 0; border-top: 1px solid #dce1e8",
};
// atom-one-light, as in vendor/hljs-light.css; title.class_ comes before title so the more specific colour wins.
const EXPORT_HLJS = [
  [["comment", "quote"], "color: #a0a1a7; font-style: italic"],
  [["doctag", "formula", "keyword"], "color: #a626a4"],
  [["deletion", "name", "section", "selector-tag", "subst"], "color: #e45649"],
  [["literal"], "color: #0184bb"],
  [["addition", "attribute", "regexp", "string"], "color: #50a14f"],
  [["attr", "number", "selector-attr", "selector-class", "selector-pseudo", "template-variable", "type", "variable"], "color: #986801"],
  [["built_in", "class_"], "color: #c18401"],
  [["bullet", "link", "meta", "selector-id", "symbol", "title"], "color: #4078f2"],
  [["emphasis"], "font-style: italic"],
  [["strong"], "font-weight: 700"],
];
const EXPORT_ATTRS = new Set(["href", "align", "colspan", "rowspan", "start"]);
const VOID_TAGS = new Set(["br", "hr", "img", "wbr"]);

const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function hljsStyle(el) {
  const names = [...el.classList].map((c) => c.replace(/^hljs-/, ""));
  const hit = EXPORT_HLJS.find(([classes]) => classes.some((c) => names.includes(c)));
  return hit ? hit[1] : null;
}

// Written as a string, not as style attributes on live nodes, which the page's CSP would refuse.
function exportNode(node) {
  if (node.nodeType === Node.TEXT_NODE) return escapeHtml(node.data);
  if (node.nodeType !== Node.ELEMENT_NODE || node.tagName === "BUTTON") return "";
  const tag = node.tagName.toLowerCase();
  const inPre = tag === "code" && node.parentElement && node.parentElement.tagName === "PRE";
  const style = tag === "span" ? hljsStyle(node) : inPre ? null : EXPORT_STYLES[tag];
  const attrs = [...node.attributes].filter((a) => EXPORT_ATTRS.has(a.name)).map((a) => ` ${a.name}="${escapeHtml(a.value)}"`).join("")
    + (style ? ` style="${style}"` : "");
  if (VOID_TAGS.has(tag)) return `<${tag}${attrs}>`;
  return `<${tag}${attrs}>${[...node.childNodes].map(exportNode).join("")}</${tag}>`;
}

const exportHtml = (node) => `<div style="${EXPORT_ROOT}">${exportNode(node)}</div>`;
const exportChildren = (box) => `<div style="${EXPORT_ROOT}">${[...box.childNodes].map(exportNode).join("")}</div>`;

const BLOCK_TAGS = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "PRE", "BLOCKQUOTE", "UL", "OL", "TABLE", "HR", "DIV"]);

// Rendered text without the Markdown marks; lists keep a bullet or number and tables become tab-separated rows.
function plainBlocks(el) {
  const blocks = [];
  let inline = "";
  const flush = () => {
    if (inline.trim()) blocks.push(inline.trim());
    inline = "";
  };
  for (const node of el.childNodes) {
    if (node.nodeType === Node.ELEMENT_NODE && node.tagName === "BR") inline += "\n";
    else if (node.nodeType !== Node.ELEMENT_NODE || !BLOCK_TAGS.has(node.tagName)) inline += node.textContent;
    else {
      flush();
      const tag = node.tagName;
      if (tag === "PRE") blocks.push(node.textContent.replace(/\n$/, ""));
      else if (tag === "TABLE") blocks.push(tableText(node));
      else if (tag === "HR") blocks.push("———");
      else if (tag === "UL" || tag === "OL") {
        const start = Number(node.getAttribute("start")) || 1;
        blocks.push([...node.children].map((li, i) => {
          const mark = tag === "OL" ? `${start + i}. ` : "• ";
          return mark + plainBlocks(li).join("\n").replace(/\n/g, `\n${" ".repeat(mark.length)}`);
        }).join("\n"));
      } else if (tag === "BLOCKQUOTE") blocks.push(plainBlocks(node).join("\n\n").replace(/^/gm, "    "));
      else blocks.push(...plainBlocks(node));
    }
  }
  flush();
  return blocks;
}

const plainText = (box) => plainBlocks(box).join("\n\n");

// With format, what a click copies, carries HTML for documents and chats and the Markdown for plain-text editors.
function markdownFormats(markdown) {
  const box = () => markdownBox(markdown, "md");
  return [
    ["With format", () => writeRich(markdown, exportChildren(box()))],
    ["Plain text", () => writeText(plainText(box()))],
    ["Markdown", markdown],
    ["HTML source", () => writeText(exportChildren(box()))],
  ];
}

function promptFormats(text) {
  const html = `<div style="${EXPORT_ROOT}; white-space: pre-wrap">${escapeHtml(text)}</div>`;
  return [["With format", () => writeRich(text, html)], ["Plain text", text]];
}

function codeFormats(pre) {
  const code = pre.textContent.replace(/\n$/, "");
  const lang = ([...(pre.querySelector("code") || pre).classList].find((c) => c.startsWith("language-")) || "").slice(9);
  const fence = "`".repeat(Math.max(3, ...(code.match(/`+/g) || []).map((run) => run.length + 1)));
  return [
    ["With format", () => writeRich(code, exportHtml(pre))],
    ["Plain text", code],
    ["Markdown", `${fence}${lang === "plaintext" ? "" : lang}\n${code}\n${fence}`],
  ];
}

const csvCell = (s) => (/[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
const tableRows = (table) => [...table.rows].map((r) => [...r.cells].map((c) => c.textContent.trim()));
const tableText = (table) => tableRows(table).map((r) => r.map((c) => c.replace(/[\t\n]/g, " ")).join("\t")).join("\n");

// source: the table's Markdown, or null when it is not known.
function tableFormats(table, source) {
  const rows = tableRows(table);
  const markdown = source || rows.map((r) => `| ${r.map((c) => c.replace(/\|/g, "\\|")).join(" | ")} |`)
    .flatMap((line, i) => (i === 1 ? [`|${" --- |".repeat(rows[0].length)}`, line] : [line])).join("\n");
  return [
    ["With format", () => writeRich(markdown, exportHtml(table))],
    ["Markdown", markdown],
    ["CSV", rows.map((r) => r.map(csvCell).join(",")).join("\r\n")],
    ["Tab-separated (spreadsheet)", tableText(table)],
  ];
}

const IMAGE_EXTENSIONS = { "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp" };

function imageFormats(b, img) {
  const dataUrl = `data:${b.media_type};base64,${b.data}`;
  const download = () => {
    h("a", { href: dataUrl, download: `image.${IMAGE_EXTENSIONS[b.media_type]}` }).click();
  };
  // Browsers only take PNG images on the clipboard; the promise keeps Safari's user gesture while the PNG is made.
  return [
    ["Image (PNG)", () => navigator.clipboard.write([new ClipboardItem({ "image/png": pngOf(b, img) })])],
    ["Data URL", dataUrl],
    ["Markdown", `![image](${dataUrl})`],
    ["Base64", b.data],
    [`Download .${IMAGE_EXTENSIONS[b.media_type]}`, download],
  ];
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
  const pager = opts.pageSize ? pagerNav() : null;
  const cls = (...names) => names.filter(Boolean).join(" ") || null;
  const setPage = (n) => {
    page = n;
    if (opts.onPage) opts.onPage(page);
  };

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
      }, columns.map((c) => h("td", { class: cls(c.num && "num", c.cls),
        title: c.num && Number.isInteger(r[c.key]) && Math.abs(r[c.key]) >= 1000 ? exact(r[c.key]) : null },
      c.render ? c.render(r) : r[c.key]))));
    }
    const foot = opts.footer
      ? h("tfoot", {}, h("tr", { class: "total" }, opts.footer.map((cell, i) => h("td", { class: cls(columns[i] && columns[i].num && "num") }, cell))))
      : null;
    wrap.replaceChildren(h("table", {}, h("thead", {}, head), h("tbody", {}, body), foot));
    if (pager) drawPager(pager, page, opts.pageSize, data.length, (n) => { setPage(n); draw(); });
  }

  draw();
  return pager ? h("div", { class: "paged" }, wrap, pager) : wrap;
}

const pagerNav = () => h("nav", { class: "pager", "aria-label": "Pages" });

// go(n) redraws page n; the page is then shown from the top.
function drawPager(pager, page, pageSize, total, go) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = page * pageSize;
  const button = (label, n, title) => h("button", { class: "btn", type: "button", title, disabled: n === page || n < 0 || n >= pages,
    onclick: () => { go(n); window.scrollTo(0, 0); } }, label);
  pager.hidden = pages < 2;
  pager.replaceChildren(button("«", 0, "First page"), button("‹ Previous", page - 1, "Previous page"),
    h("span", { class: "count" }, `${fmt(first + 1)}–${fmt(Math.min(first + pageSize, total))} of ${fmt(total)} · page ${fmt(page + 1)} of ${fmt(pages)}`),
    button("Next ›", page + 1, "Next page"), button("»", pages - 1, "Last page"));
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

async function api(path, { method = "GET", headers = {}, body: payload } = {}) {
  let response;
  try {
    response = await fetch(path, { method, headers: { Accept: "application/json", ...headers }, body: payload, cache: "no-store" });
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
  if (body && typeof body.key === "string") keyState = body.key;
  for (const row of [...rows].reverse()) convRows.set(row.id, row);
  return rows;
}

const folderLabel = () => (projectsDir ? copyable(h("b", { class: "mono" }, projectsDir), projectsDir) : "the projects folder");
const folderText = () => projectsDir || "the projects folder";

const lastFolder = (path) => String(path || "").split(/[\\/]/).filter(Boolean).pop() || String(path || "");

const projectMatches = (row, filter) => !filter || String(row.project || "").toLowerCase().includes(filter.toLowerCase());

let listFilter = "";
let listLiveOnly = false;
const listShown = (rows) => rows.filter((r) => projectMatches(r, listFilter) && (!listLiveOnly || r.live));
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

// Today's and yesterday's conversations show the time only: their group already says the day.
function cardTime(iso, now) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const time = d.toISOString().slice(11, 16);
  return ["Today", "Yesterday"].includes(dateGroup(iso, now)) ? time : `${MONTHS[d.getUTCMonth()].slice(0, 3)} ${d.getUTCDate()}, ${time}`;
}

// ---------- recaps: the newest one of each conversation, loaded behind the list ----------
const RECAP_KEY = "ctokens.recaps";
const RECAP_BATCH = 20;
// id -> { modified, recap }: a stored recap holds while its conversation's modified time is unchanged.
const recapStore = readRecaps();
const recapFailed = new Set();
let recapRun = 0;

function readRecaps() {
  try {
    const stored = JSON.parse(localStorage.getItem(RECAP_KEY) || "{}");
    return stored && typeof stored === "object" && !Array.isArray(stored) ? stored : {};
  } catch (e) {
    return {};
  }
}

function saveRecaps() {
  try {
    localStorage.setItem(RECAP_KEY, JSON.stringify(recapStore));
  } catch (e) {
    // Private mode or a full quota: the recaps are fetched again next time.
  }
}

function pruneRecaps(rows) {
  const ids = new Set(rows.map((r) => r.id));
  for (const id of Object.keys(recapStore)) if (!ids.has(id)) delete recapStore[id];
  saveRecaps();
}

const storedRecap = (id, modified) => (recapStore[id] && recapStore[id].modified === modified ? recapStore[id] : null);

// `code` spans as code; an unpaired backtick stays as text.
function recapText(text) {
  const parts = text.split("`");
  return parts.map((part, i) => (i % 2 === 0 ? part : i < parts.length - 1 ? h("code", {}, part) : `\`${part}`));
}

function fillRecap(el) {
  const { id, modified } = el.dataset;
  const entry = storedRecap(id, modified);
  const pending = !entry && !recapFailed.has(id);
  const text = entry && entry.recap ? entry.recap.text : "";
  el.hidden = !pending && !text;
  el.classList.toggle("loading", pending);
  el.setAttribute("aria-busy", String(pending));
  el.title = text;
  el.replaceChildren(...(pending ? [h("i", { class: "recap-skel", "aria-hidden": "true" })] : recapText(text)));
}

function recapLine(row) {
  const el = h("p", { class: "recap", "data-id": row.id, "data-modified": row.modified });
  fillRecap(el);
  return el;
}

// In the order given; a newer call takes over, while the answers already asked for are still kept.
async function loadRecaps(rows) {
  const run = ++recapRun;
  recapFailed.clear();
  const pending = [...new Map(rows.filter((r) => !storedRecap(r.id, r.modified)).map((r) => [r.id, r])).values()];
  for (let i = 0; i < pending.length && run === recapRun; i += RECAP_BATCH) {
    const batch = pending.slice(i, i + RECAP_BATCH);
    let body = null;
    try {
      body = await api(`/api/recaps?ids=${batch.map((r) => r.id).join(",")}`);
    } catch (e) {
      // Shown without a recap until the list is drawn again.
      if (run === recapRun) for (const r of pending.slice(i)) recapFailed.add(r.id);
    }
    if (body) {
      for (const r of batch) recapStore[r.id] = { modified: r.modified, recap: (body.recaps || {})[r.id] || null };
      saveRecaps();
    }
    for (const el of document.querySelectorAll(".recap[data-id]")) fillRecap(el);
    if (!body) return;
  }
}

function conversationCard(row, now) {
  const card = h("a", { class: "conv-card", href: convHref(row.id, row.new ? "messages" : null) },
    h("div", { class: "conv-top" },
      h("span", { class: "conv-title" }, liveBadge(row.live, false, row.id), row.title || h("span", { class: "untitled" }, row.new ? "New session" : "Untitled")),
      h("time", { class: "conv-when", datetime: row.modified, title: `${utcMinute(row.modified)} UTC` }, cardTime(row.modified, now))),
    row.new ? h("p", { class: "recap" }, "No messages yet") : recapLine(row),
    h("div", { class: "conv-meta" },
      h("span", { class: "project", title: row.project }, icon("folder"), lastFolder(row.project)),
      h("span", {}, fmtBytes(row.size_bytes)),
      row.subagents ? h("span", {}, `${fmt(row.subagents)} ${row.subagents === 1 ? "subagent" : "subagents"}`) : null));
  // A button cannot sit inside the card's link, so it is laid over the card's corner instead.
  const actions = row.live ? null : h("div", { class: "conv-actions" }, startError(row.id), startButton(row.id, "go-live"));
  return h("div", { class: actions ? "conv-item has-actions" : "conv-item" }, card, actions);
}

// Rows come most recent first; each card group is a date range of the whole list, not only of the page.
function conversationCards(rows) {
  const now = Date.now();
  const groupOf = (r) => dateGroup(r.modified, now);
  const sizes = countBy(rows, groupOf);
  const list = h("div", { class: "conv-list" });
  const pager = pagerNav();
  const draw = () => {
    const pages = Math.max(1, Math.ceil(rows.length / LIST_PAGE_SIZE));
    listState.page = Math.min(listState.page, pages - 1);
    const shown = rows.slice(listState.page * LIST_PAGE_SIZE, (listState.page + 1) * LIST_PAGE_SIZE);
    const items = [];
    let current = null;
    for (const r of shown) {
      if (groupOf(r) !== current) {
        current = groupOf(r);
        items.push(h("h2", { class: "conv-group" }, current, h("span", { class: "n" }, fmt(sizes.get(current)))));
      }
      items.push(conversationCard(r, now));
    }
    list.replaceChildren(...items);
    drawPager(pager, listState.page, LIST_PAGE_SIZE, rows.length, (n) => { listState.page = n; draw(); });
    loadRecaps([...shown, ...rows]);  // this page first
  };
  draw();
  return h("div", { class: "paged" }, list, pager);
}

function listCount(data) {
  if (data && data.search !== listSearch) return [h("span", { class: "spinner small", "aria-hidden": "true" }), "Searching…"];
  if (!data) return "";
  const shown = listShown(data.rows).length;
  return data.search ? `${fmt(shown)} conversations containing “${data.search}”` : `${fmt(shown)} of ${fmt(data.rows.length)} conversations`;
}

VIEWS.list = {
  title: () => "Conversations",
  async load() {
    const search = listSearch;
    const data = { search, rows: listRows(await api(search ? `/api/conversations?q=${encodeURIComponent(search)}` : "/api/conversations",
      { headers: sendHeaders() })) };
    if (!search) pruneRecaps(data.rows);
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
    const liveOnly = h("input", { id: "list-live", type: "checkbox", role: "switch", checked: listLiveOnly, autocomplete: "off",
      onchange: (e) => { listLiveOnly = e.target.checked; listState.page = 0; show({ keepScroll: true }); } });
    return [h("div", { class: "page-head" }, h("h1", {}, "Conversations"),
      h("div", { class: "meta" }, projectsDir ? h("span", {}, "Projects folder ", folderLabel()) : null,
        h("span", {}, "Most recent first · times in UTC"))),
    h("div", { class: "toolbar" }, h("div", { class: "filters" }, h("label", { class: "field" }, "Project", project),
      h("label", { class: "field" }, "Search", search),
      h("label", { class: "switch", title: "Only conversations running in a Claude Code process now" }, liveOnly, " Live only")), count)];
  },
  render({ search, rows }) {
    if (!rows.length && !search) {
      return emptyState("No conversations found", `No conversations were found in ${folderText()}. `
        + "Conversations appear here after you use Claude Code.");
    }
    const shown = listShown(rows);
    if (!shown.length) {
      const why = [listFilter && `a project matching “${listFilter}”`, search && `“${search}” in its title or messages`];
      if (listLiveOnly && !why.some(Boolean)) return emptyState("No live conversations", "No conversation is running in a Claude Code process now.");
      return emptyState("No matching conversations", `No ${listLiveOnly ? "live " : ""}conversation has ${why.filter(Boolean).join(" and ")}.`);
    }
    return h("div", { class: "section" }, conversationCards(shown));
  },
};

// ---------- live sessions: conversations running in a Claude Code process ----------
// The key that lets this browser type into sessions; --serve prints a link that carries it once in ?key=.
const SEND_KEY = "ctokens.sendKey";
let sendKey = "";

function takeSendKey() {
  try {
    sendKey = localStorage.getItem(SEND_KEY) || "";
  } catch (e) { /* only a key from this page's link is known then */ }
  const params = new URLSearchParams(location.search), key = params.get("key");
  if (key == null) return;
  sendKey = key;
  try {
    localStorage.setItem(SEND_KEY, key);
  } catch (e) { /* the key then lasts for this page only */ }
  params.delete("key");
  const query = params.toString();
  history.replaceState(null, "", `${location.pathname}${query ? `?${query}` : ""}${location.hash}`);
}

const sendHeaders = () => (sendKey ? { "X-Send-Key": sendKey } : {});
// id -> { live, key, send_problem } from /live, fresher than the live field of the list rows.
const liveStatus = new Map();

function liveState(live) {
  if (live.status === "waiting") return live.waiting_for ? `waiting · ${live.waiting_for}` : "waiting";
  return live.status || "running";
}

// With an id the badge opens that conversation's Conversation tab, even from inside a card's link.
function liveBadge(live, long = false, id = null) {
  if (!live) return null;
  const state = liveState(live);
  const since = live.status_since ? ` since ${utcMinute(live.status_since)} UTC` : "";
  const readOnly = live.read_only ? " · read only" : "";
  const open = id ? (e) => { e.preventDefault(); e.stopPropagation(); location.hash = convHref(id, "messages"); } : null;
  return h("span", { class: `live ${live.status || ""}${live.read_only ? " read-only" : ""}${id ? " link" : ""}`,
    title: `Running in Claude Code process ${live.pid}${live.name ? ` (${live.name})` : ""} · ${state}${since}`
      + (live.read_only ? `\nRead only: ${live.read_only_reason}` : "") + (id ? "\nClick to open the conversation" : ""), onclick: open },
  h("i", { "aria-hidden": "true" }), long ? `Live · ${state}${readOnly}` : `Live${readOnly}`);
}

// ---------- starting claude in a new tmux window: GO LIVE (resume) and New session ----------
// The send key state from the server's last answer: "ok", "missing", "wrong" or "disabled".
let keyState = null;
// id -> the action the server is starting for it; id -> why the last start failed.
const starting = new Map();
const startErrors = new Map();
const START_POLL_MS = 2000;
const START_POLLS = 15;

const START_ACTIONS = {
  "go-live": { label: "GO LIVE", cls: "go-live", title: "Resume this conversation (claude --resume) in a new tmux window" },
  "new-session": { label: "New session", cls: "", title: "Start a new claude in this conversation's folder, in a new tmux window" },
};

function startButton(id, action) {
  const spec = START_ACTIONS[action], busy = starting.get(id) === action;
  const title = keyState === "ok" ? spec.title : KEY_NOTES[keyState] || KEY_NOTES.missing;
  return h("button", { class: `btn ${spec.cls}`, type: "button", title, disabled: keyState !== "ok" || starting.has(id),
    onclick: (e) => { e.preventDefault(); e.stopPropagation(); startSession(id, action); } }, busy ? "Starting…" : spec.label);
}

const startError = (id) => (startErrors.has(id) ? h("span", { class: "start-error", title: startErrors.get(id) }, startErrors.get(id)) : null);

function redrawStart(id) {
  const route = app.route;
  if (!route) return;
  if (route.view === "list" && app.phase === "ready") show({ keepScroll: true });
  else if (route.id === id) redrawConvHead(id);
}

async function startSession(id, action) {
  starting.set(id, action);
  startErrors.delete(id);
  redrawStart(id);
  let data = null;
  try {
    data = await api(`/api/conversations/${encodeURIComponent(id)}/${action}`, { method: "POST",
      headers: { ...sendHeaders(), "Content-Type": "application/json" }, body: "{}" });
  } catch (err) {
    startErrors.set(id, `Not started: ${err.message}`);
  }
  starting.delete(id);
  if (data && !data.live) {
    startErrors.set(id, action === "new-session" ? "Started in a new tmux window; it shows up in the list once Claude Code registers it."
      : "Started in a new tmux window; waiting for Claude Code to register it.");
  }
  const opened = data && (action === "go-live" ? id : data.session_id);
  if (!opened) {
    redrawStart(id);
    return;
  }
  // Straight to the Conversation tab, with the box focused as soon as the session can take a message.
  focusComposerFor = opened;
  await refreshList();
  const target = convHref(opened, "messages");
  if (location.hash !== target) location.hash = target;
  else fetchLive(opened);
  if (!data.live) await waitLive(opened);
}

// Until the resumed session shows up live, then the list or the conversation shows it like any other.
async function waitLive(id) {
  for (let i = 0; i < START_POLLS; i++) {
    await refreshList();
    if (app.route && app.route.id === id) await fetchLive(id);
    if (liveOf(id)) break;
    await new Promise((resolve) => setTimeout(resolve, START_POLL_MS));
  }
  if (liveOf(id)) startErrors.delete(id);
  if (app.route && app.route.view === "list") load({ refresh: true });
  else redrawStart(id);
}

const liveOf = (id) => (liveStatus.has(id) ? liveStatus.get(id).live : (convRows.get(id) || {}).live || null);

async function fetchLive(id) {
  let data;
  try {
    data = await api(`/api/conversations/${encodeURIComponent(id)}/live`, { headers: sendHeaders() });
  } catch (_) {
    return;
  }
  const old = liveStatus.get(id);
  liveStatus.set(id, data);
  keyState = data.key;
  if (old && JSON.stringify(old) === JSON.stringify(data)) return;
  redrawConvHead(id);
  drawComposer();
}

// ---------- conversation header and tabs (R4.5) ----------
const TABS = [["report", "Usage"], ["messages", "Conversation"], ["response", "Last response"], ["bash", "Bash commands"], ["files", "Files"]];

async function refreshList() {
  try {
    listRows(await api("/api/conversations", { headers: sendHeaders() }));
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
  liveStatus.clear();
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
    (refresh && !revalidate) || !convRows.has(route.id) ? refreshList() : null, fetchLive(route.id)]);
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
  const title = (row && row.title) || convTasks.get(route.id) || (row && row.new ? "New session" : "Untitled conversation");
  const resume = row ? `cd ${shellQuote(row.project)} && claude --resume ${shellQuote(route.id)}` : null;
  const live = liveOf(route.id);
  const meta = [live ? h("span", {}, liveBadge(live, true, route.view === "messages" ? null : route.id), ` PID ${live.pid}`) : null,
    h("span", { class: "conv-id" }, copyable(h("span", { class: "mono" }, route.id), route.id),
      resume && !live ? copyButton(resume, resume, "Copy resume") : null),
    h("span", { class: "conv-actions-head" }, live ? null : startButton(route.id, "go-live"), startButton(route.id, "new-session"),
      startError(route.id))];
  if (row) {
    meta.push(h("span", {}, copyable(h("b", { class: "mono" }, row.project), row.project)), h("span", {}, `Modified ${utcMinute(row.modified)} UTC`),
      h("span", {}, `${fmtBytes(row.size_bytes)} · ${fmt(row.subagents)} subagent${row.subagents === 1 ? "" : "s"}`));
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
// Only the cache tiers that were written: 1.03K (5m), or 1.03K (5m) + 2K (1h).
const cacheWrite = (five, hour) => [[five, "5m"], [hour, "1h"]].filter(([n]) => n).map(([n, tier]) => `${fmt(n)} (${tier})`).join(" + ") || "0";
const cacheWriteOf = (r) => cacheWrite(r.cache_write_5m, r.cache_write_1h);
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
      claudeCodeStat(data.claude_code),
      stat("Total tokens", fmt(tokens), `${fmt(sumBy(byModel, "output"))} output`),
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
        { key: "cache_write", label: "Cache write", num: true, render: cacheWriteOf, sortValue: (r) => r.cache_write_5m + r.cache_write_1h },
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
      { key: "cache_write", label: "Cache write", num: true, render: cacheWriteOf, sortValue: (r) => r.cache_write_5m + r.cache_write_1h },
      { key: "estimated_cost_usd", label: "Cost", num: true, render: (r) => money(r.estimated_cost_usd, r.price_estimated) },
    ].filter(Boolean);
    const footer = ["Total", fmt(tokens), fmt(sumBy(byModel, "input")), fmt(sumBy(byModel, "output")), showRaw ? "" : null,
      fmt(sumBy(byModel, "cache_read")), cacheWrite(sumBy(byModel, "cache_write_5m"), sumBy(byModel, "cache_write_1h")),
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
      ], data.main_context_snapshot || [], { id: "report-context" }));
    const breakdown = h("section", { class: "section" },
      sectionHead("Context breakdown", "Main conversation · what the last observed context is made of, estimated"),
      h("div", { id: "context-breakdown" }, h("p", { class: "footnote" }, "Reading the messages…")));

    const cold = h("section", { class: "section" }, sectionHead("Cold-summary estimate", "What summarizing this context would cost without cache"),
      renderTable([
        { key: "model", label: "Model", render: (r) => modelCell(r.model) },
        { key: "context_tokens", label: "Cold input", num: true, render: (r) => fmt(r.context_tokens) },
        { key: "assumed_summary_output_tokens", label: "Assumed output", num: true, render: (r) => fmt(r.assumed_summary_output_tokens) },
        { key: "estimated_cold_summary_cost_usd", label: "Cost", num: true, render: (r) => money(r.estimated_cold_summary_cost_usd, r.price_estimated) },
      ], data.cold_summary_estimate || [], { id: "report-cold" }));

    return [stats, ...pricingNotices(data), usage, models, context, breakdown, cold];
  },
  after: (data, route) => {
    const box = $("context-breakdown");
    if (!box || box.dataset.done) return null;
    let cancelled = false;
    fillBreakdown(box, route.id, () => cancelled || !box.isConnected).catch(() => {
      if (!cancelled) box.replaceChildren(h("p", { class: "footnote" }, "The messages could not be read to break the context down."));
    });
    return () => { cancelled = true; };
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

// tableSources gets the Markdown of each table, in the order of the page.
function markdownBox(markdown, cls, tableSources = []) {
  const box = h("article", { class: cls });
  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
    box.append(h("pre", {}, markdown));
    return box;
  }
  const tokens = marked.lexer(markdown);
  marked.walkTokens(tokens, (t) => { if (t.type === "table") tableSources.push(t.raw.trim()); });
  box.innerHTML = DOMPurify.sanitize(marked.parser(tokens), SANITIZE);
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

function renderMarkdown(markdown, cls = "card md") {
  const tableSources = [];
  const box = markdownBox(markdown, cls, tableSources);
  for (const pre of box.querySelectorAll("pre")) copyCorner(pre, "Copy the code", codeFormats(pre));
  const tables = box.querySelectorAll("table");
  // A <table> written as HTML in the Markdown has no table token, so the sources only line up when the counts match.
  const sources = tables.length === tableSources.length ? tableSources : null;
  tables.forEach((table, i) => copyCorner(table, "Copy the table", tableFormats(table, sources && sources[i])));
  return box;
}

// The button sits over the top right corner and shows on hover, so the block keeps its whole width.
function copyCorner(el, title, formats) {
  const wrap = h("div", { class: "copy-wrap" });
  el.replaceWith(wrap);
  wrap.append(el, copyMenuButton(title, formats));
}

VIEWS.response = convView("/last-response", {
  title: (route) => `Last response · ${convTitle(route)}`,
  render(data) {
    if (!data.last_response) {
      return emptyState("No text response", "The main conversation has no assistant text response yet. "
        + "Responses from subagents are not shown here.");
    }
    const box = renderMarkdown(data.last_response);
    box.prepend(copyMenuButton("Copy the response", markdownFormats(data.last_response)));
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
// level: how much is shown, from 1 (prompts and replies) to 5 (everything in the log); see LEVELS.
// keep: the message at the top of the screen before a refresh redraws the list; unread: log index of the first message
// that arrived since, while the reader has not reached it.
const LEVEL_KEY = "ctokens.messages.level";
const LEVELS = [null, "Prompts and replies", "Tools and notices", "Turns and compactions", "Commands and hooks", "Everything"];

function storedLevel() {
  try {
    const level = Number(localStorage.getItem(LEVEL_KEY));
    return Number.isInteger(level) && level >= 1 && level < LEVELS.length ? level : 2;
  } catch (e) {
    return 2;
  }
}

const messagesState = { id: null, source: "main", toBottom: false, restore: false, anchor: null, level: storedLevel(), keep: null,
  unread: null };
const KIND_LABELS = { prompt: "User", meta: "Injected context", summary: "Compaction summary", tool_result: "Tool results",
  notification: "Notification" };
// Level from which each event kind is shown; blocks and messages without one are tagged where they are built.
const EVENT_LEVELS = { refusal: 1, compaction: 3, turn: 3, command: 4, recap: 4, info: 4, hook: 4, attachment: 5, system: 5 };

const withSource = (path, source) => (source === "main" ? path : `${path}?source=${encodeURIComponent(source)}`);

// Tool inputs and results can be long, so a block is only built the first time it is opened.
function lazyDetails(cls, summary, build, title = null) {
  const body = h("div", { class: "blk-body" });
  const box = h("details", { class: cls }, h("summary", { title }, summary), body);
  box.addEventListener("toggle", () => { if (box.open && !body.firstChild) append(body, build()); });
  return box;
}

// ---------- code languages (analysis.js) ----------
const highlighting = () => typeof hljs !== "undefined" && typeof detectLanguage === "function";
const coloured = (lang) => !!lang && lang !== "plaintext" && highlighting() && !!hljs.getLanguage(lang);
const languageName = (lang) => (highlighting() && hljs.getLanguage(lang) ? hljs.getLanguage(lang).name : lang);
// tool_use id -> language of its result: detection is the slow part of opening a block and of the context breakdown.
const resultLanguages = new Map();

function toolCalls(messages) {
  const calls = new Map();
  for (const m of messages) for (const b of m.blocks) if (b.type === "tool_use") calls.set(b.id, b);
  return calls;
}

function languageOfResult(result, call) {
  if (!highlighting()) return null;
  const id = result.tool_use_id;
  if (!id) return resultLanguage(hljs, result, call);
  if (!resultLanguages.has(id)) resultLanguages.set(id, resultLanguage(hljs, result, call));
  return resultLanguages.get(id);
}

function codePre(text, lang) {
  if (!coloured(lang)) return h("pre", {}, text);
  const code = h("code", { class: `language-${lang}` }, text);
  hljs.highlightElement(code);
  return h("pre", {}, code);
}

function fmtDuration(ms) {
  if (ms == null) return "N/D";
  const seconds = ms / 1000;
  if (seconds < 60) return `${Number(seconds.toFixed(seconds < 10 ? 1 : 0))} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

// Click toggles between the thumbnail and the image at its own size.
function imageBlock(b) {
  const caption = [b.media_type || "image", b.bytes != null ? fmtBytes(b.bytes) : null].filter(Boolean).join(" · ");
  if (!b.data || !IMAGE_TYPES.has(b.media_type)) return h("span", { class: "chip" }, `${caption} · not in the log`);
  const img = h("img", { src: `data:${b.media_type};base64,${b.data}`, alt: "Image from the conversation", loading: "lazy",
    title: "Click to toggle full size", onclick: () => img.classList.toggle("full") });
  return h("figure", { class: "img-block" }, img, h("figcaption", {}, caption, copyMenuButton("Copy the image", imageFormats(b, img))));
}

function pngOf(b, img) {
  if (b.media_type === "image/png") return Promise.resolve(new Blob([Uint8Array.from(atob(b.data), (c) => c.charCodeAt(0))], { type: "image/png" }));
  return img.decode().then(() => new Promise((resolve, reject) => {
    const canvas = h("canvas", { width: img.naturalWidth, height: img.naturalHeight });
    canvas.getContext("2d").drawImage(img, 0, 0);
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("no PNG"))), "image/png");
  }));
}

// Outside the collapsed tool block, so they show without opening it.
const resultImages = (result) => (result && result.images && result.images.length
  ? h("div", { class: "img-row v2" }, result.images.map(imageBlock)) : null);
// A result that is nothing but its images: the "[image]" placeholders say nothing the thumbnails do not.
const onlyImages = (result) => !!(result.images && /^(\s*\[image\])+\s*$/.test(result.text));

const clippedPre = (item, lang = null) => [codePre(item.text, lang), item.size > item.text.length
  ? h("div", { class: "footnote" }, `Showing the first ${fmt(item.text.length)} of ${fmt(item.size)} characters`) : null];

const labelled = (label, item, lang = null) => h("div", {},
  h("div", { class: "lbl" }, coloured(lang) ? `${label} · ${languageName(lang)}` : label), clippedPre(item, lang));

function usageStats(m) {
  const u = m.usage;
  const items = [
    ["Context", fmt(u.context)],
    ["Output", u.thinking ? `${fmt(u.output)} (${fmt(u.thinking)} thinking)` : fmt(u.output)],
    ["Cost", money(m.estimated_cost_usd, m.price_estimated)],
    ["Input", fmt(u.input)],
    ["Cache read", fmt(u.cache_read)],
    ["Cache write", cacheWrite(u.cache_write_5m, u.cache_write_1h)],
    u.web_search_requests ? ["Web searches", fmt(u.web_search_requests)] : null,
    u.web_fetch_requests ? ["Web fetches", fmt(u.web_fetch_requests)] : null,
    u.speed && u.speed !== "standard" ? ["Speed", u.speed] : null,
    u.service_tier && u.service_tier !== "standard" ? ["Tier", u.service_tier] : null,
  ].filter(Boolean);
  return h("dl", { class: "ustats" }, items.map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v))));
}

// Claude Code's own running total, from the last cost-state record of the main log.
function claudeCodeStat(cc) {
  if (!cc || cc.cost_usd == null) return null;
  const lines = cc.lines_added != null ? `+${fmt(cc.lines_added)} −${fmt(cc.lines_removed)} lines` : null;
  const api = cc.api_duration_ms != null ? `API ${fmtDuration(cc.api_duration_ms)}` : null;
  return stat("Claude Code's estimate", money(cc.cost_usd, false), [lines, api].filter(Boolean).join(" · ") || "its own running total");
}

const ROUTINE_STOPS = new Set(["tool_use", "end_turn", "stop_sequence"]);
const cacheMiss = (u) => u.cache_read === 0 && u.cache_write_5m + u.cache_write_1h > 0;

function permissionChip(result) {
  const p = result && result.permission;
  return p ? h("span", { class: "chip v5", title: "Permission decision" }, p.reason ? `${p.decision} · ${p.reason}` : p.decision) : null;
}

function toolBlock(block, result) {
  const failed = !!(result && result.is_error);
  return lazyDetails(failed ? "blk failed" : "blk",
    [h("span", { class: "chip" }, block.name), failed ? h("span", { class: "badge" }, "error") : null,
      result ? null : h("span", { class: "muted" }, "no result"), permissionChip(result),
      block.summary ? h("span", { class: "mono sum" }, block.summary) : null],
    () => [block.input.map((f) => labelled(f.name, f, highlighting() ? inputLanguage(hljs, block, f.name) : null)),
      result && result.patch ? labelled("patch", result.patch, "diff") : null,
      result && !onlyImages(result) ? labelled(failed ? "result (error)" : "result", result, languageOfResult(result, block)) : null],
    block.summary || null);
}

// tools: tool_use id -> its result and its call, so results render under the call that made them.
function messageBlocks(m, tools) {
  return m.blocks.map((b) => {
    if (b.type === "text") return m.role === "assistant" ? renderMarkdown(b.text, "md") : h("pre", { class: "prompt" }, b.text);
    if (b.type === "thinking") return lazyDetails("think", "Thinking", () => h("pre", {}, b.text));
    if (b.type === "image") return imageBlock(b);
    if (b.type === "tool_use") return [toolBlock(b, tools.results.get(b.id)), resultImages(tools.results.get(b.id))];
    if (b.type === "tool_result" && !tools.calls.has(b.tool_use_id)) {
      return [lazyDetails(b.is_error ? "blk failed" : "blk", ["Tool result", permissionChip(b)],
        () => [b.patch ? labelled("patch", b.patch, "diff") : null, onlyImages(b) ? null : clippedPre(b, languageOfResult(b, null))]),
      resultImages(b)];
    }
    return null;
  });
}

const lineText = (text) => h("span", { class: "event-text" }, text);

function eventBody(m) {
  if (m.kind === "refusal") return [h("b", {}, "Refused"), m.category ? h("span", { class: "badge" }, m.category) : null, lineText(m.text)];
  if (m.kind === "compaction") {
    return [h("b", {}, "Compaction"), m.trigger ? h("span", { class: "chip" }, m.trigger) : null,
      lineText(`${fmt(m.pre_tokens)} → ${fmt(m.post_tokens)} tokens · took ${fmtDuration(m.duration_ms)}`)];
  }
  if (m.kind === "turn") return [h("b", {}, "Turn"), lineText(`took ${fmtDuration(m.duration_ms)}`)];
  if (m.kind === "command") return [h("b", {}, "Command"), h("span", { class: "mono event-text" }, m.text)];
  if (m.kind === "recap") return [h("b", {}, "Recap"), lineText(m.text)];
  if (m.kind === "info") return [h("b", {}, "Info"), lineText(m.text)];
  if (m.kind === "hook") return [h("b", {}, m.name ? `Hook · ${m.name}` : "Hook"), lineText(m.text)];
  return [lazyDetails("blk", [h("span", { class: "chip" }, m.kind === "system" ? `system · ${m.name}` : m.name)], () => clippedPre(m))];
}

function eventItem(m, time) {
  const level = EVENT_LEVELS[m.kind] || 5;
  return h("li", { class: `msg event${m.kind === "refusal" ? " failed" : ""}${level > 1 ? ` v${level}` : ""}` },
    h("div", { class: "msg-head" }, time, eventBody(m)));
}

// Shown from level 3: time spent thinking and the effort the response ran with.
function responseExtras(m) {
  const parts = [m.thinking_ms ? `thinking ${fmtDuration(m.thinking_ms)}` : null, m.effort ? `effort ${m.effort}` : null].filter(Boolean);
  return parts.length ? h("span", { class: "v3 extras" }, parts.join(" · ")) : null;
}

// Only the text the message says: tool calls, results and thinking are left out.
function messageCopy(m) {
  const text = m.blocks.filter((b) => b.type === "text").map((b) => b.text).join("\n\n");
  if (!text) return null;
  return copyMenuButton("Copy the message", m.role === "assistant" ? markdownFormats(text) : promptFormats(text));
}

// showModel: the model name is written only when it differs from the previous response; the swatch is always there.
function messageItem(m, tools, showModel) {
  const time = m.when ? h("time", { datetime: m.when.toISOString(), title: `${m.when.toISOString().slice(0, 19).replace("T", " ")} UTC` }, utcTime(m.when))
    : h("span", { class: "notime" }, "—");
  if (m.role === "event") return eventItem(m, time);
  const num = m.n ? h("span", { class: "n" }, `#${m.n}`) : null;
  if (m.role === "assistant") {
    const flow = m.blocks.some((b) => b.type === "text") ? "" : " flow";
    const item = h("li", { class: (m.kind === "error" ? "msg failed" : "msg") + flow },
      h("div", { class: "msg-head" }, num, time, h("span", { class: "model", title: m.model }, swatch(m.model), showModel ? m.model : null),
        m.kind === "error" ? h("span", { class: "badge" }, "API error") : null,
        m.stop_reason && !ROUTINE_STOPS.has(m.stop_reason) ? h("span", { class: "badge warn" }, m.stop_reason) : null,
        cacheMiss(m.usage) ? h("span", { class: "badge warn", title: "Nothing was read from cache: the whole context was written again" },
          "cache miss") : null,
        responseExtras(m), usageStats(m)),
      h("div", { class: "msg-body" }, messageBlocks(m, tools)), messageCopy(m));
    item.style.borderLeftColor = colorOf(m.model);
    return item;
  }
  const collapsed = m.kind === "meta" || m.kind === "summary" || m.kind === "notification";
  return h("li", { class: (collapsed ? "msg aside" : "msg user") + (m.kind === "prompt" ? "" : " flow") },
    h("div", { class: "msg-head" }, num, time, h("b", {}, KIND_LABELS[m.kind]),
      m.queued ? h("span", { class: "badge warn", title: "Typed while the model was still working" }, "sent mid-turn") : null,
      m.title ? h("span", { class: "event-text" }, m.title) : null),
    h("div", { class: "msg-body" }, collapsed ? lazyDetails("blk", "Show", () => messageBlocks(m, tools)) : messageBlocks(m, tools)),
    messageCopy(m));
}

// context carries the day heading and the model last shown, so items appended later continue the list.
function messageItems(messages, tools, context) {
  const items = [];
  for (const m of messages) {
    const today = dayOf(m);
    if (today !== context.day) {
      items.push(h("li", { class: "day" }, today === "undated" ? "No timestamp" : `${today} (UTC)`));
      Object.assign(context, { day: today, model: null });
    }
    const item = messageItem(m, tools, m.role === "assistant" && m.model !== context.model);
    item.dataset.i = m.i;
    items.push(item);
    if (m.role === "assistant") context.model = m.model;
  }
  return items;
}

const dayOf = (m) => (m.when ? m.when.toISOString().slice(0, 10) : "undated");

function itemContext(messages) {
  const context = { day: null, model: null };
  for (const m of messages) {
    if (dayOf(m) !== context.day) Object.assign(context, { day: dayOf(m), model: null });
    if (m.role === "assistant") context.model = m.model;
  }
  return context;
}

const ellipsis = (text, n) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);
const sourceOption = (s) => `${s.id === "main" ? "main" : `subagent ${s.id.slice(0, 8)}`} · ${ellipsis(String(s.task || ""), 60)}`;
const numbered = (m) => m.kind !== "tool_result" && m.role !== "event";
const visibleMessages = (messages) => messages.filter(numbered);

// Markdown, code highlighting and fonts may still change heights in the first frames, so the target is applied again
// until the page height settles.
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

// Keeps the message at the top of the screen in place; if it gets hidden, the next one shown takes its place.
function setLevel(level) {
  messagesState.level = level;
  try {
    localStorage.setItem(LEVEL_KEY, String(level));
  } catch (e) { /* the level then lasts for this page only */ }
  const name = $("level-name");
  if (name) name.textContent = LEVELS[level];
  const anchor = topMessage(), list = document.querySelector(".msgs");
  if (!list) return;
  list.className = `msgs lvl-${level}`;
  let el = anchor && anchor.el;
  while (el && !el.getClientRects().length) el = el.nextElementSibling;
  if (el) settleScroll(() => el.getBoundingClientRect().top + window.scrollY - anchor.offset);
}

// The first message shown at or after a log index, skipping those the current level hides.
function shownFrom(index) {
  for (const el of document.querySelectorAll(".msgs > li[data-i]")) {
    if (Number(el.dataset.i) >= index && el.getClientRects().length) return el;
  }
  return null;
}

const NEW_TOP_GAP = 8;
// A new message counts as read once its top reaches the upper part of the screen, not as soon as it peeks in at the bottom.
const READ_MARGIN = "0px 0px -40% 0px";

function readNew() {
  const el = messagesState.unread == null ? null : shownFrom(messagesState.unread);
  messagesState.unread = null;
  dropNewNotice();
  const below = () => document.querySelector(".appbar").getBoundingClientRect().bottom + NEW_TOP_GAP;
  if (el) settleScroll(() => el.getBoundingClientRect().top + window.scrollY - below());
}

function dropNewNotice() {
  const notice = $("new-messages");
  if (notice) {
    if (notice.observer) notice.observer.disconnect();
    notice.remove();
  }
}

// Shown near the bottom of the screen until the reader clicks it or scrolls the first new message into view.
function showNewNotice() {
  dropNewNotice();
  const first = shownFrom(messagesState.unread);
  if (!first) return;
  const count = [...document.querySelectorAll(".msgs > li[data-i]")]
    .filter((el) => Number(el.dataset.i) >= messagesState.unread && el.getClientRects().length).length;
  const notice = h("button", { class: "btn new-messages", id: "new-messages", type: "button", onclick: readNew },
    `↓ Read new messages (${fmt(count)})`);
  notice.observer = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) {
      messagesState.unread = null;
      dropNewNotice();
    }
  }, { rootMargin: READ_MARGIN });
  notice.observer.observe(first);
  $("main").append(notice);
}

function messagesPath(route) {
  if (messagesState.id !== route.id) Object.assign(messagesState, { id: route.id, source: "main", anchor: null, unread: null });
  return withSource("/messages", messagesState.source);
}

// ---------- composer: typing into the running session, as if in its terminal ----------
const STICK_MARGIN = 80;
const composer = { id: null, el: null, text: null, button: null, note: null, sending: false, sent: null, error: null };

const KEY_NOTES = {
  disabled: "Sending is disabled on this server.",
  missing: "To send messages from this browser, open once the link with ?key= that claude_tokens.py --serve printed.",
  wrong: "The saved send key is from an earlier run of the server: open the link with ?key= it printed this time.",
};

function composerNote(status) {
  if (status.live.read_only) return [`Read only: ${status.live.read_only_reason}`, "warn"];
  if (composer.error) return [composer.error, "error"];
  if (KEY_NOTES[status.key]) return [KEY_NOTES[status.key], "warn"];
  if (status.send_problem) return [status.send_problem, "warn"];
  const sent = composer.sent ? `Sent at ${utcTime(composer.sent)} UTC · ` : "";
  return [`${sent}Typed into the session's terminal · Enter sends, Shift+Enter adds a line`, ""];
}

function buildComposer(id) {
  const text = h("textarea", { id: "composer-text", rows: 2, placeholder: "Message to the running session", "aria-label": "Message to the running session",
    onkeydown: (e) => {
      if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
      e.preventDefault();
      sendMessage();
    },
    oninput: () => { composer.error = null; drawComposer(); } });
  const button = h("button", { class: "btn primary", type: "submit" }, "Send");
  const note = h("div", { class: "composer-note", "aria-live": "polite" });
  const working = h("div", { class: "composer-activity", hidden: true });
  const el = h("form", { class: "composer", id: "composer", onsubmit: (e) => { e.preventDefault(); sendMessage(); } },
    working, h("div", { class: "composer-row" }, text, button), note);
  Object.assign(composer, { id, el, text, button, note, working, sending: false, sent: null, error: null });
}

const canSend = (status) => !!(status && status.live && status.key === "ok" && !status.send_problem);
let focusComposerFor = null;

// Only on the Conversation tab of a live conversation; the same node keeps the draft across refreshes.
function drawComposer() {
  const route = app.route, status = route && liveStatus.get(route.id);
  if (!route || route.view !== "messages" || app.phase !== "ready" || !status || !status.live) {
    if (composer.el) composer.el.remove();
    return;
  }
  if (composer.id !== route.id) buildComposer(route.id);
  composer.text.disabled = !!status.live.read_only;
  composer.text.placeholder = status.live.read_only ? "Read only: this session cannot take messages" : "Message to the running session";
  composer.button.disabled = !canSend(status) || composer.sending || !composer.text.value.trim();
  composer.button.textContent = composer.sending ? "Sending…" : "Send";
  const busy = status.live.status === "busy";
  composer.working.hidden = !busy;
  composer.working.replaceChildren(h("span", { class: "spinner small", "aria-hidden": "true" }),
    busy && stream.id === route.id && stream.activity ? stream.activity : "Working…");
  const [message, tone] = composerNote(status);
  composer.note.textContent = message;
  composer.note.className = `composer-note ${tone}`;
  if (!composer.el.isConnected) $("main").append(composer.el);
  if (focusComposerFor === route.id && canSend(status)) {
    focusComposerFor = null;
    composer.text.focus();
  }
}

async function sendMessage() {
  const id = composer.id, text = composer.text.value, status = liveStatus.get(id);
  if (composer.sending || !text.trim() || !canSend(status)) return;
  Object.assign(composer, { sending: true, error: null });
  drawComposer();
  try {
    const data = await api(`/api/conversations/${encodeURIComponent(id)}/send`, { method: "POST",
      headers: { ...sendHeaders(), "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (composer.text.value === text) composer.text.value = "";
    composer.sent = new Date();
    liveStatus.set(id, { ...status, live: data.live });
  } catch (err) {
    composer.error = `Not sent: ${err.message}`;
    fetchLive(id);
  } finally {
    composer.sending = false;
    drawComposer();
  }
}

const atBottom = () => window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - STICK_MARGIN;

// ---------- real time: the server pushes what changed in the open conversation ----------
// log: the log grew, so the new messages are fetched and appended; live: the session's state; activity: its status line.
const stream = { id: null, source: null, es: null, opened: false, activity: null };
const tail = { busy: false, again: false };

function watchConversation() {
  const route = app.route;
  const id = (route && route.id) || null, source = route && route.view === "messages" ? messagesState.source : "main";
  if (stream.id === id && stream.source === source && (stream.es || !id)) return;
  if (stream.es) stream.es.close();
  Object.assign(stream, { id, source, es: null, opened: false, activity: null });
  if (!id || typeof EventSource === "undefined") return;
  const es = new EventSource(withSource(`/api/conversations/${encodeURIComponent(id)}/events`, source));
  stream.es = es;
  const mine = () => stream.es === es;
  // A reconnect (server restarted, laptop woke up) may have missed changes, so it catches up once.
  es.addEventListener("open", () => {
    if (mine() && stream.opened) logGrew();
    stream.opened = true;
  });
  es.addEventListener("log", () => { if (mine()) logGrew(); });
  es.addEventListener("live", (e) => { if (mine()) liveChanged(id, JSON.parse(e.data)); });
  es.addEventListener("activity", (e) => {
    if (!mine()) return;
    stream.activity = JSON.parse(e.data).text;
    drawComposer();
  });
}

function liveChanged(id, data) {
  const old = liveStatus.get(id) || { key: keyState };
  liveStatus.set(id, { ...old, live: data.live, send_problem: data.send_problem });
  if (!data.live) stream.activity = null;
  redrawConvHead(id);
  drawComposer();
}

function logGrew() {
  const route = app.route;
  if (!route || !route.id) return;
  // Other tabs reload when opened; the Conversation tab takes only what is new.
  const current = route.view === "messages" ? messagesPath(route) : null;
  for (const [path, entry] of convEntries(route.id)) if (path !== current) entry.stale = true;
  if (current) pullTail();
}

// One request at a time; changes that arrive meanwhile are fetched right after it.
async function pullTail() {
  if (tail.busy) {
    tail.again = true;
    return;
  }
  tail.busy = true;
  try {
    do {
      tail.again = false;
      await appendNew();
    } while (tail.again);
  } catch (err) {
    console.error(err);
  } finally {
    tail.busy = false;
  }
}

// The last response may still grow (each content block is written when it ends), so it is fetched again with what follows.
function tailStart(messages) {
  for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "assistant") return i;
  return messages.length;
}

async function appendNew() {
  const route = app.route, data = app.data;
  if (!route || route.view !== "messages" || app.phase !== "ready" || !data || !data.messages) return;
  const from = tailStart(data.messages);
  const query = `${data.source === "main" ? "" : `source=${encodeURIComponent(data.source)}&`}from=${from}`;
  const got = await api(`/api/conversations/${encodeURIComponent(route.id)}/messages?${query}`);
  if (app.route !== route || app.data !== data) return;
  if (got.total < from) {
    load({ refresh: true, revalidate: true });
    return;
  }
  patchMessages(route, data, from, got.messages);
}

// Replaces the messages from index from on, in the data and in the page, without drawing the rest again.
function patchMessages(route, data, from, fresh) {
  const before = data.messages.length;
  data.messages = data.messages.slice(0, from).concat(fresh);
  const list = document.querySelector(".msgs");
  if (noteConvData(route.id, "/messages", data)) drawConvNav();
  if (!list) {
    renderedBodies.delete(data);
    show({ keepScroll: true });
    return;
  }
  const stick = atBottom();
  const messages = prepared(data.messages), tools = toolsOf(messages), shown = shownOf(messages, tools);
  let node = [...list.children].find((el) => el.dataset.i != null && Number(el.dataset.i) >= from);
  if (node && node.previousElementSibling && node.previousElementSibling.classList.contains("day")) node = node.previousElementSibling;
  while (node) {
    const next = node.nextElementSibling;
    node.remove();
    node = next;
  }
  list.append(...messageItems(shown.filter((m) => m.i >= from), tools, itemContext(shown.filter((m) => m.i < from))));
  list.dataset.key = `${data.source}|${messages.length}`;
  const count = $("messages-count");
  if (count) count.textContent = countText(messages);
  if (stick) {
    messagesState.unread = null;
    dropNewNotice();
    scrollToEnd();
  } else if (messages.length > before && messagesState.unread == null) {
    messagesState.unread = before;
    requestAnimationFrame(showNewNotice);
  }
}

// Same numbering as the CLI: tool results are not counted, since they render under their call, nor are events.
function prepared(list) {
  let n = 0;
  return (list || []).map((m, i) => ({ ...m, blocks: m.blocks || [], i, n: numbered(m) ? ++n : null, when: parseStamp(m.timestamp) }));
}

function toolsOf(messages) {
  const tools = { results: new Map(), calls: toolCalls(messages) };
  for (const m of messages) for (const b of m.blocks) if (b.type === "tool_result") tools.results.set(b.tool_use_id, b);
  return tools;
}

const shownOf = (messages, tools) => messages.filter((m) => !(m.kind === "tool_result" && m.blocks.every((b) => tools.calls.has(b.tool_use_id))));

function countText(messages) {
  const responses = messages.filter((m) => m.role === "assistant");
  const cost = responses.reduce((sum, m) => sum + (m.estimated_cost_usd || 0), 0);
  return `${fmt(visibleMessages(messages).length)} messages · ${fmt(responses.length)} responses · `
    + money(cost, responses.some((m) => m.price_estimated));
}

VIEWS.messages = convView(messagesPath, {
  title: convTitle,
  load: (route, opts) => {
    // A fresh open starts at the latest message; a refresh keeps the reader where they are.
    if (!opts.refresh) Object.assign(messagesState, { toBottom: true, restore: false });
    return loadConversation(route, messagesPath(route), opts);
  },
  // Coming back from another tab reattaches the same nodes, so the anchor is still in the page; otherwise start at the end.
  enter: () => Object.assign(messagesState, { toBottom: true, restore: true }),
  leave: () => { messagesState.anchor = topMessage(); },
  render(data) {
    const messages = prepared(data.messages);
    // A refresh draws a new list over the one on screen: remember which message the reader was at, and what is new.
    const key = `${data.source}|${messages.length}`, old = document.querySelector(".msgs");
    const [oldSource, oldCount] = old && messagesState.id === app.route.id ? old.dataset.key.split("|") : [];
    if (oldSource === data.source) {
      const top = topMessage();
      messagesState.keep = top && top.el.dataset.i != null ? { i: Number(top.el.dataset.i), offset: top.offset } : null;
      if (messages.length > Number(oldCount) && messagesState.unread == null) messagesState.unread = Number(oldCount);
    }
    const tools = toolsOf(messages), shown = shownOf(messages, tools);
    const source = h("select", { id: "messages-source", "aria-label": "Source",
      onchange: (e) => { messagesState.source = e.target.value; load({ refresh: false }); } },
    (data.sources || []).map((s) => h("option", { value: s.id, selected: s.id === data.source }, sourceOption(s))));
    const toolbar = h("div", { class: "toolbar" },
      h("div", { class: "filters" }, h("label", { class: "field" }, "Source", source),
        h("button", { class: "btn", type: "button", onclick: () => window.scrollTo(0, 0) }, "↑ First"),
        h("button", { class: "btn", type: "button", onclick: scrollToEnd }, "↓ Last"),
        h("label", { class: "field level", title: "How much of the log is shown; remembered for every conversation" }, "Detail",
          h("input", { type: "range", min: 1, max: LEVELS.length - 1, step: 1, value: messagesState.level, autocomplete: "off",
            "aria-valuetext": LEVELS[messagesState.level],
            oninput: (e) => { setLevel(Number(e.target.value)); e.target.setAttribute("aria-valuetext", LEVELS[messagesState.level]); } }),
          h("span", { class: "level-name", id: "level-name" }, LEVELS[messagesState.level]))),
      h("span", { class: "count", id: "messages-count" }, countText(messages)));
    const meta = h("div", { class: "meta" }, "Every message in log order · token usage of each assistant response · times in UTC");
    if (!shown.length) return [meta, toolbar, emptyState("No messages", "This log has no user or assistant messages yet.")];
    return [meta, toolbar, h("ol", { class: `msgs lvl-${messagesState.level}`, "data-key": key }, messageItems(shown, tools, itemContext([])))];
  },
  after: () => {
    const { anchor, restore, toBottom, keep, unread } = messagesState;
    Object.assign(messagesState, { anchor: null, restore: false, toBottom: false, keep: null });
    drawComposer();
    const kept = keep && shownFrom(keep.i);
    if (kept) settleScroll(() => kept.getBoundingClientRect().top + window.scrollY - keep.offset);
    else if (restore && anchor && anchor.el.isConnected) settleScroll(() => anchor.el.getBoundingClientRect().top + window.scrollY - anchor.offset);
    else if (toBottom) scrollToEnd();
    if (unread != null) requestAnimationFrame(showNewNotice);
    // The log may have grown while this tab was hidden or loading.
    pullTail();
    return () => {
      dropNewNotice();
      if (composer.el) composer.el.remove();
    };
  },
});

// ---------- context breakdown (analysis.js) ----------
const CONTEXT_PARTS = {
  system: "System prompt, tools & setup", prompt: "User prompts", meta: "Injected context (skill output, subagent reports…)", summary: "Compaction summary",
  text: "Model text (Output)", tool_use: "Model tool calls", thinking: "Thinking", other: "Not in the log: loaded tools, attachments…", result: "Tool results",
};
const PART_SLOTS = { system: 7, prompt: 2, meta: 6, summary: 4, text: 1, tool_use: 5, thinking: 3, other: 7 };
const DETECT_SLICE_MS = 40;

const partLabel = (key) => (key.startsWith("result:") ? `Tool results · ${languageName(key.slice(7))}` : CONTEXT_PARTS[key] || key);

// Tool results share one hue, lighter as they shrink, so every language reads as part of the same group.
function partColors(rows) {
  const { palette, surface } = colorState, colors = {};
  let rank = 0;
  for (const r of rows) {
    if (r.key.startsWith("result")) colors[r.key] = mixHex(palette[0], surface, Math.min(0.75, 0.2 * rank++));
    else colors[r.key] = r.key === "other" ? mixHex(palette[7], surface, 0.5) : palette[PART_SLOTS[r.key]];
  }
  return colors;
}

// Detection runs in slices so that a long conversation does not freeze the page.
async function fillBreakdown(box, id, cancelled) {
  // Events are not messages sent to the model; mid-turn prompts and notices are, and count as prompts and injected context.
  const messages = ((await fetchConv(id, "/messages", false)).messages || []).filter((m) => m.role !== "event")
    .map((m) => (m.kind === "notification" ? { ...m, kind: "meta" } : m));
  const calls = toolCalls(messages);
  const languageOf = (b) => languageOfResult(b, calls.get(b.tool_use_id));
  let slice = performance.now();
  for (const m of messages) {
    for (const b of m.blocks) {
      if (b.type !== "tool_result") continue;
      languageOf(b);
      if (performance.now() - slice < DETECT_SLICE_MS) continue;
      await new Promise((resolve) => setTimeout(resolve));
      if (cancelled()) return;
      slice = performance.now();
    }
  }
  if (cancelled()) return;
  const keyOf = (m, b) => (b.type === "tool_result" ? (languageOf(b) ? `result:${languageOf(b)}` : "result") : m.kind);
  box.replaceChildren(...breakdownView(contextBreakdown(messages, keyOf)));
  box.dataset.done = "1";
}

function breakdownView(breakdown) {
  if (!breakdown) return [h("p", { class: "footnote" }, "No response with token usage to break down.")];
  const { context, rows } = breakdown, colors = partColors(rows);
  const share = (r) => r.tokens / context;
  const bar = h("div", { class: "stack", role: "img", "aria-label": "Context breakdown" }, rows.map((r) => h("i", {
    title: `${partLabel(r.key)}: ${fmt(r.tokens)} (${pct(share(r))})`, css: { width: `${share(r) * 100}%`, background: colors[r.key] } })));
  const table = renderTable([
    { key: "key", label: "Part", sortValue: (r) => partLabel(r.key),
      render: (r) => [h("span", { class: "sw", "aria-hidden": "true", css: { background: colors[r.key] } }), partLabel(r.key)] },
    { key: "tokens", label: "Tokens", num: true, render: (r) => fmt(r.tokens) },
    { key: "share", label: "Context", num: true, sortValue: share, render: (r) => pct(share(r)) },
  ], rows, { id: "report-breakdown", footer: ["Total", fmt(context), pct(1)] });
  return [bar, table, h("p", { class: "footnote" },
    "Each context grows by the previous output (thinking included) plus what arrived since: that growth is exact and is split "
    + "among the new blocks by characters, up to 1.5 tokens per character; the rest is context the log does not show (tools "
    + "loaded on demand, attachments, pasted images). The system prompt and tools are the first context minus its messages. "
    + "A result counts as code when the command read files of that language (or it is JSON, a diff or a script) and it reads "
    + "like it; anything else is plain text.")];
}

// ---------- totals (R5, R8) ----------
let totalsFilter = "";
let totalsDraft = "";

const hasGuessed = (T, day) => Object.keys(day.models || {}).some((m) => (T.guessed_price_models || []).includes(m));
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
      stat("Total cost", money(T.estimated_total_cost_usd, guessed), `${money(T.cost_per_conversation_usd, false)} per conversation`),
      stat("Tokens", fmt(T.total_tokens), `${fmt(T.output_tokens)} generated`),
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
        ? `Undated records (no timestamp, not plotted): ${money(undated.estimated_cost_usd, hasGuessed(T, undated))} · ${fmt(undated.total_tokens)} tokens`
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
      { key: "estimated_cost_usd", label: "Cost", num: true, render: (r) => money(r.estimated_cost_usd, r.price_estimated) },
      { key: "pct_cost", label: "% cost", num: true, render: (r) => pct(r.pct_cost) },
    ], T.by_model || [], { id: "totals-models", sortKey: "estimated_cost_usd" }));
    const projectTable = h("section", { class: "section" }, sectionHead("Projects by cost"), renderTable([
      pathCol("project", "Project", true),
      { key: "conversations", label: "Conversations", num: true, render: (r) => fmt(r.conversations) },
      { key: "total_tokens", label: "Total tokens", num: true, render: (r) => fmt(r.total_tokens) },
      { key: "estimated_cost_usd", label: "Cost", num: true, render: (r) => money(r.estimated_cost_usd, false) },
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
  // Chart.js groups thousands by browser locale; ticks use the same K/M/B units as the tables instead.
  const tickNum = fmt;
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
          return ` ${i.dataset.label}: ${entry && entry.estimated_cost_usd == null ? "N/D" : money(i.raw, guessed.has(i.dataset.label))}`;
        },
        footer: (items) => `Day total: ${money(days[items[0].dataIndex].estimated_cost_usd, hasGuessed(T, days[items[0].dataIndex]))}`,
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
    values: projects.map((p) => p.estimated_cost_usd), color: accent, format: (v) => money(v, false), title: "Cost (USD)",
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
  watchConversation();
  // Inputs are drawn anew and the composer's textarea is put back, so focus is lost either way.
  const again = focused && /^(INPUT|TEXTAREA)$/.test(focused.tagName) && document.activeElement !== focused ? $(focused.id) : null;
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
  if (route.id && !hit.stale) fetchLive(route.id);
}

function setAutoRefresh(on) {
  clearInterval(app.timer);
  app.timer = on ? setInterval(() => { if (!app.busy) load({ refresh: true }); }, 30000) : null;
}

function updateToTop() {
  $("to-top").hidden = window.scrollY < window.innerHeight;
}

function boot() {
  takeSendKey();
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
