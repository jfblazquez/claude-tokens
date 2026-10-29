import base64
import http.client
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from fixtures import user

from ctokens.pricing import load_prices
from ctokens.repo import (FileIndex, RepoError, find_commits, find_files, list_dir, numstat_files, read_file, show_commit,
                          stat_paths)
from ctokens.web.server import Config, Handler, Server
from ctokens.web.shells import Shells

CONV = "55555555-5555-4555-8555-555555555555"
KEY = "repo-key"


def git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@example.com", "GIT_COMMITTER_NAME": "Dev",
           "GIT_COMMITTER_EMAIL": "dev@example.com", "GIT_AUTHOR_DATE": "2026-01-02T03:04:05Z",
           "GIT_COMMITTER_DATE": "2026-01-02T03:04:05Z"}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, env=env).stdout.decode().strip()


def make_repo(root):
    repo = Path(root) / "repo"
    (repo / "src" / "web").mkdir(parents=True)
    (repo / "docs").mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "src" / "server.py").write_text("def serve():\n    return 1\n")
    (repo / "src" / "web" / "server.py").write_text("print('web')\n")
    (repo / "docs" / "notes.md").write_text("# Notes\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "First commit")
    first = git(repo, "rev-parse", "HEAD")
    (repo / "src" / "server.py").write_text("def serve():\n    return 2\n")
    git(repo, "mv", "docs/notes.md", "docs/guide.md")
    (repo / "logo.bin").write_bytes(b"\x89PNG\0\0data")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "Second commit\n\nWith a body.")
    second = git(repo, "rev-parse", "HEAD")
    (repo / "untracked.txt").write_text("new\n")
    return repo, first, second


class RepoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo, cls.first, cls.second = make_repo(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_commits_by_short_and_full_hash(self):
        found = find_commits(self.repo, [self.first[:7], self.second, "deadbeef00", "not-a-hash", 12])
        self.assertEqual(set(found), {self.first[:7], self.second})
        self.assertEqual(found[self.first[:7]]["sha"], self.first)
        self.assertEqual((found[self.second]["subject"], found[self.second]["author"]), ("Second commit", "Dev"))

    def test_tree_hash_is_not_a_commit(self):
        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        self.assertEqual(find_commits(self.repo, [tree]), {})

    def test_no_repository(self):
        self.assertEqual(find_commits(self.tmp.name, [self.first]), {})
        with self.assertRaises(RepoError):
            show_commit(self.tmp.name, self.first)

    def test_files_by_name_path_and_absolute(self):
        found = find_files(self.repo / "src", ["server.py", "web/server.py", "docs/guide.md", "./server.py",
                                               str(self.repo / "untracked.txt"), "missing.py", "untracked.txt"],
                           FileIndex())
        self.assertEqual([m["display"] for m in found["server.py"]], ["src/server.py", "src/web/server.py"])
        self.assertEqual([m["display"] for m in found["web/server.py"]], ["src/web/server.py"])
        self.assertEqual([m["display"] for m in found["docs/guide.md"]], ["docs/guide.md"])
        self.assertEqual([m["display"] for m in found["./server.py"]], ["src/server.py"])
        self.assertEqual([m["display"] for m in found[str(self.repo / "untracked.txt")]], ["untracked.txt"])
        self.assertEqual([m["display"] for m in found["untracked.txt"]], ["untracked.txt"])
        self.assertNotIn("missing.py", found)

    def test_read_file(self):
        data = read_file(self.repo, "src/server.py")
        self.assertEqual((data["display"], data["text"], data["binary"], data["truncated"]),
                         ("src/server.py", "def serve():\n    return 2\n", False, False))
        self.assertTrue(read_file(self.repo, str(self.repo / "logo.bin"))["binary"])
        for bad in ("missing.py", "src", "", None):
            with self.subTest(bad=bad), self.assertRaises(RepoError):
                read_file(self.repo, bad)

    def test_read_file_stamp_follows_writes(self):
        target = self.repo / "untracked.txt"
        before = read_file(self.repo, "untracked.txt")["stamp"]
        target.write_text("newer and longer\n")
        try:
            self.assertNotEqual(read_file(self.repo, "untracked.txt")["stamp"], before)
        finally:
            target.write_text("new\n")

    def test_list_dir(self):
        (self.repo / ".gitignore").write_text("build/\n")
        (self.repo / "build").mkdir(exist_ok=True)
        try:
            data = list_dir(self.repo / "src", "..")
            self.assertEqual((data["path"], data["display"], data["root"]), (str(self.repo), ".", str(self.repo)))
            names = [e["name"] for e in data["entries"]]
            self.assertEqual(names, [".git", "build", "docs", "src", ".gitignore", "logo.bin", "untracked.txt"])
            entries = {e["name"]: e for e in data["entries"]}
            self.assertEqual((entries["src"]["type"], entries["src"]["size"]), ("dir", None))
            self.assertEqual((entries["untracked.txt"]["type"], entries["untracked.txt"]["size"]), ("file", 4))
            self.assertEqual({n for n, e in entries.items() if e["ignored"]}, {".git", "build"})
            self.assertEqual(list_dir(self.repo, "src/web")["display"], "src/web")
            self.assertEqual(list_dir(self.repo, "")["path"], str(self.repo))
        finally:
            (self.repo / ".gitignore").unlink()
            (self.repo / "build").rmdir()
        for bad in ("missing", "src/server.py", None):
            with self.subTest(bad=bad), self.assertRaises(RepoError):
                list_dir(self.repo, bad)

    def test_stat_paths(self):
        stats = stat_paths([str(self.repo / "src" / "server.py"), str(self.repo / "src"), str(self.repo / "gone.py"), "relative.py", 3])
        self.assertEqual(set(stats), {str(self.repo / "src" / "server.py"), str(self.repo / "src"), str(self.repo / "gone.py")})
        self.assertEqual(stats[str(self.repo / "src" / "server.py")]["type"], "file")
        self.assertEqual(stats[str(self.repo / "src")]["type"], "dir")
        self.assertIsNone(stats[str(self.repo / "gone.py")])
        self.assertEqual(stats[str(self.repo / "src" / "server.py")]["stamp"], read_file(self.repo, "src/server.py")["stamp"])

    def test_read_file_truncates(self):
        with mock.patch("ctokens.repo.MAX_FILE_BYTES", 10):
            data = read_file(self.repo, "src/server.py")
        self.assertEqual((data["text"], data["truncated"], data["size"]), ("def serve(", True, 26))

    def test_show_commit(self):
        data = show_commit(self.repo, self.second[:8])
        self.assertEqual((data["sha"], data["parents"], data["message"]), (self.second, [self.first], "Second commit\n\nWith a body."))
        files = {f["path"]: f for f in data["files"]}
        self.assertEqual(files["docs/guide.md"]["old_path"], "docs/notes.md")
        self.assertEqual((files["src/server.py"]["added"], files["src/server.py"]["deleted"]), (1, 1))
        self.assertIsNone(files["logo.bin"]["added"])
        self.assertIn("-    return 1\n+    return 2", data["patch"])

    def test_show_root_commit(self):
        data = show_commit(self.repo, self.first)
        self.assertEqual(data["parents"], [])
        self.assertEqual(sorted(f["path"] for f in data["files"]), ["docs/notes.md", "src/server.py", "src/web/server.py"])
        self.assertIn("+def serve():", data["patch"])

    def test_show_commit_rejects_options(self):
        for bad in ("--output=/tmp/x", "HEAD", "zzzzzzz", ""):
            with self.subTest(bad=bad), self.assertRaises(RepoError):
                show_commit(self.repo, bad)

    def test_numstat_rename(self):
        self.assertEqual(numstat_files("1\t2\ta.py\0" "0\t0\t\0old.md\0new.md\0" "-\t-\tlogo.bin\0"),
                         [{"added": 1, "deleted": 2, "path": "a.py"},
                          {"added": 0, "deleted": 0, "old_path": "old.md", "path": "new.md"},
                          {"added": None, "deleted": None, "path": "logo.bin"}])


def output(events, token):
    return b"".join(base64.b64decode(d["data"]) for e, d in events if e == "data" and d["id"] == token)


def read_until(shell, needle, timeout=10):
    offset, seen, deadline = 0, b"", time.monotonic() + timeout
    while needle not in seen and time.monotonic() < deadline:
        offset, data, exited = shell.read(offset, 0.5)
        seen += data
        if exited and not data:
            break
    return seen


class ShellsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shells = Shells()
        self.env = mock.patch.dict(os.environ, {"SHELL": "/bin/sh"})
        self.env.start()

    def tearDown(self):
        self.shells.close_all()
        self.env.stop()
        self.tmp.cleanup()

    def test_runs_in_the_folder_with_a_terminal(self):
        shell = self.shells.open(CONV, self.tmp.name, 100, 30)
        shell.write(b"pwd; stty size; tty\n")
        seen = read_until(shell, b"/dev/pts")
        self.assertIn(os.path.realpath(self.tmp.name).encode(), seen)
        self.assertIn(b"30 100", seen)

    def test_resize_and_exit(self):
        shell = self.shells.open(CONV, self.tmp.name)
        shell.resize(120, 40)
        shell.write(b"stty size; exit 3\n")
        seen = read_until(shell, b"never")
        self.assertIn(b"40 120", seen)
        self.assertTrue(shell.exited)
        self.assertEqual(shell.code, 3)

    def test_command_in_the_foreground(self):
        shell = self.shells.open(CONV, self.tmp.name)
        self.assertIsNone(shell.command())
        shell.write(b"sleep 30\n")
        deadline = time.monotonic() + 5
        while shell.command() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(shell.public()["command"], "sleep")

    def test_close_hangs_up(self):
        shell = self.shells.open(CONV, self.tmp.name)
        self.assertTrue(self.shells.close(shell.token))
        self.assertTrue(shell.exited)
        self.assertIsNone(self.shells.get(shell.token))

    def test_abandoned_shells_are_reaped(self):
        shell = self.shells.open(CONV, self.tmp.name)
        shell.attach()
        with mock.patch("ctokens.web.shells.DETACHED_GRACE", 0):
            self.shells.reap()
            self.assertIs(self.shells.get(shell.token), shell)
            shell.detach()
            self.shells.reap()
        self.assertIsNone(self.shells.get(shell.token))
        self.assertTrue(shell.exited)

    def test_limit_and_missing_folder(self):
        with mock.patch("ctokens.web.shells.MAX_SHELLS", 1):
            self.shells.open(CONV, self.tmp.name)
            with self.assertRaisesRegex(Exception, "already 1 shells"):
                self.shells.open(CONV, self.tmp.name)
        with self.assertRaisesRegex(Exception, "does not exist"):
            self.shells.open(CONV, str(Path(self.tmp.name) / "gone"))


class RepoApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quiet = mock.patch.object(Handler, "log_message", lambda *args: None)
        cls.quiet.start()
        cls.env = mock.patch.dict(os.environ, {"SHELL": "/bin/sh"})
        cls.env.start()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo, cls.first, cls.second = make_repo(cls.tmp.name)
        projects = Path(cls.tmp.name) / "projects"
        (projects / "-repo").mkdir(parents=True)
        event = user("hello", str(cls.repo), "2026-01-02T03:04:05Z", "u1")
        (projects / "-repo" / f"{CONV}.jsonl").write_text(json.dumps(event) + "\n")
        cls.server = Server(Config(projects, load_prices(None), send_key=KEY), 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(10)
        cls.tmp.cleanup()
        cls.env.stop()
        cls.quiet.stop()

    def request(self, method, path, body=None, key=KEY, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            headers = {"Host": f"127.0.0.1:{self.port}", **({"X-Send-Key": key} if key else {}), **(headers or {})}
            if body is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(body).encode()
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            data = response.read()
            return response.status, json.loads(data) if data and response.headers.get_content_type() == "application/json" else data
        finally:
            connection.close()

    def test_resolve(self):
        status, data = self.request("POST", f"/api/conversations/{CONV}/resolve",
                                    {"commits": [self.first[:7], "abcdef1234"], "files": ["server.py", "nope.py"]})
        self.assertEqual(status, 200)
        self.assertEqual(list(data["commits"]), [self.first[:7]])
        self.assertEqual(len(data["files"]["server.py"]), 2)
        self.assertEqual(data["root"], str(self.repo))

    def test_resolve_from_a_folder(self):
        status, data = self.request("POST", f"/api/conversations/{CONV}/resolve", {"files": ["./server.py"], "cwd": str(self.repo / "src/web")})
        self.assertEqual((status, data["files"]["./server.py"][0]["display"]), (200, "src/web/server.py"))
        self.assertEqual(self.request("POST", f"/api/conversations/{CONV}/resolve", {"files": [], "cwd": "relative"})[0], 400)

    def test_dir_and_stat(self):
        status, data = self.request("GET", f"/api/conversations/{CONV}/dir?path=src")
        self.assertEqual((status, [e["name"] for e in data["entries"]]), (200, ["web", "server.py"]))
        self.assertEqual(self.request("GET", f"/api/conversations/{CONV}/dir")[1]["path"], str(self.repo))
        self.assertEqual(self.request("GET", f"/api/conversations/{CONV}/dir?path=nope")[0], 404)
        status, data = self.request("POST", f"/api/conversations/{CONV}/stat", {"paths": [str(self.repo / "src"), str(self.repo / "x")]})
        self.assertEqual((status, data["stats"][str(self.repo / "src")]["type"], data["stats"][str(self.repo / "x")]), (200, "dir", None))
        self.assertEqual(self.request("POST", f"/api/conversations/{CONV}/stat", {"paths": "x"})[0], 400)

    def test_resolve_bad_body(self):
        status, _ = self.request("POST", f"/api/conversations/{CONV}/resolve", {"commits": "x"})
        self.assertEqual(status, 400)

    def test_everything_needs_the_key(self):
        for method, path, body in (("POST", f"/api/conversations/{CONV}/resolve", {}),
                                   ("POST", f"/api/conversations/{CONV}/shell", {}),
                                   ("GET", f"/api/conversations/{CONV}/commit?sha={self.first}", None),
                                   ("GET", f"/api/conversations/{CONV}/file?path=src/server.py", None),
                                   ("GET", f"/api/conversations/{CONV}/dir?path=src", None),
                                   ("POST", f"/api/conversations/{CONV}/stat", {"paths": []})):
            for key in (None, "wrong"):
                with self.subTest(path=path, key=key):
                    self.assertEqual(self.request(method, path, body, key=key)[0], 403)

    def test_commit_and_file(self):
        status, data = self.request("GET", f"/api/conversations/{CONV}/commit?sha={self.second[:9]}")
        self.assertEqual((status, data["sha"]), (200, self.second))
        status, data = self.request("GET", f"/api/conversations/{CONV}/file?path=src/web/server.py")
        self.assertEqual((status, data["text"]), (200, "print('web')\n"))
        self.assertEqual(self.request("GET", f"/api/conversations/{CONV}/commit?sha=deadbeef00")[0], 404)
        self.assertEqual(self.request("GET", f"/api/conversations/{CONV}/file?path=nope")[0], 404)
        self.assertEqual(self.request("GET", "/api/conversations/66666666-6666-4666-8666-666666666666/file?path=x")[0], 404)

    def test_shell_round_trip(self):
        status, data = self.request("POST", f"/api/conversations/{CONV}/shell", {"cols": 90, "rows": 20})
        self.assertEqual(status, 200)
        token = data["shell"]["id"]
        self.assertEqual(data["shell"]["cwd"], str(self.repo))
        self.assertEqual(self.request("POST", f"/api/shells/{token}/resize", {"cols": 91, "rows": 21})[0], 200)
        status, data = self.request("POST", f"/api/shells/{token}/state", {})
        self.assertEqual((status, data["shell"]["id"], data["shell"]["command"]), (200, token, None))
        self.assertEqual(self.request("POST", f"/api/shells/{token}/input", {"data": "stty size; exit 0\n"})[0], 200)
        events = self.stream(f"{token}:0")
        self.assertIn(b"21 91", output(events, token))
        self.assertIn(("exit", {"id": token, "code": 0}), events)
        self.assertEqual(events[-1][0], "end")
        self.assertEqual(self.request("POST", f"/api/shells/{token}/input", {"data": "x"})[0], 409)
        self.assertEqual(self.request("POST", f"/api/shells/{token}/close", {})[0], 200)
        self.assertEqual(self.request("POST", f"/api/shells/{token}/close", {})[0], 404)
        self.assertEqual(self.stream(f"{token}:0"), [("exit", {"id": token, "code": None}), ("end", {})])

    def stream(self, start, last=None):
        status, body = self.request("GET", f"/api/shells/stream?from={start}",
                                    headers={"Last-Event-ID": last} if last else None)
        self.assertEqual(status, 200)
        return [(block.split("event: ")[1].split("\n")[0], json.loads(block.split("data: ")[1]))
                for block in body.decode().split("\n\n") if "event: " in block]

    def test_one_stream_for_several_shells(self):
        tokens = [self.request("POST", f"/api/conversations/{CONV}/shell", {})[1]["shell"]["id"] for _ in range(2)]
        for n, token in enumerate(tokens):
            self.request("POST", f"/api/shells/{token}/input", {"data": f"echo shell-{n}-says-hi; exit {n + 4}\n"})
        events = self.stream(",".join(f"{t}:0" for t in tokens))
        for n, token in enumerate(tokens):
            self.assertIn(f"shell-{n}-says-hi".encode(), output(events, token))
            self.assertIn(("exit", {"id": token, "code": n + 4}), events)
        # A reconnect sends the offsets reached in Last-Event-ID, so nothing is written twice.
        reached = ",".join(f"{t}:{max(d['at'] for e, d in events if e == 'data' and d['id'] == t)}" for t in tokens)
        again = self.stream(",".join(f"{t}:0" for t in tokens), last=reached)
        self.assertEqual(output(again, tokens[0]) + output(again, tokens[1]), b"")
        for token in tokens:
            self.request("POST", f"/api/shells/{token}/close", {})

    def test_resolve_from_where_a_shell_is_now(self):
        status, data = self.request("POST", f"/api/conversations/{CONV}/shell", {"cwd": self.tmp.name})
        token = data["shell"]["id"]
        ask = {"commits": [self.second[:7]], "files": ["src/server.py"], "shell": token}
        before = self.request("POST", f"/api/conversations/{CONV}/resolve", ask)[1]
        self.assertEqual((before["cwd"], before["commits"], before["files"]), (os.path.realpath(self.tmp.name), {}, {}))
        self.request("POST", f"/api/shells/{token}/input", {"data": f"cd {self.repo}\n"})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            after = self.request("POST", f"/api/conversations/{CONV}/resolve", ask)[1]
            if after["commits"]:
                break
            time.sleep(0.1)
        self.assertEqual(after["cwd"], str(self.repo))
        self.assertEqual(after["commits"][self.second[:7]]["sha"], self.second)
        self.assertEqual([m["display"] for m in after["files"]["src/server.py"]], ["src/server.py"])
        self.request("POST", f"/api/shells/{token}/close", {})
        self.assertEqual(self.request("POST", f"/api/conversations/{CONV}/resolve", ask)[0], 404)

    def test_commit_from_another_folder(self):
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        git(other, "init", "-q", "-b", "main")
        (other / "lib.c").write_text("int main(void) { return 0; }\n")
        git(other, "add", ".")
        git(other, "commit", "-q", "-m", "Another repository")
        first = git(other, "rev-parse", "HEAD")
        self.assertEqual(self.request("GET", f"/api/conversations/{CONV}/commit?sha={first}")[0], 404)
        status, data = self.request("GET", f"/api/conversations/{CONV}/commit?sha={first}&cwd={other}")
        self.assertEqual((status, data["sha"]), (200, first))
        for bad in ("relative", str(other / "nope")):
            with self.subTest(cwd=bad):
                self.assertEqual(self.request("GET", f"/api/conversations/{CONV}/commit?sha={first}&cwd={bad}")[0], 400)

    def test_stream_needs_shells(self):
        for start in ("", "bad/token:0", ",".join(f"t{n}:0" for n in range(9))):
            with self.subTest(start=start):
                self.assertEqual(self.request("GET", f"/api/shells/stream?from={start}")[0], 400)

    def test_shell_actions_need_the_key_and_post(self):
        status, data = self.request("POST", f"/api/conversations/{CONV}/shell", {})
        token = data["shell"]["id"]
        self.assertEqual(self.request("POST", f"/api/shells/{token}/input", {"data": "x"}, key=None)[0], 403)
        self.assertEqual(self.request("GET", f"/api/shells/{token}/input")[0], 405)
        self.assertEqual(self.request("POST", f"/api/shells/{token}/close", {})[0], 200)

    def test_shell_in_another_folder(self):
        status, data = self.request("POST", f"/api/conversations/{CONV}/shell", {"cwd": str(self.repo / "src")})
        self.assertEqual((status, data["shell"]["cwd"]), (200, str(self.repo / "src")))
        self.request("POST", f"/api/shells/{data['shell']['id']}/close", {})
        self.assertEqual(self.request("POST", f"/api/conversations/{CONV}/shell", {"cwd": "relative"})[0], 400)
        self.assertEqual(self.request("POST", f"/api/conversations/{CONV}/shell", {"cwd": "/no/such/dir"})[0], 409)


if __name__ == "__main__":
    unittest.main()
