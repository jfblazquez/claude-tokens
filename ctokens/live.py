"""Running Claude Code sessions: the registry Claude Code keeps in <config>/sessions, and typing into their tmux pane."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

PROC = Path("/proc")
# A prompt typed while the model works is queued for the next turn; any other state (a permission prompt or another
# dialog, shell mode) would take the text, and the Enter after it, as its own input.
SENDABLE = frozenset({"idle", "busy"})
STATES = {"shell": "in shell mode", None: "in an unknown state"}
MAX_MESSAGE_CHARS = 100_000
TMUX_TIMEOUT = 5
# Claude Code may still be handling the paste when the Enter arrives right behind it.
ENTER_DELAY = 0.3
# A new claude registers its session within a few seconds; past this the UI keeps looking for it on its own.
START_TIMEOUT = 30
START_POLL = 0.5
# The spinner glyph cycles; the verb ends in an ellipsis and the elapsed time and tokens follow in parentheses.
SPINNER = re.compile(r"^[·✢✳✶✻✽*]\s+(\S[^…]*….*?)\s*$")


class SendError(Exception):
    pass


def sessions_dir(projects_dir):
    return Path(projects_dir).parent / "sessions"


def iso_ms(ms):
    if not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def proc_stat(pid):
    """Fields of /proc/<pid>/stat after the command name (field 3 first); None when there is no such process."""
    try:
        data = (PROC / str(pid) / "stat").read_text()
    except OSError:
        return None
    return data[data.rfind(")") + 2:].split()


def running(record):
    """The registry outlives crashed processes and pids get reused: the start time must match too."""
    pid, start = record.get("pid"), record.get("procStart")
    if not isinstance(pid, int) or pid <= 0:
        return False
    if not (PROC / "self" / "stat").exists():
        try:
            os.kill(pid, 0)
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    stat = proc_stat(pid)
    return stat is not None and len(stat) > 19 and (start is None or stat[19] == str(start))


def read_record(path):
    """(session id, info) of a registry record whose process is running, else None."""
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    session_id = record.get("sessionId") if isinstance(record, dict) else None
    if not isinstance(session_id, str) or not running(record):
        return None
    return session_id, {
        "pid": record["pid"], "status": record.get("status"), "waiting_for": record.get("waitingFor"),
        "status_since": iso_ms(record.get("statusUpdatedAt")), "started": iso_ms(record.get("startedAt")),
        "name": record.get("name"), "entrypoint": record.get("entrypoint"), "version": record.get("version"),
        "cwd": record.get("cwd"), "updated_ms": record.get("updatedAt") or 0,
    }


def live_sessions(directory):
    """session id -> what the UI shows of its running process; the most recently updated one when several share it."""
    sessions = {}
    try:
        names = [p for p in Path(directory).iterdir() if p.suffix == ".json" and p.stem.isdigit()]
    except OSError:
        return sessions
    for path in names:
        found = read_record(path)
        if found is None:
            continue
        session_id, info = found
        old = sessions.get(session_id)
        if old is None or old["updated_ms"] < info["updated_ms"]:
            sessions[session_id] = info
    return sessions


def public(info):
    """What the API shows of a live session: read_only when no message can ever be typed into it."""
    try:
        channel(info)
        problem = None
    except SendError as error:
        problem = str(error)
    return {**{key: value for key, value in info.items() if key != "updated_ms"},
            "read_only": problem is not None, "read_only_reason": problem}


def tmux(socket, *args, text=None):
    command = ["tmux", *(["-S", socket] if socket else []), *args]
    try:
        result = subprocess.run(command, input=text, capture_output=True, text=True, timeout=TMUX_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SendError(f"tmux failed: {error}") from None
    if result.returncode:
        raise SendError(f"tmux failed: {result.stderr.strip() or result.returncode}")
    return result.stdout


def environ(pid):
    try:
        data = (PROC / str(pid) / "environ").read_bytes()
    except OSError:
        return {}
    pairs = (item.decode("utf-8", "replace").partition("=") for item in data.split(b"\0") if item)
    return {name: value for name, _, value in pairs}


def channel(info):
    """(tmux socket, pane) that is this session's terminal, or SendError when it has none for as long as it runs."""
    if info.get("entrypoint") != "cli":
        raise SendError("This session does not run in an interactive terminal.")
    pid = info["pid"]
    env = environ(pid)
    pane = env.get("TMUX_PANE")
    if not env.get("TMUX") or not pane:
        raise SendError("The session is not running inside tmux.")
    socket = env["TMUX"].split(",")[0]
    try:
        tty = os.readlink(PROC / str(pid) / "fd" / "0")
    except OSError:
        raise SendError("The terminal of the session cannot be read.") from None
    # TMUX_PANE is inherited, so a claude started from another one's shell names its parent's pane.
    if tmux(socket, "display-message", "-p", "-t", pane, "#{pane_tty}").strip() != tty:
        raise SendError("The session's tmux pane shows another program.")
    return socket, pane


def target(info):
    """(tmux socket, pane) showing this session's prompt, or SendError saying why text cannot go there now."""
    socket, pane = channel(info)
    status = info.get("status")
    if status not in SENDABLE:
        state = f"waiting ({info['waiting_for']})" if info.get("waiting_for") else STATES.get(status, status)
        raise SendError(f"The session is {state}; deal with it in its terminal first.")
    stat = proc_stat(info["pid"])
    if not stat or stat[2] != stat[5]:
        raise SendError("The session is not in the foreground of its terminal.")
    return socket, pane


def activity(socket, pane):
    """The line Claude Code shows while it works, such as "Forming… (2m 10s · ↓ 11.0k tokens)"; None when there is none."""
    try:
        screen = tmux(socket, "capture-pane", "-p", "-t", pane)
    except SendError:
        return None
    found = None
    for line in screen.splitlines():
        match = SPINNER.match(line)
        if match:
            found = match.group(1).replace(" · esc to interrupt", "")
    return found


def send_problem(info):
    """Why text cannot be typed into this session now, or None when it can."""
    try:
        target(info)
    except SendError as error:
        return str(error)
    return None


def send(directory, session_id, text):
    """Type text into the prompt of a running session and press Enter, as if typed in its terminal."""
    if not text.strip():
        raise SendError("The message is empty.")
    if len(text) > MAX_MESSAGE_CHARS:
        raise SendError(f"The message is longer than {MAX_MESSAGE_CHARS:,} characters.")
    return type_in(directory, session_id, text)


def rename(directory, session_id, title):
    """Name a running session with its own /rename, which also renames it in its terminal and on claude.ai."""
    return type_in(directory, session_id, f"/rename {title}")


def type_in(directory, session_id, text):
    info = live_sessions(directory).get(session_id)
    if info is None:
        raise SendError("The conversation is not running in any Claude Code process.")
    socket, pane = target(info)
    # A bracketed paste keeps line breaks in the prompt instead of sending each line on its own.
    buffer = f"ctokens-{os.getpid()}-{time.monotonic_ns()}"
    tmux(socket, "load-buffer", "-b", buffer, "-", text=text)
    tmux(socket, "paste-buffer", "-p", "-d", "-b", buffer, "-t", pane)
    time.sleep(ENTER_DELAY)
    tmux(socket, "send-keys", "-t", pane, "Enter")
    return public(info)


def launch(cwd, command, name):
    """Run command in the user's shell in a new background tmux window; the tmux pane id."""
    if not cwd or not Path(cwd).is_dir():
        raise SendError(f"The folder {cwd} does not exist any more.")
    window = ("-d", "-P", "-F", "#{pane_id}", "-n", name, "-c", cwd)
    try:
        pane = tmux(None, "new-window", *window).strip()
    except SendError:
        pane = tmux(None, "new-session", "-s", f"claude-{os.getpid()}", *window).strip()
    # Typed into an interactive shell rather than run by tmux, so the user's aliases and functions for claude apply.
    tmux(None, "send-keys", "-t", pane, "-l", command)
    tmux(None, "send-keys", "-t", pane, "Enter")
    return pane


def wait_for(directory, found):
    """(session id, info) of the first live session found accepts, or (None, None) when none shows up in time."""
    deadline = time.monotonic() + START_TIMEOUT
    while True:
        for session_id, info in live_sessions(directory).items():
            # A session registers before its first status; until then the UI could only say it is in an unknown state.
            if info["status"] and found(session_id, info):
                return session_id, public(info)
        if time.monotonic() >= deadline:
            return None, None
        time.sleep(START_POLL)


def go_live(directory, session_id, cwd):
    """Resume a conversation in a new tmux window; its live info, or None when it has not registered yet."""
    if session_id in live_sessions(directory):
        raise SendError("The conversation is already running in a Claude Code process.")
    launch(cwd, f"cd {shlex.quote(cwd)} && claude --resume {shlex.quote(session_id)}", f"claude-{session_id[:8]}")
    return wait_for(directory, lambda found, info: found == session_id)[1]


def new_session(directory, cwd):
    """Start a fresh claude in cwd in a new tmux window; (session id, live info), or (None, None) if not registered yet."""
    pane = launch(cwd, f"cd {shlex.quote(cwd)} && claude", "claude-new")
    return wait_for(directory, lambda found, info: info["entrypoint"] == "cli"
                    and environ(info["pid"]).get("TMUX_PANE") == pane)
