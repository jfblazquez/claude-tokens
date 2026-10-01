import contextlib
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from characterization import DATA, ENV, SCRIPT
from fixtures import AMBIGUOUS, CONV_A, CONV_B, CONV_EMPTY, ROOT, build_projects

from ctokens.catalog import conversation_rows
from ctokens.pricing import load_prices
from ctokens.reports import scan_totals, totals_report
from ctokens.web.server import CSP, STATIC_FILES, Config, Handler, Server

DEFAULT_HOST = object()


def start_server(config, static_dir=None):
    server = Server(config, 0, **({"static_dir": static_dir} if static_dir else {}))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(10)


def write_static(root):
    """Placeholder files for the fixed static map plus files that must never be served."""
    for name in STATIC_FILES.values():
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"/* {name} */", encoding="utf-8")
    (Path(root) / "secret.txt").write_text("secret", encoding="utf-8")
    (Path(root) / "vendor" / "VERSIONS.txt").write_text("versions", encoding="utf-8")
    return Path(root)


def http_request(port, path, method="GET", host=DEFAULT_HOST, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        if host is DEFAULT_HOST:
            host = f"127.0.0.1:{port}"
        if host is not None:
            connection.putheader("Host", host)
        if body is not None:
            connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body)
        response = connection.getresponse()
        return response.status, response.headers, response.read()
    finally:
        connection.close()


def get_json(port, path):
    status, _, body = http_request(port, path)
    return status, json.loads(body.decode("utf-8"))


class ServerTestCase(unittest.TestCase):
    """Real server on a free port in a thread, fixtures in a temporary projects folder."""

    @classmethod
    def setUpClass(cls):
        cls.quiet = mock.patch.object(Handler, "log_message", lambda *args: None)
        cls.quiet.start()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.projects = build_projects(cls.tmp.name)
        cls.static = write_static(Path(cls.tmp.name) / "static")
        cls.server, cls.thread = start_server(Config(cls.projects, load_prices(None)), cls.static)
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.server, cls.thread)
        cls.tmp.cleanup()
        cls.quiet.stop()

    def request(self, path, method="GET", host=DEFAULT_HOST, body=None, port=None):
        return http_request(port or self.port, path, method, host, body)

    def get_json(self, path, port=None):
        status, headers, body = self.request(path, port=port)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        return status, json.loads(body.decode("utf-8"))


class SecurityGateTest(ServerTestCase):
    def test_bad_host(self):
        for host in ("evil.example", "evil.example:8765", "127.0.0.2", "localhost.evil.example", "[::1]:8765",
                     "localhost:abc", "localhost:", ""):
            with self.subTest(host=host):
                status, headers, body = self.request("/", host=host)
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(body), {"error": "host not allowed"})
                self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")

    def test_no_host(self):
        status, _, body = self.request("/api/conversations", host=None)
        self.assertEqual((status, json.loads(body)), (403, {"error": "host not allowed"}))

    def test_bad_host_reads_no_conversation(self):
        with mock.patch("ctokens.catalog.lines", side_effect=AssertionError("read a log")) as lines:
            status, _, _ = self.request("/api/conversations", host="evil.example")
        self.assertEqual(status, 403)
        lines.assert_not_called()

    def test_allowed_hosts_any_port(self):
        for host in ("localhost:9000", "localhost", "127.0.0.1", "LOCALHOST:1", f"127.0.0.1:{self.port}"):
            with self.subTest(host=host):
                self.assertEqual(self.request("/", host=host)[0], 200)

    def test_other_methods(self):
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "CONNECT", "FOO", "do_GET"):
            with self.subTest(method=method):
                status, headers, body = self.request("/api/conversations", method=method, body=b"x=1")
                self.assertEqual(status, 405)
                self.assertEqual(headers["Allow"], "GET, HEAD")
                self.assertEqual(json.loads(body), {"error": "method not allowed"})

    def test_bad_host_wins_over_method(self):
        self.assertEqual(self.request("/", method="POST", host="evil.example", body=b"")[0], 403)

    def test_unknown_paths(self):
        for path in ("/nope", "/index.html", "/static/", "/static/secret.txt", "/static/vendor/VERSIONS.txt",
                     "/static/../secret.txt", "/static/%2e%2e/secret.txt", "/static/vendor/../app.js",
                     "/static/app.js/", "/api", "/api/", "/api/totals/", "/api/conversations/",
                     "http://127.0.0.1/static/app.js", "*"):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 404)
                self.assertEqual(json.loads(body), {"error": "not found"})

    def test_common_headers(self):
        for path, method in (("/", "GET"), ("/static/app.js", "GET"), ("/nope", "GET"), ("/", "POST"),
                             ("/", "HEAD")):
            with self.subTest(path=path, method=method):
                _, headers, _ = self.request(path, method=method)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        _, headers, _ = self.request("/", host="evil.example")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_csp_on_html_only(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(headers["Content-Security-Policy"], CSP)
        for directive in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "object-src 'none'",
                          "base-uri 'none'", "frame-ancestors 'none'"):
            self.assertIn(directive, headers["Content-Security-Policy"])
        self.assertNotIn("http", CSP)
        self.assertIsNone(self.request("/static/app.js")[1]["Content-Security-Policy"])

    def test_head_has_no_body(self):
        status, headers, body = self.request("/", method="HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(headers["Content-Length"], str(len((self.static / "index.html").read_bytes())))

    def test_malformed_request_is_json(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=30) as raw:
            raw.sendall(b"GET / extra HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            data = b""
            while chunk := raw.recv(65536):
                data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.0 400 "), head)
        self.assertIn(b"Content-Type: application/json; charset=utf-8", head)
        self.assertIn("error", json.loads(body))


class StaticFilesTest(ServerTestCase):
    def test_fixed_map(self):
        types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}
        self.assertEqual(sorted(STATIC_FILES), sorted([
            "/", "/static/app.js", "/static/app.css", "/static/vendor/chart.umd.min.js",
            "/static/vendor/marked.min.js", "/static/vendor/purify.min.js", "/static/vendor/highlight.min.js",
            "/static/vendor/hljs-light.css", "/static/vendor/hljs-dark.css"]))
        for route, name in STATIC_FILES.items():
            with self.subTest(route=route):
                status, headers, body = self.request(route)
                self.assertEqual(status, 200)
                self.assertEqual(body, (self.static / name).read_bytes())
                self.assertEqual(headers["Content-Type"], types[Path(name).suffix])

    def test_missing_file_is_404(self):
        missing = Path(self.tmp.name) / "missing-static"
        missing.mkdir()
        server, thread = start_server(Config(self.projects, load_prices(None)), missing)
        try:
            status, _, body = self.request("/static/app.js", port=server.server_address[1])
        finally:
            stop_server(server, thread)
        self.assertEqual((status, json.loads(body)), (404, {"error": "not found"}))


def cli_json(*args):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    env.update(ENV)
    done = subprocess.run([sys.executable, str(SCRIPT), *args], stdin=subprocess.DEVNULL, capture_output=True,
                          env=env, cwd=str(ROOT), timeout=60)
    if done.returncode:
        raise AssertionError(done.stderr.decode("utf-8"))
    return json.loads(done.stdout.decode("utf-8"))


BAD_IDS = ("../x", "..%2f..%2fetc%2fpasswd", "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "%2Fetc%2Fpasswd", "*", "%2A",
           CONV_A.replace("1", "A", 1), CONV_A[:-1], CONV_A + ".jsonl", CONV_A + "%00", "%31" + CONV_A[1:],
           "99999999-9999-4999-8999-999999999999")


class ApiParityTest(ServerTestCase):
    """Every route returns the same JSON as the matching CLI --json run (D-005)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.custom_args = ("--pricing", str(DATA / "pricing.json"), "--cold-summary-output", "500",
                           "--context-window", "1000000")
        config = Config(cls.projects, load_prices(DATA / "pricing.json"), 500, 1000000)
        cls.custom, cls.custom_thread = start_server(config)

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.custom, cls.custom_thread)
        super().tearDownClass()

    def assert_parity(self, route, *cli_args, port=None, custom=False):
        status, data = self.get_json(route, port=self.custom.server_address[1] if custom else port)
        self.assertEqual(status, 200)
        extra = self.custom_args if custom else ()
        self.assertEqual(data, cli_json(*cli_args, "--projects-dir", str(self.projects), *extra))

    def test_report(self):
        for conversation in (CONV_A, CONV_B, CONV_EMPTY):
            with self.subTest(conversation=conversation):
                self.assert_parity(f"/api/conversations/{conversation}", conversation, "--json")

    def test_report_with_options(self):
        for conversation in (CONV_A, CONV_B):
            with self.subTest(conversation=conversation):
                self.assert_parity(f"/api/conversations/{conversation}", conversation, "--json", custom=True)

    def test_content_views(self):
        for conversation in (CONV_A, CONV_B, CONV_EMPTY):
            for view, flag in (("last-response", "--last-response"), ("bash", "--bash"), ("files", "--files")):
                with self.subTest(conversation=conversation, view=view):
                    self.assert_parity(f"/api/conversations/{conversation}/{view}", conversation, flag, "--json")

    def test_totals(self):
        self.assert_parity("/api/totals", "--totals", "--json")
        self.assert_parity("/api/totals?project=billing", "--totals", "--json", "--project", "billing")
        self.assert_parity("/api/totals?project=BILLING&ignored=1", "--totals", "--json", "--project", "billing")
        self.assert_parity("/api/totals", "--totals", "--json", custom=True)

    def test_conversations(self):
        status, data = self.get_json("/api/conversations")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"projects_dir": str(self.projects), "conversations": conversation_rows(self.projects)})
        self.assertEqual([row["id"] for row in data["conversations"]],
                         [CONV_A, CONV_B, AMBIGUOUS, AMBIGUOUS, CONV_EMPTY])

    def test_conversations_filter(self):
        _, data = self.get_json("/api/conversations?project=Billing&x=y")
        self.assertEqual([row["id"] for row in data["conversations"]], [CONV_B, AMBIGUOUS])
        _, data = self.get_json("/api/conversations?project=")
        self.assertEqual(len(data["conversations"]), 5)
        _, data = self.get_json("/api/conversations?project=nothing-matches")
        self.assertEqual(data["conversations"], [])

    def test_head(self):
        status, headers, body = self.request(f"/api/conversations/{CONV_A}", method="HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertGreater(int(headers["Content-Length"]), 0)


class ApiErrorsTest(ServerTestCase):
    def test_bad_ids(self):
        for conversation_id in BAD_IDS:
            for view in ("", "/last-response", "/bash", "/files"):
                with self.subTest(id=conversation_id, view=view):
                    status, data = self.get_json(f"/api/conversations/{conversation_id}{view}")
                    message = "not found" if "/" in conversation_id else "conversation not found"
                    self.assertEqual((status, data), (404, {"error": message}))

    def test_bad_ids_touch_no_file(self):
        with mock.patch.object(Path, "glob", side_effect=AssertionError("glob")) as glob:
            for conversation_id in BAD_IDS[:-1]:
                self.assertEqual(self.get_json(f"/api/conversations/{conversation_id}")[0], 404)
        glob.assert_not_called()

    def test_traversal_paths(self):
        for path in ("/api/conversations/../../etc/passwd", "/api/conversations/x/../../../etc/passwd",
                     f"/api/conversations/{CONV_A}/../../totals", f"/api/conversations/{CONV_A}/other",
                     f"/api/conversations/{CONV_A}/bash/", "/api/conversations/%2F%2Fetc%2Fpasswd/files/x"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_ambiguous_id(self):
        expected = {"error": "ambiguous id",
                    "projects": ["/home/dev/projects/api-gateway", "/home/dev/projects/billing-service"]}
        for view in ("", "/last-response", "/bash", "/files"):
            with self.subTest(view=view):
                self.assertEqual(self.get_json(f"/api/conversations/{AMBIGUOUS}{view}"), (409, expected))

    def test_unexpected_exception(self):
        stderr = io.StringIO()
        with mock.patch("ctokens.web.server.conversation_rows", side_effect=RuntimeError("secret detail")), \
                contextlib.redirect_stderr(stderr):
            status, headers, body = self.request("/api/conversations")
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(body), {"error": "internal error"})
        self.assertNotIn(b"secret", body)
        self.assertNotIn(b"Traceback", body)
        self.assertIn("Traceback", stderr.getvalue())
        self.assertIn("secret detail", stderr.getvalue())
        self.assertEqual(headers["Cache-Control"], "no-store")


class EmptyFolderTest(unittest.TestCase):
    def test_empty_and_missing_folders(self):
        with tempfile.TemporaryDirectory() as base, mock.patch.object(Handler, "log_message", lambda *a: None):
            empty = Path(base) / "empty"
            empty.mkdir()
            for folder in (empty, Path(base) / "missing"):
                with self.subTest(folder=folder.name):
                    server, thread = start_server(Config(folder, load_prices(None)))
                    try:
                        port = server.server_address[1]
                        status, data = get_json(port, "/api/conversations")
                        self.assertEqual((status, data), (200, {"projects_dir": str(folder), "conversations": []}))
                        status, data = get_json(port, "/api/totals")
                        self.assertEqual(status, 200)
                        self.assertEqual(data, json.loads(json.dumps(
                            totals_report(scan_totals(folder), load_prices(None)))))
                        self.assertEqual((data["conversations"], data["by_model"]), (0, []))
                        self.assertEqual(get_json(port, f"/api/conversations/{CONV_A}")[0], 404)
                    finally:
                        stop_server(server, thread)


if __name__ == "__main__":
    unittest.main()
