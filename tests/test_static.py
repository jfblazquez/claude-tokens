import hashlib
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "ctokens" / "web" / "static"
VENDOR = STATIC / "vendor"
VENDORED = ["chart.umd.min.js", "marked.min.js", "purify.min.js", "highlight.min.js", "hljs-light.css", "hljs-dark.css",
            "xterm.min.js", "xterm.css"]


class _Scan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline_scripts, self.style_attrs, self.style_tags, self.handlers, self.refs = 0, 0, 0, [], []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "style" in attrs:
            self.style_attrs += 1
        self.handlers += [name for name in attrs if name.startswith("on")]
        if tag == "style":
            self.style_tags += 1
        self._in_script = tag == "script"
        for name in ("src", "href"):
            if attrs.get(name):
                self.refs.append(attrs[name])

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script and data.strip():
            self.inline_scripts += 1


def versions():
    rows = {}
    for line in (VENDOR / "VERSIONS.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            fields = line.split("  ")
            rows[fields[0]] = fields
    return rows


class IndexHtmlTest(unittest.TestCase):
    """The page must work under the 'self'-only CSP (design §5.2, ADR 0002)."""

    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.scan = _Scan()
        cls.scan.feed(cls.html)

    def test_no_absolute_urls(self):
        self.assertIsNone(re.search(r"https?://", self.html, re.IGNORECASE))

    def test_no_inline_script_or_style(self):
        self.assertEqual(self.scan.inline_scripts, 0)
        self.assertEqual(self.scan.style_tags, 0)
        self.assertEqual(self.scan.style_attrs, 0)
        self.assertEqual(self.scan.handlers, [])

    def test_references_only_served_files(self):
        served = {"/static/app.js", "/static/analysis.js", "/static/panels.js", "/static/app.css", "#/", "#/totals", "data:,"} | {f"/static/vendor/{f}" for f in VENDORED}
        self.assertEqual(set(self.scan.refs) - served, set())
        for name in VENDORED + ["analysis.js", "panels.js", "app.js", "app.css"]:
            self.assertIn(name, self.html)


class VendorTest(unittest.TestCase):
    def test_every_served_file_is_recorded(self):
        self.assertEqual(set(VENDORED) - set(versions()), set())

    def test_recorded_files_match_their_hash(self):
        for name, fields in versions().items():
            with self.subTest(file=name):
                data = (VENDOR / name).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), fields[4])

    def test_chart_js_needs_no_inline_styles(self):
        source = (VENDOR / "chart.umd.min.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"createElement\(\s*[\"'`]style[\"'`]\s*\)", source))
        self.assertIsNone(re.search(r"setAttribute\(\s*[\"'`]style[\"'`]", source))


class AppJsTest(unittest.TestCase):
    def test_innerhtml_only_with_dompurify(self):
        source = "\n".join((STATIC / name).read_text(encoding="utf-8") for name in ("panels.js", "app.js"))
        for line in source.splitlines():
            if "innerHTML" in line:
                self.assertIn("DOMPurify.sanitize(", line)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_syntax(self):
        # Both run as classic scripts in one global scope, so a name declared twice breaks the page.
        source = "\n".join((STATIC / name).read_text(encoding="utf-8") for name in ("analysis.js", "panels.js", "app.js"))
        result = subprocess.run(["node", "--check"], input=source, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


ANALYSIS_CHECKS = r"""
const fs = require("fs"), assert = require("assert");
const [vendor, analysis] = process.argv.slice(1);
const hljs = new Function(fs.readFileSync(vendor, "utf8") + "; return hljs;")();
const A = require(analysis);

assert.strictEqual(A.languageOfPath(hljs, "src/a/Thing.hpp"), "cpp");
assert.strictEqual(A.languageOfPath(hljs, "Thing.h"), "cpp");
assert.strictEqual(A.languageOfPath(hljs, "build/Makefile"), "makefile");
assert.strictEqual(A.languageOfPath(hljs, "notes.txt"), "plaintext");
assert.strictEqual(A.languageOfPath(hljs, "LICENSE"), null);
assert.deepStrictEqual(A.pathLanguages(hljs, "cat a.cpp /opt/b.cpp x.py Makefile && ls"), ["cpp", "python", "makefile"]);
// Only the files a command reads count: not what it runs, edits or writes.
assert.deepStrictEqual(A.readLanguages(hljs, "./build.sh && python3 run.py; sed -i 's/a/b/' x.go; cat > y.md <<EOF"), []);
assert.deepStrictEqual(A.readLanguages(hljs, "f=src/Db.cpp; awk 'NR>1 && NR<9' \"$f\" | rg -n 'a|b'"), ["cpp"]);

const call = (name, fields) => ({ type: "tool_use", id: name, name,
  input: Object.entries(fields).map(([n, text]) => ({ name: n, text, size: text.length })) });
const result = (text, extra = {}) => ({ type: "tool_result", tool_use_id: "t", text, size: text.length, is_error: false, ...extra });
const bash = (command, output) => A.resultLanguage(hljs, result(output), call("Bash", { command }));
const cpp = "bool CDb::Find(const char *name)\n{\n\tstd::string key(name);\n\treturn m_users.find(key) != m_users.end();\n}";
const grep = cpp.split("\n").map((line, i) => `abc123:src/Db.cpp:${40 + i}:${line}`).join("\n");
assert.strictEqual(bash("git grep -n users", grep), "cpp");
assert.strictEqual(bash("f=src/Db.cpp; sed -n 40,44p \"$f\"", cpp), "cpp");
assert.strictEqual(bash("make -C src Db.cpp", cpp), "plaintext");
assert.strictEqual(bash("cat -n run", "     1\t#!/usr/bin/env bash\n     2\techo hi"), "bash");
assert.strictEqual(bash("diff a b", "3c3\n< int a;\n---\n> int b;"), "diff");
assert.strictEqual(bash("git show HEAD -- src/Db.cpp", "commit 0123456789abcdef\nAuthor: A <a@b>\n\n    Fix it"), "plaintext");
assert.strictEqual(bash("git log --oneline -- src/Db.cpp", "ab12cd3 Fix the cache\n98fe76a Merge develop"), "plaintext");
assert.strictEqual(A.resultLanguage(hljs, result('{"issues": {"nodes": [{"key": 1'), call("mcp__jira", {})), "json");
assert.strictEqual(A.resultLanguage(hljs, result("1\tdef f():\n2\t    return 1\n"), call("Read", { file_path: "a.py" })), "python");
assert.strictEqual(A.resultLanguage(hljs, result("[image]"), call("Read", { file_path: "a.png" })), "image");
assert.strictEqual(A.resultLanguage(hljs, result("boom", { is_error: true }), call("Bash", { command: "x" })), "plaintext");
assert.strictEqual(A.resultLanguage(hljs, result("  \n"), call("Bash", { command: "true" })), null);
assert.strictEqual(A.inputLanguage(hljs, call("Bash", { command: "ls" }), "command"), "bash");
assert.strictEqual(A.inputLanguage(hljs, call("Write", { file_path: "a.rs", content: "" }), "content"), "rust");
assert.strictEqual(A.inputLanguage(hljs, call("Write", { file_path: "a.rs", content: "" }), "file_path"), null);

const usage = (context, output, thinking = null) => ({ context, output, thinking });
const text = (n, c = "x") => ({ type: "text", text: c.repeat(n) });
const parts = (messages, keyOf) => Object.fromEntries(A.contextBreakdown(messages, keyOf).rows.map((r) => [r.key, Math.round(r.tokens)]));
const keyOf = (m, b) => (b.type === "tool_result" ? (b.text === "[image]" ? "result:image" : "result:cpp") : m.kind);

// Contexts 1000 -> 1500 -> 2000: the second grows by output 100 (40 thinking) + a 400-token result, the third by 50 + 450.
const messages = [
  { role: "user", kind: "prompt", blocks: [text(100)] },
  { role: "assistant", kind: "response", usage: usage(1000, 100, 40), blocks: [call("Bash", { command: "y".repeat(60) })] },
  { role: "user", kind: "tool_result", blocks: [result("z".repeat(800), { tool_use_id: "a" })] },
  { role: "assistant", kind: "response", usage: usage(1500, 50), blocks: [{ type: "text", text: "Done" }] },
  { role: "assistant", kind: "error", usage: usage(0, 0), blocks: [{ type: "text", text: "API Error" }] },
  { role: "user", kind: "prompt", blocks: [text(400)] },
  { role: "assistant", kind: "response", usage: usage(2000, 10), blocks: [] },
];
assert.strictEqual(A.contextBreakdown(messages, keyOf).context, 2000);
// Gap rates 0.5 and 1.125 tokens/char; the first prompt is estimated at the median one, the rest of 1000 is the system prompt.
assert.deepStrictEqual(parts(messages, keyOf), { system: 888, prompt: 563, "result:cpp": 400, thinking: 40, tool_use: 60, text: 50 });
assert.strictEqual(A.contextBreakdown([messages[0]], keyOf), null);

// Growth far beyond its text is context the log does not show; an image takes what the text with it does not explain.
const swollen = [{ role: "user", kind: "prompt", blocks: [text(10)] }, { role: "assistant", usage: usage(1000, 0), blocks: [] },
  { role: "user", kind: "prompt", blocks: [text(100)] }, { role: "assistant", usage: usage(3000, 0), blocks: [] }];
assert.deepStrictEqual(parts(swollen, keyOf), { system: 997, other: 1650, prompt: 353 });
const image = [{ role: "user", kind: "prompt", blocks: [text(10)] }, { role: "assistant", usage: usage(1000, 0), blocks: [] },
  { role: "user", kind: "tool_result", blocks: [result("[image]"), result("y".repeat(100))] },
  { role: "assistant", usage: usage(2500, 0), blocks: [] }];
assert.deepStrictEqual(parts(image, keyOf), { system: 997, "result:image": 1470, "result:cpp": 30, prompt: 3 });
const pasted = [{ role: "user", kind: "prompt", blocks: [text(10)] }, { role: "assistant", usage: usage(1000, 0), blocks: [] },
  { role: "user", kind: "prompt", blocks: [{ type: "image", media_type: "image/png", bytes: 9000 }, text(100)] },
  { role: "assistant", usage: usage(2500, 0), blocks: [] }];
assert.deepStrictEqual(parts(pasted, keyOf), { prompt: 1503, system: 997 });

// A compaction summary starts the context over.
const compacted = [...messages, { role: "user", kind: "summary", blocks: [text(200, "s")] },
  { role: "assistant", kind: "response", usage: usage(700, 10), blocks: [] }];
const after = parts(compacted, keyOf);
assert.deepStrictEqual(Object.keys(after).sort(), ["summary", "system"]);
assert.strictEqual(after.summary + after.system, 700);
"""


class AnalysisJsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_language_detection_and_context_breakdown(self):
        result = subprocess.run(["node", "-e", ANALYSIS_CHECKS, str(VENDOR / "highlight.min.js"), str(STATIC / "analysis.js")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
