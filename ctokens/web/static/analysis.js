"use strict";

// ---------- language detection and context breakdown: no DOM, so node tests can load them ----------

// highlight.js aliases .h to C; in C++ code bases headers are C++, and both highlight the same.
const EXTENSION_LANGUAGES = { h: "cpp", txt: "plaintext", log: "plaintext" };
const DETECT_SAMPLE = 1500;
// highlight.js relevance a text needs to be taken for the language of the files it comes from; "path:line:" prefixes also
// come from compiler and test errors, so they need more.
const READ_RELEVANCE = 2;
const PREFIX_RELEVANCE = 5;
const PATH_RE = /(?:^|[\s:'"=(<])(?:[\w.+@~-]*\/)*((?:GNU)?[Mm]akefile|[\w+-]+\.[A-Za-z][A-Za-z0-9+]{0,9})(?=$|[\s:'")\],;>])/gm;
// grep and Read prefixes: "rev:path:12:", "path:12:", "12:", "12\t", "   12\t" (cat -n).
const LINE_PREFIX_RE = /^[ \t]*(?:[^\s:]+:){0,2}\d+[:\t-]/gm;
const GREP_PATH_RE = /^(?:[^\s:]+:)?([^\s:]+):\d+[:-]/gm;
// Commands whose output is the text of the files they name.
const READER_RE = /^(?:sudo\s+)?(?:cat|head|tail|sed(?!\s+-i)|nl|bat|less|more|grep|egrep|rg|awk|git\s+(?:show|grep|blame))\b/;
const REDIRECT_RE = />>?\s*\S+/g;
const QUOTED_RE = /'[^']*'|"[^"]*"/g;
const ASSIGNMENT_RE = /(?:^|[\s;&])([A-Za-z_]\w*)=(["']?)([^\s"';&|]+)\2/g;
const ANSI_RE = /\x1b\[[0-9;]*[A-Za-z]/g;
// Unified diffs, and the classic "12,14c12" format of plain diff.
const DIFF_RE = /^(diff --git |--- \S.*\n\+\+\+ \S|\d+(,\d+)?[acd]\d+(,\d+)?\n[<>] )/m;
const GIT_COMMIT_RE = /^commit [0-9a-f]{7,40}\b/;
const SHEBANG_RE = /^\s*#!\s*\S*\/(?:env\s+)?([a-z]+)/;
const XML_RE = /^\s*<(?:\?xml|!DOCTYPE|html|testsuites?)\b/i;
// Tool results that are only "[image]" or "[document]" placeholders: their tokens are not in the log.
const MEDIA_RE = /^\s*\[(image|document)\](\s*\[(image|document)\])*\s*$/;
const FILE_TOOLS = new Set(["Read", "Write", "Edit", "MultiEdit", "NotebookEdit"]);
const CODE_FIELDS = new Set(["content", "old_string", "new_string"]);

const languageKeys = new WeakMap();

// Canonical highlight.js key ("cpp") of a name or alias ("hpp", "c++"); null when not registered.
function languageKey(hljs, name) {
  if (!name) return null;
  if (!languageKeys.has(hljs)) {
    languageKeys.set(hljs, new Map(hljs.listLanguages().map((key) => [hljs.getLanguage(key), key])));
  }
  return languageKeys.get(hljs).get(hljs.getLanguage(name)) || null;
}

function languageOfPath(hljs, path) {
  const base = String(path || "").split("/").pop();
  if (/^(GNU)?makefile$/i.test(base)) return "makefile";
  const ext = (base.match(/\.([^.]+)$/) || [])[1];
  if (!ext) return null;
  const lower = ext.toLowerCase();
  return EXTENSION_LANGUAGES[lower] || languageKey(hljs, lower);
}

function countLanguages(hljs, paths) {
  const counts = new Map();
  for (const path of paths) {
    const lang = languageOfPath(hljs, path);
    if (lang && lang !== "plaintext") counts.set(lang, (counts.get(lang) || 0) + 1);
  }
  return [...counts].sort((a, b) => b[1] - a[1]).map(([lang]) => lang);
}

const pathLanguages = (hljs, text) => countLanguages(hljs, [...String(text || "").matchAll(PATH_RE)].map((m) => m[1]));

// Variables set in the command itself (f=src/a.cpp; sed -n 1,9p "$f") are expanded first.
function expandVariables(command) {
  const values = new Map([...command.matchAll(ASSIGNMENT_RE)].map((m) => [m[1], m[3]]));
  return values.size ? command.replace(/\$\{?([A-Za-z_]\w*)\}?/g, (all, name) => values.get(name) ?? all) : command;
}

function readLanguages(hljs, command) {
  // Quoted patterns (rg 'a|b', awk '... && ...') would split a command in the wrong place.
  const readers = expandVariables(String(command || "")).replace(QUOTED_RE, (quoted) => quoted.replace(/[|&;\n]/g, " ")).split(/\|\||&&|[;|\n]/).map((part) => part.trim()).filter((part) => READER_RE.test(part))
    .map((part) => part.replace(REDIRECT_RE, ""));
  return pathLanguages(hljs, readers.join("\n"));
}

// Clipped JSON no longer parses, so an opening object or array of objects is enough.
const looksJson = (text) => /^\s*(\{\s*"|\[\s*[{\["])/.test(text) || (() => {
  try { return typeof JSON.parse(text) === "object"; } catch (_) { return false; }
})();

function interpreterLanguage(hljs, sample) {
  const name = (sample.match(SHEBANG_RE) || [])[1];
  return name ? languageKey(hljs, name.replace(/\d+$/, "")) : null;
}

// Without its own markers, a text is only taken for code when a file it comes from says which language and it reads like it:
// highlight.js guessing alone, or the files a command merely mentions, take logs for Python and git output for C++.
// hints: [{ lang, min }], min being the relevance the text needs to be taken for lang.
function detectLanguage(hljs, text, hints = []) {
  if (!String(text || "").trim()) return null;
  if (looksJson(text)) return "json";
  const head = text.slice(0, DETECT_SAMPLE);
  if (DIFF_RE.test(head)) return "diff";
  if (GIT_COMMIT_RE.test(head)) return "plaintext";
  const sample = head.replace(ANSI_RE, "").replace(LINE_PREFIX_RE, "");
  const interpreter = interpreterLanguage(hljs, sample);
  if (interpreter) return interpreter;
  if (XML_RE.test(sample)) return "xml";
  const hint = hints.find(({ lang, min }) => hljs.getLanguage(lang)
    && hljs.highlight(sample, { language: lang, ignoreIllegals: true }).relevance >= min);
  return hint ? hint.lang : "plaintext";
}

const inputValue = (call, name) => ((call && call.input) || []).find((f) => f.name === name);
const inputText = (call, name) => (inputValue(call, name) || {}).text || "";

// The language of a tool input field, when it holds code: Bash commands and the text Write/Edit put in a file.
function inputLanguage(hljs, call, field) {
  if (call.name === "Bash" && field === "command") return "bash";
  if (FILE_TOOLS.has(call.name) && CODE_FIELDS.has(field)) return languageOfPath(hljs, inputText(call, "file_path"));
  return null;
}

function resultHints(hljs, result, call) {
  const read = readLanguages(hljs, inputText(call, "command"));
  const prefixed = countLanguages(hljs, [...result.text.slice(0, DETECT_SAMPLE).matchAll(GREP_PATH_RE)].map((m) => m[1]));
  return [...read.map((lang) => ({ lang, min: READ_RELEVANCE })),
    ...prefixed.filter((lang) => !read.includes(lang)).map((lang) => ({ lang, min: PREFIX_RELEVANCE }))];
}

// A Read result takes the language of its file; any other result is detected.
function resultLanguage(hljs, result, call) {
  if (!result || result.is_error) return result && String(result.text || "").trim() ? "plaintext" : null;
  const media = String(result.text || "").match(MEDIA_RE);
  if (media) return media[1];
  if (call && call.name === "Read") {
    const known = languageOfPath(hljs, inputText(call, "file_path"));
    if (known) return known;
  }
  return detectLanguage(hljs, result.text, resultHints(hljs, result, call));
}

// ---------- context breakdown ----------
// Context growth = previous output (thinking stays in context) + the blocks that arrived since; only its split is estimated.
const DEFAULT_TOKENS_PER_CHAR = 0.3;
const MIN_RATE_CHARS = 200;
// Dense code stays under 1 token per character; growth beyond this cap (plus some message framing) is context the log does not
// show: tools loaded on demand, attachments, reminders, pasted images.
const MAX_TOKENS_PER_CHAR = 1.5;
const GAP_FRAMING = 200;

const blockChars = (b) => (b.size != null ? b.size : String(b.text || "").length);
const callChars = (b) => (b.input || []).reduce((sum, f) => sum + blockChars(f), 0);

// keyOf(message, block) names the category of a user-side block, e.g. "prompt" or "result:cpp".
function userItems(m, keyOf) {
  return (m.blocks || []).map((b) => ({ key: keyOf(m, b), chars: blockChars(b), media: MEDIA_RE.test(String(b.text || "")) }));
}

function outputItems(m) {
  return (m.blocks || []).flatMap((b) => {
    if (b.type === "text") return [{ key: "text", chars: blockChars(b) }];
    if (b.type === "tool_use") return [{ key: "tool_use", chars: callChars(b) }];
    return [];
  });
}

function spread(comp, items, tokens, fallback) {
  const chars = items.reduce((sum, i) => sum + i.chars, 0);
  if (!chars) {
    if (tokens) comp.set(fallback, (comp.get(fallback) || 0) + tokens);
    return;
  }
  for (const i of items) comp.set(i.key, (comp.get(i.key) || 0) + tokens * i.chars / chars);
}

// Media take whatever the text that arrived with them does not explain; text alone is capped and the rest is "other".
function spreadGap(comp, gap, fresh, rate) {
  const media = gap.filter((i) => i.media), text = gap.filter((i) => !i.media);
  const textChars = text.reduce((sum, i) => sum + i.chars, 0);
  if (media.length) {
    const visible = Math.min(fresh, textChars * rate);
    spread(comp, text, visible, "other");
    spread(comp, media.map((i) => ({ ...i, chars: 1 })), fresh - visible, "other");
    return;
  }
  const visible = Math.min(fresh, textChars * MAX_TOKENS_PER_CHAR + (textChars ? GAP_FRAMING : 0));
  spread(comp, text, visible, "other");
  if (fresh > visible) comp.set("other", (comp.get("other") || 0) + fresh - visible);
}

function scale(comp, factor) {
  for (const [key, tokens] of comp) comp.set(key, tokens * factor);
}

// Walks the responses that carry usage; step(prev, response, gap, reset) sees each one with the user-side blocks before it.
function walkResponses(messages, keyOf, step) {
  let prev = null, gap = [], reset = false;
  for (const m of messages) {
    if (m.role !== "assistant") {
      gap.push(...userItems(m, keyOf));
      reset = reset || m.kind === "summary";
    } else if (m.usage && m.usage.context > 0) {
      step(prev, m, gap, reset || !prev);
      prev = m;
      gap = [];
      reset = false;
    }
  }
  return prev;
}

// The median gap, so that the few gaps swollen by context the log does not show do not skew it.
function tokensPerChar(messages, keyOf) {
  const rates = [];
  walkResponses(messages, keyOf, (prev, m, gap, reset) => {
    const gapChars = gap.reduce((sum, i) => sum + i.chars, 0);
    const fresh = reset ? -1 : m.usage.context - prev.usage.context - prev.usage.output;
    if (fresh > 0 && gapChars >= MIN_RATE_CHARS && !gap.some((i) => i.media)) rates.push(fresh / gapChars);
  });
  rates.sort((a, b) => a - b);
  return rates.length ? rates[Math.floor(rates.length / 2)] : DEFAULT_TOKENS_PER_CHAR;
}

// Token estimate per category in the context of the last response with usage: { context, rows: [{ key, tokens }] }, or null.
function contextBreakdown(messages, keyOf) {
  const rate = tokensPerChar(messages, keyOf);
  let comp = new Map();
  const last = walkResponses(messages, keyOf, (prev, m, gap, reset) => {
    const context = m.usage.context;
    const estimate = (items) => items.reduce((sum, i) => sum + i.chars * rate, 0);
    if (reset) {
      comp = new Map();
      const visible = Math.min(context, estimate(gap));
      spread(comp, gap, visible, "other");
      comp.set("system", context - visible);
      return;
    }
    const thinking = Math.min(prev.usage.thinking || 0, prev.usage.output);
    if (thinking) comp.set("thinking", (comp.get("thinking") || 0) + thinking);
    spread(comp, outputItems(prev), prev.usage.output - thinking, "text");
    const fresh = context - prev.usage.context - prev.usage.output;
    if (fresh >= 0) {
      spreadGap(comp, gap, fresh, rate);
      return;
    }
    // The context shrank (cleared tool results, a compaction without its summary): keep the proportions.
    spread(comp, gap, estimate(gap), "other");
    const total = [...comp.values()].reduce((sum, t) => sum + t, 0);
    if (total > 0) scale(comp, context / total);
  });
  if (!last) return null;
  const rows = [...comp].filter(([, tokens]) => tokens >= 0.5).map(([key, tokens]) => ({ key, tokens }))
    .sort((a, b) => b.tokens - a.tokens);
  return { context: last.usage.context, rows };
}

if (typeof module !== "undefined") {
  module.exports = { languageOfPath, pathLanguages, readLanguages, detectLanguage, inputLanguage, resultLanguage, contextBreakdown };
}
