"""Build a synthetic Claude Code projects folder for the README screenshots: invented projects, no real data.

Usage: python3 tools/demo_projects.py OUTPUT_DIR   (writes OUTPUT_DIR/projects; same seed, same files)
"""
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 7
START = datetime(2026, 9, 7, tzinfo=timezone.utc)
DAYS = 30
FEATURED_TITLE = "Add rate limiting to the public API"

PROJECTS = {
    "/home/dev/projects/api-gateway": ["src/router.py", "src/middleware/auth.py", "src/middleware/rate_limit.py",
                                       "src/cache.py", "tests/test_router.py", "tests/test_rate_limit.py", "README.md"],
    "/home/dev/projects/billing-service": ["billing/invoices.py", "billing/ledger.py", "billing/exports.py",
                                           "tests/test_ledger.py", "migrations/0042_invoice_status.sql"],
    "/home/dev/projects/web-dashboard": ["src/App.tsx", "src/pages/Usage.tsx", "src/components/Chart.tsx",
                                         "src/api/client.ts", "package.json"],
    "/home/dev/projects/data-pipeline": ["pipeline/ingest.py", "pipeline/transform.py", "dags/daily_rollup.py",
                                         "tests/test_transform.py"],
    "/home/dev/projects/mobile-app": ["lib/main.dart", "lib/screens/settings.dart", "lib/services/sync.dart",
                                      "pubspec.yaml"],
    "/home/dev/projects/infra": ["terraform/main.tf", "terraform/modules/db/main.tf", "k8s/deployment.yaml",
                                 ".github/workflows/ci.yml"],
}
TITLES = {
    "/home/dev/projects/api-gateway": ["Fix flaky router tests", "Cache invalidation on config reload",
                                       "Migrate auth middleware to async", "Structured request logging"],
    "/home/dev/projects/billing-service": ["Retry policy for ledger exports", "Invoice status migration",
                                           "Investigate rounding in VAT totals", "Monthly export to CSV"],
    "/home/dev/projects/web-dashboard": ["Dark mode for the usage page", "Paginate the invoices table",
                                         "Replace chart library", "Fix layout on small screens"],
    "/home/dev/projects/data-pipeline": ["Backfill September rollups", "Speed up the transform step",
                                         "Schema drift alerts"],
    "/home/dev/projects/mobile-app": ["Offline sync conflicts", "Settings screen redesign"],
    "/home/dev/projects/infra": ["Terraform plan for the new database", "CI cache for dependencies"],
}
WEIGHTS = [5, 3, 3, 2, 1, 1]
BASH = [
    ("git status --short", "Show working tree status"),
    ("git log --oneline -15", "Show recent commits"),
    ("git diff --stat", "Summarize uncommitted changes"),
    ("python3 -m pytest -q", "Run the test suite"),
    ("python3 -m pytest tests/test_rate_limit.py -q", "Run rate limiter tests"),
    ("ruff check src tests", "Lint the sources"),
    ("grep -rn 'TODO' src | head -20", "List pending TODOs"),
    ("npm run build", "Build the frontend"),
    ("npm test -- --watch=false", "Run frontend tests"),
    ("docker compose up -d redis", "Start a local Redis"),
    ("curl -s localhost:8080/healthz", "Check the health endpoint"),
    ("terraform plan -out plan.bin", "Plan infrastructure changes"),
    ("ls -la src", "List source files"),
]
SKILLS = ["code-review", "simplify", "security-review", "tdd", "explain-code", "diagnosing-bugs"]
SUBAGENT_TASKS = ["Explore call sites of the limiter", "Review the rate limit tests", "Security review of the change",
                  "Check the docs for outdated examples", "Benchmark the middleware", "Find similar bugs elsewhere"]
LAST_RESPONSE = """## Rate limiting is in place

Requests are now limited **per API key** with a token bucket stored in Redis.

| Endpoint | Limit | Burst |
|---|---|---|
| `GET /v1/items` | 600/min | 100 |
| `POST /v1/items` | 120/min | 20 |
| `POST /v1/export` | 10/min | 2 |

```python
@app.middleware("http")
async def rate_limit(request, call_next):
    bucket = await buckets.take(request.state.api_key)
    if bucket.empty:
        return JSONResponse({"error": "rate limited"}, status_code=429,
                            headers={"Retry-After": str(bucket.retry_after)})
    return await call_next(request)
```

All 214 tests pass. Next steps:

1. Expose the remaining quota in `X-RateLimit-Remaining`.
2. Add a dashboard panel for rejected requests.
"""


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


class Log:
    def __init__(self, rnd, cwd, model, start):
        self.rnd, self.cwd, self.model, self.t = rnd, cwd, model, start
        self.events, self.context, self.n = [], rnd.randint(12000, 22000), 0

    def user(self, text):
        self.events.append({"type": "user", "uuid": f"u{len(self.events)}", "timestamp": stamp(self.t), "cwd": self.cwd,
                            "message": {"role": "user", "content": text}})

    def respond(self, blocks, model=None):
        self.t += timedelta(seconds=self.rnd.randint(8, 70))
        self.n += 1
        new = self.rnd.randint(1500, 9000)
        fresh = self.n == 1 or self.rnd.random() < 0.08
        use = {"input_tokens": self.rnd.randint(3, 40), "output_tokens": self.rnd.randint(150, 2600),
               "cache_read_input_tokens": 0 if fresh else self.context,
               "cache_creation_input_tokens": self.context + new if fresh else new,
               "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": self.context + new if fresh else new}}
        self.context += new
        self.events.append({"type": "assistant", "uuid": f"e{len(self.events)}", "timestamp": stamp(self.t),
                            "message": {"id": f"msg_{self.rnd.getrandbits(64):016x}", "model": model or self.model, "role": "assistant",
                                        "content": blocks, "usage": use}})

    def tool(self, name, **data):
        self.respond([{"type": "tool_use", "id": f"toolu_{self.rnd.getrandbits(64):016x}", "name": name, "input": data}])


def work(rnd, log, files, steps):
    for _ in range(steps):
        kind = rnd.choices(["Bash", "Read", "Edit", "Grep", "Write", "text"], [6, 5, 3, 2, 1, 2])[0]
        path = f"{log.cwd}/{rnd.choice(files)}"
        if kind == "Bash":
            command, description = rnd.choice(BASH)
            log.tool("Bash", command=command, description=description)
        elif kind in ("Read", "Edit", "Write"):
            log.tool(kind, file_path=path)
        elif kind == "Grep":
            log.tool("Grep", pattern=rnd.choice(["rate_limit", "def handle", "TODO", "export"]))
        else:
            log.respond([{"type": "text", "text": "Checking the next step."}])


def write(path, events, when):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    os.utime(path, (when.timestamp(), when.timestamp()))


def conversation(rnd, root, cwd, title, day, featured=False):
    model = "claude-opus-5" if day < 14 and rnd.random() < 0.7 else rnd.choices(
        ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"], [6, 3, 1])[0]
    start = START + timedelta(days=day, hours=rnd.randint(7, 18), minutes=rnd.randint(0, 59))
    log = Log(rnd, cwd, "claude-opus-5-5" if featured else model, start)
    log.user(title)
    log.events.append({"type": "ai-title", "aiTitle": title})
    files = PROJECTS[cwd]
    work(rnd, log, files, 40 if featured else rnd.randint(6, 45))
    if featured or rnd.random() < 0.35:
        log.tool("Skill", skill=rnd.choice(SKILLS[:3]) if featured else rnd.choice(SKILLS))
    conv_id = f"{rnd.getrandbits(32):08x}-{rnd.getrandbits(16):04x}-4{rnd.getrandbits(12):03x}-8{rnd.getrandbits(12):03x}-{rnd.getrandbits(48):012x}"
    folder = root / cwd.replace("/", "-")
    subagents = 5 if featured else rnd.choices([0, 0, 0, 1, 2, 3], k=1)[0]
    for s in range(subagents):
        sub_id = f"a{rnd.getrandbits(64):016x}"
        task = SUBAGENT_TASKS[s % len(SUBAGENT_TASKS)] if featured else rnd.choice(SUBAGENT_TASKS)
        log.tool("Agent", description=task, prompt=task)
        sub = Log(rnd, cwd, rnd.choice(["claude-sonnet-5-5", "claude-haiku-4-5", "claude-opus-5-5"]), log.t)
        sub.user(task)
        work(rnd, sub, files, rnd.randint(4, 14))
        sub_dir = folder / conv_id / "subagents"
        write(sub_dir / f"agent-{sub_id}.jsonl", sub.events, sub.t)
        (sub_dir / f"agent-{sub_id}.meta.json").write_text(json.dumps({"description": task}), encoding="utf-8")
    work(rnd, log, files, 6 if featured else rnd.randint(1, 6))
    log.respond([{"type": "text", "text": LAST_RESPONSE if featured else f"Done: {title.lower()}."}])
    write(folder / f"{conv_id}.jsonl", log.events, log.t)
    return conv_id


def build(base):
    rnd = random.Random(SEED)
    root = Path(base) / "projects"
    cwds = list(PROJECTS)
    for _ in range(48):
        day = rnd.randint(0, DAYS - 2)
        if rnd.random() < 0.25 and day % 7 in (5, 6):
            continue
        cwd = rnd.choices(cwds, WEIGHTS)[0]
        conversation(rnd, root, cwd, rnd.choice(TITLES[cwd]), day)
    featured = conversation(rnd, root, cwds[0], FEATURED_TITLE, DAYS - 1, featured=True)
    return root, featured


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip())
    projects, featured_id = build(sys.argv[1])
    print(f"{projects}\nfeatured conversation: {featured_id}")
