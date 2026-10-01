# claude-tokens

Dependency-free utility that summarizes tokens and estimated cost from a Claude
Code JSONL conversation and the JSONL files in `<session>/subagents/`.

```bash
python3 claude_tokens.py /path/to/conversation.jsonl
python3 claude_tokens.py /path/to/conversation.jsonl --json
python3 claude_tokens.py d91dbfb9-4ca2-495a-aa23-938757a38997   # by conversation id
```

Instead of a path you can pass a bare **conversation id** (the JSONL filename
without extension); it is located automatically under the projects folder.

If you omit the conversation, it browses the Claude projects folder
(`~/.claude/projects`, or `$CLAUDE_CONFIG_DIR/projects`) and shows an
interactive picker with the most recent conversations first: the session GUID
(the JSONL filename, i.e. the session id), size in KB, number of subagents used,
project path, and the session title (its rename/`aiTitle`, blank when the
session was never named). The list is paged 10 at a time: type a
number to analyze that conversation, press Enter for the next 10, `a` to show
them all, or `q` to quit. Filter by project with `--project`:

```bash
python3 claude_tokens.py                       # pick from all projects
python3 claude_tokens.py --project webfilter   # only matching project paths
python3 claude_tokens.py --projects-dir /other/projects
```

The picker looks like this (data below is illustrative):

```
 #  | Date             | GUID                                 | Size KB | Subagents | Project                       | Title
----+------------------+--------------------------------------+---------+-----------+-------------------------------+------------------------------------
 1  | 2026-01-15 18:42 | d91dbfb9-4ca2-495a-aa23-938757a38997 | 246     | 0         | /home/dev/projects/webfilter  | Add request-cache invalidation
 2  | 2026-01-15 17:10 | 4a2f8c1e-7b6d-4e9a-9f03-1c2d3e4f5a6b | 3.377   | 12        | /home/dev/projects/webfilter  | Migrate parser to streaming API
 3  | 2026-01-15 09:58 | 8e7d6c5b-4a39-4281-b0f1-2a3b4c5d6e7f | 152     | 1         | /home/dev/projects/api-gateway | Fix flaky auth integration test
 4  | 2026-01-14 20:31 | 1b2c3d4e-5f60-4718-8293-a4b5c6d7e8f9 | 4       | 0         | /home/dev/projects/api-gateway |
 5  | 2026-01-14 11:05 | f0e1d2c3-b4a5-4967-8879-0a1b2c3d4e5f | 799     | 3         | /home/dev/projects/dashboard  | Redesign metrics landing page

Select 1-42, Enter for next 10, 'a' for all, 'q' to quit:
```

After you pick one (or pass a path directly) it prints the usage report:

```
Conversation usage
Scope    | ID    | Task                     | Model           | Total     | Input  | Output | Cache read | Cache write 5m/1h | Cost
---------+-------+--------------------------+-----------------+-----------+--------+--------+------------+-------------------+--------
main     | main  | Add request-cache inva…  | claude-opus-4-8 | 1.284.902 | 12.430 | 48.117 | 1.180.355  | 44.000/0          | $2.9871

Summary by model
Model           | Total     | Input  | Output | Raw output* | Cache read | Cache write 5m/1h | Cost
----------------+-----------+--------+--------+-------------+------------+-------------------+--------
claude-opus-4-8 | 1.284.902 | 12.430 | 48.117 |             | 1.180.355  | 44.000/0          | $2.9871

Estimated cost: $2.9871
```

## Overall usage (`--totals`)

`--totals` ignores single conversations and aggregates everything in the
projects folder (each session plus its subagents) in one pass, so you can see
how much you have used Claude Code as a whole. Because it is not obvious how
long these logs are kept, it reports the **time window** the data actually
covers (span in days and first/last activity), and it also breaks down cost and
tokens per model, tool usage, skills invoked, and cost per project. Respects
`--project` and `--json`.

```bash
python3 claude_tokens.py --totals
python3 claude_tokens.py --totals --project webfilter
python3 claude_tokens.py --totals --json
```

Example (illustrative data — real paths/names are not shown here):

```
Overall usage (projects folder)
  Time window : 31 days (2026-01-01 → 2026-01-31), 23 active days
  Busiest day : 2026-01-14 (1.371 responses)
  Volume      : 192 conversations across 14 projects, 127 subagents
  Tokens      : 1.836.911.842 total, 8.172.167 generated (output)
  Cache hits  : 97.7% of input tokens served from cache
  Total cost  : $1989.12 ($10.3600 per conversation)

Usage by model
Model           | Total tokens  | % tokens | Cost     | % cost
----------------+---------------+----------+----------+--------
claude-fable-5  | 759.984.932   | 41.4%    | $1175.74 | 59.1%
claude-opus-4-8 | 949.413.549   | 51.7%    | $772.53  | 38.8%
claude-sonnet-5 | 105.567.607   | 5.7%     | $37.44   | 1.9%

Top tools
Tool | Calls | % of calls
-----+-------+------------
Bash | 1.155 | 48.8%
Read | 606   | 25.6%
Edit | 346   | 14.6%

Skills used
Skill           | Invocations
----------------+------------
explain-code    | 7
code-review:pr  | 3

Top projects by cost
Project                       | Conversations | Total tokens | Cost
------------------------------+---------------+--------------+---------
/home/dev/projects/webfilter  | 32            | 910.166.272  | $775.22
/home/dev/projects/api-gateway | 99           | 400.175.203  | $463.74
```

Metrics reported: time window (span, active days, busiest day), total cost and
cost per conversation, tokens generated, cache-hit ratio, per-model token/cost
share, tool-call distribution, skills invoked, and per-project cost.

Each tool call (and skill invocation) is counted once by its `tool_use` id. Claude
Code writes one event per content block of a response, all with the same
`message.id`, so counting only the first event of each response would miss most
tool calls.

`--totals --json` also includes a `daily` series: for each Day (a UTC calendar
day) the assistant responses, tokens and estimated cost, broken down by model.
Records without a timestamp go to a last entry with `"day": null`. The daily
costs add up to `estimated_total_cost_usd`; the text output does not show the
series.

For each conversation it shows the task/reason (the `.meta.json` description
when available, otherwise the first user message), usage by model and cache
class, and estimated cost. Subagents are shown first, then the main
conversation, followed by model aggregates.

It de-duplicates assistant events by `message.id` (falling back to `uuid`),
because a JSONL can persist the same streamed API response multiple times.
The model aggregate also displays `output in persisted events` when it differs
from the de-duplicated output. This is a diagnostic value for comparisons with
tools that aggregate stream events; it is not used in the cost calculation.

The report includes the last observed context for the main conversation (new
input + cache read + cache write) and a no-cache estimate for summarizing that
context. The cold summary assumes 2,000 output tokens; change this with:

```bash
python3 claude_tokens.py CONVERSATION.jsonl --cold-summary-output 5000
```

The JSONL does not record the context window a session ran with (200k is the
default; 1M needs a beta flag). The context percentage is therefore computed
against the smallest standard tier (200k or 1M) that fits the largest context
actually observed — so a 200k session is no longer reported as if it were 1M.
Set it explicitly when you know it:

```bash
python3 claude_tokens.py CONVERSATION.jsonl --context-window 200000
```

The JSONL does not break down the internal `System prompt`, tools, memory,
skills, and messages categories, so those cannot be reconstructed reliably.

## Inspecting a conversation

Three flags print raw conversation material instead of the usage report (each
works with a path or a bare id, and with `--json`):

```bash
python3 claude_tokens.py CONVERSATION --last-response   # final assistant turn, Markdown rendered for the terminal
python3 claude_tokens.py CONVERSATION --bash            # every Bash command it and its subagents ran, by time
python3 claude_tokens.py CONVERSATION --files           # files touched by Read/Write/Edit, with per-tool counts
```

`--last-response` renders inline `code`, **bold**, and headings with ANSI when
writing to a terminal, and falls back to plain text when piped. It shows the
main conversation's last response only.

`--bash` and `--files` cover the main conversation and its subagents. A Bash
command run by a subagent is headed `# [subagent <id>]`. The files table has one
row per file with the counts added across sources and a `Sources` column. With
`--json`, each command has `source` (`main` or the subagent id) and `timestamp`,
and each file has `sources`. A block repeated in the log is counted once.

Built-in rates are USD per million tokens, checked on 2026-10-01 against the
[official Anthropic pricing page](https://platform.claude.com/docs/en/about-claude/pricing).
They include the published cache multipliers: `0.1x` for reads (`0.05x` on
`claude-opus-5-5`, `0.025x` on `claude-fable-5-1` and `claude-mythos-5-1`),
`1.25x` for 5-minute writes, and `2x` for 1-hour writes. The result is an API estimate; it
does not include taxes, discounts, server-tool charges, fast mode, or
provider/region premiums.

| Model | Input | Output |
|---|---|---|
| `claude-fable-5-1`, `claude-mythos-5-1`, `claude-fable-5`, `claude-mythos-5` | 10 | 50 |
| `claude-opus-5-5` | 4 | 20 |
| `claude-opus-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-opus-4-5` | 5 | 25 |
| `claude-opus-4-1`, `claude-opus-4`, `claude-3-opus` | 15 | 75 |
| `claude-sonnet-5-5`, `claude-sonnet-5` | 2 | 10 |
| `claude-sonnet-4-6`, `claude-sonnet-4-5`, `claude-sonnet-4`, `claude-3-7-sonnet`, `claude-3-5-sonnet` | 3 | 15 |
| `claude-haiku-4-5` | 1 | 5 |
| `claude-3-5-haiku` | 0.8 | 4 |
| `claude-3-haiku` | 0.25 | 1.25 |

Fast mode bills at `8`/`40` on `claude-opus-5-5` and `10`/`50` on `claude-opus-5`,
but the JSONL does not record it, so those responses are costed at the standard rate.

A model that is not in the table but belongs to a known family — a future
`claude-opus-6`, `claude-fable-5-2`, `claude-sonnet-6` — is priced from the
newest known model of the same family. Those costs are printed with a leading
`~` and the report ends with an estimated-price warning naming the models.
Trailing `-YYYYMMDD` release dates are stripped before the lookup.

Override or add model rates without changing the code:

```json
{"claude-sonnet-5": {"input": 3, "output": 15},
 "claude-opus-5-5": {"input": 4, "output": 20, "cache_read": 0.05}}
```

`cache_read` is the optional cache-read multiplier; it defaults to `0.1`.

```bash
python3 claude_tokens.py CONVERSATION.jsonl --pricing prices.json
```

## Web UI (`--serve`)

`--serve` starts a local web server with the same data as the CLI: the
conversation list, the usage report, the last response, Bash commands, files
and the totals, plus charts (daily cost by model, model share, projects by cost,
daily activity, tools and skills).

```bash
python3 claude_tokens.py --serve               # http://127.0.0.1:8765
python3 claude_tokens.py --serve --port 9000 --pricing prices.json
```

It only listens on `127.0.0.1` and has no authentication. It rejects requests
whose `Host` is not `localhost` or `127.0.0.1`, and anything but `GET`/`HEAD`.
It never writes to the projects folder.
`--serve` accepts `--port`, `--projects-dir`, `--pricing`,
`--cold-summary-output` and `--context-window`; the project filter is chosen in
the UI. A port that is already in use is an error.

When the tool runs on a remote machine, open an SSH tunnel and browse
`http://localhost:8765` on your own machine (any local port works):

```bash
ssh -N -L 8765:localhost:8765 <remote-host>
```

Every request re-reads the logs that changed since the previous one, so the data
is always current. The first totals load parses everything (about as long as
`--totals`); later loads take a fraction of a second when nothing changed.

The browser libraries (Chart.js, marked, DOMPurify, highlight.js) are bundled in
`ctokens/web/static/vendor/`, so the UI works offline and loads nothing from
other sites. `tools/vendor.py` refreshes them.

The JSON API behind the UI returns the same objects as the CLI's `--json`:

| Route | Same as |
|---|---|
| `GET /api/conversations?project=` | the picker list, as `{"projects_dir", "conversations": [...]}` |
| `GET /api/conversations/<id>` | `<id> --json` |
| `GET /api/conversations/<id>/last-response` | `<id> --last-response --json` |
| `GET /api/conversations/<id>/bash` | `<id> --bash --json` |
| `GET /api/conversations/<id>/files` | `<id> --files --json` |
| `GET /api/totals?project=` | `--totals --json` |

## Development

The code lives in the `ctokens/` package; `claude_tokens.py` is the entry point.
Tests use only the standard library and synthetic fixtures (never your real
logs):

```bash
python3 -m unittest discover -s tests
python3 tests/coverage.py              # line coverage of the CLI characterization cases
python3 tests/golden/refresh.py CASE   # regenerate a golden after a deliberate output change
```

