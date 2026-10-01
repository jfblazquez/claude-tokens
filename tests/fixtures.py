"""Synthetic Claude Code projects folder for tests: fixed contents and mtimes, never real data."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

API = "-home-dev-projects-api-gateway"
BILLING = "-home-dev-projects-billing-service"
CONV_A = "11111111-1111-4111-8111-111111111111"
CONV_B = "22222222-2222-4222-8222-222222222222"
AMBIGUOUS = "33333333-3333-4333-8333-333333333333"
CONV_EMPTY = "44444444-4444-4444-8444-444444444444"
SUB_EXPLORE = "a1b2c3d4e5f6a7b8c"
SUB_REVIEW = "b2c3d4e5f6a7b8c9d"

LAST_RESPONSE = (
    "## Request cache now invalidates on reload\n\n"
    "Entries are keyed by the **config generation** and `reload()` bumps it.\n\n"
    "```python\ndef get(self, key):\n    return self._entries.get(key)\n```\n\n"
    "<script>alert('xss')</script>See the <a href=\"javascript:alert(1)\">cache notes</a>."
)


def usage(input_tokens=0, output=0, cache_read=0, five=0, hour=0, legacy=None):
    value = {"input_tokens": input_tokens, "output_tokens": output, "cache_read_input_tokens": cache_read,
             "cache_creation_input_tokens": five + hour if legacy is None else legacy}
    if legacy is None:
        value["cache_creation"] = {"ephemeral_5m_input_tokens": five, "ephemeral_1h_input_tokens": hour}
    return value


def user(text, cwd, stamp, uuid):
    return {"type": "user", "uuid": uuid, "timestamp": stamp, "cwd": cwd, "message": {"role": "user", "content": text}}


def assistant(msg_id, model, stamp, uuid, blocks, use):
    """One event of an API response; real logs write one event per content block, all with the same message.id."""
    event = {"type": "assistant", "uuid": uuid,
             "message": {"id": msg_id, "model": model, "role": "assistant", "content": blocks, "usage": use}}
    if stamp:
        event["timestamp"] = stamp
    return event


def text(body):
    return {"type": "text", "text": body}


def tool(tool_id, name, **data):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": data}


def conversation_a(cwd):
    u1 = usage(120, 900, 40000, hour=3000)
    u2 = usage(15, 1400, 52000, five=800)
    u3 = usage(9, 2100, 61000)
    events = [
        user("Add request-cache invalidation when the config is reloaded", cwd, "2026-09-28T10:00:00.000Z", "u-a1"),
        {"type": "ai-title", "aiTitle": "Add request-cache invalidation"},
        assistant("msg_A1", "claude-opus-5-5", "2026-09-28T10:00:05.000Z", "e-a1", [text("Looking at the cache.")], u1),
        assistant("msg_A1", "claude-opus-5-5", "2026-09-28T10:00:05.100Z", "e-a2",
                  [tool("toolu_A1", "Bash", command="git status --short", description="Show working tree status")], u1),
        assistant("msg_A2", "claude-opus-5-5", "2026-09-29T23:59:50.000Z", "e-a3",
                  [tool("toolu_A2", "Read", file_path="/home/dev/projects/api-gateway/src/cache.py")], u2),
        assistant("msg_A2", "claude-opus-5-5", "2026-09-29T23:59:50.200Z", "e-a4",
                  [tool("toolu_A3", "Edit", file_path="/home/dev/projects/api-gateway/src/cache.py",
                        old_string="a", new_string="b")], u2),
        assistant("msg_A2", "claude-opus-5-5", "2026-09-29T23:59:50.300Z", "e-a5",
                  [tool("toolu_A2", "Read", file_path="/home/dev/projects/api-gateway/src/cache.py")], u2),
        assistant("msg_A3", "claude-opus-5-5", "2026-09-30T00:00:10.000Z", "e-a6",
                  [tool("toolu_A4", "Skill", skill="code-review")], u3),
        assistant("msg_A3", "claude-opus-5-5", "2026-09-30T00:00:10.100Z", "e-a7",
                  [tool("toolu_A5", "Bash", command="python3 -m unittest -v", description="Run tests")], u3),
        assistant("msg_A3", "claude-opus-5-5", "2026-09-30T00:00:10.200Z", "e-a8", [text(LAST_RESPONSE)], u3),
    ]
    return events


def subagent_explore():
    use = usage(300, 500, 9000, five=1200)
    return [
        user("Find every call site of invalidate()", None, "2026-09-28T10:01:00.000Z", "s1-u"),
        assistant("msg_S1", "claude-haiku-4-5", "2026-09-28T10:01:02.000Z", "s1-e1",
                  [tool("toolu_S1", "Bash", command="grep -rn 'invalidate(' src/", description="Find call sites")], use),
        assistant("msg_S1", "claude-haiku-4-5", "2026-09-28T10:01:02.100Z", "s1-e2",
                  [tool("toolu_S2", "Read", file_path="/home/dev/projects/api-gateway/src/cache.py")], use),
    ]


def subagent_review():
    use = usage(200, 700, 15000, hour=2500)
    return [
        user("Review cache tests", None, "2026-09-28T11:00:00.000Z", "s2-u"),
        assistant("msg_S2", "claude-sonnet-5-5", None, "s2-e1",
                  [tool("toolu_S3", "Bash", command="python3 -m unittest tests.test_cache", description="Run cache tests")], use),
        assistant("msg_S2", "claude-sonnet-5-5", None, "s2-e2",
                  [tool("toolu_S4", "Write", file_path="/home/dev/projects/api-gateway/tests/test_reload.py", content="")], use),
    ]


def conversation_b(cwd):
    return [
        user("Retry policy for ledger exports", cwd, "2026-09-29T08:00:00.000Z", "u-b1"),
        assistant("msg_B1", "claude-sonnet-5-6", "2026-09-29T08:00:04.000Z", "e-b1", [text("Adding retries.")],
                  usage(50, 800, 20000, legacy=1500)),
        "{not valid json",
        assistant("msg_B2", "acme-model-1", "2026-09-30T12:00:00.000Z", "e-b2", [text("Done.")], usage(400, 300)),
        assistant("msg_B2", "acme-model-1", "2026-09-30T12:00:00.000Z", "e-b3", [text("Done.")], usage(400, 300)),
    ]


def ambiguous(cwd):
    return [user("Same id in two projects", cwd, "2026-09-27T09:00:00.000Z", "u-c1"),
            assistant("msg_C1", "claude-haiku-4-5", "2026-09-27T09:00:01.000Z", "e-c1", [text("Hi.")], usage(10, 20))]


def empty_conversation(cwd):
    return [user("Explain picker pagination", cwd, "2026-09-26T09:00:00.000Z", "u-d1")]


def write_jsonl(path, events, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for event in events:
            f.write((event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)) + "\n")
    os.utime(path, (mtime, mtime))


def build_projects(base):
    """Create the synthetic projects folder under base and return its path."""
    root = Path(base) / "projects"
    api_cwd, billing_cwd = "/home/dev/projects/api-gateway", "/home/dev/projects/billing-service"
    t = 1790000000  # 2026-09-21T14:13:20Z; every file gets a fixed offset from it
    write_jsonl(root / API / f"{CONV_A}.jsonl", conversation_a(api_cwd), t + 900)
    subagents = root / API / CONV_A / "subagents"
    write_jsonl(subagents / f"agent-{SUB_EXPLORE}.jsonl", subagent_explore(), t + 600)
    meta = subagents / f"agent-{SUB_EXPLORE}.meta.json"
    meta.write_text(json.dumps({"description": "Explore cache invalidation call sites"}), encoding="utf-8")
    os.utime(meta, (t + 600, t + 600))
    write_jsonl(subagents / f"agent-{SUB_REVIEW}.jsonl", subagent_review(), t + 700)
    write_jsonl(root / API / f"{AMBIGUOUS}.jsonl", ambiguous(api_cwd), t + 100)
    write_jsonl(root / API / f"{CONV_EMPTY}.jsonl", empty_conversation(api_cwd), t + 50)
    write_jsonl(root / BILLING / f"{CONV_B}.jsonl", conversation_b(billing_cwd), t + 800)
    write_jsonl(root / BILLING / f"{AMBIGUOUS}.jsonl", ambiguous(billing_cwd), t + 200)
    return root


def snapshot(root):
    """(relative path, size, mtime, bytes) for every file, to compare two builds."""
    return sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime, p.read_bytes())
                  for p in Path(root).rglob("*") if p.is_file())
