# Design — web server

Status: **approved** (2026-10-01) · Implements [requirements.md](requirements.md) · Glossary:
[CONTEXT.md](../../CONTEXT.md) · ADR: [0001 stdlib only](../../docs/adr/0001-web-server-stdlib-only.md) ·
Visual reference: [prototype/ui-mock.html](prototype/ui-mock.html) (approved; mock data, throwaway code)

## 1. Overview

```
 browser ──HTTP(127.0.0.1)──▶ ctokens/web/server.py ──▶ ctokens core modules ──▶ ~/.claude/projects/**.jsonl
   │  ctokens/web/static/          security gate, routes,     logs · reports · catalog    (read-only)
   │  index.html app.js app.css    JSON responses, cache       content · pricing
   └─ static/vendor/: Chart.js, marked, DOMPurify, highlight.js (vendored, ADR 0002)
```

- `claude_tokens.py` started as a proof of concept (~870 lines, one file). This feature first **splits it into a
  package `ctokens/`** without changing behaviour, protected by characterization tests (R10.7), and then adds the
  web feature in new modules (D-029).
- The core modules keep all parsing and pricing. They gain the daily series (R6), multi-source content views (R7),
  a JSON-ready conversation list (R3) and a pure per-file stats function the cache can reuse (R9).
- `ctokens/web/` holds the server and the UI; browser libraries are vendored, so nothing is loaded from a third-party origin (ADR 0002). It has no business logic: every response is built by a core
  function, so the API and `--json` stay identical by construction (D-005).
- `claude_tokens.py` remains the entry point (`python3 claude_tokens.py …` keeps working). `--serve` imports
  `ctokens.web` lazily, so CLI start-up is unchanged.

Python target: **3.9+** (this machine's `python3` is 3.9.21; the code already uses `str.removeprefix`).

## 2. Layout

The package can't be named `claude_tokens/` because it would clash with `claude_tokens.py` on import; it is
`ctokens/`.

```
claude_tokens.py            entry point: from ctokens.cli import main; main()
ctokens/
  __init__.py
  pricing.py    PRICES, FAMILIES, load_prices, parse_model, priced, rate_of, estimated_cost
  logs.py       FIELDS, zero, lines, short, parse_timestamp, task_from_log, parse_log,
                conversation_sources (new), discover, file_stats (new; replaces accumulate_file)
  reports.py    CONTEXT_TIERS, infer_context_window, report, scan_totals, totals_report (+ daily)
  catalog.py    default_projects_dir, project_path_of, count_subagents, session_title, list_conversations,
                conversation_rows (new), resolve_conversation, find_conversation (new)
  content.py    last_response, bash_commands, touched_files
  text.py       ANSI, fmt, money, guessed_notice, table, render_markdown, report_text (was text),
                totals_text, show_page
  cli.py        argument parsing, pick_conversation, show_last_response, show_bash_commands,
                show_touched_files, main
  web/
    __init__.py serve(config, port): entry used by --serve
    server.py   Handler, security gate, routes
    cache.py    StatsCache
    static/     index.html, app.js, app.css
      vendor/   chart.umd.min.js, marked.min.js, purify.min.js, highlight.min.js,
                hljs-light.css, hljs-dark.css, VERSIONS.txt, LICENSES/
tools/
  vendor.py     downloads the pinned library versions into static/vendor/ (run by hand on upgrades)
tests/
  fixtures.py   synthetic projects-folder builder
  golden/       pinned CLI outputs (characterization)
  test_characterization.py, test_core.py, test_cli.py, test_server.py
```

Dependency direction (acyclic): `logs` and `pricing` import nothing from the package; `catalog → logs`;
`reports → catalog, logs, pricing`; `content → logs`; `text → logs`; `cli` and `web` import the rest. No module
imports `cli` or `web`. _(Amended in T3: the first map put `short` in `text` and the `show_*` printers in `text`,
which made the cycle logs → text → content → logs.)_

Rules for the split (R1.7, R10.7):

- Function bodies move unchanged; only imports change. The single rename (`text` → `report_text`) avoids clashing
  with the module name `text`.
- The characterization tests in `tests/golden/` must pass unchanged after the split.

## 3. Core changes

### 3.1 Sources of a conversation (`logs.py`)

New `conversation_sources(main) -> list[tuple[str, Path]]`: `("main", main)` followed by `(subagent_id, path)`
for each `<stem>/subagents/agent-*.jsonl`, sorted. `subagent_id` is the stem without `agent-`, the same id the
usage report already shows. `discover()` is rewritten on top of it, with no behaviour change.

### 3.2 Per-file stats, pure (`logs.py`) — R6, R9

Today's `accumulate_file(path, tools, skills, window, daily)` mutates shared accumulators, so it can't be cached.
It is replaced by a pure function:

```python
def file_stats(path) -> dict:
    # {"models": {model: tokens}, "tools": Counter, "skills": Counter,
    #  "window": [first, last], "responses": Counter(day -> n),
    #  "daily_models": {day_or_None: {model: tokens}}}
```

`day` is `stamp.strftime("%Y-%m-%d")` of the UTC timestamp. A usage record with no valid timestamp goes under the
`None` key, the "undated" bucket (R6.4). The dedup rule (one count per `message.id` per file) is kept as is.

`scan_totals(projects_dir, project_filter=None, stats=file_stats)` merges the per-file dicts. The `stats` parameter
is where the server plugs in its cache; the CLI uses the default.

### 3.3 Daily series in totals (`reports.py`) — R6, R8.4

`totals_report()` adds one key, so `--totals --json` and `GET /api/totals` gain it together:

```json
"daily": [
  {"day": "2026-09-30", "responses": 412, "total_tokens": 1234567, "estimated_cost_usd": 3.21,
   "models": {"claude-opus-5-5": {"input": 0, "output": 0, "cache_read": 0, "cache_write_5m": 0,
                                  "cache_write_1h": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}}},
  {"day": null, "...": "undated bucket, present only when non-empty"}
]
```

- Sorted by day ascending; the undated bucket (`null`) goes last.
- Each (day, model) is priced with the same `rate_of`/`estimated_cost` as the totals. Cost is linear in tokens, so
  the daily costs add up to `estimated_total_cost_usd` up to float rounding (R6.3, tested to 4 decimals).
- A model without pricing has `estimated_cost_usd: null` and adds nothing to its day's cost (R6.5), the same rule
  the totals follow.
- `totals_text()` is not touched (R6.2).

### 3.4 Content views from all sources (`content.py`) — R7

- `bash_commands(main)` iterates `conversation_sources(main)` and returns
  `[{"command", "description", "source", "timestamp"}]` in **chronological** order of the event timestamps.
  Entries without a timestamp keep their log order after the dated ones (D-028).
- `touched_files(main)` returns `{file: {"Read": n, "Write": n, "Edit": n, "sources": ["main", "a0c…"]}}`: one entry
  per file, with counts summed across sources (R7.3 / D-023).
- `last_response(main)` is unchanged and reads the main log only (D-016).
- CLI text output: a Bash entry from a subagent prints `# [subagent <id>] <description>`, and the files table gains
  a `Sources` column. Entries from the main log look exactly as today.
- The JSON changes are additive (D-028): the format is not frozen and may gain fields.

### 3.5 Conversation list as data (`catalog.py`) — R3

New `conversation_rows(projects_dir, project_filter)` turns `list_conversations()` into JSON-ready dicts:
`{"id", "modified" (ISO 8601 UTC, e.g. "2026-10-01T09:05:45Z"), "size_kb", "subagents", "project", "title"}`.
The CLI picker keeps using `list_conversations()`.

### 3.6 Safe lookup by id (`catalog.py`) — R2.4, R2.5, R4.3, R4.4

New `find_conversation(conversation_id, projects_dir) -> (path | None, matches)`:

1. `re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", conversation_id)`, or else
   `(None, [])`. Nothing touches the filesystem before this check passes (R2.4). All 387 current ids match.
2. `projects_dir.glob(f"*/{conversation_id}.jsonl")`. This is safe because a valid id has no glob or path
   characters.
3. Each match must pass `path.resolve().is_relative_to(projects_dir.resolve())`, which also excludes symlinks that
   point outside (R2.5).

`resolve_conversation()`, which accepts paths, is for the CLI only; the server never calls it.

## 4. CLI changes (`cli.py`) — R1

- `--serve` starts the server; `--port N` sets the port (default 8765, valid 1–65535).
- `--serve` accepts only `--port`, `--projects-dir`, `--pricing`, `--cold-summary-output` and `--context-window`
  (D-027). Combined with a conversation argument, `--totals`, `--json`, `--last-response`, `--bash`, `--files` or
  `--project`, it is a `parser.error`. `--port` without `--serve` is also a `parser.error`.
- `--pricing` is loaded once at start-up; an invalid file fails before binding, with the same message as today.
- Port in use: the bind `OSError` becomes `error: port 8765 is already in use`, exit 1, no retry (R1.5).
- Ctrl+C: catch `KeyboardInterrupt`, call `server_close()`, exit 0 (R1.6).
- Start-up banner (R1.3):

```
Serving on http://127.0.0.1:8765  (Ctrl+C to stop)
  projects dir: /home/dev/.claude/projects
  from your machine: ssh -N -L 8765:localhost:8765 <this-host>
```

## 5. Server (`ctokens/web/server.py`)

### 5.1 Process model

`ThreadingHTTPServer(("127.0.0.1", port), Handler)`. With threads, the list and content views stay responsive
while a cold totals scan runs (~4 s). The only shared mutable state is the cache (§7), protected by a single lock.
The configuration (projects dir, prices, cold-summary output, context window) is an immutable object attached to
the server.

### 5.2 Security gate — R2

Runs before routing, on every request:

| Check | Response | Req |
|-------|----------|-----|
| Host name (before `:port`) not in `{"127.0.0.1", "localhost"}`, or no `Host` header | `403` JSON | R2.2 |
| Method other than `GET`/`HEAD` | `405` + `Allow: GET, HEAD` | R2.3 |
| Path not in the route table | `404` | R2.5 |

Detail for R2.3: `BaseHTTPRequestHandler` answers `501` for any method without a `do_<METHOD>` attribute. The
handler defines `__getattr__` so that any undefined `do_*` name resolves to the 405 responder; even `FOO /` gets 405.

Headers on every response: `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` and
`Referrer-Policy: no-referrer`. The HTML page also gets a Content-Security-Policy:

```
default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self';
object-src 'none'; base-uri 'none'; frame-ancestors 'none'
```

The CSP is defence in depth for R2.7: even if an escaping bug slipped through, no inline or third-party script
would run. Chart.js only touches styles through the CSSOM (`.style.width/height/setProperty`; checked in 4.4.1:
no `<style>` elements and no `style` attributes), which `style-src 'self'` doesn't block.

### 5.3 Routes — R3, R4, R5, R7

| Route | Core call | Equivalent CLI |
|-------|-----------|----------------|
| `GET /` | `static/index.html` | — |
| `GET /static/app.js`, `/static/app.css`, `/static/vendor/<file>` | fixed map to the files listed in §2; nothing else is served | — |
| `GET /api/conversations?project=` | `conversation_rows()` | picker |
| `GET /api/conversations/{id}` | `report(discover(path), …)` | `<id> --json` |
| `GET /api/conversations/{id}/last-response` | `last_response()` | `--last-response --json` |
| `GET /api/conversations/{id}/bash` | `bash_commands()` | `--bash --json` |
| `GET /api/conversations/{id}/files` | `touched_files()` | `--files --json` |
| `GET /api/totals?project=` | `totals_report(scan_totals(…, stats=cache))` | `--totals --json` |

- Responses are `application/json; charset=utf-8` and contain the same dict the CLI dumps (`ensure_ascii=False`).
- Errors are `{"error": "<message>"}` with 400/403/404/405. An ambiguous id gets `409 {"error": "ambiguous id",
  "projects": [...]}` (R4.4). An unexpected exception gets `500 {"error": "internal error"}`, with the traceback on
  stderr only.
- `/api/totals` with no conversations returns the empty report (R5.4), not the CLI's `parser.error`.
- Query strings are parsed with `urllib.parse.parse_qs`; unknown parameters are ignored.
- Access log: one line per request on stderr (stdlib default).

## 6. Data flow per request (R9.1)

Every API request lists the projects folder and `stat()`s the files it needs. It never reuses a previous answer, so
a log that changed between two requests is always re-read (R9.1). Only parsing is cached (§7).

## 7. Cache (`ctokens/web/cache.py`) — R9.2, R9.3

```python
class StatsCache:
    # key: resolved path → (st_mtime_ns, st_size, value)
    def get(self, namespace, path, compute): ...
```

- It is a hit if `mtime_ns` and `size` haven't changed; otherwise `compute(path)` runs and its result replaces the
  entry.
- Three namespaces with the same key rule: `file_stats` (totals), `parse_log` (usage report per source) and `meta`
  (`project_path_of` + `session_title` for the list).
- Cached values don't depend on prices: pricing is applied afterwards, in `report()` / `totals_report()`.
- After each totals scan, entries for paths that were not seen are evicted (deleted logs).
- A log that is still being written may end in a partial line. `lines()` skips it with its usual warning, and the
  next request re-parses the file because its `mtime`/`size` changed.
- Expected cost: a cold totals scan costs the same as today's `--totals` (~4.2 s, R9.2). A warm scan is ~725
  `stat()` calls plus merging small dicts, well under 1 s (R9.3, verified manually per D-025).

## 8. UI (`ctokens/web/static/`)

### 8.1 Structure

One page with hash routing:

| Hash | View | Req |
|------|------|-----|
| `#/` | Conversation list | R3 |
| `#/c/{id}` | Usage report, with tabs to the content views | R4 |
| `#/c/{id}/response`, `/bash`, `/files` | Content views | R7 |
| `#/totals` | Totals + charts | R5, R8 |

Every view has the same header: navigation (Conversations · Totals), "Loaded at HH:MM:SS UTC", a Refresh button and
an auto-refresh toggle (30 s; off on every page load and not persisted) (R9.4, R9.5).

### 8.2 Rendering rules (R2.7)

- All text from the logs is inserted with `textContent` / `createTextNode`. `innerHTML` is used **only** with the
  output of `DOMPurify.sanitize(marked.parse(markdown))`.
- Code blocks in the last response are highlighted with highlight.js after sanitizing (R7.5).
- Tables are built by one generic `renderTable(columns, rows)` with click-to-sort on every column; numeric columns
  sort numerically (R3.4).
- Numbers and money are formatted as in the CLI (`fmt`, `money`): `.` as thousands separator, a `~` prefix for
  guessed prices, `N/D` for unknown prices.
- Empty states: explicit messages for no conversations, no response, no Bash commands and no files (R3.6, R5.4,
  R7.6).

### 8.3 Charts (R8) — Chart.js

| Chart | Data | Type |
|-------|------|------|
| Daily cost by model | `totals.daily[]` (dated only) | stacked bar, x = Day (UTC) |
| Model share | `totals.by_model[]` | two bars: % cost and % tokens |
| Projects by cost | `totals.projects[]` (top 15, like the CLI) | horizontal bar |
| Daily activity | `totals.daily[].responses` | line, x = Day (UTC) |
| Tools / skills | `totals.tools`, `totals.skills` (top 15) | horizontal bars |

- The undated bucket is not plotted; when it exists, a note under the daily chart shows its cost and tokens.
- Every per-day axis title ends in "(UTC)" (R8.5).
- The project filter on the Totals view requests `/api/totals?project=…` again, so charts and tables always come from
  the same response (R8.6).

### 8.4 Visual design — R11

- **Tokens** (`app.css` `:root`): background, surface, text, muted text, border and accent colours, a spacing scale
  and radii, in light values, redefined under `@media (prefers-color-scheme: dark)` (R11.2, R11.3). Font:
  `system-ui` stack; code: `ui-monospace` stack.
- **Model colours** (R11.1): a fixed categorical palette of 8 colours (`--m0`…`--m7`) that work in both themes.
  A model's colour is assigned in the client:
  - known families have fixed slots (opus, sonnet, haiku, fable, mythos), so their colours never change between
    views or loads;
  - within a family, the newest version (highest version numbers) gets the family's base colour, and each older
    version present in the data gets a lighter tint of it (mixed towards the surface colour by 38 %, then 55 %);
  - unknown models take the remaining slots in order of first appearance and keep them for the session.

  Every chart and every model cell in a table (as a swatch) uses the same assignment. Reference: the prototype
  (`prototype/ui-mock.html`, `assignColors`).
- **Charts** read their axis, grid and text colours from the CSS tokens, so they follow the theme.
- **Numbers** (R11.4): `text-align: right; font-variant-numeric: tabular-nums` on numeric cells.
- **States** (R11.5): each view shows a skeleton/spinner while waiting (a cold totals scan takes ~4 s) and, on
  error, the API's `error` message with a Retry button.
- **Width** (R11.6): max content width ~1200 px; the layout works from 768 px up (charts fill their container, wide
  tables scroll horizontally inside their card).
- The highlight.js theme is chosen per colour scheme (one light and one dark stylesheet, switched with `media`).

### 8.5 Libraries (R2.8, ADR 0002)

Chart.js, marked, DOMPurify and highlight.js (core + one light and one dark stylesheet) are vendored in
`static/vendor/` and loaded with plain same-origin `<script>`/`<link>` tags. `tools/vendor.py` (stdlib `urllib`)
downloads the pinned versions from cdnjs, writes them with their license texts into `vendor/LICENSES/`, and
records each file's version and SHA-256 in `vendor/VERSIONS.txt`. It is run by hand when upgrading, never by the
tests or the server. The versions are fixed in T13 (the latest stable release at that time; the prototype used
Chart.js 4.4.1, marked 12.0.2, DOMPurify 3.1.6 and highlight.js 11.9.0).

## 9. Testing — R10

`python3 -m unittest discover -s tests` (stdlib only).

- `tests/fixtures.py` builds a temporary projects folder with fixed file mtimes and contents:
  - conversations with assistant usage on several UTC days, including one record without timestamp;
  - two projects;
  - subagents with Bash/Read/Edit calls;
  - a duplicated `message.id` and a malformed line;
  - a conversation id present in two projects;
  - a model without pricing and a model with guessed pricing.
- **test_characterization** (written **before** the split, R10.7): runs `claude_tokens.py` with `TZ=UTC` and the
  fixture folder, and compares against `tests/golden/` the text and `--json` output of: the usage report, `--totals`,
  `--last-response`, `--bash`, `--files` and the non-TTY picker listing. Goldens are refreshed by an explicit script
  (`tests/golden/refresh.py`), never automatically. The only goldens allowed to change later are those for R6.2
  (`--totals --json` gains `daily`) and R7.2–R7.4 (`--bash`/`--files` gain sources).
- **test_core**:
  - daily series: sum equals the total to 4 decimals, undated bucket, unpriced model → null;
  - `touched_files` aggregation and sources; chronological `bash_commands`;
  - `find_conversation`: rejects `../x`, `/etc/passwd`, `*` and a symlink that points outside; detects an
    ambiguous id;
  - `conversation_rows` fields and UTC format.
- **test_cli** (subprocess): flag conflicts (`--port` without `--serve`, `--serve` with each forbidden option);
  `--serve` with the allowed options; port in use → exit 1.
- **test_server**: the server runs on port 0 in a thread.
  - Parity (D-005): the JSON of every route equals the matching CLI `--json` output.
  - Gate and errors: 403 for a bad Host; 405 for POST and for an arbitrary method; 404 for bad ids, for encoded
    traversal (`%2e%2e%2f`, `%2Fetc%2Fpasswd`) and for unknown paths; 409 for an ambiguous id.
  - Security headers are present.
  - Cache: a second `/api/totals` doesn't call `file_stats` again for unchanged files, and touching one file
    re-parses only that one.
- **Manual UI checklist** (in tasks.md): charts and UTC labels, model colours that match across views, light and
  dark themes, Markdown + highlighting, sanitizing (`<img src=x onerror=…>` in a fixture response), sorting,
  filtering, refresh and auto-refresh, loading and error states, 768 px width, an SSH tunnel to another local port,
  and the R9.2/R9.3 timings on the real folder.

## 10. Traceability

| Req | Design |
|-----|--------|
| R1 | §2, §4 |
| R2 | §3.6, §5.2, §8.2, §8.5 |
| R3 | §3.5, §5.3, §8.1–8.2 |
| R4 | §3.6, §5.3, §8.1 |
| R5 | §3.3, §5.3, §8.3 |
| R6 | §3.2, §3.3 |
| R7 | §3.1, §3.4, §5.3, §8.2 |
| R8 | §8.3 |
| R9 | §6, §7, §8.1 |
| R10 | §2 (split rules), §9, README |
| R11 | §8.4 |

## Resolved during review

- **RV1 — layout:** split the PoC into the `ctokens/` package, with new functionality in separate modules, so files
  don't grow large (D-029). Characterization tests come first (R10.7).
- **RV2 — JSON changes:** accepted; the JSON format is not frozen and may gain fields (D-028).
- **RV3 — Chart.js:** accepted; an external library is preferred so the effort goes into usability and a coherent,
  modern visual design (§8.4, R11, D-030).
- **RV4 — `--serve` options:** only `--port` plus the configuration options (`--projects-dir`, `--pricing`,
  `--cold-summary-output`, `--context-window`); everything else is an error (D-027).
