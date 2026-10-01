# Requirements — web server

Status: **approved** (2026-10-01; amended in design review: R1.4 clarified, R10.7 and R11 added; amended in risk review: R2.8; amended in implementation: R5.5, R7.7) · Glossary: [CONTEXT.md](../../CONTEXT.md) · Decisions: D-001…D-022 in
[the learning log](../../docs/sdd-learning/web-server-log.md) · ADR: [0001](../../docs/adr/0001-web-server-stdlib-only.md)

## Introduction

`claude-tokens` reports token usage and estimated cost of Claude Code conversations from the terminal. This feature
adds a local web server that exposes the same information as a JSON **API** and a browser **UI** with charts, so the
data can be explored from a browser (through an SSH tunnel when the tool runs on a remote machine).

Acceptance criteria use EARS: `WHEN <event> THEN THE SYSTEM SHALL …`, `IF <condition> THEN …`,
`WHILE <state> …`, and `THE SYSTEM SHALL …` for things that must always hold.

## R1 — Launching the server

**User story:** As a user, I want to start a web server from the same script, so that I can explore my usage in a
browser with the same configuration I use on the CLI. _(D-011, D-021)_

1. WHEN the user runs `claude_tokens.py --serve` THEN THE SYSTEM SHALL start an HTTP server on `127.0.0.1` port
   `8765` and keep running in the foreground until interrupted.
2. WHEN `--port N` is given with `--serve` THEN THE SYSTEM SHALL listen on port `N`.
3. WHEN the server starts THEN THE SYSTEM SHALL print the URL, the projects folder in use and an example SSH tunnel
   command for that port.
4. THE SYSTEM SHALL apply `--projects-dir`, `--pricing`, `--cold-summary-output` and `--context-window` to every
   API response exactly as the CLI applies them; the project filter is chosen per request (R3.3, R5.2).
   IF `--serve` is combined with any other option (a conversation, `--totals`, `--json`, `--last-response`,
   `--bash`, `--files`, `--project`) THEN THE SYSTEM SHALL exit with an error.
5. IF the port is already in use THEN THE SYSTEM SHALL exit with a non-zero status and an error message naming the
   port, without trying another port.
6. WHEN the user presses Ctrl+C THEN THE SYSTEM SHALL stop the server and exit with status 0.
7. THE SYSTEM SHALL keep every existing CLI mode working unchanged when `--serve` is not given, except for the
   changes required by R7.

## R2 — Access and security

**User story:** As a user, I want the server to be reachable only by me and to never expose files outside my
projects folder, because conversation content includes prompts, commands and file paths. _(D-008, D-020)_

1. THE SYSTEM SHALL bind only to `127.0.0.1`; THE SYSTEM SHALL NOT offer an option to bind to another address.
2. IF the host name in a request's `Host` header is not `127.0.0.1` or `localhost` (any port, so SSH tunnels to a
   different local port work) THEN THE SYSTEM SHALL answer `403` without reading any conversation.
3. IF a request uses a method other than `GET` (or `HEAD`) THEN THE SYSTEM SHALL answer `405`.
4. IF a conversation id in a request does not match the UUID format THEN THE SYSTEM SHALL answer `404` without
   touching the filesystem.
5. THE SYSTEM SHALL only read conversation logs located inside the configured projects folder; a request SHALL NOT
   be able to name a file path.
6. THE SYSTEM SHALL never modify, create or delete files in the projects folder.
7. THE SYSTEM SHALL escape every value taken from conversation logs (titles, tasks, commands, file paths, project
   paths) before inserting it in the UI.
8. THE SYSTEM SHALL serve every browser library from its own static files (pinned versions, shipped with their
   licenses); THE UI SHALL NOT load any resource from a third-party origin.

## R3 — Conversation list

**User story:** As a user, I want to see my conversations, most recent first, so that I can pick one to analyze.
_(D-005, D-007, D-012)_

1. THE API SHALL return the list of conversations with, for each one: last-modified time, conversation id, size in
   KB, number of subagents, project and title — the same fields as the CLI picker.
2. THE API SHALL order the list by last-modified time, most recent first.
3. WHEN a project filter is given THEN THE API SHALL return only conversations whose project contains that
   substring, case-insensitively (same rule as `--project`).
4. THE UI SHALL show the list as a table that can be sorted by any column and filtered by project.
5. WHEN the user selects a conversation in the list THEN THE UI SHALL open its usage report.
6. IF the projects folder does not exist or has no conversations THEN THE API SHALL return an empty list and THE
   UI SHALL say that no conversations were found in that folder.

## R4 — Usage report of a conversation

**User story:** As a user, I want the token and cost breakdown of one conversation, so that I know where its cost
comes from. _(D-005, D-007)_

1. WHEN a conversation id is requested THEN THE API SHALL return the same data as
   `claude_tokens.py <id> --json` for the same options.
2. THE UI SHALL show every section of the CLI report: usage per scope (main and each subagent), summary by model,
   last observed context, cold-summary estimate, estimated total cost, and the notices for models without pricing
   or with guessed pricing.
3. IF the id matches no conversation THEN THE API SHALL answer `404`.
4. IF the id matches conversations in more than one project THEN THE API SHALL answer `409` listing the matching
   projects.
5. THE UI SHALL link from the report to the content views (R7) of the same conversation.

## R5 — Overall totals

**User story:** As a user, I want aggregate usage across all my conversations, so that I can see how much I use
Claude Code overall. _(D-005, D-007)_

1. THE API SHALL return the same data as `claude_tokens.py --totals --json` for the same options, plus the daily
   cost series of R6.
2. WHEN a project filter is given THEN THE API SHALL aggregate only matching conversations.
3. THE UI SHALL show every section of the CLI totals: time window, volume, tokens, cache hit ratio, total cost,
   usage by model, top tools, skills used, top projects by cost and pricing notices.
4. IF there are no conversations THEN THE API SHALL answer with empty totals (not an error) and THE UI SHALL say so.
5. THE SYSTEM SHALL count each tool call (and each skill invocation) exactly once, identified by its `tool_use`
   id, however the log splits one API response into several events. _(Found in T1: `--totals` counted 5,252 of
   24,726 real tool calls; D-042.)_

## R6 — Daily cost (new calculation)

**User story:** As a user, I want tokens and cost per day and per model, so that I can see how my spending evolves.
_(D-013, D-014, D-015)_

1. THE SYSTEM SHALL compute, for each Day (UTC calendar day) and each model, the token fields and estimated cost of
   the usage recorded that Day, including subagents.
2. THE SYSTEM SHALL include that series in `--totals --json` output; THE SYSTEM SHALL NOT change the text output of
   `--totals`.
3. THE SYSTEM SHALL make the sum of daily costs equal the estimated total cost (within rounding to 4 decimals).
4. IF a usage record has no valid timestamp THEN THE SYSTEM SHALL count it in an "undated" bucket so that R6.3
   still holds.
5. WHEN a model has no pricing THEN THE SYSTEM SHALL report its daily tokens with a null cost, as the CLI does for
   totals.

## R7 — Content views

**User story:** As a user, I want to see the last response, the Bash commands and the files touched by a
conversation, so that I can understand what it did. _(D-007, D-016, D-017)_

1. THE API SHALL return the last assistant text response of the conversation's main log (same as
   `--last-response --json`).
2. THE SYSTEM SHALL return the Bash commands of the main log **and of every subagent**, in order, each with its
   description and its source (`main` or the subagent id), in both the CLI (`--bash`) and the API.
3. THE SYSTEM SHALL return the files read, written or edited by the main log **and by every subagent**, as one
   entry per file with per-tool counts aggregated across all sources and the list of sources that touched it, in
   both the CLI (`--files`) and the API.
4. WHEN the CLI prints Bash commands or files in text mode THEN THE SYSTEM SHALL show the source of each entry that
   comes from a subagent.
5. THE UI SHALL render the last response as Markdown (tables, lists, code blocks), sanitize any embedded HTML, and
   apply syntax highlighting to code blocks.
6. IF the conversation has no text response, no Bash commands or no files THEN THE UI SHALL show an explicit empty
   state for that view.
7. THE SYSTEM SHALL list each Bash command and count each file operation once per `tool_use` id, even when the log
   repeats the same block (D-042).

## R8 — Charts

**User story:** As a user, I want charts of my usage, so that trends and outliers are visible at a glance.
_(D-012, D-013, D-014)_

1. THE UI SHALL show a daily cost chart stacked by model.
2. THE UI SHALL show the cost and token share per model.
3. THE UI SHALL show projects ranked by cost.
4. THE UI SHALL show daily activity (assistant responses per Day) and tool and skill usage.
5. THE UI SHALL label every per-day axis and table as UTC.
6. WHILE a project filter is active THE UI SHALL show charts for the filtered data only.

## R9 — Freshness, refresh and performance

**User story:** As a user, I want what I see to reflect my logs as they are now, without waiting on every click.
_(D-010, D-019, D-021)_

1. WHEN a request arrives THEN THE SYSTEM SHALL answer with data that reflects the conversation logs as they are at
   that moment, including logs that changed since the previous request.
2. WHEN totals are requested for the first time after start-up THEN THE SYSTEM SHALL answer in ≤ 5 s on the
   reference dataset (521 MB, 725 JSONL; `--totals` takes 4.2 s today). Verified manually.
3. WHEN totals are requested again and no log has changed THEN THE SYSTEM SHALL answer in < 1 s on the reference
   dataset. Verified manually; automated tests check that unchanged logs are not parsed again.
4. THE UI SHALL show the time its data was loaded and a Refresh button that reloads it.
5. THE UI SHALL offer an auto-refresh toggle that reloads the current view every 30 s; it SHALL be off by default.

## R10 — Tests and documentation

**User story:** As a maintainer, I want automated tests and up-to-date docs, so that the feature can evolve without
breaking. _(D-018, D-021)_

1. THE SYSTEM SHALL have tests runnable with `python3 -m unittest` using only the standard library.
2. Tests SHALL use synthetic JSONL fixtures in a temporary projects folder, never the user's real data.
3. API tests SHALL start the real server on a free port and call it over HTTP.
4. Tests SHALL cover the security criteria of R2 (Host check, methods, id validation, no path traversal).
5. UI behaviour that is not automated (charts, Markdown rendering, sorting, refresh) SHALL be covered by a manual
   checklist in `tasks.md`.
6. THE README SHALL document `--serve`, `--port`, the SSH tunnel and the new daily data in `--totals --json`.
7. Before the existing code is restructured, THE SYSTEM SHALL have characterization tests that pin the current
   CLI output (text and JSON) of every mode on the fixtures; later changes to that output SHALL be deliberate and
   traced to a requirement (R6.2, R7.2–R7.4).

## R11 — Visual design

**User story:** As a user, I want a coherent, modern UI, so that I can read my usage at a glance and the data
looks the same everywhere. _(D-030)_

1. THE UI SHALL give each model one stable colour, used in every chart and table of every view.
2. THE UI SHALL follow the system light/dark preference (`prefers-color-scheme`).
3. THE UI SHALL define its colours, spacing and type as shared CSS custom properties and use the system font.
4. THE UI SHALL right-align numeric columns and use tabular figures.
5. WHILE a view is loading THE UI SHALL show a loading state; IF a request fails THEN THE UI SHALL show the error
   message from the API in that view.
6. THE UI SHALL be fully usable from 768 px wide upwards; phone layouts are out of scope.

## Out of scope (v1)

Binding to the network or any authentication, HTTPS, multiple users, write operations, configurable time zone,
browser end-to-end tests, data export. _(D-022)_

## Resolved during review

1. **R7.3:** one entry per file, counts aggregated across sources, plus the list of sources.
2. **R6.4:** records with no timestamp go to an "undated" bucket.
3. **R9.2/R9.3:** thresholds are verified manually on the reference dataset.
