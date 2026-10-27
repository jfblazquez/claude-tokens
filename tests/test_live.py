import http.client
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fixtures import API, BILLING, CONV_A, CONV_B, build_projects, user
from test_server import http_request, start_server, stop_server

from ctokens import live
from ctokens.content import Transcript, transcript
from ctokens.pricing import load_prices
from ctokens.web import server as web_server
from ctokens.web.server import Config, Handler

PANE, SOCKET, TTY = "%7", "/tmp/tmux-1000/default", "/dev/pts/7"


def fake_process(proc, pid, start=100, pgrp=None, tpgid=None, env=None, tty=TTY):
    """A /proc/<pid> with the stat fields, environment and stdin that live.py reads."""
    folder = proc / str(pid)
    (folder / "fd").mkdir(parents=True)
    pgrp = pid if pgrp is None else pgrp
    tpgid = pgrp if tpgid is None else tpgid
    fields = ["S", "1", str(pgrp), str(pgrp), "34823", str(tpgid), *["0"] * 13, str(start), "0", "0"]
    (folder / "stat").write_text(f"{pid} (claude (x)) {' '.join(fields)}\n")
    env = {"TMUX": f"{SOCKET},123,0", "TMUX_PANE": PANE} if env is None else env
    (folder / "environ").write_bytes(b"".join(f"{k}={v}".encode() + b"\0" for k, v in env.items()))
    os.symlink(tty, folder / "fd" / "0")


def record(sessions, pid, session_id, start=100, **extra):
    data = {"pid": pid, "sessionId": session_id, "procStart": str(start), "status": "idle", "entrypoint": "cli",
            "cwd": "/home/dev/projects/api-gateway",
            "startedAt": 1790000000000, "statusUpdatedAt": 1790000060000, "updatedAt": 1790000060000,
            "name": f"session-{pid}", "version": "2.1.311", **extra}
    (sessions / f"{pid}.json").write_text(json.dumps(data))


def tmux_ok(command, **kwargs):
    stdout = f"{TTY}\n" if "display-message" in command else ""
    return subprocess.CompletedProcess(command, 0, stdout, "")


class LiveTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.proc, self.sessions = base / "proc", base / "sessions"
        (self.proc / "self").mkdir(parents=True)
        (self.proc / "self" / "stat").write_text("1 (python3) S")
        self.sessions.mkdir()
        patch = mock.patch.object(live, "PROC", self.proc)
        patch.start()
        self.addCleanup(patch.stop)


class LiveSessionsTest(LiveTestCase):
    def test_running_session(self):
        fake_process(self.proc, 41, start=555)
        record(self.sessions, 41, CONV_A, start=555, status="busy")
        self.assertEqual(live.live_sessions(self.sessions), {CONV_A: {
            "pid": 41, "status": "busy", "waiting_for": None, "status_since": "2026-09-21T14:14:20Z",
            "started": "2026-09-21T14:13:20Z", "name": "session-41", "entrypoint": "cli", "version": "2.1.311",
            "cwd": "/home/dev/projects/api-gateway", "updated_ms": 1790000060000}})

    def test_dead_and_reused_pids_are_not_live(self):
        record(self.sessions, 41, CONV_A)
        fake_process(self.proc, 42, start=999)
        record(self.sessions, 42, CONV_B, start=100)
        self.assertEqual(live.live_sessions(self.sessions), {})

    def test_newest_record_wins_and_junk_is_skipped(self):
        for pid, updated in ((41, 5), (42, 9), (43, 7)):
            fake_process(self.proc, pid)
            record(self.sessions, pid, CONV_A, updatedAt=updated)
        (self.sessions / "44.json").write_text("{not json")
        (self.sessions / "45.json").write_text("[]")
        (self.sessions / "notes.json").write_text("{}")
        self.assertEqual(live.live_sessions(self.sessions)[CONV_A]["pid"], 42)

    def test_missing_folder(self):
        self.assertEqual(live.live_sessions(self.sessions / "nope"), {})


class SendTest(LiveTestCase):
    def setUp(self):
        super().setUp()
        fake_process(self.proc, 41)
        record(self.sessions, 41, CONV_A)
        self.run = mock.patch.object(live.subprocess, "run", side_effect=tmux_ok).start()
        mock.patch.object(live.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)

    def info(self):
        return live.live_sessions(self.sessions)[CONV_A]

    def test_pastes_then_presses_enter(self):
        sent = live.send(self.sessions, CONV_A, "first line\nsecond line")
        self.assertEqual(sent["pid"], 41)
        commands = [call.args[0] for call in self.run.call_args_list if "capture-pane" not in call.args[0]]
        self.assertEqual(commands[0], ["tmux", "-S", SOCKET, "display-message", "-p", "-t", PANE, "#{pane_tty}"])
        self.assertEqual(commands[1][:4], ["tmux", "-S", SOCKET, "load-buffer"])
        self.assertEqual([c for c in self.run.call_args_list if "load-buffer" in c.args[0]][0].kwargs["input"],
                         "first line\nsecond line")
        buffer = commands[1][5]
        self.assertEqual(commands[2], ["tmux", "-S", SOCKET, "paste-buffer", "-p", "-d", "-b", buffer, "-t", PANE])
        self.assertEqual(commands[3], ["tmux", "-S", SOCKET, "send-keys", "-t", PANE, "Enter"])

    def test_states_that_would_take_the_text(self):
        for extra, problem in (({"status": "waiting", "waitingFor": "permission prompt"}, "waiting (permission prompt)"),
                               ({"status": "shell"}, "in shell mode"),
                               ({"status": None}, "in an unknown state"),
                               ({"entrypoint": "sdk-cli"}, "interactive terminal")):
            with self.subTest(extra=extra):
                record(self.sessions, 41, CONV_A, **extra)
                self.assertIn(problem, live.send_problem(self.info()))
                with self.assertRaises(live.SendError):
                    live.send(self.sessions, CONV_A, "hi")
        self.assertFalse([call for call in self.run.call_args_list if "paste-buffer" in call.args[0]])

    def screen(self, mark):
        rule = "─" * 40
        text = f"● Done.\n{rule}\n{mark} \n{rule}\n  ⏵⏵ auto mode on\n❯ ◯ general-purpose\n"
        self.run.side_effect = lambda command, **kw: (subprocess.CompletedProcess(command, 0, text, "")
                                                      if "capture-pane" in command else tmux_ok(command))

    def test_the_screen_has_the_last_word_on_shell_mode(self):
        # Claude Code may leave "shell" in the registry after shell mode ends, and may not have written it yet.
        for status, mark, problem in (("shell", "❯", None), ("shell", "!", "in shell mode"), ("idle", "!", "in shell mode"),
                                      ("busy", "!", "in shell mode"), ("idle", "❯", None), ("shell", "?", "in shell mode")):
            with self.subTest(status=status, mark=mark):
                record(self.sessions, 41, CONV_A, status=status)
                self.screen(mark)
                found = live.send_problem(self.info())
                if problem is None:
                    self.assertIsNone(found)
                else:
                    self.assertIn(problem, found)

    def test_read_only_only_for_sessions_without_a_terminal_to_type_in(self):
        record(self.sessions, 41, CONV_A, status="waiting", waitingFor="permission prompt")
        self.assertEqual(live.public(self.info())["read_only"], False)
        fake_process(self.proc, 42, env={})
        record(self.sessions, 42, CONV_B, status="busy")
        shown = live.public(live.live_sessions(self.sessions)[CONV_B])
        self.assertEqual((shown["read_only"], shown["read_only_reason"]), (True, "The session is not running inside tmux."))
        self.assertNotIn("updated_ms", shown)

    def test_busy_session_queues_the_prompt(self):
        record(self.sessions, 41, CONV_A, status="busy")
        self.assertIsNone(live.send_problem(self.info()))

    def test_pane_must_be_the_session_terminal_in_foreground(self):
        cases = ((42, {"env": {}}, "not running inside tmux"),
                 (43, {"tty": "/dev/pts/9"}, "shows another program"),
                 (44, {"tpgid": 1}, "not in the foreground"))
        for pid, process, problem in cases:
            with self.subTest(problem=problem):
                fake_process(self.proc, pid, **process)
                record(self.sessions, pid, CONV_B)
                self.assertIn(problem, live.send_problem(live.live_sessions(self.sessions)[CONV_B]))
                (self.sessions / f"{pid}.json").unlink()

    def test_bad_messages_and_unknown_sessions(self):
        for session, text, problem in ((CONV_A, " \n", "empty"), (CONV_A, "x" * (live.MAX_MESSAGE_CHARS + 1), "longer"),
                                       (CONV_B, "hi", "not running")):
            with self.subTest(problem=problem), self.assertRaisesRegex(live.SendError, problem):
                live.send(self.sessions, session, text)
        self.run.assert_not_called()

    def test_rename_types_the_rename_command(self):
        live.rename(self.sessions, CONV_A, "New name")
        load = next(call for call in self.run.call_args_list if "load-buffer" in call.args[0])
        self.assertEqual(load.kwargs["input"], "/rename New name")

    def test_tmux_failure(self):
        self.run.side_effect = lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "no server running")
        with self.assertRaisesRegex(live.SendError, "no server running"):
            live.send(self.sessions, CONV_A, "hi")


RULE = "─" * 80
# Screens captured from Claude Code 2.1.311 while it waited on AskUserQuestion and on a permission prompt.
QUESTION_SCREEN = f"""❯ Ask me two questions
{RULE}
←  ☒ Color  ☐ Fruits  ✔ Submit  →

Which fruits do you like?

  1. [✔] Apple
         Apple
  2. [ ] Pear
         Pear
  3. [ ] Type something
❯    Submit
{RULE}
  4. Chat about this

Enter to select · Tab/Arrow keys to navigate · Esc to cancel
"""
PERMISSION_SCREEN = f"""● Bash(touch hello.txt)
  1. not an option: the conversation above the dialog
{RULE}
 Bash command
 Create empty hello.txt file
{"╌" * 80}
 touch hello.txt
{"╌" * 80}
 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and always allow access to
      /home/dev/projects/api-gateway from this project
   3. No

 Esc to cancel · Tab to amend
"""


class DialogTest(LiveTestCase):
    def test_question(self):
        found = live.dialog(QUESTION_SCREEN.splitlines())
        self.assertEqual(found["text"], "←  ☒ Color  ☐ Fruits  ✔ Submit  →\n\nWhich fruits do you like?")
        self.assertEqual(found["question"], "Which fruits do you like?")
        self.assertEqual(found["hint"], "Enter to select · Tab/Arrow keys to navigate · Esc to cancel")
        self.assertEqual([(o["key"], o["label"], o["detail"], o["current"], o["checked"]) for o in found["options"]],
                         [("1", "Apple", "Apple", False, True), ("2", "Pear", "Pear", False, False),
                          ("3", "Type something", "", False, False), (None, "Submit", "", True, None),
                          ("4", "Chat about this", "", False, None)])

    def test_permission_prompt(self):
        found = live.dialog(PERMISSION_SCREEN.splitlines())
        self.assertTrue(found["text"].startswith("Bash command\nCreate empty hello.txt file\n"))
        self.assertEqual(found["question"], "Do you want to proceed?")
        self.assertEqual(found["hint"], "Esc to cancel · Tab to amend")
        self.assertEqual([(o["key"], o["label"], o["detail"], o["current"]) for o in found["options"]],
                         [("1", "Yes", "", True),
                          ("2", "Yes, and always allow access to", "/home/dev/projects/api-gateway from this project", False),
                          ("3", "No", "", False)])

    def test_no_dialog(self):
        for screen in ("", f"● Done.\n{RULE}\n❯ \n{RULE}\n", "Steps:\n  2. second\n"):
            with self.subTest(screen=screen):
                self.assertIsNone(live.dialog(screen.splitlines()))


class AnswerTest(SendTest):
    def show(self, screen):
        self.run.side_effect = lambda command, **kw: (subprocess.CompletedProcess(command, 0, screen, "")
                                                      if "capture-pane" in command else tmux_ok(command))

    def keys(self):
        return [call.args[0][6:] for call in self.run.call_args_list if "send-keys" in call.args[0]]

    def test_presses_keys_and_types_text_into_the_dialog(self):
        record(self.sessions, 41, CONV_A, status="waiting", waitingFor="input needed")
        self.show(QUESTION_SCREEN)
        shown = live.answer(self.sessions, CONV_A, [{"key": "Up"}, {"text": "A parrot"}, {"key": "Enter"}])
        self.assertEqual(self.keys(), [["Up"], ["-l", "A parrot"], ["Enter"]])
        self.assertEqual((shown["status"], shown["dialog"]["question"]), ("waiting", "Which fruits do you like?"))

    def test_refusals(self):
        record(self.sessions, 41, CONV_A, status="waiting", waitingFor="input needed")
        self.show(QUESTION_SCREEN)
        for steps in ([], [{"key": "C-c"}], [{"text": "two\nlines"}], [{"text": " "}], [{"key": "1", "text": "x"}],
                      [{"key": "1"}] * (live.MAX_DIALOG_STEPS + 1), "1"):
            with self.subTest(steps=steps), self.assertRaisesRegex(live.SendError, "steps"):
                live.answer(self.sessions, CONV_A, steps)
        with self.assertRaisesRegex(live.SendError, "not running"):
            live.answer(self.sessions, CONV_B, [{"key": "1"}])
        # The question was answered in the terminal meanwhile: the digit would go into the prompt.
        for status, screen in (("idle", QUESTION_SCREEN), ("waiting", f"{RULE}\n❯ \n{RULE}\n")):
            with self.subTest(status=status):
                record(self.sessions, 41, CONV_A, status=status)
                self.show(screen)
                with self.assertRaisesRegex(live.SendError, "not waiting"):
                    live.answer(self.sessions, CONV_A, [{"key": "1"}])
        self.assertEqual(self.keys(), [])

    def test_public_shows_the_dialog_and_the_status_the_screen_shows(self):
        record(self.sessions, 41, CONV_A, status="waiting", waitingFor="permission prompt")
        self.show(PERMISSION_SCREEN)
        self.assertEqual(live.public(self.info())["dialog"]["question"], "Do you want to proceed?")
        for status, mark, shown in (("shell", "❯", "idle"), ("idle", "!", "shell"), ("busy", "❯", "busy")):
            with self.subTest(status=status, mark=mark):
                record(self.sessions, 41, CONV_A, status=status)
                self.screen(mark)
                self.assertEqual((live.public(self.info())["status"], live.public(self.info())["dialog"]), (shown, None))


class LiveApiCase(LiveTestCase):
    """A server with a send key over the fixtures, with CONV_A live in a tmux pane."""
    KEY = "s3cret-key"

    def setUp(self):
        super().setUp()
        quiet = mock.patch.object(Handler, "log_message", lambda *args: None)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.projects = build_projects(self.tmp.name)
        fake_process(self.proc, 41)
        record(self.sessions, 41, CONV_A)
        mock.patch.object(live.subprocess, "run", side_effect=tmux_ok).start()
        self.addCleanup(mock.patch.stopall)
        self.server, thread = start_server(Config(self.projects, load_prices(None), send_key=self.KEY))
        self.addCleanup(stop_server, self.server, thread)
        self.port = self.server.server_address[1]

    def request(self, method, path, body=None, headers=()):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            connection.request(method, path, body=body, headers=dict(headers))
            response = connection.getresponse()
            return response.status, response.headers, json.loads(response.read())
        finally:
            connection.close()

    def post(self, conversation_id, body, key=KEY, content_type="application/json", origin=None, action=None):
        headers = {"Content-Type": content_type, **({"X-Send-Key": key} if key else {}), **({"Origin": origin} if origin else {})}
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        action = action or ("send" if isinstance(body, bytes) or body else "go-live")
        status, _, answer = self.request("POST", f"/api/conversations/{conversation_id}/{action}", data, headers)
        return status, answer

    def get(self, path, key=None):
        return self.request("GET", path, headers={"X-Send-Key": key} if key else {})



class LiveApiTest(LiveApiCase):
    def test_list_marks_live_rows_only(self):
        _, _, data = self.get("/api/conversations")
        rows = {row["id"]: row for row in data["conversations"]}
        self.assertEqual(rows[CONV_A]["live"]["pid"], 41)
        self.assertNotIn("updated_ms", rows[CONV_A]["live"])
        self.assertNotIn("live", rows[CONV_B])

    def test_live_states_of_every_session(self):
        for key, state in ((None, "missing"), (self.KEY, "ok")):
            with self.subTest(key=key):
                status, _, data = self.get("/api/live", key)
                self.assertEqual((status, data["key"], list(data["live"]), data["live"][CONV_A]["status"]), (200, state, [CONV_A], "idle"))

    def test_answer(self):
        with mock.patch("ctokens.web.server.answer", return_value={"pid": 41}) as answer:
            status, data = self.post(CONV_A, {"steps": [{"key": "1"}]}, action="answer")
        self.assertEqual((status, data), (200, {"live": {"pid": 41}}))
        self.assertEqual(answer.call_args.args[1:], (CONV_A, [{"key": "1"}]))
        status, data = self.post(CONV_A, {"steps": [{"key": "1"}]}, key=None, action="answer")
        self.assertEqual(status, 403)
        status, data = self.post(CONV_A, {"steps": [{"key": "1"}]}, action="answer")
        self.assertEqual((status, data), (409, {"error": "The session is not waiting on a question or a dialog any more."}))

    def test_live_view_reports_the_key(self):
        for key, state in ((None, "missing"), ("nope", "wrong"), (self.KEY, "ok")):
            with self.subTest(key=key):
                status, _, data = self.get(f"/api/conversations/{CONV_A}/live", key)
                self.assertEqual((status, data["key"], data["live"]["pid"]), (200, state, 41))
        self.assertIsNone(self.get(f"/api/conversations/{CONV_A}/live")[2]["send_problem"])
        self.assertEqual(self.get(f"/api/conversations/{CONV_B}/live")[2], {"live": None, "key": "missing", "send_problem": None})

    def test_send(self):
        with mock.patch("ctokens.web.server.send", return_value={"pid": 41}) as send:
            status, data = self.post(CONV_A, {"text": "hello"}, origin=f"http://127.0.0.1:{self.port}")
        self.assertEqual((status, data), (200, {"sent": True, "live": {"pid": 41}}))
        self.assertEqual(send.call_args.args[1:], (CONV_A, "hello"))
        self.assertEqual(send.call_args.args[0], self.projects.parent / "sessions")

    def test_send_refusals(self):
        cases = (({"key": None}, {"text": "hi"}, 403, "send key missing"),
                 ({"key": "nope"}, {"text": "hi"}, 403, "wrong send key"),
                 ({"origin": "http://evil.example"}, {"text": "hi"}, 403, "origin not allowed"),
                 ({"content_type": "text/plain"}, {"text": "hi"}, 415, "expected application/json"),
                 ({}, {"message": "hi"}, 400, 'expected {"text": "..."}'),
                 ({}, b"not json", 400, "expected a JSON object"))
        with mock.patch("ctokens.web.server.send") as send:
            for options, body, code, error in cases:
                with self.subTest(error=error, options=options):
                    status, data = self.post(CONV_A, body, **options)
                    self.assertEqual((status, data["error"]), (code, error))
        send.assert_not_called()

    def test_send_to_session_that_cannot_take_it(self):
        record(self.sessions, 41, CONV_A, status="waiting", waitingFor="permission prompt")
        status, data = self.post(CONV_A, {"text": "hi"})
        self.assertEqual(status, 409)
        self.assertIn("permission prompt", data["error"])
        self.assertEqual(self.post("55555555-5555-4555-8555-555555555555", {"text": "hi"})[0], 404)

    def test_disabled_without_key(self):
        server, thread = start_server(Config(self.projects, load_prices(None)))
        self.addCleanup(stop_server, server, thread)
        self.port = server.server_address[1]
        self.assertEqual(self.post(CONV_A, {"text": "hi"}), (403, {"error": "sending is disabled", "key": "disabled"}))

    def test_methods(self):
        status, headers, _ = http_request(self.port, f"/api/conversations/{CONV_A}/send")
        self.assertEqual((status, headers["Allow"]), (405, "POST"))
        status, headers, _ = http_request(self.port, f"/api/conversations/{CONV_A}/send", "PUT", body=b"{}")
        self.assertEqual((status, headers["Allow"]), (405, "POST"))
        self.assertEqual(http_request(self.port, f"/api/conversations/{CONV_A}/send", "POST", host="evil.example",
                                      body=b"{}")[0], 403)

    def test_new_session_without_log_is_listed_and_opens(self):
        fresh = "55555555-5555-4555-8555-555555555555"
        fake_process(self.proc, 50)
        record(self.sessions, 50, fresh, cwd="/home/dev/projects/scratch", startedAt=1999999999000)
        rows = self.get("/api/conversations")[2]["conversations"]
        self.assertEqual(rows[0]["id"], fresh)
        self.assertEqual({k: rows[0][k] for k in ("new", "project", "title", "size_bytes", "modified")},
                         {"new": True, "project": "/home/dev/projects/scratch", "title": "", "size_bytes": 0,
                          "modified": "2033-05-18T03:33:19Z"})
        self.assertEqual(sum(row["id"] == CONV_A for row in rows), 1)
        self.assertNotIn(fresh, [r["id"] for r in self.get("/api/conversations?project=billing")[2]["conversations"]])
        self.assertNotIn(fresh, [r["id"] for r in self.get("/api/conversations?q=cache")[2]["conversations"]])
        self.assertEqual(self.get(f"/api/conversations/{fresh}/messages")[2]["messages"], [])
        self.assertEqual(self.get(f"/api/conversations/{fresh}/bash")[2], {"bash_commands": []})
        self.assertEqual(self.get(f"/api/conversations/{fresh}")[0], 404)
        self.assertEqual(self.get(f"/api/conversations/{fresh}/live")[2]["live"]["pid"], 50)
        with mock.patch("ctokens.web.server.send", return_value={"pid": 50}):
            self.assertEqual(self.post(fresh, {"text": "hi"})[0], 200)

    def test_go_live_resumes_in_the_conversation_folder(self):
        with mock.patch("ctokens.web.server.go_live", return_value={"pid": 60}) as go:
            self.assertEqual(self.post(CONV_B, {}), (200, {"started": True, "live": {"pid": 60}}))
        self.assertEqual(go.call_args.args, (self.projects.parent / "sessions", CONV_B, "/home/dev/projects/billing-service"))

    def test_new_session_in_the_conversation_folder(self):
        with mock.patch("ctokens.web.server.new_session", return_value=("66666666-6666-4666-8666-666666666666", {"pid": 61})) as new:
            status, data = self.post(CONV_B, {}, action="new-session")
        self.assertEqual((status, data["session_id"]), (200, "66666666-6666-4666-8666-666666666666"))
        self.assertEqual(new.call_args.args, (self.projects.parent / "sessions", "/home/dev/projects/billing-service"))

    def test_start_actions_need_the_key(self):
        for action in ("go-live", "new-session"):
            with self.subTest(action=action), mock.patch("ctokens.web.server.go_live") as go, \
                    mock.patch("ctokens.web.server.new_session") as new:
                self.assertEqual(self.post(CONV_B, {}, key="nope", action=action)[0], 403)
                go.assert_not_called()
                new.assert_not_called()


class RenameAndFavoritesApiTest(LiveApiCase):
    def log(self, folder, conversation_id):
        return self.projects / folder / f"{conversation_id}.jsonl"

    def test_live_session_renames_itself_and_the_answer_waits_for_its_log(self):
        def rename(sessions, conversation_id, title):
            with self.log(API, conversation_id).open("a") as f:
                f.write(json.dumps({"type": "custom-title", "customTitle": f"{title}-2"}) + "\n")
        with mock.patch("ctokens.web.server.rename", side_effect=rename) as typed:
            self.assertEqual(self.post(CONV_A, {"title": " Release\nnotes "}, action="rename"), (200, {"title": "Release notes-2"}))
        self.assertEqual(typed.call_args.args, (self.projects.parent / "sessions", CONV_A, "Release notes"))

    def test_live_session_that_does_not_take_the_name(self):
        with mock.patch("ctokens.web.server.rename"), mock.patch.object(web_server, "RENAME_TIMEOUT", 0.2):
            status, data = self.post(CONV_A, {"title": "Name"}, action="rename")
        self.assertEqual(status, 409)
        self.assertIn("did not take the new name", data["error"])

    def test_live_session_without_a_terminal_is_not_written_behind_its_back(self):
        record(self.sessions, 41, CONV_A, entrypoint="sdk-cli")
        before = self.log(API, CONV_A).read_bytes()
        status, data = self.post(CONV_A, {"title": "Name"}, action="rename")
        self.assertEqual(status, 409)
        self.assertIn("interactive terminal", data["error"])
        self.assertEqual(self.log(API, CONV_A).read_bytes(), before)

    def test_conversation_no_process_runs_is_renamed_in_its_log(self):
        with mock.patch("ctokens.web.server.rename") as typed:
            self.assertEqual(self.post(CONV_B, {"title": "Ledger work"}, action="rename"), (200, {"title": "Ledger work"}))
        typed.assert_not_called()
        self.assertIn('"customTitle":"Ledger work"', self.log(BILLING, CONV_B).read_text())
        rows = {r["id"]: r for r in self.get("/api/conversations")[2]["conversations"]}
        self.assertEqual(rows[CONV_B]["title"], "Ledger work")

    def test_rename_refusals(self):
        cases = (({"key": "nope"}, {"title": "x"}, 403), ({"key": None}, {"title": "x"}, 403), ({}, {"title": " \n "}, 400),
                 ({}, {"name": "x"}, 400), ({}, {"title": "x" * 201}, 400))
        with mock.patch("ctokens.web.server.rename") as typed, mock.patch("ctokens.web.server.save_title") as saved:
            for options, body, code in cases:
                with self.subTest(body=body, options=options):
                    self.assertEqual(self.post(CONV_B, body, action="rename", **options)[0], code)
            self.assertEqual(self.post(CONV_A, {"title": "Add request-cache invalidation"}, action="rename"),
                             (200, {"title": "Add request-cache invalidation"}))
        typed.assert_not_called()
        saved.assert_not_called()

    def test_favorites_need_no_key_and_show_whatever_the_filters(self):
        self.assertEqual(self.post(CONV_B, {"favorite": True}, key=None, action="favorite"), (200, {"favorite": True}))
        self.assertEqual(self.post(CONV_A, {"favorite": True}, key=None, action="favorite"), (200, {"favorite": True}))
        data = self.get("/api/conversations?project=billing")[2]
        self.assertEqual([r["id"] for r in data["favorites"]], [CONV_A, CONV_B])
        self.assertEqual(data["favorites"][0]["live"]["pid"], 41)
        self.assertEqual(data["favorites"][1], {"id": CONV_B, "title": "", "project": "/home/dev/projects/billing-service",
                                                "modified": data["favorites"][1]["modified"]})
        self.assertEqual({r["id"]: r.get("favorite") for r in data["conversations"]}[CONV_B], True)
        self.assertEqual(self.post(CONV_A, {"favorite": False}, key=None, action="favorite"), (200, {"favorite": False}))
        data = self.get("/api/conversations")[2]
        self.assertEqual([r["id"] for r in data["favorites"]], [CONV_B])
        self.assertNotIn("favorite", {r["id"]: r for r in data["conversations"]}[CONV_A])
        stored = json.loads((self.projects.parent / "claude-tokens" / "favorites.json").read_text())
        self.assertEqual(stored, {"favorites": [CONV_B]})

    def test_favorite_refusals(self):
        cases = (({"origin": "http://evil.example"}, {"favorite": True}, 403), ({}, {"favorite": "yes"}, 400),
                 ({"content_type": "text/plain"}, {"favorite": True}, 415))
        for options, body, code in cases:
            with self.subTest(body=body, options=options):
                self.assertEqual(self.post(CONV_B, body, action="favorite", **options)[0], code)
        self.assertEqual(self.post("55555555-5555-4555-8555-555555555555", {"favorite": True}, action="favorite")[0], 404)
        self.assertEqual(self.get("/api/conversations")[2]["favorites"], [])


class LaunchTest(LiveTestCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.fail_new_window = False
        mock.patch.object(live.subprocess, "run", side_effect=self.tmux).start()
        mock.patch.object(live.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)
        self.folder = Path(self.tmp.name) / "my project"
        self.folder.mkdir()

    def tmux(self, command, **kwargs):
        self.calls.append(command)
        if "new-window" in command and self.fail_new_window:
            return subprocess.CompletedProcess(command, 1, "", "no server running")
        if "new-window" in command or "new-session" in command:
            fake_process(self.proc, 70, env={"TMUX": f"{SOCKET},1,0", "TMUX_PANE": "%90"})
            record(self.sessions, 70, CONV_B, cwd=str(self.folder))
            return subprocess.CompletedProcess(command, 0, "%90\n", "")
        return tmux_ok(command)

    def test_go_live_types_the_resume_command_in_a_new_window(self):
        info = live.go_live(self.sessions, CONV_B, str(self.folder))
        self.assertEqual(info["pid"], 70)
        self.assertEqual(self.calls[0][:3], ["tmux", "new-window", "-d"])
        self.assertIn(str(self.folder), self.calls[0])
        self.assertEqual(self.calls[1], ["tmux", "send-keys", "-t", "%90", "-l",
                                         f"cd '{self.folder}' && claude --resume {CONV_B}"])
        self.assertEqual(self.calls[2], ["tmux", "send-keys", "-t", "%90", "Enter"])

    def test_new_session_finds_the_session_of_its_pane_and_starts_a_server_if_needed(self):
        self.fail_new_window = True
        self.assertEqual(live.new_session(self.sessions, str(self.folder))[0], CONV_B)
        self.assertEqual(self.calls[1][1], "new-session")
        self.assertEqual(self.calls[2][-1], f"cd '{self.folder}' && claude")

    def test_already_live_or_missing_folder(self):
        fake_process(self.proc, 41)
        record(self.sessions, 41, CONV_A)
        with self.assertRaisesRegex(live.SendError, "already running"):
            live.go_live(self.sessions, CONV_A, str(self.folder))
        with self.assertRaisesRegex(live.SendError, "does not exist"):
            live.new_session(self.sessions, str(self.folder / "gone"))
        self.assertEqual(self.calls, [])

    def test_not_registered_in_time(self):
        with mock.patch.object(live, "START_TIMEOUT", 0):
            self.assertIsNone(live.go_live(self.sessions, CONV_A, str(self.folder)))


class GrowingTranscriptTest(unittest.TestCase):
    """A Transcript advanced while its log is written gives what one read of the finished log gives."""

    def test_advance_matches_one_read_at_every_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = build_projects(tmp)
            source = next(projects.glob(f"*/{CONV_A}.jsonl"))
            data, prices = source.read_bytes(), load_prices(None)
            whole = transcript(source, prices)
            grow = Path(tmp) / "grow.jsonl"
            for step in (1, 7, 250):
                with self.subTest(step=step):
                    grow.write_bytes(b"")
                    reader = Transcript(grow, prices)
                    for end in [*range(0, len(data), step), len(data)]:
                        grow.write_bytes(data[:end])
                        reader.advance()
                    self.assertEqual(reader.messages, whole)

    def test_rewritten_log_starts_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = build_projects(tmp)
            log = next(projects.glob(f"*/{CONV_A}.jsonl"))
            prices = load_prices(None)
            reader = Transcript(log, prices)
            reader.advance()
            first = log.read_text().splitlines(keepends=True)[0]
            log.write_text(first)
            self.assertEqual(reader.advance(), transcript(log, prices))


class RealTimeApiTest(LiveApiCase):
    def log(self):
        return next(self.projects.glob(f"*/{CONV_A}.jsonl"))

    def test_messages_from(self):
        _, _, full = self.get(f"/api/conversations/{CONV_A}/messages")
        _, _, part = self.get(f"/api/conversations/{CONV_A}/messages?from=2")
        self.assertEqual(part, {"source": "main", "from": 2, "total": len(full["messages"]), "messages": full["messages"][2:]})
        with self.log().open("a") as f:
            f.write(json.dumps(user("one more prompt", "/home/dev/projects/api-gateway", "2026-09-21T15:00:00Z", "u-more")) + "\n")
        _, _, grown = self.get(f"/api/conversations/{CONV_A}/messages?from={len(full['messages'])}")
        self.assertEqual([m["blocks"][0]["text"] for m in grown["messages"]], ["one more prompt"])
        self.assertEqual(self.get(f"/api/conversations/{CONV_A}/messages?from=x")[0], 400)
        self.assertEqual(self.get(f"/api/conversations/{CONV_A}/messages?from=0&source=nope")[0], 404)

    def test_events_report_log_growth_and_session_changes(self):
        with mock.patch("ctokens.web.server.EVENT_TICK", 0.02):
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            self.addCleanup(connection.close)
            connection.request("GET", f"/api/conversations/{CONV_A}/events")
            response = connection.getresponse()
            self.assertEqual((response.status, response.headers["Content-Type"]), (200, "text/event-stream; charset=utf-8"))
            time.sleep(0.2)
            with self.log().open("a") as f:
                f.write(json.dumps(user("typed from the web", "/home/dev/projects/api-gateway", "2026-09-21T15:00:01Z", "u-web")) + "\n")
            self.assertEqual(self.next_event(response)[0], "log")
            record(self.sessions, 41, CONV_A, status="busy", updatedAt=1790000099000)
            event, data = self.next_event(response)
            self.assertEqual((event, data["live"]["status"]), ("live", "busy"))
            (self.sessions / "41.json").unlink()
            for _ in range(3):
                event, data = self.next_event(response)
                if event == "live":
                    break
            self.assertEqual(data, {"live": None, "send_problem": None})

    @staticmethod
    def next_event(response):
        event = None
        while True:
            line = response.fp.readline().decode().rstrip("\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event:
                return event, json.loads(line[6:])

    def test_events_of_unknown_conversation(self):
        self.assertEqual(self.get("/api/conversations/55555555-5555-4555-8555-555555555555/events")[0], 404)


class ActivityTest(LiveTestCase):
    def test_status_line_of_a_working_session(self):
        screen = "● Reading files\n✻ Cooking… (12s · ↓ 1.2k tokens · esc to interrupt)\n─────\n❯ \n"
        with mock.patch.object(live.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, screen, "")):
            self.assertEqual(live.activity(SOCKET, PANE), "Cooking… (12s · ↓ 1.2k tokens)")
        with mock.patch.object(live.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, "✻ Churned for 1s · done 7:33 AM\n❯ \n", "")):
            self.assertIsNone(live.activity(SOCKET, PANE))
