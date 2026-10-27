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
    """Last user-facing session rename (aiTitle); empty when there is none."""
    try:
        with path.open("rb") as f:
            size = path.stat().st_size
            if size > tail:
                f.seek(-tail, 2)
            data = f.read()
    except OSError:
        return ""
    title = ""
    for line in data.decode("utf-8", "ignore").splitlines():
        if '"aiTitle"' not in line:
            continue
        try:
            value = json.loads(line).get("aiTitle")
        except json.JSONDecodeError:
            continue
        if value:
            title = value
    return title


RECAP_HINT = re.compile(r"\s*\(disable recaps in /config\)\s*$")


def last_recap(path, block=1 << 16):
    """Newest recap (away_summary) as {"text", "timestamp"}, or None; reads backwards since it is usually near the end."""
    try:
        with path.open("rb") as f:
            end = f.seek(0, 2)
            rest = b""
            while end > 0:
                start = max(0, end - block)
                f.seek(start)
                chunk = (f.read(end - start) + rest).split(b"\n")
                # The first piece may be the tail of a line that starts in the previous block.
                rest = chunk.pop(0) if start > 0 else b""
                for line in reversed(chunk):
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
                end = start
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


def list_conversations(projects_dir, project_filter=None, project_of=project_path_of, title_of=session_title,
                       search=None, text_of=conversation_text):
    """Top-level session logs across every project, most recent first; search matches the title or the text."""
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
            stat = path.stat()
            conversations.append({
                "path": path, "mtime": stat.st_mtime, "size_bytes": conversation_bytes(path),
                "subagents": len(subagent_logs(path)), "project": cwd, "title": title,
            })
    conversations.sort(key=lambda row: row["mtime"], reverse=True)
    return conversations


def conversation_rows(projects_dir, project_filter=None, project_of=project_path_of, title_of=session_title,
                      search=None, text_of=conversation_text):
    """The picker's list as JSON-ready dicts; modified is ISO 8601 UTC."""
    return [{"id": row["path"].stem,
             "modified": datetime.fromtimestamp(row["mtime"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "size_bytes": row["size_bytes"], "subagents": row["subagents"],
             "project": row["project"], "title": row["title"]}
            for row in list_conversations(projects_dir, project_filter, project_of, title_of, search, text_of)]


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
