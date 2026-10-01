import hashlib
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "ctokens" / "web" / "static"
VENDOR = STATIC / "vendor"
VENDORED = ["chart.umd.min.js", "marked.min.js", "purify.min.js", "highlight.min.js", "hljs-light.css", "hljs-dark.css"]


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
        served = {"/static/app.js", "/static/app.css", "#/", "#/totals", "data:,"} | {f"/static/vendor/{f}" for f in VENDORED}
        self.assertEqual(set(self.scan.refs) - served, set())
        for name in VENDORED + ["app.js", "app.css"]:
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
        source = (STATIC / "app.js").read_text(encoding="utf-8")
        for line in source.splitlines():
            if "innerHTML" in line:
                self.assertIn("DOMPurify.sanitize(", line)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_syntax(self):
        result = subprocess.run(["node", "--check", str(STATIC / "app.js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
