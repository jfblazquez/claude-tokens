"""Running Claude Code sessions: the registry Claude Code keeps in <config>/sessions, and typing into their tmux pane."""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import time
import uuid
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
# An image path pasted on its own becomes an [Image #N] attachment in the prompt, once Claude Code has read the file.
IMAGE_MARK = re.compile(r"\[Image #(\d+)\]")
IMAGE_TYPES = {"image/png": (".png", (b"\x89PNG\r\n\x1a\n",)), "image/jpeg": (".jpg", (b"\xff\xd8\xff",)),
               "image/gif": (".gif", (b"GIF87a", b"GIF89a")), "image/webp": (".webp", (b"RIFF",))}
MAX_IMAGE_BYTES = 10 << 20
MAX_IMAGES = 20
# Long enough for a message sent a while after its images were pasted, or for the session to read them again.
IMAGE_KEEP = 24 * 3600
PASTE_DELAY = 0.3
# Claude Code wraps a paste of 20 characters or more in <pasted_content> tags, and takes over 800 characters read at
# once for a paste too, so a message is typed in smaller batches.
TYPE_BATCH = 400
TYPE_DELAY = 0.03
# A file name after @ keeps the completion menu open, and the Enter would pick from it instead of sending.
OPEN_MENTION = re.compile(r"(?:^|\s)@\S*$")
# Claude Code saves as it goes and removes its session record on SIGTERM; this is how long that may take.
STOP_TIMEOUT = 5
# The tmux window option that marks the windows this tool opened, which go away with their session.
OWN_WINDOW = "@ctokens"
# A new claude registers its session within a few seconds; past this the UI keeps looking for it on its own.
START_TIMEOUT = 30
START_POLL = 0.5
# The spinner glyph cycles; the verb ends in an ellipsis and the elapsed time and tokens follow in parentheses.
SPINNER = re.compile(r"^[·✢✳✶✻✽*]\s+(\S[^…]*….*?)\s*$")
# The prompt box sits between two rules; its first character is ❯ (or >) for a message and ! in shell mode.
RULE = re.compile(r"^\s*[─━]{8}")
PROMPT_MARKS = {"❯": "prompt", ">": "prompt", "!": "shell"}
# A dialog (a question, a permission prompt) lists its choices as "1. Yes", the highlighted one behind ❯; a multiple
# choice question puts a box in front of each label.
OPTION = re.compile(r"^(\s*)(❯)?\s*([1-9])\.\s+(\S.*?)\s*$")
CHECKBOX = re.compile(r"^\[([ ✔])\]\s*")
UNNUMBERED = re.compile(r"^\s*(❯)?\s*(\S.*?)\s*$")
DASHES = re.compile(r"^\s*[╌─━]+$")
# What the page can press in a dialog: a choice's digit, moving between choices and questions, confirming, cancelling.
DIALOG_KEYS = frozenset({"Enter", "Escape", "Up", "Down", "Left", "Right", "Tab", *"123456789"})
MAX_DIALOG_STEPS = 8
# Room for Claude Code to take a key before the next one, and to draw the dialog again before it is read back.
STEP_DELAY = 0.15


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
    """What the API shows of a live session: read_only when no message can ever be typed into it, its status as its
    screen shows it, and the dialog it waits on."""
    try:
        socket, pane = channel(info)
        problem = None
    except SendError as error:
        problem = str(error)
    status, shown = info.get("status"), None
    if problem is None:
        lines = screen(socket, pane)
        status = screen_status(status, prompt_mode(socket, pane, lines))
        shown = dialog(lines) if status == "waiting" else None
    return {**{key: value for key, value in info.items() if key != "updated_ms"}, "status": status, "dialog": shown,
            "read_only": problem is not None, "read_only_reason": problem}


def screen_status(status, mode):
    """Claude Code does not always write the registry when shell mode ends, and typing into shell mode runs a command,
    so the screen has the last word on shell mode either way."""
    if status in SENDABLE and mode == "shell":
        return "shell"
    if status == "shell" and mode == "prompt":
        return "idle"
    return status


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


def screen(socket, pane):
    """The lines the session's pane shows now; [] when it cannot be read."""
    try:
        return tmux(socket, "capture-pane", "-p", "-t", pane).splitlines()
    except SendError:
        return []


def prompt_mode(socket, pane, lines=None):
    """'prompt' or 'shell' from the prompt box on the session's screen; None when no box is found."""
    lines = screen(socket, pane) if lines is None else lines
    rules = [i for i, line in enumerate(lines) if RULE.match(line)]
    for top, bottom in zip(rules[-2::-1], rules[:0:-1]):
        inside = [line.strip() for line in lines[top + 1:bottom] if line.strip()]
        if inside:
            return PROMPT_MARKS.get(inside[0][0])
    return None


def dialog(lines):
    """The dialog at the bottom of a screen: {"text", "question", "options", "hint"}, or None when there is none.
    Its text starts below the rule above its first choice; the tool behind it is only logged once it is answered."""
    lines = [line.rstrip() for line in lines]
    while lines and not lines[-1]:
        lines.pop()
    numbered = [i for i, line in enumerate(lines) if OPTION.match(line)]
    first = next((i for i in reversed(numbered) if OPTION.match(lines[i]).group(3) == "1"), None)
    if first is None:
        return None
    top = max((i for i in range(first) if RULE.match(lines[i])), default=-1)
    text = lines[top + 1:first]
    while text and not text[0].strip():
        text.pop(0)
    while text and not text[-1].strip():
        text.pop()
    indent = min((len(line) - len(line.lstrip()) for line in text if line.strip() and not DASHES.match(line)), default=0)
    hint = lines[-1].strip() if len(lines) - 1 > numbered[-1] and not lines[-2].strip() else None
    options, column = [], 0
    for line in lines[first:len(lines) - 1 if hint else len(lines)]:
        match = OPTION.match(line)
        if match:
            label, box = match.group(4), CHECKBOX.match(match.group(4))
            column = match.start(4) + (box.end() if box else 0)
            options.append({"key": match.group(3), "label": label[box.end():] if box else label, "detail": "",
                            "current": bool(match.group(2)), "checked": box.group(1) != " " if box else None})
            continue
        item = UNNUMBERED.match(line)
        if not item or RULE.match(line):
            continue
        # Below a choice and in line with its label it goes on with it; further left it is a choice without a digit,
        # such as the Submit of a multiple choice question, reached with the arrows.
        if item.start(2) >= column:
            options[-1]["detail"] = f"{options[-1]['detail']}\n{item.group(2)}".lstrip("\n")
        else:
            options.append({"key": None, "label": item.group(2), "detail": "", "current": bool(item.group(1)),
                            "checked": None})
    question = next((line.strip() for line in reversed(text) if line.strip()), "")
    return {"text": "\n".join(line[indent:] for line in text), "question": question, "options": options, "hint": hint}


def target(info):
    """(tmux socket, pane) showing this session's prompt, or SendError saying why text cannot go there now."""
    socket, pane = channel(info)
    status = info.get("status")
    if status in SENDABLE or status == "shell":
        status = screen_status(status, prompt_mode(socket, pane))
        if status == "shell":
            raise SendError("The session is in shell mode; deal with it in its terminal first.")
    if status not in SENDABLE:
        state = f"waiting ({info['waiting_for']})" if info.get("waiting_for") else STATES.get(status, status)
        raise SendError(f"The session is {state}; deal with it in its terminal first.")
    foreground(info)
    return socket, pane


def foreground(info):
    stat = proc_stat(info["pid"])
    if not stat or stat[2] != stat[5]:
        raise SendError("The session is not in the foreground of its terminal.")


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


def images_dir():
    return Path(tempfile.gettempdir()) / f"ctokens-images-{os.getuid()}"


def save_image(kind, data):
    """An image pasted into the page, as a file only this user can read, for a message to attach; the path."""
    if kind not in IMAGE_TYPES:
        raise SendError("Only PNG, JPEG, GIF and WebP images can be attached.")
    suffix, magics = IMAGE_TYPES[kind]
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise SendError(f"An image can take up to {MAX_IMAGE_BYTES >> 20} MB.")
    if not data.startswith(magics):
        raise SendError("The file is not the image it says it is.")
    folder = images_dir()
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.is_symlink() or folder.stat().st_uid != os.getuid():
        raise SendError(f"{folder} is not this user's own folder.")
    now = time.time()
    for old in folder.iterdir():
        try:
            if now - old.stat().st_mtime > IMAGE_KEEP:
                old.unlink()
        except OSError:
            pass
    path = folder / f"{uuid.uuid4().hex}{suffix}"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return str(path)


def message_parts(text, images):
    """The text cut at its [Image #N] marks, each mark that names a saved image replaced by the image's path."""
    if not images:
        return [text]
    folder = images_dir()
    parts, at = [], 0
    for m in IMAGE_MARK.finditer(text):
        path = images.get(m.group(1))
        if path is None:
            continue
        if Path(path).parent != folder or not Path(path).is_file():
            raise SendError(f"Image #{m.group(1)} is gone; paste it again.")
        parts += [text[at:m.start()], {"image": path}]
        at = m.end()
    parts.append(text[at:])
    return [p for p in parts if p != ""]


def send(directory, session_id, text, images=None):
    """Type text into the prompt of a running session and press Enter, as if typed in its terminal. images:
    {"N": path} for the [Image #N] marks of the text, each pasted as a path that Claude Code attaches."""
    if not text.strip():
        raise SendError("The message is empty.")
    if len(text) > MAX_MESSAGE_CHARS:
        raise SendError(f"The message is longer than {MAX_MESSAGE_CHARS:,} characters.")
    if images is not None and (not isinstance(images, dict) or len(images) > MAX_IMAGES
                               or not all(isinstance(k, str) and isinstance(v, str) for k, v in images.items())):
        raise SendError(f"Expected up to {MAX_IMAGES} images as {{\"N\": path}}.")
    return type_in(directory, session_id, message_parts(text, images))


def rename(directory, session_id, title):
    """Name a running session with its own /rename, which also renames it in its terminal and on claude.ai."""
    return type_in(directory, session_id, f"/rename {title}")


def type_in(directory, session_id, parts):
    """parts: text, or a list of texts and {"image": path}, each image pasted on its own so Claude Code attaches it."""
    info = live_sessions(directory).get(session_id)
    if info is None:
        raise SendError("The conversation is not running in any Claude Code process.")
    socket, pane = target(info)
    for i, part in enumerate([parts] if isinstance(parts, str) else parts):
        if i:
            time.sleep(PASTE_DELAY)
        if isinstance(part, dict):
            buffer = f"ctokens-{os.getpid()}-{time.monotonic_ns()}"
            tmux(socket, "load-buffer", "-b", buffer, "-", text=part["image"])
            tmux(socket, "paste-buffer", "-p", "-d", "-b", buffer, "-t", pane)
        else:
            type_text(socket, pane, part)
    time.sleep(ENTER_DELAY)
    tmux(socket, "send-keys", "-t", pane, "Enter")
    return public(info)


def type_text(socket, pane, text):
    """Typed as keys so the message reads as the user's own words, with Ctrl+J for its line breaks, as Enter would send.
    A Tab would complete a name instead of being typed, so it goes in as spaces."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    if OPEN_MENTION.search(text):
        text += " "
    keys, size = [], 0
    for i, line in enumerate(text.split("\n")):
        pieces = [None] if i else []
        pieces += [line[at:at + TYPE_BATCH] for at in range(0, len(line), TYPE_BATCH)]
        for piece in pieces:
            if keys and size + len(piece or " ") > TYPE_BATCH:
                tmux(socket, *keys[:-1])
                time.sleep(TYPE_DELAY)
                keys, size = [], 0
            keys += ["send-keys", "-t", pane, *(["C-j"] if piece is None else ["-l", "--", piece]), ";"]
            size += len(piece or " ")
    if keys:
        tmux(socket, *keys[:-1])


def dialog_step(step):
    """A key from DIALOG_KEYS or one line of text; a line break would answer the dialog halfway through the text."""
    if not isinstance(step, dict) or len(step) != 1:
        return False
    if "key" in step:
        return step["key"] in DIALOG_KEYS
    text = step.get("text")
    return (isinstance(text, str) and bool(text.strip()) and len(text) <= MAX_MESSAGE_CHARS
            and not any(c in text for c in "\r\n\x1b"))


def answer(directory, session_id, steps):
    """Press keys and type text into the dialog a session waits on, as if in its terminal; its live info after."""
    if not isinstance(steps, list) or not 0 < len(steps) <= MAX_DIALOG_STEPS or not all(map(dialog_step, steps)):
        raise SendError(f"Expected 1 to {MAX_DIALOG_STEPS} steps, each a key ({', '.join(sorted(DIALOG_KEYS))}) "
                        "or one line of text.")
    info = live_sessions(directory).get(session_id)
    if info is None:
        raise SendError("The conversation is not running in any Claude Code process.")
    socket, pane = channel(info)
    # A key meant for a dialog, typed into the prompt instead, would end up in the next message.
    if info.get("status") != "waiting" or dialog(screen(socket, pane)) is None:
        raise SendError("The session is not waiting on a question or a dialog any more.")
    foreground(info)
    for step in steps:
        if "text" in step:
            tmux(socket, "send-keys", "-t", pane, "-l", step["text"])
        else:
            tmux(socket, "send-keys", "-t", pane, step["key"])
        time.sleep(STEP_DELAY)
    found = read_record(Path(directory) / f"{info['pid']}.json")
    return public(found[1]) if found and found[0] == session_id else None


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
    tmux(None, "set-option", "-w", "-t", pane, OWN_WINDOW, "1")
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


def go_offline(directory, session_id):
    """Stop the Claude Code process of a conversation running in tmux, as closing its terminal would; the window goes too
    when this tool opened it, while a pane of the user's keeps its shell. {"stopped": True, "closed_window": bool}."""
    info = live_sessions(directory).get(session_id)
    if info is None:
        raise SendError("The conversation is not running in any Claude Code process.")
    socket, pane = channel(info)
    try:
        own = tmux(socket, "show-options", "-w", "-q", "-v", "-t", pane, OWN_WINDOW).strip() == "1"
    except SendError:
        own = False
    try:
        os.kill(info["pid"], signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as error:
        raise SendError(f"Could not stop process {info['pid']}: {error.strerror or error}") from None
    deadline = time.monotonic() + STOP_TIMEOUT
    while session_id in live_sessions(directory):
        if time.monotonic() > deadline:
            raise SendError(f"Process {info['pid']} has not stopped within {STOP_TIMEOUT} s.")
        time.sleep(START_POLL / 5)
    if own:
        try:
            tmux(socket, "kill-pane", "-t", pane)
        except SendError:
            own = False
    return {"stopped": True, "closed_window": own}


def new_session(directory, cwd):
    """Start a fresh claude in cwd in a new tmux window; (session id, live info), or (None, None) if not registered yet."""
    pane = launch(cwd, f"cd {shlex.quote(cwd)} && claude", "claude-new")
    return wait_for(directory, lambda found, info: info["entrypoint"] == "cli"
                    and environ(info["pid"]).get("TMUX_PANE") == pane)
