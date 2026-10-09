"""Content views of a conversation: messages, last response, Bash commands and touched files."""
from __future__ import annotations

import json
import re
from datetime import datetime

from .logs import conversation_sources, lines, parse_timestamp, short, subagent_task, task_from_log, tool_uses
from .pricing import estimated_cost, rate_of

# Tool inputs and results can hold whole files; the transcript keeps their head and the original length.
CLIP = 4000
SUMMARY_KEYS = ("command", "file_path", "path", "pattern", "skill", "description", "prompt", "url", "query")


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


def clipped(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return {"text": text[:CLIP], "size": len(text)}


def result_text(content):
    if isinstance(content, list):
        return "\n".join(b.get("text", "") if b.get("type") == "text" else f"[{b.get('type')}]"
                         for b in content if isinstance(b, dict))
    return content if isinstance(content, str) else ""


def first_text(value):
    if isinstance(value, str):
        return value if value.strip() else ""
    values = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return next((text for text in map(first_text, values) if text), "")


def tool_summary(data):
    """The most telling input field (command, path, pattern...), else the first text anywhere in the input."""
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
                           "summary": tool_summary(data),
                           "input": [{"name": str(name), **clipped(value)} for name, value in fields]})
        elif kind == "tool_result":
            blocks.append({"type": "tool_result", "tool_use_id": block.get("tool_use_id"),
                           "is_error": bool(block.get("is_error")), **clipped(result_text(block.get("content")))})
    return blocks


def user_kind(event, blocks):
    if event.get("isCompactSummary"):
        return "summary"
    if event.get("isMeta"):
        return "meta"
    return "tool_result" if all(b["type"] == "tool_result" for b in blocks) else "prompt"


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
    rate = rate_of(prices, model)
    server = usage.get("server_tool_use")
    return {"role": "assistant", "kind": "error" if event.get("isApiErrorMessage") else "response",
            "timestamp": timestamp, "model": model, "stop_reason": message.get("stop_reason"),
            "usage": {**tokens, "thinking": count(usage.get("output_tokens_details"), "thinking_tokens"),
                      "context": tokens["input"] + tokens["cache_read"] + five + hour,
                      "web_search_requests": count(server, "web_search_requests"),
                      "web_fetch_requests": count(server, "web_fetch_requests"),
                      "service_tier": usage.get("service_tier"), "speed": usage.get("speed")},
            "estimated_cost_usd": estimated_cost(tokens, rate), "price_estimated": bool(rate and rate[2]), "blocks": []}


def transcript(path, prices):
    """User and assistant messages of one log in order; the events of one API response become one message."""
    messages, responses = [], {}
    for event in lines(path):
        kind, message = event.get("type"), event.get("message")
        if kind not in ("user", "assistant") or not isinstance(message, dict):
            continue
        timestamp = event.get("timestamp") if parse_timestamp(event.get("timestamp")) else None
        blocks = message_blocks(message.get("content"))
        if kind == "user":
            if blocks:
                messages.append({"role": "user", "kind": user_kind(event, blocks), "timestamp": timestamp, "blocks": blocks})
            continue
        # Usage is taken from the first event of a response, as parse_log does.
        identity = message.get("id") or event.get("uuid")
        entry = responses.get(identity) if isinstance(identity, str) else None
        if entry is None:
            entry = response_entry(event, message, timestamp, prices)
            messages.append(entry)
            if isinstance(identity, str):
                responses[identity] = entry
        entry["blocks"] += [block for block in blocks if block not in entry["blocks"]]
    return messages


def source_list(main):
    return [{"id": source, "task": task_from_log(path) if source == "main" else subagent_task(path)}
            for source, path in conversation_sources(main)]


def conversation_messages(main, source, prices, read=transcript):
    """Messages of the main log or of one subagent, plus every source; None when the source does not exist."""
    path = dict(conversation_sources(main)).get(source)
    if path is None:
        return None
    return {"source": source, "sources": source_list(main), "messages": read(path, prices)}
