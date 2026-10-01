# claude-tokens

Analyzes Claude Code conversation logs to report token usage and estimated cost, from the terminal and (in
progress) from a web server.

## Language

### Sources

**Projects folder**:
The directory where Claude Code stores conversation logs, one subfolder per project.
_Avoid_: logs dir, history

**Project**:
The working directory a conversation was run in, as recorded in its log.
_Avoid_: repo, workspace

**Conversation**:
One top-level Claude Code conversation log together with the logs of its subagents; the unit that gets analyzed.
_Avoid_: session, transcript, chat

**Conversation id**:
The identifier of a conversation (its log file name without extension).
_Avoid_: session id, GUID

**Subagent**:
A child agent launched by a conversation, whose usage counts towards that conversation.
_Avoid_: sidechain, task agent

### Time

**Day**:
A calendar day in UTC; every per-day figure (activity, daily cost) is bucketed this way.
_Avoid_: local day, date

### Web

**API**:
The JSON interface of the web server; exposes the same data as the CLI's `--json` output.

**UI**:
The browser pages served by the web server, built on top of the API.
