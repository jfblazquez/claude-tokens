"""Build a synthetic Claude Code projects folder for the README screenshots: invented projects, no real data.

Usage: python3 tools/demo_projects.py OUTPUT_DIR   (writes OUTPUT_DIR/projects; same seed, same files)

The api-gateway project is also a real git repository at OUTPUT_DIR/home/dev/projects/api-gateway, so its links to
commits and files open, and OUTPUT_DIR/home holds a .bashrc with a neutral prompt for the shell panel.
"""
import json
import os
import random
import subprocess
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
# Recaps for some titles, so the list shows cards with and without one.
RECAPS = {
    FEATURED_TITLE: "Rate limiting is in place for `/v1/*` with a Redis token bucket and the tests pass. Next: decide "
                    "whether to expose the remaining quota in `X-RateLimit-Remaining`.",
    "Fix flaky router tests": "The flaky test came from a shared event loop; each test now gets its own and the suite "
                              "passed 50 runs in a row. Next: open the PR.",
    "Migrate auth middleware to async": "The auth middleware is async and the old sync path is gone. Two integration "
                                        "tests still time out on CI; next is raising their timeout or mocking the IdP.",
    "Retry policy for ledger exports": "Exports now retry three times with exponential backoff. Waiting for you to "
                                       "confirm whether failed exports should page on-call.",
    "Investigate rounding in VAT totals": "VAT totals were rounded per line instead of per invoice. The fix is ready; "
                                          "next, check last month's invoices for affected customers.",
    "Dark mode for the usage page": "Dark mode works on the usage page; the chart colours still need a darker grid. "
                                    "Next: pick the grid colour with you.",
    "Backfill September rollups": "September rollups are backfilled up to the 21st; the job stopped on a schema "
                                  "change. Next: rerun from the 22nd after the migration.",
    "Terraform plan for the new database": "The plan creates the database, its subnet group and two parameter groups. "
                                           "Next: review the plan with you before `terraform apply`.",
}
SKILLS = ["code-review", "simplify", "security-review", "tdd", "explain-code", "diagnosing-bugs"]
SUBAGENT_TASKS = ["Explore call sites of the limiter", "Review the rate limit tests", "Security review of the change",
                  "Check the docs for outdated examples", "Benchmark the middleware", "Find similar bugs elsewhere"]
LAST_RESPONSE = """## Rate limiting is in place

Requests are now limited **per API key** with a token bucket stored in Redis. It landed in {limit}, and
{retry} added `Retry-After`; the middleware is `src/middleware/rate_limit.py:15` and is exported from `__init__.py`.

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


ROUTER_V1 = """from fastapi import FastAPI

from .cache import cache
from .middleware import auth

app = FastAPI()
app.middleware("http")(auth)


@app.get("/v1/items")
async def items():
    return await cache.get_or_load("items")


@app.post("/v1/items")
async def create_item(item: dict):
    await cache.invalidate("items")
    return {"created": item}


@app.post("/v1/export")
async def export():
    return {"queued": True}
"""
RATE_LIMIT_V1 = """import time

from fastapi.responses import JSONResponse

from .buckets import RedisBuckets

LIMITS = {
    ("GET", "/v1/items"): (600, 100),
    ("POST", "/v1/items"): (120, 20),
    ("POST", "/v1/export"): (10, 2),
}
buckets = RedisBuckets(LIMITS)


async def rate_limit(request, call_next):
    key = request.state.api_key
    bucket = await buckets.take(key, request.method, request.url.path)
    if bucket.empty:
        return JSONResponse({"error": "rate limited"}, status_code=429)
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(bucket.limit)
    return response
"""
FILES_V1 = {
    "README.md": "# api-gateway\n\nPublic HTTP API in front of the item and export services.\n\n"
                 "```bash\npython3 -m pytest -q\n```\n",
    "src/__init__.py": "from .router import app\n\n__all__ = [\"app\"]\n",
    "src/router.py": ROUTER_V1,
    "src/cache.py": "class Cache:\n    def __init__(self):\n        self.entries = {}\n\n"
                    "    async def get_or_load(self, key):\n        return self.entries.setdefault(key, [])\n\n"
                    "    async def invalidate(self, key):\n        self.entries.pop(key, None)\n\n\ncache = Cache()\n",
    "src/middleware/__init__.py": "from .auth import auth\n\n__all__ = [\"auth\"]\n",
    "src/middleware/auth.py": "from fastapi.responses import JSONResponse\n\n\nasync def auth(request, call_next):\n"
                              "    key = request.headers.get(\"X-API-Key\")\n    if not key:\n"
                              "        return JSONResponse({\"error\": \"missing API key\"}, status_code=401)\n"
                              "    request.state.api_key = key\n    return await call_next(request)\n",
    "tests/test_router.py": "def test_items(client):\n    assert client.get(\"/v1/items\").status_code == 200\n",
}
FILES_V2 = {
    "src/middleware/__init__.py": "from .auth import auth\nfrom .rate_limit import rate_limit\n\n"
                                  "__all__ = [\"auth\", \"rate_limit\"]\n",
    "src/middleware/rate_limit.py": RATE_LIMIT_V1,
    "src/router.py": ROUTER_V1.replace("from .middleware import auth\n", "from .middleware import auth, rate_limit\n")
                              .replace("app.middleware(\"http\")(auth)\n",
                                       "app.middleware(\"http\")(rate_limit)\napp.middleware(\"http\")(auth)\n"),
    "tests/test_rate_limit.py": "def test_burst_is_limited(client):\n"
                                "    codes = [client.post(\"/v1/export\").status_code for _ in range(3)]\n"
                                "    assert codes == [200, 200, 429]\n",
}
FILES_V3 = {
    "src/middleware/rate_limit.py": RATE_LIMIT_V1.replace(
        "        return JSONResponse({\"error\": \"rate limited\"}, status_code=429)\n",
        "        return JSONResponse({\"error\": \"rate limited\"}, status_code=429,\n"
        "                            headers={\"Retry-After\": str(bucket.retry_after)})\n"),
}
COMMITS = [("Initial API gateway", FILES_V1, 0),
           ("Add token bucket rate limiting per API key\n\nLimits come from LIMITS and the buckets live in Redis, so "
            "every gateway\ninstance shares them.", FILES_V2, 28),
           ("Return Retry-After on 429", FILES_V3, 29)]
BASHRC = "PS1='dev@demo:\\W\\$ '\nalias ls='ls --color=auto'\n"


def build_repo(repo):
    """The api-gateway repository with fixed authors and dates, so the commit ids are the same on every build."""
    shas = []
    for i, (message, files, day) in enumerate(COMMITS):
        when = stamp(START + timedelta(days=day, hours=9 + i))
        env = {**os.environ, "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@example.com", "GIT_AUTHOR_DATE": when,
               "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@example.com", "GIT_COMMITTER_DATE": when,
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        git = lambda *args: subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, stdout=subprocess.PIPE,
                                           text=True).stdout.strip()
        if i == 0:
            repo.mkdir(parents=True)
            git("init", "-q", "-b", "main")
        for name, text in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(text, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", message)
        shas.append(git("rev-parse", "--short=7", "HEAD"))
    return shas


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
    if title in RECAPS:
        log.events.append({"type": "system", "subtype": "away_summary", "timestamp": stamp(log.t),
                           "content": f"{RECAPS[title]} (disable recaps in /config)"})
    log.respond([{"type": "text", "text": last}])
    write(folder / f"{conv_id}.jsonl", log.events, log.t)
    return conv_id


def build(base):
    rnd = random.Random(SEED)
    base = Path(base).resolve()
    root = base / "projects"
    api = PROJECTS[0]
    repo = base / api.cwd.lstrip("/")
    shas = build_repo(repo)
    (base / "home").mkdir(exist_ok=True)
    (base / "home" / ".bashrc").write_text(BASHRC, encoding="utf-8")
    projects = [api._replace(cwd=str(repo))] + PROJECTS[1:]
    for _ in range(48):
        day = rnd.randint(0, DAYS - 2)
        if rnd.random() < 0.25 and day % 7 in (5, 6):
            continue
        project = rnd.choices(projects, [p.weight for p in projects])[0]
        title = rnd.choice(project.titles)
        model = "claude-opus-5" if day < 14 and rnd.random() < 0.7 else rnd.choices(
            ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"], [6, 3, 1])[0]
        conversation(rnd, root, project, title, day, model, steps=(rnd.randint(6, 45), rnd.randint(1, 6)),
                     skill=rnd.choice(SKILLS) if rnd.random() < 0.35 else None,
                     tasks=rnd.choices(SUBAGENT_TASKS, k=rnd.choice([0, 0, 0, 1, 2, 3])), last=f"Done: {title.lower()}.")
    last = LAST_RESPONSE.replace("{limit}", shas[1]).replace("{retry}", shas[2])
    featured = conversation(rnd, root, projects[0], FEATURED_TITLE, DAYS - 1, "claude-opus-5-5", steps=(40, 6),
                            skill=rnd.choice(SKILLS[:3]), tasks=SUBAGENT_TASKS[:5], last=last)
    return root, featured


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip())
    projects, featured_id = build(sys.argv[1])
    print(f"{projects}\nfeatured conversation: {featured_id}")
