"""HTTP server: security gate, routes and JSON responses."""
from __future__ import annotations

import copy
import hmac
import json
import os
import re
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple, Optional
from urllib.parse import parse_qs

from ..catalog import (CONVERSATION_ID, clean_title, conversation_rows, conversation_text, find_conversation, last_recap,
                       project_path_of, save_title, session_title)
from ..content import bash_commands, conversation_messages, last_response, touched_files
from ..live import (SendError, activity, channel, go_live, live_sessions, new_session, public, read_record, rename, send,
                    send_problem, sessions_dir)
from ..logs import conversation_sources, discover, file_stats, parse_log
from ..reports import report, scan_totals, totals_report
from .cache import StatsCache, TranscriptCache
from .favorites import Favorites, favorites_path

HOST = "127.0.0.1"
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
STATIC_DIR = Path(__file__).resolve().parent / "static"
VENDOR_FILES = ("chart.umd.min.js", "marked.min.js", "purify.min.js", "highlight.min.js",
                "hljs-light.css", "hljs-dark.css")
STATIC_FILES = {"/": "index.html", "/static/app.js": "app.js", "/static/analysis.js": "analysis.js",
                "/static/app.css": "app.css",
                **{f"/static/vendor/{name}": f"vendor/{name}" for name in VENDOR_FILES}}
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}
JSON_TYPE = "application/json; charset=utf-8"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
COMMON_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
MAX_DISCARDED_BODY = 1 << 20
MAX_RECAP_IDS = 100
MAX_SEND_BODY = 1 << 20
CONVERSATION_ROUTE = re.compile(r"/api/conversations/([^/]+)(?:/(last-response|bash|files|messages|live))?")
ACTION_ROUTE = re.compile(r"/api/conversations/([^/]+)/(send|go-live|new-session|rename|favorite)")
EVENTS_ROUTE = re.compile(r"/api/conversations/([^/]+)/events")
# The events stream checks the log, the session and its status line this often; a new log line shows within a tick.
EVENT_TICK = 0.25
EVENT_RESCAN = 2.0
ACTIVITY_EVERY = 1.0
HEARTBEAT = 15.0
# EventSource reconnects by itself, so a stream ends now and then instead of holding a thread forever.
STREAM_LIFETIME = 30 * 60
SEND_KEY_HEADER = "X-Send-Key"
MAX_TITLE_CHARS = 200
# A running session writes its new name to the log within a moment of reading /rename.
RENAME_TIMEOUT = 5.0
RENAME_POLL = 0.1


class Config(NamedTuple):
    projects_dir: Path
    prices: dict
    cold_summary_output: int = 2000
    context_window: Optional[int] = None
    # Typing into a session runs whatever it is allowed to run, and any local user can reach 127.0.0.1.
    send_key: Optional[str] = None


class Response(NamedTuple):
    status: int
    body: bytes
    content_type: str = JSON_TYPE
    headers: tuple = ()


def json_response(status, data, headers=()):
    return Response(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), JSON_TYPE, headers)


NOT_FOUND = json_response(404, {"error": "not found"})
KEY_ERRORS = {"disabled": "sending is disabled", "missing": "send key missing", "wrong": "wrong send key"}


class Handler(BaseHTTPRequestHandler):
    server_version = "claude-tokens"
    sys_version = ""

    def __getattr__(self, name):
        # BaseHTTPRequestHandler answers 501 when do_<METHOD> is missing; every other method gets 405.
        if name.startswith("do_"):
            return self.method_not_allowed
        raise AttributeError(name)

    def do_GET(self):
        if not self.host_allowed():
            return
        path, _, query = self.path.partition("?")
        events = EVENTS_ROUTE.fullmatch(path)
        if events:
            return self.events(events.group(1), parse_qs(query).get("source", ["main"])[0])
        try:
            response = self.route(path, query)
        except Exception:
            traceback.print_exc()
            response = json_response(500, {"error": "internal error"})
        self.respond(response)

    do_HEAD = do_GET

    def do_POST(self):
        path = self.path.partition("?")[0]
        match = ACTION_ROUTE.fullmatch(path)
        if not match:
            return self.method_not_allowed()
        if not self.host_allowed():
            return self.discard_body()
        try:
            response = self.action(*match.groups())
        except Exception:
            traceback.print_exc()
            response = json_response(500, {"error": "internal error"})
        self.respond(response)

    def method_not_allowed(self):
        self.discard_body()
        allow = "POST" if ACTION_ROUTE.fullmatch(self.path.partition("?")[0]) else "GET, HEAD"
        if self.host_allowed():
            self.respond(json_response(405, {"error": "method not allowed"}, (("Allow", allow),)))

    def host_allowed(self):
        hosts = self.headers.get_all("Host") or []
        host = hosts[0].strip().lower() if len(hosts) == 1 else ""
        if ":" in host:
            host, _, port = host.rpartition(":")
            if not port.isdigit():
                host = ""
        if host in ALLOWED_HOSTS:
            return True
        self.respond(json_response(403, {"error": "host not allowed"}))
        return False

    def key_state(self):
        key, given = self.server.config.send_key, self.headers.get(SEND_KEY_HEADER)
        if not key:
            return "disabled"
        if not given:
            return "missing"
        return "ok" if hmac.compare_digest(given.encode("utf-8"), key.encode("utf-8")) else "wrong"

    def action(self, conversation_id, name):
        """POST actions start, drive or rename claude sessions, so on top of the Host check they need the key; starring
        a conversation touches only this tool's own file."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 < length <= MAX_SEND_BODY:
            self.close_connection = True
            return json_response(413 if length > MAX_SEND_BODY else 400, {"error": "bad request body"})
        body = self.rfile.read(length)
        origin = self.headers.get("Origin")
        if origin is not None and origin.lower() != f"http://{self.headers.get('Host', '').lower()}":
            return json_response(403, {"error": "origin not allowed"})
        state = self.key_state()
        if state != "ok" and name != "favorite":
            return json_response(403, {"error": KEY_ERRORS[state], "key": state})
        if self.headers.get_content_type() != "application/json":
            return json_response(415, {"error": "expected application/json"})
        try:
            data = json.loads(body.decode("utf-8"))
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return json_response(400, {"error": "expected a JSON object"})
        config = self.server.config
        sessions = sessions_dir(config.projects_dir)
        path, live = locate(config, conversation_id)
        if path is None and live is None:
            return json_response(404, {"error": "conversation not found"})
        if name == "favorite":
            if not isinstance(data.get("favorite"), bool):
                return json_response(400, {"error": "expected {\"favorite\": true|false}"})
            self.server.favorites.set(conversation_id, data["favorite"])
            return json_response(200, {"favorite": data["favorite"]})
        try:
            if name == "rename":
                return self.rename(sessions, conversation_id, path, data.get("title"))
            if name == "send":
                if not isinstance(data.get("text"), str):
                    return json_response(400, {"error": "expected {\"text\": \"...\"}"})
                return json_response(200, {"sent": True, "live": send(sessions, conversation_id, data["text"])})
            cwd = project_path_of(path) if path is not None else live["cwd"]
            if name == "go-live":
                return json_response(200, {"started": True, "live": go_live(sessions, conversation_id, cwd)})
            session_id, info = new_session(sessions, cwd)
            return json_response(200, {"started": True, "session_id": session_id, "live": info})
        except SendError as error:
            return json_response(409, {"error": str(error)})

    def rename(self, sessions, conversation_id, path, title):
        title = clean_title(title) if isinstance(title, str) else ""
        if not title:
            return json_response(400, {"error": "expected {\"title\": \"...\"} with some text"})
        if len(title) > MAX_TITLE_CHARS:
            return json_response(400, {"error": f"the name is longer than {MAX_TITLE_CHARS} characters"})
        old = session_title(path) if path is not None else None
        if old == title:
            return json_response(200, {"title": title})
        if conversation_id not in live_sessions(sessions):
            save_title(path, conversation_id, title)
            return json_response(200, {"title": session_title(path)})
        # Its own /rename, since a running session keeps its name in memory and writes it back to the log.
        rename(sessions, conversation_id, title)
        deadline = time.monotonic() + RENAME_TIMEOUT
        while path is not None:
            new = session_title(path)
            if new != old:
                return json_response(200, {"title": new})
            if time.monotonic() >= deadline:
                raise SendError("The session did not take the new name; look at its terminal.")
            time.sleep(RENAME_POLL)
        return json_response(200, {"title": title})

    def discard_body(self):
        # Closing a socket with unread request data can reset the connection before the client reads the answer.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if 0 < length <= MAX_DISCARDED_BODY:
            self.rfile.read(length)

    def route(self, path, query):
        if path in STATIC_FILES:
            return self.static(STATIC_FILES[path])
        config, cache = self.server.config, self.server.cache
        params = parse_qs(query)
        project = params.get("project", [None])[0]
        if path == "/api/conversations":
            search = params.get("q", [None])[0]
            rows = conversation_rows(config.projects_dir, project, *cached_meta(cache), search, cached_text(cache))
            live = live_sessions(sessions_dir(config.projects_dir))
            starred = self.server.favorites.ids()
            favorites = favorite_rows(starred, live, config.projects_dir, cache)
            for row in rows:
                if row["id"] in live:
                    row["live"] = public(live.pop(row["id"]))
            if not search:
                rows = sorted(rows + new_session_rows(live, project, config.projects_dir), key=lambda r: r["modified"],
                              reverse=True)
            for row in rows:
                if row["id"] in starred:
                    row["favorite"] = True
            return json_response(200, {"projects_dir": str(config.projects_dir), "key": self.key_state(),
                                       "conversations": rows, "favorites": favorites})
        if path == "/api/recaps":
            ids = [i for i in params.get("ids", [""])[0].split(",") if i]
            if len(ids) > MAX_RECAP_IDS:
                return json_response(400, {"error": f"at most {MAX_RECAP_IDS} ids per request"})
            return json_response(200, {"recaps": {i: recap_of(cache, config, i) for i in ids}})
        if path == "/api/totals":
            return json_response(200, cached_totals(cache, config, project))
        if ACTION_ROUTE.fullmatch(path):
            return json_response(405, {"error": "method not allowed"}, (("Allow", "POST"),))
        match = CONVERSATION_ROUTE.fullmatch(path)
        if match:
            first = params.get("from", [None])[0]
            if first is not None and not first.isdigit():
                return json_response(400, {"error": "from must be a message index"})
            return self.conversation(config, cache, *match.groups(), params.get("source", ["main"])[0],
                                     None if first is None else int(first))
        return NOT_FOUND

    def conversation(self, config, cache, conversation_id, view, source, first=None):
        if view == "live":
            info = live_sessions(sessions_dir(config.projects_dir)).get(conversation_id)
            if info is None and find_conversation(conversation_id, config.projects_dir)[0] is None:
                return json_response(404, {"error": "conversation not found"})
            return json_response(200, {"live": info and public(info), "key": self.key_state(),
                                       "send_problem": send_problem(info) if info else None})
        path, matches = find_conversation(conversation_id, config.projects_dir)
        if path is None:
            if len(matches) > 1:
                return json_response(409, {"error": "ambiguous id", "projects": [project_path_of(m) for m in matches]})
            if locate(config, conversation_id)[1] is not None:
                return new_session_view(view, source)
            return json_response(404, {"error": "conversation not found"})
        if view == "last-response":
            return json_response(200, {"last_response": last_response(path)})
        if view == "bash":
            return json_response(200, {"bash_commands": bash_commands(path)})
        if view == "files":
            return json_response(200, {"files": touched_files(path)})
        if view == "messages":
            read = self.server.transcripts.get
            start = first
            if start is None:
                data = conversation_messages(path, source, config.prices, read)
                return json_response(200, data) if data else json_response(404, {"error": "source not found"})
            log = dict(conversation_sources(path)).get(source)
            if log is None:
                return json_response(404, {"error": "source not found"})
            # Only what is new: the client keeps the rest; sources are left out, they take long with many subagents.
            messages = read(log, config.prices)
            return json_response(200, {"source": source, "from": start, "total": len(messages), "messages": messages[start:]})
        return json_response(200, report(discover(path, cached_parse(cache)), config.prices,
                                         config.cold_summary_output, config.context_window))

    def events(self, conversation_id, source):
        """Server-sent events while the page shows a conversation: log (it grew), live (session state), activity."""
        config = self.server.config
        sessions = sessions_dir(config.projects_dir)
        path, live = locate(config, conversation_id)
        if path is None and live is None:
            return self.respond(json_response(404, {"error": "conversation not found"}))
        self.send_response(200)
        for name, value in (("Content-Type", "text/event-stream; charset=utf-8"), *COMMON_HEADERS.items()):
            self.send_header(name, value)
        self.end_headers()
        if self.command == "HEAD":
            return
        self.close_connection = True
        watch = Watch(config, sessions, conversation_id, source)
        watch.check(time.monotonic())
        try:
            while not self.server.stopping.wait(EVENT_TICK) and watch.age() < STREAM_LIFETIME:
                for event, data in watch.check(time.monotonic()):
                    self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
                if watch.heartbeat_due():
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except OSError:
            pass

    def static(self, name):
        try:
            body = (self.server.static_dir / name).read_bytes()
        except OSError:
            return NOT_FOUND
        content_type = CONTENT_TYPES[Path(name).suffix]
        headers = (("Content-Security-Policy", CSP),) if content_type.startswith("text/html") else ()
        return Response(200, body, content_type, headers)

    def respond(self, response):
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for name, value in (*COMMON_HEADERS.items(), *response.headers):
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)

    def send_error(self, code, message=None, explain=None):
        self.close_connection = True
        self.respond(json_response(code, {"error": message or self.responses.get(code, ("error",))[0].lower()}))


class Watch:
    """What an events stream watches: the source's log, the session's registry record and its status line."""

    def __init__(self, config, sessions, conversation_id, source):
        self.config, self.sessions, self.id, self.source = config, sessions, conversation_id, source
        self.started = self.beat = time.monotonic()
        self.log = self.stamp = self.info = self.pane = None
        self.live_key = self.text = None
        self.rescan = self.next_activity = 0.0
        self.first = True

    def age(self):
        return time.monotonic() - self.started

    def heartbeat_due(self):
        if time.monotonic() - self.beat < HEARTBEAT:
            return False
        self.beat = time.monotonic()
        return True

    def log_path(self):
        if self.log is None:
            path, _ = find_conversation(self.id, self.config.projects_dir)
            if path is not None:
                self.log = dict(conversation_sources(path)).get(self.source)
        return self.log

    def session(self, now):
        # The record of a known pid is one small file; finding a session that was not live means reading them all.
        if self.info is not None:
            found = read_record(self.sessions / f"{self.info['pid']}.json")
            self.info = found[1] if found and found[0] == self.id else None
        if self.info is None and now >= self.rescan:
            self.info = live_sessions(self.sessions).get(self.id)
            self.rescan = now + EVENT_RESCAN
        return self.info

    def check(self, now):
        """The events since the last check; the first check only records where things stand."""
        events, first = [], self.first
        self.first = False
        log = self.log_path()
        try:
            stat = os.stat(log) if log else None
            stamp = (stat.st_size, stat.st_mtime_ns) if stat else None
        except OSError:
            stamp = None
        if stamp != self.stamp:
            self.stamp = stamp
            events.append(("log", {"size": stamp and stamp[0]}))
        info = self.session(now)
        key = info and (info["pid"], info["updated_ms"], info["status"])
        if key != self.live_key:
            self.live_key = key
            try:
                self.pane = channel(info) if info else None
            except SendError:
                self.pane = None
            events.append(("live", {"live": info and public(info), "send_problem": info and send_problem(info)}))
        text = self.text
        if not (info and info["status"] == "busy" and self.pane):
            text = None
        elif now >= self.next_activity:
            text = activity(*self.pane)
            self.next_activity = now + ACTIVITY_EVERY
        if text != self.text:
            self.text = text
            events.append(("activity", {"text": text}))
        return [] if first else events


def locate(config, conversation_id):
    """(log path or None, live info or None); a live interactive session has no log until its first message."""
    path, _ = find_conversation(conversation_id, config.projects_dir)
    info = live_sessions(sessions_dir(config.projects_dir)).get(conversation_id)
    return path, info if info and info["entrypoint"] == "cli" and info["cwd"] else None


def new_session_rows(live, project, projects_dir):
    """List rows for interactive sessions still without a log, so a session started from the UI shows up at once."""
    return [{"id": session_id, "modified": info["started"], "size_bytes": 0, "subagents": 0, "project": info["cwd"],
             "title": "", "new": True, "live": public(info)}
            for session_id, info in live.items()
            if info["entrypoint"] == "cli" and info["cwd"] and info["started"] and CONVERSATION_ID.fullmatch(session_id)
            and (not project or project.lower() in info["cwd"].lower())
            and not any(projects_dir.glob(f"*/{session_id}.jsonl"))]


def favorite_rows(ids, live, projects_dir, cache):
    """The starred conversations whatever the filters, most recently active first; those gone are left out."""
    project_of, title_of = cached_meta(cache)
    rows = []
    for conversation_id in ids:
        path, _ = find_conversation(conversation_id, projects_dir)
        info = live.get(conversation_id)
        if path is not None:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            row = {"id": conversation_id, "title": title_of(path), "project": project_of(path),
                   "modified": datetime.fromtimestamp(mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        elif info is not None and info["entrypoint"] == "cli" and info["cwd"] and info["started"]:
            row = {"id": conversation_id, "title": "", "project": info["cwd"], "modified": info["started"], "new": True}
        else:
            continue
        if info is not None:
            row["live"] = public(info)
        rows.append(row)
    return sorted(rows, key=lambda r: r["modified"], reverse=True)


def new_session_view(view, source):
    if view == "messages":
        if source != "main":
            return json_response(404, {"error": "source not found"})
        return json_response(200, {"source": "main", "sources": [{"id": "main", "task": ""}], "messages": [],
                                   "from": 0, "total": 0})
    if view == "last-response":
        return json_response(200, {"last_response": ""})
    if view == "bash":
        return json_response(200, {"bash_commands": []})
    if view == "files":
        return json_response(200, {"files": {}})
    return json_response(404, {"error": "This session has no messages yet."})


def cached_totals(cache, config, project):
    seen = set()

    def stats(path):
        seen.add(Path(path))
        return cache.get("file_stats", path, file_stats)

    data = totals_report(scan_totals(config.projects_dir, project, stats=stats), config.prices)
    cache.prune(seen)
    return data


def cached_parse(cache):
    def parse(path, kind, identifier, task):
        value = cache.get("parse_log", path, lambda p: parse_log(p, kind, identifier, task))
        # report() adds costs to these dicts; kind, id and task come from the caller (task may live in .meta.json).
        return {**copy.deepcopy(value), "kind": kind, "id": identifier, "task": task}
    return parse


def cached_meta(cache):
    def meta(path):
        return cache.get("meta", path, lambda p: (project_path_of(p), session_title(p)))
    return (lambda path: meta(path)[0]), (lambda path: meta(path)[1])


def recap_of(cache, config, conversation_id):
    """None also for an unknown or ambiguous id: the list shows those without a recap."""
    path, _ = find_conversation(conversation_id, config.projects_dir)
    try:
        return None if path is None else cache.get("recap", path, last_recap)
    except OSError:
        return None


def cached_text(cache):
    return lambda path: cache.get("text", path, conversation_text)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # SO_REUSEPORT would let two servers share the port instead of failing (R1.5).
    allow_reuse_port = False

    def __init__(self, config, port, static_dir=STATIC_DIR):
        self.config = config
        self.static_dir = Path(static_dir)
        self.cache = StatsCache()
        self.transcripts = TranscriptCache()
        self.favorites = Favorites(favorites_path(config.projects_dir))
        self.stopping = threading.Event()
        super().__init__((HOST, port), Handler)

    def server_close(self):
        self.stopping.set()
        super().server_close()
