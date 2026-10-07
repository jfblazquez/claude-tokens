"""Build a synthetic Claude Code projects folder for the README screenshots: invented projects, no real data.

Usage: python3 tools/demo_projects.py OUTPUT_DIR   (writes OUTPUT_DIR/projects; same seed, same files)
"""
import json
import os
import random
import sys
import uuid
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 7
START = datetime(2026, 9, 7, tzinfo=timezone.utc)
DAYS = 30
FEATURED_TITLE = "Add rate limiting to the public API"

Project = namedtuple("Project", "cwd weight files titles")
PROJECTS = [
    Project("/home/dev/projects/api-gateway", 5,
            ["src/router.py", "src/middleware/auth.py", "src/middleware/rate_limit.py", "src/cache.py",
             "tests/test_router.py", "tests/test_rate_limit.py", "README.md"],
            ["Fix flaky router tests", "Cache invalidation on config reload", "Migrate auth middleware to async",
             "Structured request logging"]),
    Project("/home/dev/projects/billing-service", 3,
            ["billing/invoices.py", "billing/ledger.py", "billing/exports.py", "tests/test_ledger.py",
             "migrations/0042_invoice_status.sql"],
            ["Retry policy for ledger exports", "Invoice status migration", "Investigate rounding in VAT totals",
             "Monthly export to CSV"]),
    Project("/home/dev/projects/web-dashboard", 3,
            ["src/App.tsx", "src/pages/Usage.tsx", "src/components/Chart.tsx", "src/api/client.ts", "package.json"],
            ["Dark mode for the usage page", "Paginate the invoices table", "Replace chart library",
             "Fix layout on small screens"]),
    Project("/home/dev/projects/data-pipeline", 2,
            ["pipeline/ingest.py", "pipeline/transform.py", "dags/daily_rollup.py", "tests/test_transform.py"],
            ["Backfill September rollups", "Speed up the transform step", "Schema drift alerts"]),
    Project("/home/dev/projects/mobile-app", 1,
            ["lib/main.dart", "lib/screens/settings.dart", "lib/services/sync.dart", "pubspec.yaml"],
            ["Offline sync conflicts", "Settings screen redesign"]),
    Project("/home/dev/projects/infra", 1,
            ["terraform/main.tf", "terraform/modules/db/main.tf", "k8s/deployment.yaml", ".github/workflows/ci.yml"],
            ["Terraform plan for the new database", "CI cache for dependencies"]),
]
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


def conversation(rnd, root, project, title, day, model, steps, skill, tasks, last):
    start = START + timedelta(days=day, hours=rnd.randint(7, 18), minutes=rnd.randint(0, 59))
    log = Log(rnd, project.cwd, model, start)
    log.user(title)
    log.events.append({"type": "ai-title", "aiTitle": title})
    work(rnd, log, project.files, steps[0])
    if skill:
        log.tool("Skill", skill=skill)
    conv_id = str(uuid.UUID(int=rnd.getrandbits(128), version=4))
    folder = root / project.cwd.replace("/", "-")
    for task in tasks:
        sub_id = f"a{rnd.getrandbits(64):016x}"
        log.tool("Agent", description=task, prompt=task)
        sub = Log(rnd, project.cwd, rnd.choice(["claude-sonnet-5-5", "claude-haiku-4-5", "claude-opus-5-5"]), log.t)
        sub.user(task)
        work(rnd, sub, project.files, rnd.randint(4, 14))
        sub_dir = folder / conv_id / "subagents"
        write(sub_dir / f"agent-{sub_id}.jsonl", sub.events, sub.t)
        (sub_dir / f"agent-{sub_id}.meta.json").write_text(json.dumps({"description": task}), encoding="utf-8")
    work(rnd, log, project.files, steps[1])
    log.respond([{"type": "text", "text": last}])
    write(folder / f"{conv_id}.jsonl", log.events, log.t)
    return conv_id


def build(base):
    rnd = random.Random(SEED)
    root = Path(base) / "projects"
    for _ in range(48):
        day = rnd.randint(0, DAYS - 2)
        if rnd.random() < 0.25 and day % 7 in (5, 6):
            continue
        project = rnd.choices(PROJECTS, [p.weight for p in PROJECTS])[0]
        title = rnd.choice(project.titles)
        model = "claude-opus-5" if day < 14 and rnd.random() < 0.7 else rnd.choices(
            ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"], [6, 3, 1])[0]
        conversation(rnd, root, project, title, day, model, steps=(rnd.randint(6, 45), rnd.randint(1, 6)),
                     skill=rnd.choice(SKILLS) if rnd.random() < 0.35 else None,
                     tasks=rnd.choices(SUBAGENT_TASKS, k=rnd.choice([0, 0, 0, 1, 2, 3])), last=f"Done: {title.lower()}.")
    featured = conversation(rnd, root, PROJECTS[0], FEATURED_TITLE, DAYS - 1, "claude-opus-5-5", steps=(40, 6),
                            skill=rnd.choice(SKILLS[:3]), tasks=SUBAGENT_TASKS[:5], last=LAST_RESPONSE)
    return root, featured


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip())
    projects, featured_id = build(sys.argv[1])
    print(f"{projects}\nfeatured conversation: {featured_id}")
