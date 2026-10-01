# Tasks — web server

Status: **approved** (2026-10-01) · Implements [requirements.md](requirements.md) and [design.md](design.md) ·
Visual reference: [prototype/ui-mock.html](prototype/ui-mock.html)

## How to work through this plan

- Branch `feature/web-server`, created from `main`. One commit per task (T3: one commit per module moved), with a
  short one-line message and no trailers. The user has authorised these commits (TV1).
- Tasks run in order: each phase depends on the previous one. Tick a task (`[x]`) only when its **Done when**
  checks pass.
- After every task: `python3 -m unittest discover -s tests` must pass on **Python 3.9 and 3.12**
  (`python3` and `python3.12` on this machine).
- Golden files in `tests/golden/` may change **only** in T5b, T6 and T7, and only for the outputs named there
  (R10.7).
- The prototype is a visual reference, not code to copy. The UI is rewritten properly with the design's rules
  (escaping, vendored libraries, CSP).

## Phase 0 — Specs under version control

- [x] **T0. Commit the SDD artifacts**
  - Create the branch; commit `CONTEXT.md`, `docs/adr/0001-…`, `docs/sdd-learning/web-server-log.md` and
    `specs/web-server/` (requirements, design, tasks, prototype).
  - Done when: `git status` is clean on `feature/web-server`.

## Phase 1 — Safety net before touching code (R10.7)

- [x] **T1. Synthetic fixtures** — `tests/fixtures.py` (design §9)
  - `build_projects(tmpdir) -> Path` creates a projects folder with fixed contents and fixed mtimes:
    - usage on several UTC days and one record without timestamp;
    - two projects;
    - subagents with Bash/Read/Edit calls (with `.meta.json` descriptions);
    - a duplicated `message.id` and a malformed line;
    - the same conversation id in two projects;
    - a model without pricing and a model with guessed pricing (e.g. `claude-sonnet-5-6`);
    - an assistant text response containing `<script>` and a `javascript:` link.
  - Tests: `test_fixtures` checks the tree is identical across two builds (paths, sizes, mtimes).
  - Done when: two builds are byte-identical.
- [x] **T2. Characterization tests of the current CLI**
  - `tests/golden/refresh.py` regenerates the goldens explicitly (it never runs inside the tests).
  - `tests/test_characterization.py` runs `claude_tokens.py` as a subprocess with `TZ=UTC` and `--projects-dir
    <fixtures>`, and compares stdout/stderr/exit code with the goldens for: the usage report (text, `--json`),
    `--totals` (text, `--json`), `--last-response`, `--bash` and `--files` (text, `--json`), the non-TTY picker
    listing, and the errors for an ambiguous id and an unknown id.
  - Stable goldens (risk K-1):
    - each subprocess runs with `TZ=UTC`, `COLUMNS=120` and `LANG=C.UTF-8`;
    - the temporary fixture path is replaced with `<FIXTURES>` before comparing;
    - the `--help` heading is normalised (`optional arguments:` on 3.9 → `options:` on 3.12).
  - Coverage (risk K-2): run the characterization suite under `python3 -m trace --count --missing` and require
    **≥ 80 %** of the lines of `claude_tokens.py` executed. Record the uncovered functions and lines in the learning
    log, with a reason for each.
  - Done when: the goldens are generated from the **unmodified** `claude_tokens.py`, the tests pass on 3.9 and
    3.12, and coverage is ≥ 80 %.

## Phase 2 — Split the PoC into `ctokens/` (design §2, R1.7)

- [x] **T3. Move code into the package without changing behaviour** (one commit per module, TV2)
  - Create `ctokens/{__init__,pricing,logs,reports,catalog,content,text,cli}.py` following the map in design §2.
    Function bodies move unchanged; only the imports change. Rename `text()` → `report_text()`.
  - `claude_tokens.py` becomes the entry point (`from ctokens.cli import main`).
  - Check the dependency direction of §2 (no module imports `cli` or `web`).
  - Tests: characterization passes unchanged; `--help` output identical to before (add to goldens in T2 if
    missing).
  - Manual: interactive picker in a real TTY (paging, `a`, `q`, selecting a number), which goldens can't cover.
  - Done when: characterization is green and the manual picker check is OK.

## Phase 3 — Core changes (design §3)

- [x] **T4. `conversation_sources()` and `discover()` on top of it** (§3.1)
  - Tests: sources order (`main` first, subagents sorted, id without `agent-`); characterization unchanged.
- [x] **T5. Pure `file_stats()` and `scan_totals(stats=…)`** (§3.2, R9)
  - Replace `accumulate_file`. Undated records go under the `None` key.
  - Tests: `file_stats` is pure (same input → equal output, no shared state); characterization of `--totals`
    unchanged; the `stats` hook is called once per log.
- [x] **T5b. Count each tool call once by `tool_use` id** (R5.5, D-042)
  - In `file_stats`, keep the `message.id` dedup for usage and responses, but count `tool_use` blocks from
    **every** event, deduplicated by block `id` (fall back to counting the block when it has no id).
  - Tests: a response split over several events with text + 2 tool_use blocks counts 2 tools; a repeated block with
    the same id counts once; `Skill` invocations follow the same rule.
  - Goldens: `--totals` text and JSON regenerated (tool and skill counts change). Usage, tokens and cost must not
    change.
- [x] **T6. Daily series in `totals_report()`** (§3.3, R6)
  - Tests: daily costs add up to the total within 4 decimals (R6.3); undated bucket last and only when non-empty
    (R6.4); unpriced model → `null` daily cost (R6.5); days ascending and in UTC.
  - Goldens: `--totals --json` regenerated (gains `daily`). `--totals` text must stay unchanged (R6.2).
- [x] **T7. Content views from all sources** (§3.4, R7.1–R7.4)
  - `bash_commands` in chronological order with `source` and `timestamp`; `touched_files` with aggregated counts
    and `sources`; text output with `# [subagent <id>]` and a `Sources` column.
  - Deduplicate Bash entries and file operations by `tool_use` id (R7.7).
  - Tests: interleaved order across main and subagents; entries without a timestamp after the dated ones; one row
    per file with summed counts; a repeated block listed/counted once; `last_response` still main-only.
  - Goldens: `--bash` and `--files` (text and JSON) regenerated. Nothing else may change.
- [x] **T8. `conversation_rows()` and `find_conversation()`** (§3.5, §3.6, R2.4, R2.5, R3.1)
  - Tests: row fields and `modified` as ISO 8601 UTC with `Z`; `find_conversation` rejects `../x`,
    `/etc/passwd`, `*`, an uppercase/short id and a symlink that points outside, all without touching the
    filesystem (check with a patched `glob`); ambiguous id → two matches.

## Phase 4 — Server (design §4–§7)

- [x] **T9. `--serve` / `--port` in the CLI and a bare server** (§4, R1)
  - `ctokens/web/__init__.py: serve(config, port)`; `ThreadingHTTPServer` on `127.0.0.1`; start-up banner;
    Ctrl+C → exit 0; port in use → error, exit 1.
  - Tests (`test_cli`): `--port` without `--serve`; `--serve` with each forbidden option; allowed options accepted;
    an invalid `--pricing` fails before binding; port in use → exit 1 with the port in the message.
- [x] **T10. Security gate and headers** (§5.2, R2.1–R2.3)
  - Host check (name only, any port), `__getattr__` → 405 for any method other than GET/HEAD, 404 outside the
    route table, the common headers, and the CSP on the HTML.
  - Tests (`test_server`, server on port 0): bad Host → 403; no Host → 403; `localhost:9000` Host → allowed;
    POST/PUT/DELETE and `FOO` → 405 with `Allow`; unknown path → 404; headers present.
- [x] **T11. API routes** (§5.3, R3–R5, R7)
  - Tests: **parity**, where every route's JSON equals the matching CLI `--json` output on the fixtures; bad id,
    `%2e%2e%2f…`, `%2Fetc%2Fpasswd` → 404; ambiguous id → 409 with projects; empty projects folder → empty list and
    empty totals (not an error); `?project=` filter; unexpected exception → 500 with no traceback in the body.
- [x] **T12. `StatsCache`** (§7, R9.1, R9.3)
  - Wire it into totals, report and list.
  - Tests: a second `/api/totals` doesn't call `file_stats` for unchanged logs; touching one log (mtime/size)
    re-parses only that one; a deleted log disappears from the next response and from the cache; concurrent
    requests don't corrupt the cache (a few threads calling `/api/totals`).

## Phase 5 — UI (design §8, prototype)

- [x] **T13. Static shell** (§8.1, §8.4, §8.5, R9.4, R9.5, R11)
  - `ctokens/web/static/index.html`, `app.css` (tokens light/dark taken from the prototype), `app.js` (hash
    router, app bar with "Loaded at … UTC", Refresh, auto-refresh 30 s off by default, generic `renderTable`,
    loading/empty/error states).
  - `tools/vendor.py` downloads the latest stable Chart.js, marked, DOMPurify and highlight.js (+ light/dark
    stylesheets) into `static/vendor/` with `LICENSES/` and `VERSIONS.txt` (ADR 0002). Commit the vendored files.
  - Tests: `/` serves the HTML with the `'self'`-only CSP; every file of the fixed map (§2) is served with the right
    content type; any other `/static/…` → 404; `index.html` references no absolute `http(s)://` URL.
- [x] **T14. Conversation list and usage report views** (§8.1–8.2, R3, R4)
- [x] **T15. Content views** (§8.2, R7.5, R7.6)
  - Markdown with marked + DOMPurify, highlight.js with light and dark stylesheets, the Bash list with source chips
    and the files table with sources.
- [x] **T16. Totals view, charts and model colours** (§8.3, §8.4, R5, R8, R11.1)
  - The 5 charts, the undated note, the project filter, and `assignColors` with the per-version tint rule (D-033).

## Phase 6 — Docs and verification

- [x] **T17. README** (R10.6)
  - `--serve`, `--port`, the allowed options, the SSH tunnel, the API routes, the `daily` field in
    `--totals --json`, the sources in `--bash`/`--files`, and how to run the tests.
- [ ] **T18. Manual verification** (automatable part done; visual checks pending — see the learning log) (R9.2, R9.3, R10.5)
  - Run the checklist below against the real projects folder through an SSH tunnel; record results, timings and
    any defect in the learning log.

## Manual UI checklist (R10.5)

| # | Check | Req |
|---|-------|-----|
| M1 | The list matches `claude_tokens.py` picker data (same order, counts, titles); sorting works on every column; the project filter narrows rows | R3 |
| M2 | Report sections match the CLI text report for the same conversation; the guessed-price notice appears when it applies | R4 |
| M3 | Last response renders tables, lists and highlighted code; the fixture's `<script>` and `javascript:` link do nothing | R7.5, R2.7 |
| M4 | Bash entries are chronological with source chips; files show one row per file with sources | R7 |
| M5 | Totals: the 5 charts render; day axes say UTC; the undated note appears with the fixture | R8 |
| M6 | One model has the same colour in every chart and table; two versions of a family are distinguishable | R11.1 |
| M7 | Light and dark follow the OS setting; nothing is unreadable in either theme | R11.2 |
| M8 | Loading state during a cold totals scan; error state with the API message when the server is stopped | R11.5 |
| M9 | Refresh updates "Loaded at"; auto-refresh is off on load and reloads every 30 s when turned on | R9.4, R9.5 |
| M10 | Usable at 768 px wide; wide tables scroll inside their card | R11.6 |
| M11 | Works through `ssh -N -L 9000:localhost:8765 <host>` (a different local port) | R2.2 |
| M12 | First `/api/totals` ≤ 5 s and the next one < 1 s on the real folder (`curl -w '%{time_total}'`) | R9.2, R9.3 |
| M13 | No console errors or CSP violations in the browser dev tools; the Network tab shows no request to another origin | R2.8 |

## Traceability

| Req | Tasks |
|-----|-------|
| R1 | T3, T9 |
| R2 | T8, T10, T11, T13, T15, M3, M11, M13 |
| R3 | T8, T11, T14, M1 |
| R4 | T11, T14, M2 |
| R5 | T5b, T6, T11, T16 |
| R6 | T5, T6 |
| R7 | T4, T7, T11, T15, M3, M4 |
| R8 | T16, M5 |
| R9 | T5, T12, T13, M9, M12 |
| R10 | T1, T2, T17, T18 |
| R11 | T13, T16, M6–M8, M10 |

## Risk register

Every risk is closed (shown not to apply, with evidence), mitigated (a task or test covers it) or accepted (with
its rationale). Reviewed on 2026-10-01.

| # | Risk | Status | How |
|---|------|--------|-----|
| K-1 | Unstable goldens: `argparse` help differs between 3.9 and 3.12, the JSON includes temporary paths, the help width depends on `COLUMNS` | Mitigated | T2: fixed env, `<FIXTURES>` placeholder, normalised help heading |
| K-2 | Characterization covers only what the fixtures exercise | Mitigated | T2: ≥ 80 % of lines executed (stdlib `trace`), uncovered lines recorded; manual TTY picker check in T3 |
| K-3 | CDN dependency (offline, blocked networks) and SRI upkeep | Closed | Libraries vendored (ADR 0002); CSP `'self'` only; T13 test and M13 |
| K-4 | Chart.js blocked by the CSP | Closed | Checked in 4.4.1: CSSOM only, no `<style>` or `style` attributes; M13 confirms in the browser |
| K-5 | stderr noise from malformed lines | Accepted | 0 warnings over the 725 real logs (2026-10-01); the cache only re-parses changed logs; the warning is the server's diagnostic log |
| K-6 | Python 3.9 compatibility | Mitigated | Every task requires the suite to pass on 3.9 and 3.12 |
| K-7 | Prototype in `main` mistaken for production code | Accepted | D-035; the file says PROTOTYPE in a comment and in its control bar, and design.md links it as a visual reference |

## Resolved during review

- **TV1 — commits:** the user authorises one commit per task during implementation.
- **TV2 — granularity:** T3 is done as one commit per module moved.
