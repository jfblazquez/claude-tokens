"""Finding conversations in the projects folder."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .logs import lines, subagent_logs


def default_projects_dir():
    root = os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")
    return Path(root) / "projects"


def project_path_of(path):
    """Real cwd stored in the log; fall back to the encoded folder name."""
    for event in lines(path):
        cwd = event.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd
    return "/" + path.parent.name.lstrip("-").replace("-", "/")


def session_title(path, tail=131072):
    """The session's name: its last rename (customTitle), else its last generated title (aiTitle); empty when none."""
    try:
        with path.open("rb") as f:
            size = path.stat().st_size
            if size > tail:
                f.seek(-tail, 2)
            data = f.read()
    except OSError:
        return ""
    custom = ai = None
    for line in data.decode("utf-8", "ignore").splitlines():
        key = "customTitle" if '"customTitle"' in line else "aiTitle" if '"aiTitle"' in line else None
        if key is None:
            continue
        try:
            value = json.loads(line).get(key)
        except (json.JSONDecodeError, AttributeError):
            continue
        if key == "customTitle" and isinstance(value, str):
            custom = value
        elif value:
            ai = value
    # Claude Code writes the name to the log again now and then; a rename older than the tail is only in its sidecar.
    if custom is None:
        custom = sidecar_title(path)
    return custom or ai or ""


def title_sidecar(path):
    return path.parent / path.stem / "custom-title.json"


def sidecar_title(path):
    try:
        value = json.loads(title_sidecar(path).read_text(encoding="utf-8")).get("customTitle")
    except (OSError, ValueError, AttributeError):
        return ""
    return value if isinstance(value, str) else ""


def clean_title(text):
    """A name as one line of printable text, or "" when nothing is left."""
    return " ".join("".join(c if c.isprintable() else " " for c in str(text)).split())


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def save_title(path, session_id, title):
    """Rename a conversation no process runs, writing what /rename writes; its modified time stays."""
    stat = path.stat()
    entries = [{"type": "custom-title", "customTitle": title, "sessionId": session_id},
               {"type": "agent-name", "agentName": title, "sessionId": session_id}]
    with path.open("rb+") as f:
        end = f.seek(0, 2)
        torn = False
        if end:
            f.seek(end - 1)
            torn = f.read(1) != b"\n"
        # Compact like Claude Code's own lines: it finds them by looking for "customTitle":" in the text.
        f.write((("\n" if torn else "") + "".join(compact(e) + "\n" for e in entries)).encode("utf-8"))
    sidecar = title_sidecar(path)
    sidecar.parent.mkdir(mode=0o700, exist_ok=True)
    temporary = sidecar.with_name(f"{sidecar.name}.{os.getpid()}.tmp")
    temporary.write_text(compact({"customTitle": title}), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, sidecar)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))


RECAP_HINT = re.compile(r"\s*\(disable recaps in /config\)\s*$")


def reversed_lines(path, block=1 << 16):
    """The lines of a file from the last one up, read in blocks from its end."""
    with path.open("rb") as f:
        end = f.seek(0, 2)
        rest = b""
        while end > 0:
            start = max(0, end - block)
            f.seek(start)
            chunk = (f.read(end - start) + rest).split(b"\n")
            # The first piece may be the tail of a line that starts in the previous block.
            rest = chunk.pop(0) if start > 0 else b""
            yield from reversed(chunk)
            end = start


def last_recap(path, block=1 << 16):
    """Newest recap (away_summary) as {"text", "timestamp"}, or None; reads backwards since it is usually near the end."""
    try:
        for line in reversed_lines(path, block):
            if b'"away_summary"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "system" and event.get("subtype") == "away_summary":
                text = RECAP_HINT.sub("", str(event.get("content") or "")).strip()
                if text:
                    return {"text": text, "timestamp": event.get("timestamp")}
    except OSError:
        pass
    return None


def epoch(stamp):
    """Seconds since the epoch of an ISO 8601 timestamp such as 2026-10-14T20:07:11.452Z; None when it is not one."""
    if not isinstance(stamp, str):
        return None
    try:
        when = datetime.fromisoformat(stamp[:-1] + "+00:00" if stamp.endswith("Z") else stamp)
    except ValueError:
        return None
    return when.timestamp() if when.tzinfo else None


def last_activity(path, block=1 << 16):
    """Epoch seconds of the newest event with a timestamp, or None. Resuming a session appends its title, mode and
    bridge lines, which carry none: they move the file's mtime without anything being said."""
    try:
        for line in reversed_lines(path, block):
            if b'"timestamp"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            when = epoch(event.get("timestamp")) if isinstance(event, dict) else None
            if when is not None:
                return when
    except OSError:
        pass
    return None


def conversation_text(path):
    """User prompts and assistant text of a log, whitespace-collapsed and casefolded for phrase search."""
    parts = []
    for event in lines(path):
        message = event.get("message")
        if event.get("type") not in ("user", "assistant") or not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts += [str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return normalized(" ".join(parts))


def normalized(text):
    return " ".join(text.split()).casefold()


CONVERSATION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def conversation_bytes(main):
    """The log plus its session folder (subagent logs, saved tool results), as du --apparent-size counts it."""
    folder = main.parent / main.stem
    extra = sum(path.stat().st_size for path in folder.rglob("*") if path.is_file()) if folder.is_dir() else 0
    return main.stat().st_size + extra


def active_time(path, activity_of=last_activity):
    """When the conversation last had activity; a log is never written after its mtime, so a later timestamp (clock
    skew) yields to it, as does a log without any."""
    mtime = path.stat().st_mtime
    active = activity_of(path)
    return mtime if active is None else min(active, mtime)


def list_conversations(projects_dir, project_filter=None, project_of=project_path_of, title_of=session_title,
                       search=None, text_of=conversation_text, activity_of=last_activity):
    """Top-level session logs across every project, most recently active first; search matches the title or the text."""
    phrase = normalized(search or "")
    conversations = []
    for project in projects_dir.iterdir() if projects_dir.is_dir() else []:
        if not project.is_dir():
            continue
        for path in project.glob("*.jsonl"):
            cwd = project_of(path)
            if project_filter and project_filter.lower() not in cwd.lower():
                continue
            title = title_of(path)
            if phrase and phrase not in normalized(title) and phrase not in text_of(path):
                continue
            conversations.append({
                "path": path, "active": active_time(path, activity_of), "size_bytes": conversation_bytes(path),
                "subagents": len(subagent_logs(path)), "project": cwd, "title": title,
            })
    conversations.sort(key=lambda row: row["active"], reverse=True)
    return conversations


def iso_utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conversation_rows(projects_dir, project_filter=None, project_of=project_path_of, title_of=session_title,
                      search=None, text_of=conversation_text, activity_of=last_activity):
    """The picker's list as JSON-ready dicts; modified is the last activity, ISO 8601 UTC."""
    return [{"id": row["path"].stem, "modified": iso_utc(row["active"]),
             "size_bytes": row["size_bytes"], "subagents": row["subagents"],
             "project": row["project"], "title": row["title"]}
            for row in list_conversations(projects_dir, project_filter, project_of, title_of, search, text_of, activity_of)]


def find_conversation(conversation_id, projects_dir):
    """(path or None, matches) for a bare id; never touches the filesystem unless the id is a UUID."""
    if not isinstance(conversation_id, str) or not CONVERSATION_ID.fullmatch(conversation_id):
        return None, []
    if not projects_dir.is_dir():
        return None, []
    root = projects_dir.resolve()
    matches = [path for path in sorted(projects_dir.glob(f"*/{conversation_id}.jsonl"))
               if path.resolve().is_relative_to(root) and path.is_file()]
    return (matches[0] if len(matches) == 1 else None), matches


def resolve_conversation(reference, projects_dir):
    """Accept a JSONL path or a bare conversation id (its filename stem)."""
    path = Path(reference)
    if path.is_file():
        return path, []
    stem = path.name[:-6] if path.name.endswith(".jsonl") else path.name
    matches = sorted(projects_dir.glob(f"*/{stem}.jsonl")) if projects_dir.is_dir() else []
    if len(matches) == 1:
        return matches[0], matches
    return None, matches
