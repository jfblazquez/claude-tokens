// Browser checks of the panels: links in a conversation and in a shell, the folder browser, the Markdown preview,
// Ctrl+G and reloading what changed on disk. Runs against a server on the synthetic folder from tools/demo_projects.py.
// Needs Playwright (npm i --no-save playwright && npx playwright install chromium-headless-shell).
// Usage: node tests/e2e/panels.js
const { chromium } = require("playwright");
const assert = require("assert/strict");
const { spawn, execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const CONV = "77777777-7777-4777-8777-777777777777";
const URL_INLINE = "https://example.com/docs/rate-limits?tier=free";
const URL_BLOCK = "http://localhost:8767/limits?key=abc";
const LONG_URL = `https://example.com/${"x".repeat(220)}`;

// A conversation of the demo's api-gateway project whose answer names a URL, a short file and a path the highlighting
// splits across spans.
function addConversation(projects, repo) {
  const folder = path.join(projects, repo.replace(/\//g, "-"));
  const text = [
    `Docs at \`${URL_INLINE}\`, the helper is \`ab.py\` and the limiter \`src/middleware/rate_limit.py:15\`.`,
    "",
    "```ruby",
    `open ${URL_BLOCK} then src/middleware/rate_limit.py:15`,
    "```",
  ].join("\n");
  const usage = { input_tokens: 5, output_tokens: 50, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 };
  const events = [
    { type: "user", uuid: "u1", timestamp: "2026-10-06T10:00:00.000Z", cwd: repo, message: { role: "user", content: "Where is it?" } },
    { type: "assistant", uuid: "a1", timestamp: "2026-10-06T10:00:10.000Z", cwd: repo,
      message: { id: "msg_1", model: "claude-opus-5-5", role: "assistant", content: [{ type: "text", text }], usage } },
  ];
  fs.writeFileSync(path.join(folder, `${CONV}.jsonl`), events.map((e) => JSON.stringify(e)).join("\n") + "\n");
}

function startServer(demo) {
  return new Promise((resolve, reject) => {
    const server = spawn("python3", [path.join(ROOT, "claude_tokens.py"), "--serve", "--port", String(8900 + Math.floor(Math.random() * 90)),
      "--projects-dir", path.join(demo, "projects")], { env: { ...process.env, HOME: path.join(demo, "home"), SHELL: "/bin/bash" } });
    let out = "";
    server.stdout.on("data", (chunk) => {
      out += chunk;
      const m = out.match(/Serving on (http:\/\/\S+)[\s\S]*\?key=(\S+)/);
      if (m) resolve({ server, base: m[1], key: m[2] });
    });
    server.stderr.on("data", (chunk) => { out += chunk; });
    server.on("exit", (code) => reject(new Error(`server exited (${code}): ${out}`)));
  });
}

const checks = [];
const check = (name, fn) => checks.push({ name, fn });

check("links a URL, a short name and names split by highlighting", async ({ page }) => {
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.waitForSelector(".md .ref-file");
  const url = page.locator(`a.ref-url[href="${URL_INLINE}"]`);
  assert.equal(await url.textContent(), URL_INLINE);
  assert.equal(await url.getAttribute("target"), "_blank");
  assert.equal(await page.locator(".md p .ref-file[data-file='ab.py']").count(), 1);
  const block = page.locator("pre code");
  await block.locator(".ref-file").first().waitFor();
  const parts = await block.locator(".ref-file").evaluateAll((els) => els.map((e) => [e.dataset.file, e.textContent]));
  assert.ok(parts.length > 1, "the highlighting splits the path");
  assert.ok(parts.every(([file]) => file === "src/middleware/rate_limit.py"));
  assert.equal(parts.map(([, t]) => t).join(""), "src/middleware/rate_limit.py:15");
  const urls = await block.locator("a.ref-url").evaluateAll((els) => els.map((e) => [e.getAttribute("href"), e.textContent]));
  assert.ok(urls.length > 1 && urls.every(([href]) => href === URL_BLOCK));
  assert.equal(urls.map(([, t]) => t).join(""), URL_BLOCK);
  await block.locator(".ref-file").last().click();
  await page.waitForSelector(".dock-tab:has-text('rate_limit.py')");
});

check("browses folders and opens their files", async ({ page }) => {
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.click("#conv-head button:has-text('Browse')");
  await page.waitForSelector(".dir-row[data-name='src']");
  assert.deepEqual(await page.locator(".dir-row .dir-name").allTextContents(), ["src/", "tests/", "ab.py", "README.md"]);
  await page.click(".dir-row[data-name='src']");
  await page.waitForSelector(".dir-row[data-name='middleware']");
  assert.equal(await page.locator(".dock-tab[aria-selected='true'] .dock-title").textContent(), "src/");
  await page.keyboard.press("Backspace");
  await page.waitForSelector(".dir-row[data-name='README.md']");
  assert.equal(await page.evaluate(() => document.activeElement.dataset.name), "src");
  await page.click(".dir-row[data-name='.']", { trial: true }).catch(() => {});
  await page.check(".dir-hidden input");
  await page.waitForSelector(".dir-row[data-name='.git'].ignored");
  await page.uncheck(".dir-hidden input");
  // Typing in the list filters it.
  await page.keyboard.type("read");
  assert.equal(await page.inputValue(".dir-filter"), "read");
  assert.deepEqual(await page.locator(".dir-row .dir-name").allTextContents(), ["README.md"]);
  await page.keyboard.press("Enter");
  await page.waitForSelector(".fv-md h1");
  await page.click(".panel-body.file:not([hidden]) button:has-text('Folder')");
  await page.waitForSelector(".dock-tab[aria-selected='true']:has-text('api-gateway/')");
});

check("opens Markdown as a preview, and the source at a line", async ({ page }) => {
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.click("#conv-head button:has-text('Browse')");
  await page.click(".dir-row[data-name='README.md']");
  await page.waitForSelector(".fv-md h1");
  assert.equal(await page.locator(".fv-modes [aria-pressed='true']").textContent(), "Preview");
  assert.ok(await page.locator(".fv-preview").isVisible());
  assert.ok(!(await page.locator(".panel-body.file:not([hidden]) .fv-scroll:not(.fv-preview)").isVisible()));
  await page.click(".fv-modes button:has-text('Source')");
  assert.ok(await page.locator(".fv-gutter").isVisible());
  await page.click(".fv-modes button:has-text('Preview')");
  await page.keyboard.press("Control+g");
  assert.equal(await page.evaluate(() => document.activeElement.className), "fv-goto");
  assert.equal(await page.locator(".fv-modes [aria-pressed='true']").textContent(), "Source");
  await page.keyboard.type("3");
  await page.keyboard.press("Enter");
  assert.equal(await page.locator(".fv-mark").evaluate((m) => [m.hidden, m.style.top].join()), "false,48px");
});

check("Ctrl+G goes to a line of the file in focus", async ({ page }) => {
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.click(".md p .ref-file[data-file='src/middleware/rate_limit.py']");
  await page.waitForSelector(".fv-mark:not([hidden])");
  await page.click(".fv-text");
  await page.keyboard.press("Control+g");
  assert.equal(await page.evaluate(() => document.activeElement.className), "fv-goto");
  await page.keyboard.type("2-4");
  await page.keyboard.press("Enter");
  assert.equal(await page.locator(".fv-mark").evaluate((m) => [m.style.top, m.style.height].join()), "28px,60px");
  assert.equal(await page.evaluate(() => document.activeElement.classList.contains("fv-scroll")), true);
  // With the focus nowhere, Ctrl+G still goes to the file in view.
  await page.evaluate(() => document.activeElement.blur());
  await page.keyboard.press("Control+g");
  assert.equal(await page.evaluate(() => document.activeElement.className), "fv-goto");
});

check("reloads a file that changed on disk, or asks first", async ({ page, repo }) => {
  const file = path.join(repo, "src", "cache.py");
  const original = fs.readFileSync(file, "utf8");
  try {
    await page.goto(`${page.base}/#/c/${CONV}/messages`);
    await page.click("#conv-head button:has-text('Browse')");
    await page.click(".dir-row[data-name='src']");
    await page.click(".dir-row[data-name='cache.py']");
    await page.waitForSelector(".fv-text");
    fs.writeFileSync(file, `${original}# changed on disk\n`);
    await page.waitForFunction(() => document.querySelector(".panel-body.file:not([hidden]) .fv-text").textContent.includes("# changed on disk"),
      null, { timeout: 8000 });
    await page.waitForSelector(".fv-note:has-text('Reloaded')");
    await page.evaluate(() => localStorage.setItem("ctokens.panels.reload", "ask"));
    fs.writeFileSync(file, `${original}# asked first\n`);
    await page.waitForSelector(".changed-notice:has-text('changed on disk')", { timeout: 8000 });
    assert.ok(await page.locator(".dock-tab.changed:has-text('cache.py')").count());
    assert.ok(!(await page.locator(".fv-text").textContent()).includes("# asked first"));
    await page.click(".changed-notice button:has-text('Reload')");
    await page.waitForFunction(() => document.querySelector(".panel-body.file:not([hidden]) .fv-text").textContent.includes("# asked first"));
    assert.equal(await page.locator(".changed-notice").count(), 0);
    assert.equal(await page.locator(".dock-tab.changed").count(), 0);
    // A folder follows its entries.
    await page.evaluate(() => localStorage.setItem("ctokens.panels.reload", "auto"));
    await page.click(".dock-tab:has-text('src/')");
    fs.writeFileSync(path.join(repo, "src", "fresh.py"), "x = 1\n");
    await page.waitForSelector(".dir-row[data-name='fresh.py']", { timeout: 8000 });
  } finally {
    fs.writeFileSync(file, original);
    fs.rmSync(path.join(repo, "src", "fresh.py"), { force: true });
  }
});

check("lines the panel menu's chevron up and shows Copied below a path at the top", async ({ page }) => {
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.click("#conv-head button:has-text('Browse')");
  await page.click(".dir-row[data-name='ab.py']");
  await page.waitForSelector(".fv-text");
  const [button, chevron] = await page.evaluate(() => [document.querySelector(".dock-menu-btn"), document.querySelector(".dock-menu-btn svg")]
    .map((el) => { const r = el.getBoundingClientRect(); return r.top + r.height / 2; }));
  assert.ok(Math.abs(button - chevron) <= 1, `chevron centre ${chevron} vs button centre ${button}`);
  const path = page.locator(".panel-body.file:not([hidden]) .panel-bar .copyable");
  await path.dblclick();
  await page.waitForSelector(".panel-bar .copyable.copied-below[data-copied='Copied']");
  const [tip, body] = await path.evaluate((el) => [parseFloat(getComputedStyle(el, "::after").top), el.closest(".panel-body").getBoundingClientRect().top]);
  assert.ok(tip > 0, "the tip goes under the path");
  assert.ok(body >= 0);
});

// A live session faked in the page: the composer shows, and what it sends is caught here instead of reaching tmux.
async function fakeLive(page, repo) {
  const live = { pid: 4242, status: "idle", waiting_for: null, status_since: "2026-10-06T10:00:10Z", started: "2026-10-06T10:00:00Z",
    name: "demo", entrypoint: "cli", version: "2.1.312", cwd: repo, read_only: false, read_only_reason: null };
  const state = { live, sent: [], offline: 0 };
  await page.route(`**/api/conversations/${CONV}/live`, (route) => route.fulfill({ json: { live: state.live, key: "ok", send_problem: null } }));
  await page.route(`**/api/conversations/${CONV}/events*`, (route) => route.abort());
  await page.route(`**/api/conversations/${CONV}/send`, (route) => {
    state.sent.push(route.request().postDataJSON());
    route.fulfill({ json: { sent: true, live } });
  });
  await page.route(`**/api/conversations/${CONV}/go-offline`, (route) => {
    state.offline++;
    state.live = null;
    route.fulfill({ json: { stopped: true, closed_window: true } });
  });
  return state;
}

const PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

check("attaches pasted and dropped images to a message", async ({ page, repo }) => {
  const state = await fakeLive(page, repo);
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.waitForSelector("#composer-text");
  await page.fill("#composer-text", "look at ");
  await page.focus("#composer-text");
  await page.evaluate((b64) => {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const data = new DataTransfer();
    data.items.add(new File([bytes], "shot.png", { type: "image/png" }));
    document.getElementById("composer-text").dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
  }, PNG_BASE64);
  await page.waitForSelector(".composer-image:not(.loading) img");
  assert.equal(await page.inputValue("#composer-text"), "look at [Image #1] ");
  await page.keyboard.type("and this ");
  await page.evaluate((b64) => {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const data = new DataTransfer();
    data.items.add(new File([bytes], "drop.png", { type: "image/png" }));
    document.getElementById("composer").dispatchEvent(new DragEvent("drop", { dataTransfer: data, bubbles: true, cancelable: true }));
  }, PNG_BASE64);
  await page.waitForFunction(() => document.querySelectorAll(".composer-image:not(.loading)").length === 2);
  assert.equal(await page.inputValue("#composer-text"), "look at [Image #1] and this [Image #2] ");
  // Removing an image takes its mark out of the text.
  await page.click(".composer-image:has-text('#2') button");
  assert.equal(await page.inputValue("#composer-text"), "look at [Image #1] and this ");
  await page.keyboard.type("please");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.getElementById("composer-text").value === "");
  assert.equal(state.sent.length, 1);
  const { text, images } = state.sent[0];
  assert.equal(text, "look at [Image #1] and this please");
  assert.deepEqual(Object.keys(images), ["1"]);
  assert.ok(fs.readFileSync(images["1"]).equals(Buffer.from(PNG_BASE64, "base64")), "the server saved the pasted bytes");
  assert.equal(await page.locator(".composer-images").isVisible(), false);
});

check("offers what a project's folder allows on right-click, and asks before going offline", async ({ page, repo }) => {
  const state = await fakeLive(page, repo);
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.waitForSelector("#conv-head .live");
  await page.click(`#conv-head span:has(> b.mono)`, { button: "right" });
  const entries = await page.locator(".copy-menu .copy-menu-item").allTextContents();
  assert.deepEqual(entries, ["▦ Browse the folder", "❯ Shell here", "☰ Commits", " Search the files", "New session here",
    "Only this project's conversations", "Totals of this project", "Copy the path", "Copy a cd command"]);
  await page.click(".copy-menu-item:has-text('Browse the folder')");
  await page.waitForSelector(".dock-tab[aria-selected='true']:has-text('api-gateway/')");
  // A card in the list has the same menu on its project.
  await page.goto(`${page.base}/#/`);
  await page.click(`a[href*='${CONV}'] .project`, { button: "right" });
  await page.click(".copy-menu-item:has-text('Only this project')");
  await page.waitForFunction(() => [...document.querySelectorAll(".project")].every((p) => p.textContent.includes("api-gateway")));
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.waitForSelector("#conv-head .live");
  let asked = null;
  page.once("dialog", (dialog) => { asked = dialog.message(); dialog.dismiss(); });
  await page.click("#conv-head .live", { button: "right" });
  await page.click(".copy-menu-item:has-text('Go offline')");
  await page.waitForTimeout(300);
  assert.match(asked, /stop the Claude Code session .* \(PID 4242\) running in tmux/);
  assert.equal(state.offline, 0, "dismissed: nothing stopped");
  page.once("dialog", (dialog) => dialog.accept());
  await page.click("#conv-head .live", { button: "right" });
  await page.click(".copy-menu-item:has-text('Go offline')");
  await page.waitForFunction(() => !document.querySelector("#conv-head .live"));
  assert.equal(state.offline, 1);
  assert.ok(await page.locator("#conv-head:has-text('tmux window closed')").count());
  assert.equal(await page.locator("#composer").count(), 0);
});

check("lists the commits, marking the one not pushed yet", async ({ page }) => {
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.click("#conv-head button:has-text('Commits')");
  await page.waitForSelector(".log-row");
  assert.match(await page.locator(".log-status").textContent(), /⎇ main.*↑ 1 to push · origin\/main.*fetched/);
  const rows = await page.locator(".log-row").evaluateAll((els) => els.map((e) => [e.className, e.querySelector(".log-subject").textContent]));
  assert.deepEqual(rows, [["log-row out", "Return Retry-After on 429main"], ["log-row pushed", "Add token bucket rate limiting per API keyorigin/main"],
    ["log-row pushed", "Initial API gateway"]]);
  await page.click(".log-row.out");
  await page.waitForSelector(".commit-subject:has-text('Return Retry-After on 429')");
});

check("searches the files, with case, whole word and globs", async ({ page }) => {
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.click("#conv-head button:has-text('Search')");
  await page.fill(".search-q", "Rate_Limit");
  await page.keyboard.press("Enter");
  await page.waitForSelector(".search-file");
  const files = () => page.locator(".search-file > summary").evaluateAll((els) => els.map((e) => e.title.split("/api-gateway/")[1]));
  assert.deepEqual((await files()).sort(), ["src/middleware/__init__.py", "src/middleware/rate_limit.py", "src/router.py"]);
  assert.equal(await page.locator(".search-hit mark").first().textContent(), "rate_limit");
  await page.click(".search-opt[title='Match case']");
  await page.waitForSelector(".search-summary:has-text('No results')");
  await page.click(".search-opt[title='Match case']");
  await page.click(".search-filters summary");
  await page.fill(".search-glob[aria-label='Files to exclude']", "middleware/");
  await page.press(".search-glob[aria-label='Files to exclude']", "Enter");
  await page.waitForFunction(() => document.querySelectorAll(".search-file").length === 1);
  assert.deepEqual(await files(), ["src/router.py"]);
  await page.click(".search-hit");
  await page.waitForSelector(".dock-tab[aria-selected='true']:has-text('router.py')");
  await page.waitForSelector(".panel-body.file:not([hidden]) .fv-mark:not([hidden])");
  await page.evaluate(() => localStorage.removeItem("ctokens.search"));
});

check("searches while the query and the globs are typed, without Enter", async ({ page }) => {
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.click("#conv-head button:has-text('Search')");
  const searches = [];
  page.on("request", (r) => { if (r.url().includes("/search?")) searches.push(new URL(r.url()).searchParams.get("q")); });
  await page.locator(".search-q").pressSequentially("Rate_Limit", { delay: 20 });
  await page.waitForFunction(() => document.querySelectorAll(".search-file").length === 3);
  // Typed at that pace, the word goes as one search.
  assert.deepEqual(searches, ["Rate_Limit"]);
  await page.click(".search-filters summary");
  await page.fill(".search-glob[aria-label='Files to exclude']", "middleware/");
  await page.waitForFunction(() => document.querySelectorAll(".search-file").length === 1);
  await page.evaluate(() => localStorage.removeItem("ctokens.search"));
});

check("a commit's view opens the list of commits at that commit", async ({ page }) => {
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.click("#conv-head button:has-text('Commits')");
  await page.click(".log-row:has-text('Add token bucket')");
  await page.waitForSelector(".commit-subject:has-text('Add token bucket')");
  await page.click(".commit-head button:has-text('Commits')");
  await page.waitForSelector(".log-row.here");
  assert.match(await page.locator(".log-row.here .log-subject").textContent(), /^Add token bucket/);
  assert.equal(await page.locator(".dock-tab").count(), 2);
});

// The demo's longest conversation, by its title.
async function demoConversation(page, title) {
  await page.goto(`${page.base}/#/`);
  return page.evaluate(async (t) => (await (await fetch("/api/conversations")).json()).conversations.find((c) => c.title === t).id, title);
}

check("the header folds into the app bar while the page scrolls", async ({ page }) => {
  const id = await demoConversation(page, "Add rate limiting to the public API");
  await page.goto(`${page.base}/#/c/${id}/messages`);
  await page.waitForSelector(".msgs");
  // It opens at the last message, with the header out of sight.
  await page.waitForSelector("#bar-conv:not([hidden])");
  await page.waitForTimeout(500);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForSelector("#bar-conv[hidden]", { state: "attached" });
  await page.evaluate(() => window.scrollTo(0, 1200));
  await page.waitForSelector("#bar-conv:not([hidden])");
  assert.equal(await page.locator(".bar-conv-name").textContent(), "Add rate limiting to the public API");
  assert.deepEqual(await page.locator("#bar-conv .btn").evaluateAll((els) => els.map((e) => e.textContent.trim())),
    ["", "New session", "▦ Browse", "❯ Shell", "☰ Commits", "Search"]);
  // Laid over the page: the conversation does not move when it shows.
  assert.equal(await page.evaluate(() => window.scrollY), 1200);
  await page.click("#bar-conv button:has-text('Search')");
  await page.waitForSelector(".panel-body.search:not([hidden]) .search-q");
  await page.click(".bar-conv-name");
  await page.waitForSelector("#bar-conv[hidden]", { state: "attached" });
});

// Selects the text of the first element matching selector, as a drag would, and lets go of the mouse over it.
async function selectText(page, selector, text) {
  await page.evaluate(([sel, wanted]) => {
    const el = document.querySelector(sel);
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const at = node.textContent.indexOf(wanted);
      if (at < 0) continue;
      const range = document.createRange();
      range.setStart(node, at);
      range.setEnd(node, at + wanted.length);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      const r = range.getBoundingClientRect();
      node.parentElement.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, button: 0, detail: 1, clientX: r.right, clientY: r.bottom }));
      return;
    }
    throw new Error(`no text ${wanted}`);
  }, [selector, text]);
}

async function openShellPanel(page) {
  await page.click("#conv-head button:has-text('Shell')");
  await page.waitForFunction(() => document.querySelector(".xterm-rows") && document.querySelector(".xterm-rows").innerText.includes("$"));
}

// What the shell's screen shows, without the spaces of its empty cells.
const screenText = (page) => page.evaluate(() => document.querySelector(".xterm-rows").innerText.replace(/\u00a0/g, " "));

check("a selection in the conversation is quoted, searched for or pasted into a shell without Enter", async ({ page, repo }) => {
  await fakeLive(page, repo);
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.waitForSelector("#composer-text");
  await openShellPanel(page);
  await selectText(page, ".msg-body .md p", "the helper is");
  await page.waitForSelector(".copy-menu");
  assert.deepEqual(await page.locator(".copy-menu .copy-menu-item").allTextContents(),
    ["Copy", "Ask Claude", " Find in files", "❯ Paste into Shell 1"]);
  await page.click(".copy-menu-item:has-text('Ask Claude')");
  assert.equal(await page.inputValue("#composer-text"), "> the helper is");
  await selectText(page, ".msg-body .md p", "Docs at");
  await page.click(".copy-menu-item:has-text('Paste into Shell 1')");
  await page.waitForFunction(() => document.querySelector(".xterm-rows").innerText.includes("Docs at"));
  await page.waitForTimeout(400);
  const screen = await screenText(page);
  assert.match(screen, /\$ Docs at\s*$/, "typed at the prompt");
  assert.ok(!screen.includes("command not found"), "not run");
  await selectText(page, ".msg-body .md p", "middleware");
  await page.click(".copy-menu-item:has-text('Find in files')");
  await page.waitForSelector(".dock-tab[aria-selected='true'] .dock-title:text-is('middleware')");
  assert.equal(await page.inputValue(".search-q"), "middleware");
  await page.waitForSelector(".search-file > summary[title$='/src/router.py']");
});

check("a copy button and a selection in a file paste into the shell on screen", async ({ page }) => {
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.click("#conv-head button:has-text('Browse')");
  await page.waitForSelector(".dir-row[data-name='ab.py']");
  // Not while the shell is out of view.
  await page.click(".msg-body .copy-wrap:has(pre) > .copy-btn", { button: "right" });
  assert.equal(await page.locator(".copy-menu-item:has-text('Paste into')").count(), 0);
  await page.keyboard.press("Escape");
  await openShellPanel(page);
  await page.click(".msg-body .copy-wrap:has(pre) > .copy-btn", { button: "right" });
  assert.deepEqual(await page.locator(".copy-menu-head").allTextContents(), ["Copy as", "Paste"]);
  // The shell printing scrolls its own screen, which leaves the menu where it is.
  await page.evaluate(() => document.querySelector(".xterm-viewport").dispatchEvent(new Event("scroll")));
  assert.equal(await page.locator(".copy-menu").count(), 1);
  await page.click(".copy-menu-item:has-text('Paste into Shell 1')");
  await page.waitForFunction(() => document.querySelector(".xterm-rows").innerText.includes("rate_limit.py:15"));
  await page.keyboard.press("Control+c");
  // Side by side, the file and the shell are both on screen.
  await page.click(".dock-menu-btn");
  await page.click(".copy-menu-item:has-text('Floating')");
  // The shell's window may cover the folder's.
  await page.locator(".dir-row[data-name='ab.py']").dispatchEvent("click");
  await page.waitForSelector(".fv-text");
  await selectText(page, ".fv-text", "print");
  await page.click(".copy-menu-item:has-text('Paste into Shell 1')");
  await page.waitForTimeout(400);
  assert.match(await screenText(page), /\$ print\s*$/);
  // Over the overlay too.
  await page.click(".dock-menu-btn");
  await page.click(".copy-menu-item:has-text('Overlay')");
  await page.click(".dock-tab:has-text('ab.py')");
  await selectText(page, ".panel-body.file:not([hidden]) .fv-text", "print");
  const box = await page.locator(".copy-menu").boundingBox();
  assert.ok(await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y).closest(".copy-menu"), [box.x + box.width / 2, box.y + box.height / 2]));
  await page.evaluate(() => localStorage.removeItem("ctokens.dock.mode"));
});

// The row of the terminal whose text starts with prefix, and the one after it.
async function rowAfter(page, prefix) {
  await page.waitForFunction((p) => [...document.querySelectorAll(".xterm-rows > div")].some((r) => r.textContent.startsWith(p)), prefix,
    { timeout: 5000 }).catch(() => {});
  const index = await page.evaluate((p) => [...document.querySelectorAll(".xterm-rows > div")].findIndex((r) => r.textContent.startsWith(p)), prefix);
  assert.ok(index >= 0, `no row starts with ${prefix}`);
  return page.locator(".xterm-rows > div").nth(index + 1);
}

// The rows let the pointer through to the screen under them, where xterm.js finds the links.
async function clickRow(page, row) {
  const box = await row.boundingBox();
  await page.mouse.move(box.x + 30, box.y + box.height / 2);
  await page.waitForTimeout(500);
  await page.mouse.click(box.x + 30, box.y + box.height / 2);
}

check("links a URL and a path the terminal wrapped onto the next row", async ({ page }) => {
  await page.goto(`${page.base}/#/c/${CONV}/messages`);
  await page.evaluate(() => { window.opened = []; window.open = (url) => { window.opened.push(url); }; });
  await page.click("#conv-head button:has-text('Shell')");
  await page.waitForFunction(() => document.querySelector(".xterm-rows") && document.querySelector(".xterm-rows").innerText.includes("$"));
  await page.keyboard.type(`clear; echo ${LONG_URL}\n`);
  const tail = await rowAfter(page, "https://example.com/xxx");
  await clickRow(page, tail);
  await page.waitForFunction(() => window.opened.length > 0);
  assert.equal(await page.evaluate(() => window.opened[0]), LONG_URL);
  await page.keyboard.type('clear; printf "%*s%s\\n" $(( $(tput cols) - 10 )) "" src/middleware/rate_limit.py:3\n');
  const rest = await rowAfter(page, " ".repeat(20));
  assert.ok((await rest.textContent()).startsWith("ware/rate_limit.py:3"));
  await clickRow(page, rest);
  await page.waitForSelector(".dock-tab[aria-selected='true']:has-text('rate_limit.py')");
  await page.waitForSelector(".panel-body.file:not([hidden]) .fv-mark:not([hidden])");
});

(async () => {
  const demo = fs.mkdtempSync(path.join(os.tmpdir(), "ctokens-e2e-"));
  let server = null, browser = null, failed = 0;
  try {
    execFileSync("python3", [path.join(ROOT, "tools", "demo_projects.py"), demo]);
    const repo = path.join(demo, "home", "dev", "projects", "api-gateway");
    fs.writeFileSync(path.join(repo, "ab.py"), "print('ab')\n");
    addConversation(path.join(demo, "projects"), repo);
    const started = await startServer(demo);
    server = started.server;
    browser = await chromium.launch();
    for (const { name, fn } of checks) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 860 } });
      await context.addInitScript((k) => localStorage.setItem("ctokens.sendKey", k), started.key);
      const page = await context.newPage();
      page.base = started.base;
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      try {
        await fn({ page, repo });
        assert.deepEqual(errors, []);
        console.log(`ok   ${name}`);
      } catch (error) {
        failed++;
        console.log(`FAIL ${name}\n${error.stack || error}`);
        await page.screenshot({ path: path.join(demo, `${name.replace(/\W+/g, "-")}.png`) }).catch(() => {});
      }
      await context.close();
    }
  } finally {
    if (browser) await browser.close();
    if (server) server.kill();
    if (failed) console.log(`${failed} of ${checks.length} failed; screenshots in ${demo}`);
    else fs.rmSync(demo, { recursive: true, force: true });
  }
  process.exit(failed ? 1 : 0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
