"""Content views of a conversation: messages, last response, Bash commands and touched files."""
from __future__ import annotations

import contextvars
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from .logs import (conversation_sources, lines, parse_timestamp, response_identity, short, subagent_task, task_from_log,
                   tool_uses)
from .pricing import estimated_cost, rate_of, usage_key

# Tool inputs and results can hold whole files; the transcript keeps their head and the original length.
CLIP = 4000
SUMMARY_KEYS = ("command", "file_path", "path", "pattern", "skill", "description", "prompt", "url", "query")
BASH_SUMMARY = 100
# Only raster types are inlined as data: URIs, and only up to this much base64.
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
MAX_IMAGE = 8 << 20
# Fields every log event repeats; the generic view of an unknown system event leaves them out.
EVENT_FIELDS = frozenset({"parentUuid", "logicalParentUuid", "isSidechain", "type", "subtype", "uuid", "timestamp",
                          "userType", "entrypoint", "cwd", "sessionId", "session_id", "version", "gitBranch", "slug",
                          "agentId", "isMeta", "level"})


def last_response(path):
    """Text of the final assistant turn (concatenated text blocks)."""
    result = ""
    for event in lines(path):
        message = event.get("message")
        if event.get("type") != "assistant" or not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            text_blocks = [content]
        elif isinstance(content, list):
            text_blocks = [b.get("text", "") for b in content
                           if isinstance(b, dict) and b.get("type") == "text"]
        else:
            text_blocks = []
        joined = "\n".join(t for t in text_blocks if t)
        if joined.strip():
            result = joined
    return result


def chronological_key(timestamp):
    """Sort key: dated entries by time (with sub-second precision), undated ones after them."""
    stamp = parse_timestamp(timestamp)
    if stamp is None:
        return (1, datetime.min, 0.0)
    fraction = re.match(r"\.(\d+)", timestamp[19:])
    return (0, stamp, float("0." + fraction.group(1)) if fraction else 0.0)


def bash_commands(main):
    """Every Bash tool_use command of the conversation and its subagents, in chronological order."""
    commands, seen = [], set()
    for source, path in conversation_sources(main):
        for event in lines(path):
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            timestamp = event.get("timestamp")
            timestamp = timestamp if parse_timestamp(timestamp) else None
            for block in tool_uses(message, seen):
                if block.get("name") == "Bash":
                    data = block.get("input") or {}
                    commands.append({"command": str(data.get("command") or ""),
                                     "description": str(data.get("description") or ""),
                                     "source": source, "timestamp": timestamp})
    # sorted() is stable, so undated entries keep their log order.
    return sorted(commands, key=lambda entry: chronological_key(entry["timestamp"]))


def touched_files(main):
    """Files opened by Read or changed by Write/Edit across the conversation and its subagents."""
    files, seen = {}, set()
    for source, path in conversation_sources(main):
        for event in lines(path):
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            for block in tool_uses(message, seen):
                name = block.get("name")
                if name not in ("Read", "Write", "Edit"):
                    continue
                target = (block.get("input") or {}).get("file_path")
                if not target:
                    continue
                entry = files.setdefault(str(target), {"Read": 0, "Write": 0, "Edit": 0, "sources": []})
                entry[name] += 1
                if source not in entry["sources"]:
                    entry["sources"].append(source)
    return files


# None while full_text() builds the transcript again; a context variable, so the requests of other threads still clip.
CLIP_LIMIT = contextvars.ContextVar("clip_limit", default=CLIP)
# Where a clipped text sits: a message (an event), a block of it (a tool result), its patch, or a field of a tool call.
CLIPPED_AT = re.compile(r"(\d+)(?:\.(\d+)(?:\.patch|\.input\.(\d+))?)?")


def clipped(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    limit = CLIP_LIMIT.get()
    return {"text": text if limit is None else text[:limit], "size": len(text)}


def result_part(block):
    if block.get("type") == "text":
        return block.get("text", "")
    if block.get("type") == "tool_reference":
        return str(block.get("tool_name") or "[tool_reference]")
    return f"[{block.get('type')}]"


def result_text(content):
    if isinstance(content, list):
        return "\n".join(result_part(b) for b in content if isinstance(b, dict))
    return content if isinstance(content, str) else ""


def image_block(block):
    """Media type, decoded size and, for inlinable images, the base64 data of an image block."""
    source = block.get("source") if isinstance(block.get("source"), dict) else {}
    media, data = source.get("media_type"), source.get("data")
    data = data if source.get("type") == "base64" and isinstance(data, str) else None
    size = len(data) * 3 // 4 - data[-2:].count("=") if data else None
    inline = data if media in IMAGE_TYPES and len(data or "") <= MAX_IMAGE else None
    return {"type": "image", "media_type": media if isinstance(media, str) else None, "bytes": size, "data": inline}


def first_text(value):
    if isinstance(value, str):
        return value if value.strip() else ""
    values = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return next((text for text in map(first_text, values) if text), "")


def bash_summary(data):
    """The Bash description, else the head of the command."""
    description = " ".join(str(data.get("description") or "").split())
    if description:
        return description
    command = " ".join(str(data.get("command") or "").split())
    return command if len(command) <= BASH_SUMMARY else command[:BASH_SUMMARY] + "..."


def tool_summary(name, data):
    """The most telling input field (command, path, pattern...), else the first text anywhere in the input."""
    if name == "Bash" and isinstance(data, dict):
        return bash_summary(data)
    known = [data.get(key) for key in SUMMARY_KEYS] if isinstance(data, dict) else []
    return short(first_text(known) or first_text(data), 200)


def message_blocks(content):
    """Text, thinking, tool_use and tool_result blocks of a message; empty text and redacted thinking are dropped."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content.strip() else []
    blocks = []
    for block in content if isinstance(content, list) else []:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind == "text" and str(block.get("text") or "").strip():
            blocks.append({"type": "text", "text": block["text"]})
        elif kind == "thinking" and str(block.get("thinking") or "").strip():
            blocks.append({"type": "thinking", "text": block["thinking"]})
        elif kind == "tool_use":
            data = block.get("input")
            fields = data.items() if isinstance(data, dict) else [("input", data)]
            blocks.append({"type": "tool_use", "id": block.get("id"), "name": str(block.get("name") or "unknown"),
                           "summary": tool_summary(block.get("name"), data),
                           "input": [{"name": str(name), **clipped(value)} for name, value in fields]})
        elif kind == "image":
            blocks.append(image_block(block))
        elif kind == "tool_result":
            content = block.get("content")
            images = [image_block(b) for b in content if isinstance(b, dict) and b.get("type") == "image"] \
                if isinstance(content, list) else []
            blocks.append({"type": "tool_result", "tool_use_id": block.get("tool_use_id"),
                           "is_error": bool(block.get("is_error")), **clipped(result_text(content)),
                           **({"images": images} if images else {})})
    return blocks


def patch_text(hunks):
    """structuredPatch hunks of an Edit/Write result as a unified diff."""
    parts = []
    for hunk in hunks if isinstance(hunks, list) else []:
        if not isinstance(hunk, dict):
            continue
        parts.append(f"@@ -{hunk.get('oldStart')},{hunk.get('oldLines')} +{hunk.get('newStart')},{hunk.get('newLines')} @@")
        parts += [str(line) for line in hunk.get("lines") or []]
    return "\n".join(parts)


def add_result_details(blocks, event):
    """The diff of an Edit/Write and the permission decision, both kept outside message.content."""
    results = [b for b in blocks if b["type"] == "tool_result"]
    detail = event.get("toolUseResult")
    patch = patch_text(detail.get("structuredPatch")) if isinstance(detail, dict) else ""
    if patch and len(results) == 1:
        results[0]["patch"] = clipped(patch)
    decision = event.get("permissionDecision")
    if isinstance(decision, dict) and decision.get("decision"):
        for block in results:
            block["permission"] = {"decision": str(decision["decision"]), "reason": decision.get("reasonType")}


def user_kind(event, blocks):
    if event.get("isCompactSummary"):
        return "summary"
    if event.get("isMeta"):
        return "meta"
    return "tool_result" if all(b["type"] == "tool_result" for b in blocks) else "prompt"


def tag(text, name):
    match = re.search(f"<{name}>(.*?)</{name}>", text, re.S)
    return match.group(1).strip() if match else ""


def notification_title(attachment, text):
    origin = attachment.get("origin") if isinstance(attachment.get("origin"), dict) else {}
    if attachment.get("commandMode") == "task-notification" or text.startswith("<task-notification>"):
        summary, status = tag(text, "summary") or "Background task", tag(text, "status")
        return summary if not status or status.lower() in summary.lower() else f"{summary} · {status}"
    if origin.get("kind") == "peer":
        return f"Message from {origin.get('name') or 'an agent'}"
    return "Queued message"


def queued_entry(attachment, timestamp):
    """A prompt typed while the model was working (or a task/agent notice) is logged as a queued_command attachment."""
    prompt = attachment.get("prompt")
    blocks = message_blocks(prompt if isinstance(prompt, (str, list)) else "")
    origin = attachment.get("origin") if isinstance(attachment.get("origin"), dict) else {}
    if origin.get("kind") == "human" and not attachment.get("isMeta"):
        return {"role": "user", "kind": "prompt", "queued": True, "timestamp": timestamp, "blocks": blocks}
    text = prompt if isinstance(prompt, str) else ""
    return {"role": "user", "kind": "notification", "title": notification_title(attachment, text),
            "timestamp": timestamp, "blocks": blocks}


def rendered_text(event):
    rendered = event.get("rendered")
    if isinstance(rendered, list):
        return "\n".join(str(r.get("content") or "") for r in rendered if isinstance(r, dict))
    return ""


def attachment_entry(event, timestamp):
    attachment = event.get("attachment")
    if not isinstance(attachment, dict):
        return None
    name = str(attachment.get("type") or "attachment")
    if name == "queued_command":
        return queued_entry(attachment, timestamp)
    if name == "hook_system_message":
        return {"role": "event", "kind": "hook", "timestamp": timestamp, "name": str(attachment.get("hookEvent") or ""),
                "text": str(attachment.get("content") or "")}
    return {"role": "event", "kind": "attachment", "timestamp": timestamp, "name": name,
            **clipped(rendered_text(event) or attachment)}


def local_command(content):
    name = tag(content, "command-name")
    if name:
        return " ".join(part for part in (name, tag(content, "command-args")) if part)
    return tag(content, "local-command-stdout") or tag(content, "local-command-stderr") or content


def system_entry(event, timestamp):
    subtype, content = event.get("subtype"), str(event.get("content") or "")
    entry = {"role": "event", "timestamp": timestamp}
    if subtype == "compact_boundary":
        meta = event.get("compactMetadata") if isinstance(event.get("compactMetadata"), dict) else {}
        return {**entry, "kind": "compaction", "trigger": meta.get("trigger"), "pre_tokens": count(meta, "preTokens"),
                "post_tokens": count(meta, "postTokens"), "duration_ms": count(meta, "durationMs")}
    if subtype == "turn_duration":
        return {**entry, "kind": "turn", "duration_ms": count(event, "durationMs"),
                "message_count": count(event, "messageCount")}
    if subtype == "model_refusal_no_fallback":
        return {**entry, "kind": "refusal", "model": event.get("originalModel"),
                "category": event.get("apiRefusalCategory"), "text": str(event.get("apiRefusalExplanation") or "")}
    if subtype == "local_command":
        return {**entry, "kind": "command", "text": local_command(content)}
    if subtype in ("away_summary", "informational"):
        return {**entry, "kind": "recap" if subtype == "away_summary" else "info", "text": content}
    return {**entry, "kind": "system", "name": str(subtype or "system"),
            **clipped({key: value for key, value in event.items() if key not in EVENT_FIELDS})}


def count(mapping, key):
    value = mapping.get(key) if isinstance(mapping, dict) else None
    return int(value) if isinstance(value, (int, float)) else None


def response_entry(event, message, timestamp, prices):
    usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
    creation = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    five, hour = count(creation, "ephemeral_5m_input_tokens") or 0, count(creation, "ephemeral_1h_input_tokens") or 0
    # Same rules as parse_log, so the messages add up to the usage report.
    five += max(0, (count(usage, "cache_creation_input_tokens") or 0) - five - hour)
    tokens = {"input": count(usage, "input_tokens") or 0, "output": count(usage, "output_tokens") or 0,
              "cache_read": count(usage, "cache_read_input_tokens") or 0, "cache_write_5m": five, "cache_write_1h": hour}
    model = str(message.get("model") or "modelo-desconocido")
    rate = rate_of(prices, usage_key(model, tokens["input"] + tokens["cache_read"] + five + hour))
    server = usage.get("server_tool_use")
    return {"role": "assistant", "kind": "error" if event.get("isApiErrorMessage") else "response",
            "timestamp": timestamp, "model": model, "stop_reason": message.get("stop_reason"),
            "usage": {**tokens, "thinking": count(usage.get("output_tokens_details"), "thinking_tokens"),
                      "context": tokens["input"] + tokens["cache_read"] + five + hour,
                      "web_search_requests": count(server, "web_search_requests"),
                      "web_fetch_requests": count(server, "web_fetch_requests"),
                      "service_tier": usage.get("service_tier"), "speed": usage.get("speed")},
            "estimated_cost_usd": estimated_cost(tokens, rate), "price_estimated": bool(rate and rate[2]),
            "effort": event.get("effort") if isinstance(event.get("effort"), str) else None,
            "thinking_ms": count(event, "thinkingDurationMs"), "blocks": []}


class Transcript:
    """transcript() of a log that keeps growing: each advance() only reads the lines appended since the last one."""

    def __init__(self, path, prices):
        self.path, self.prices = Path(path), prices
        self.reset(None)

    def reset(self, identity):
        self.identity, self.offset, self.line = identity, 0, 0
        self.messages, self.responses = [], {}

    def advance(self):
        stat = os.stat(self.path)
        identity = (stat.st_dev, stat.st_ino)
        if identity != self.identity or stat.st_size < self.offset:
            self.reset(identity)
        with self.path.open("rb") as f:
            f.seek(self.offset)
            data = f.read()
        *complete, tail = data.split(b"\n")
        for raw in complete:
            self.read_line(raw)
        self.offset += sum(len(raw) + 1 for raw in complete)
        # The last piece has no newline yet: it is taken only once it is whole JSON, else read again next time.
        if tail.strip() and self.parse(tail, warn=False) is not None:
            self.read_line(tail)
            self.offset += len(tail)
        return self.messages

    def parse(self, raw, warn=True):
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            if warn:
                print(f"warning: {self.path}:{self.line}: {getattr(error, 'msg', error)}", file=sys.stderr)
            return None

    def read_line(self, raw):
        self.line += 1
        if not raw.strip():
            return
        event = self.parse(raw)
        if isinstance(event, dict):
            self.add(event)

    def add(self, event):
        kind, message = event.get("type"), event.get("message")
        timestamp = event.get("timestamp") if parse_timestamp(event.get("timestamp")) else None
        if kind in ("attachment", "system"):
            entry = attachment_entry(event, timestamp) if kind == "attachment" else system_entry(event, timestamp)
            if entry and (entry["role"] == "event" or entry["blocks"]):
                self.messages.append(entry)
            return
        if kind not in ("user", "assistant") or not isinstance(message, dict):
            return
        blocks = message_blocks(message.get("content"))
        if kind == "user":
            add_result_details(blocks, event)
            if blocks:
                self.messages.append({"role": "user", "kind": user_kind(event, blocks), "timestamp": timestamp,
                                      "blocks": blocks})
            return
        identity = response_identity(event, message)
        entry = self.responses.get(identity)
        if entry is None:
            entry = self.responses[identity] = response_entry(event, message, timestamp, self.prices)
            self.messages.append(entry)
        else:
            # Usage is taken from the last event of a response, as parse_log does.
            latest = response_entry(event, message, timestamp, self.prices)
            entry.update({key: latest[key] for key in ("usage", "estimated_cost_usd", "price_estimated", "stop_reason")})
            if latest["thinking_ms"] is not None:
                entry["thinking_ms"] = (entry["thinking_ms"] or 0) + latest["thinking_ms"]
        entry["blocks"] += [block for block in blocks if block not in entry["blocks"]]


def transcript(path, prices):
    """Messages and events (role "event") of one log in order; the events of one API response become one message."""
    return Transcript(path, prices).advance()


def full_text(log, prices, at):
    """The whole of a text the transcript of log clips, by where it sits (CLIPPED_AT); None when there is no such text."""
    match = CLIPPED_AT.fullmatch(at or "")
    if not match:
        return None
    token = CLIP_LIMIT.set(None)
    try:
        messages = transcript(log, prices)
    finally:
        CLIP_LIMIT.reset(token)
    message, block, field = (None if n is None else int(n) for n in match.groups())
    try:
        item = messages[message]
        if block is not None:
            item = item["blocks"][block]
            if at.endswith(".patch"):
                item = item["patch"]
            elif field is not None:
                item = item["input"][field]
    except (IndexError, KeyError, TypeError):
        return None
    text = item.get("text") if isinstance(item, dict) else None
    return text if isinstance(text, str) else None


def source_list(main):
    return [{"id": source, "task": task_from_log(path) if source == "main" else subagent_task(path)}
            for source, path in conversation_sources(main)]


def conversation_messages(main, source, prices, read=transcript):
    """Messages of the main log or of one subagent, plus every source; None when the source does not exist."""
    path = dict(conversation_sources(main)).get(source)
    if path is None:
        return None
    return {"source": source, "sources": source_list(main), "messages": read(path, prices)}
