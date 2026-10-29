# claude-tokens

Reads Claude Code logs (CLI report and a local web UI, `--serve`). Python standard library only; browser libraries are
vendored in `ctokens/web/static/vendor/` (refresh with `tools/vendor.py`). The page runs under a `'self'`-only CSP: no
inline scripts, styles or handlers, no remote URLs.

## No real data in the repository

The README, screenshots, tests and fixtures are public. Everything in them comes from the synthetic playground:

- Screenshots: only from `tools/demo_projects.py` through `tools/screenshots.js` (it swaps the scratch paths for
  `/home/dev/...` and fails if the real projects folder leaks). Never capture a real `~/.claude/projects`.
- Examples and fixtures: invented projects (`/home/dev/projects/api-gateway`...), `example.com` URLs, made-up ids and
  PIDs. No real conversation ids, send keys, hostnames, user or company names, internal repositories or paths.
- Images pasted into a session for testing stay in the scratchpad; e2e tests make their own tiny PNG.
- Before committing, scan the diff and the README:
  `git diff --cached | grep -inE "$USER|/home/$USER|/opt/workspaces|/tmp/claude-|scratchpad|key=[A-Za-z0-9_-]{20}"`
  and look at any new image in `docs/images/`.

## How every change is validated

1. `python3 -m unittest discover -s tests`: server and parsing logic, synthetic fixtures only.
2. `node tests/e2e/panels.js`: Playwright against a server it starts on the demo folder (Playwright with
   `npm i --no-save playwright && npx playwright install chromium-headless-shell`, or `NODE_PATH` to an existing
   install). Each UI feature or fix gets a check there; a new check must fail against the code before the change.
   Live sessions are faked in the page (`page.route`) so nothing reaches a real Claude.
3. Look at screenshots of the change (light and dark) taken against the demo server:
   `python3 tools/demo_projects.py <scratch>` then
   `HOME=<scratch>/home SHELL=/bin/bash python3 claude_tokens.py --serve --port 8798 --projects-dir <scratch>/projects`.
4. Behaviour of Claude Code itself (what a paste or a signal does) is checked on a real `claude` in an isolated tmux
   server (`tmux -L <name>`, in a scratch folder), without submitting a prompt, and the server is killed after.

Other `--serve` instances of the user may be running: stop only the processes you started, by PID (a `pkill -f` on a
pattern also matches the shell running it).

## README

Every feature and fix is described in the README section it belongs to, with its routes in the API tables and any new
test or tool in **Development**, in the same plain style as the rest. Screenshots are regenerated only from the demo.
