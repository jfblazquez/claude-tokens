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
from fixtures import AMBIGUOUS, CONV_A, CONV_B, CONV_EMPTY, ROOT, SUB_EXPLORE, build_projects

from ctokens.catalog import conversation_rows
from ctokens.logs import file_stats, parse_log
from ctokens.pricing import load_prices
from ctokens.reports import scan_totals, totals_report
from ctokens.web.cache import StatsCache
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

    def test_messages(self):
        for conversation in (CONV_A, CONV_B, CONV_EMPTY):
            with self.subTest(conversation=conversation):
                self.assert_parity(f"/api/conversations/{conversation}/messages", conversation, "--messages", "--json")
        self.assert_parity(f"/api/conversations/{CONV_A}/messages?source={SUB_EXPLORE}", CONV_A, "--messages",
                           "--source", SUB_EXPLORE, "--json")
        self.assert_parity(f"/api/conversations/{CONV_B}/messages", CONV_B, "--messages", "--json", custom=True)

    def test_messages_unknown_source(self):
        for source in ("nope", "..%2Fmain", "main%00"):
            with self.subTest(source=source):
                self.assertEqual(self.get_json(f"/api/conversations/{CONV_A}/messages?source={source}"),
                                 (404, {"error": "source not found"}))

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
            for view in ("", "/last-response", "/bash", "/files", "/messages"):
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
        for view in ("", "/last-response", "/bash", "/files", "/messages"):
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


class StatsCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "a.jsonl"
        self.path.write_text("one\n", encoding="utf-8")
        os.utime(self.path, ns=(1_000_000_000, 1_000_000_000))
        self.cache = StatsCache()
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def compute(self, path):
        self.calls.append(path)
        return {"text": path.read_text(encoding="utf-8"), "call": len(self.calls)}

    def test_hit_while_unchanged(self):
        first = self.cache.get("ns", self.path, self.compute)
        self.assertIs(self.cache.get("ns", str(self.path), self.compute), first)
        self.assertEqual(self.calls, [self.path])

    def test_mtime_change_recomputes(self):
        self.cache.get("ns", self.path, self.compute)
        os.utime(self.path, ns=(2_000_000_000, 2_000_000_000))
        self.assertEqual(self.cache.get("ns", self.path, self.compute)["call"], 2)

    def test_size_change_recomputes_even_with_same_mtime(self):
        self.cache.get("ns", self.path, self.compute)
        self.path.write_text("one\ntwo\n", encoding="utf-8")
        os.utime(self.path, ns=(1_000_000_000, 1_000_000_000))
        self.assertEqual(self.cache.get("ns", self.path, self.compute), {"text": "one\ntwo\n", "call": 2})

    def test_namespaces_are_separate(self):
        self.cache.get("a", self.path, self.compute)
        self.cache.get("b", self.path, self.compute)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.cache.paths("a"), {self.path})

    def test_prune_evicts_only_deleted_unseen_paths(self):
        other = Path(self.tmp.name) / "b.jsonl"
        other.write_text("x\n", encoding="utf-8")
        gone = Path(self.tmp.name) / "c.jsonl"
        gone.write_text("y\n", encoding="utf-8")
        for path in (self.path, other, gone):
            self.cache.get("ns", path, self.compute)
        gone.unlink()
        self.cache.prune({self.path})
        self.assertEqual(self.cache.paths("ns"), {self.path, other})

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.cache.get("ns", Path(self.tmp.name) / "missing.jsonl", self.compute)
        self.assertEqual(self.calls, [])

    def test_concurrent_gets(self):
        paths = []
        for index in range(20):
            path = Path(self.tmp.name) / f"f{index}.jsonl"
            path.write_text(f"{index}\n", encoding="utf-8")
            paths.append(path)
        errors, barrier = [], threading.Barrier(8)

        def worker():
            barrier.wait()
            try:
                for _ in range(20):
                    for path in paths:
                        value = self.cache.get("ns", path, self.compute)
                        if value["text"] != path.read_text(encoding="utf-8"):
                            errors.append(path)
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(self.cache.paths("ns"), set(paths))


class CacheWiringTest(unittest.TestCase):
    """The server re-parses only logs whose mtime or size changed (R9.1, R9.3)."""

    def setUp(self):
        self.quiet = mock.patch.object(Handler, "log_message", lambda *args: None)
        self.quiet.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.projects = build_projects(self.tmp.name)
        self.server, self.thread = start_server(Config(self.projects, load_prices(None)))
        self.port = self.server.server_address[1]
        self.logs = sorted(self.projects.rglob("*.jsonl"))

    def tearDown(self):
        stop_server(self.server, self.thread)
        self.tmp.cleanup()
        self.quiet.stop()

    def get(self, path):
        status, data = get_json(self.port, path)
        self.assertEqual(status, 200)
        return data

    def cli(self, *args):
        return cli_json(*args, "--projects-dir", str(self.projects))

    def touch(self, path, append=None):
        if append is not None:
            with path.open("a", encoding="utf-8") as f:
                f.write(append + "\n")
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    def test_totals_parse_each_log_once_then_only_changed_ones(self):
        with mock.patch("ctokens.web.server.file_stats", wraps=file_stats) as stats:
            first = self.get("/api/totals")
            self.assertEqual(sorted(call.args[0] for call in stats.call_args_list), self.logs)
            stats.reset_mock()
            self.assertEqual(self.get("/api/totals"), first)
            stats.assert_not_called()
            changed = self.projects / "-home-dev-projects-billing-service" / f"{CONV_B}.jsonl"
            self.touch(changed)
            self.assertEqual(self.get("/api/totals"), first)
            self.assertEqual([call.args[0] for call in stats.call_args_list], [changed])
        self.assertEqual(first, self.cli("--totals", "--json"))

    def test_changed_log_is_reflected(self):
        main = self.projects / "-home-dev-projects-api-gateway" / f"{CONV_A}.jsonl"
        self.get("/api/totals")
        self.get(f"/api/conversations/{CONV_A}")
        record = {"type": "assistant", "uuid": "e-new", "timestamp": "2026-10-01T08:00:00.000Z",
                  "message": {"id": "msg_NEW", "model": "claude-opus-5-5", "role": "assistant",
                              "content": [{"type": "text", "text": "Later."}],
                              "usage": {"input_tokens": 7, "output_tokens": 11}}}
        self.touch(main, json.dumps(record))
        self.assertEqual(self.get("/api/totals"), self.cli("--totals", "--json"))
        self.assertEqual(self.get(f"/api/conversations/{CONV_A}"), self.cli(CONV_A, "--json"))
        self.assertEqual(self.get(f"/api/conversations/{CONV_A}/last-response"),
                         self.cli(CONV_A, "--last-response", "--json"))

    def test_deleted_log_is_evicted(self):
        before = self.get("/api/totals")
        deleted = self.projects / "-home-dev-projects-billing-service" / f"{CONV_B}.jsonl"
        self.assertIn(deleted, self.server.cache.paths("file_stats"))
        deleted.unlink()
        after = self.get("/api/totals")
        self.assertEqual(after["conversations"], before["conversations"] - 1)
        self.assertEqual(after, self.cli("--totals", "--json"))
        self.assertEqual(self.server.cache.paths("file_stats"), set(self.logs) - {deleted})

    def test_report_uses_cache_and_stays_equal(self):
        expected = self.cli(CONV_A, "--json")
        with mock.patch("ctokens.web.server.parse_log", wraps=parse_log) as parse:
            self.assertEqual(self.get(f"/api/conversations/{CONV_A}"), expected)
            self.assertEqual(parse.call_count, 3)
            parse.reset_mock()
            self.assertEqual(self.get(f"/api/conversations/{CONV_A}"), expected)
            parse.assert_not_called()

    def test_subagent_description_change_without_log_change(self):
        self.get(f"/api/conversations/{CONV_A}")
        meta = next(self.projects.rglob("*.meta.json"))
        meta.write_text(json.dumps({"description": "Renamed task"}), encoding="utf-8")
        data = self.get(f"/api/conversations/{CONV_A}")
        self.assertIn("Renamed task", [row["task"] for row in data["conversations"]])
        self.assertEqual(data, self.cli(CONV_A, "--json"))

    def test_list_uses_cache(self):
        expected = self.get("/api/conversations")
        with mock.patch("ctokens.web.server.session_title") as title, \
                mock.patch("ctokens.web.server.project_path_of") as project:
            self.assertEqual(self.get("/api/conversations"), expected)
            title.assert_not_called()
            project.assert_not_called()
        main = self.projects / "-home-dev-projects-api-gateway" / f"{CONV_A}.jsonl"
        self.touch(main, json.dumps({"type": "ai-title", "aiTitle": "Renamed"}))
        rows = self.get("/api/conversations")["conversations"]
        self.assertEqual(rows[0]["title"], "Renamed")
        self.assertEqual(rows, conversation_rows(self.projects))

    def test_concurrent_totals(self):
        expected = self.cli("--totals", "--json")
        results, errors, barrier = [], [], threading.Barrier(6)

        def worker():
            barrier.wait()
            try:
                for _ in range(3):
                    results.append(get_json(self.port, "/api/totals"))
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 18)
        for status, data in results:
            self.assertEqual((status, data), (200, expected))
        self.assertEqual(self.server.cache.paths("file_stats"), set(self.logs))


if __name__ == "__main__":
    unittest.main()
