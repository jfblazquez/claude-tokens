# claude-tokens

Dependency-free utility that summarizes tokens and estimated cost from a Claude
Code JSONL conversation and the JSONL files in `<session>/subagents/`.

```bash
python3 claude_tokens.py /path/to/conversation.jsonl
python3 claude_tokens.py /path/to/conversation.jsonl --json
```

If you omit the conversation, it browses the Claude projects folder
(`~/.claude/projects`, or `$CLAUDE_CONFIG_DIR/projects`) and shows an
interactive picker with the most recent conversations first: size in KB, number
of subagents used, project path, and the session title (its rename/`aiTitle`,
blank when the session was never named). The list is paged 10 at a time: type a
number to analyze that conversation, press Enter for the next 10, `a` to show
them all, or `q` to quit. Filter by project with `--project`:

```bash
python3 claude_tokens.py                       # pick from all projects
python3 claude_tokens.py --project webfilter   # only matching project paths
python3 claude_tokens.py --projects-dir /other/projects
```

The picker looks like this (data below is illustrative):

```
 #  | Date             | Size KB | Subagents | Project                       | Title
----+------------------+---------+-----------+-------------------------------+------------------------------------
 1  | 2026-01-15 18:42 | 246     | 0         | /home/dev/projects/webfilter  | Add request-cache invalidation
 2  | 2026-01-15 17:10 | 3.377   | 12        | /home/dev/projects/webfilter  | Migrate parser to streaming API
 3  | 2026-01-15 09:58 | 152     | 1         | /home/dev/projects/api-gateway | Fix flaky auth integration test
 4  | 2026-01-14 20:31 | 4       | 0         | /home/dev/projects/api-gateway |
 5  | 2026-01-14 11:05 | 799     | 3         | /home/dev/projects/dashboard  | Redesign metrics landing page

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

The JSONL does not break down the internal `System prompt`, tools, memory,
skills, and messages categories, so those cannot be reconstructed reliably.

Built-in rates are USD per million tokens, checked on 2026-07-17 against the
[official Anthropic pricing page](https://platform.claude.com/docs/en/about-claude/pricing).
They include the published cache multipliers: `0.1x` for reads, `1.25x` for
5-minute writes, and `2x` for 1-hour writes. The result is an API estimate; it
does not include taxes, discounts, server-tool charges, or provider/region
premiums.

Override or add model rates without changing the code:

```json
{"claude-sonnet-5": {"input": 3, "output": 15}}
```

```bash
python3 claude_tokens.py CONVERSATION.jsonl --pricing prices.json
```
