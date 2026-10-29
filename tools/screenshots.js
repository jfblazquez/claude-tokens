// README screenshots of the web UI, taken against the synthetic folder from tools/demo_projects.py.
// Needs Playwright (npm i --no-save playwright && npx playwright install chromium-headless-shell).
// Usage: node tools/screenshots.js BASE_URL PROJECTS_DIR CONVERSATION_ID OUT_DIR SEND_KEY
const { chromium } = require("playwright");
const path = require("path");

const [base, projectsDir, conv, out, key] = process.argv.slice(2);
if (!key) {
  console.error("usage: node tools/screenshots.js BASE_URL PROJECTS_DIR CONVERSATION_ID OUT_DIR SEND_KEY");
  process.exit(2);
}
const SHOWN_DIR = "~/.claude/projects";
// The demo repository lives at <demo>/home/dev/...; it is shown, and asked for, as /home/dev/...
const demo = path.dirname(path.resolve(projectsDir));
const REAL_HOME = `${demo}/home/`, SHOWN_HOME = "/home/";

async function openPanel(page, ref, ready) {
  await page.locator(ref).first().click();
  await page.waitForSelector(ready);
  // The panel narrows the conversation, which moves the message with the link out of view.
  await page.locator(ref).first().evaluate((el) => el.scrollIntoView({ block: "center" }));
}

const SHOTS = [
  { name: "conversations", hash: "#/" },
  { name: "totals", hash: "#/totals", until: "main > .charts" },
  { name: "usage", hash: `#/c/${conv}` },
  { name: "last-response", hash: `#/c/${conv}/response` },
  { name: "bash", hash: `#/c/${conv}/bash` },
  { name: "files", hash: `#/c/${conv}/files` },
  { name: "panel-commit", hash: `#/c/${conv}/messages`,
    act: (page) => openPanel(page, ".msg-body .ref-commit >> nth=0", ".commit-subject") },
  { name: "panel-file", hash: `#/c/${conv}/messages`,
    act: (page) => openPanel(page, ".ref-file >> text=rate_limit.py:15", ".fv-mark:not([hidden])") },
  { name: "panel-pick", hash: `#/c/${conv}/messages`,
    act: (page) => openPanel(page, ".ref-file.many >> text=__init__.py", ".pick") },
  { name: "panel-shell", hash: `#/c/${conv}/messages`,
    act: async (page) => {
      await openPanel(page, "#conv-head button:has-text('Shell')", ".xterm-screen");
      await page.waitForFunction(() => document.querySelector(".xterm-rows").innerText.includes("$"), null, { timeout: 10000 });
      await page.keyboard.type("git log --oneline --decorate && ls src src/middleware\n");
      await page.waitForFunction(() => /\$\s*$/.test(document.querySelector(".xterm-rows").innerText.trim()), null, { timeout: 10000 });
    } },
  { name: "panel-commits", hash: `#/c/${conv}/messages`,
    act: (page) => openPanel(page, "#conv-head button:has-text('Commits')", ".log-row") },
  { name: "panel-search", hash: `#/c/${conv}/messages`,
    act: async (page) => {
      await openPanel(page, "#conv-head button:has-text('Search')", ".search-q");
      await page.fill(".search-q", "rate_limit");
      await page.keyboard.press("Enter");
      await page.waitForSelector(".search-file");
    } },
  { name: "panel-selection", hash: `#/c/${conv}/messages`,
    act: async (page) => {
      await openPanel(page, "#conv-head button:has-text('Shell')", ".xterm-screen");
      await page.waitForFunction(() => document.querySelector(".xterm-rows").innerText.includes("$"), null, { timeout: 10000 });
      // A few words of the first long paragraph of an answer, selected as a drag would leave them.
      await page.evaluate(() => {
        const node = [...document.querySelectorAll(".msg-body .md p")].flatMap((p) => [...p.childNodes])
          .find((n) => n.nodeType === 3 && n.textContent.trim().split(/\s+/).length > 6);
        const words = node.textContent.match(/^\s*\S+\s+\S+\s+\S+/)[0];
        const range = document.createRange();
        range.setStart(node, words.length - words.trimStart().length);
        range.setEnd(node, words.length);
        getSelection().removeAllRanges();
        getSelection().addRange(range);
        node.parentElement.scrollIntoView({ block: "center" });
        const r = range.getBoundingClientRect();
        node.parentElement.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, button: 0, detail: 1, clientX: r.right, clientY: r.bottom }));
      });
      await page.waitForSelector(".copy-menu");
    } },
];

const swap = (text, from, to) => text.split(from).join(to).split(encodeURIComponent(from)).join(encodeURIComponent(to));

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  await context.addInitScript((k) => localStorage.setItem("ctokens.sendKey", k), key);
  const page = await context.newPage();
  // The synthetic folder lives in a scratch directory; show it where a real one would be.
  const escaped = JSON.stringify(projectsDir).slice(1, -1);
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    // Event streams never end, so fetching them here would never return; the demo has no live session or path in them.
    if (/\/(events|output|stream)(\?|$)/.test(request.url())) return route.continue();
    const body = request.postData();
    const response = await route.fetch({ url: swap(request.url(), SHOWN_HOME + "dev/", REAL_HOME + "dev/"),
      postData: body == null ? undefined : swap(body, SHOWN_HOME + "dev/", REAL_HOME + "dev/") });
    const text = swap((await response.text()).split(escaped).join(SHOWN_DIR), REAL_HOME, SHOWN_HOME);
    route.fulfill({ response, body: text });
  });
  for (const shot of SHOTS) {
    if (shot.act) await page.goto("about:blank");
    await page.goto(`${base}/${shot.hash}`);
    await page.waitForFunction(() => /^\d\d:\d\d:\d\d UTC$/.test(document.getElementById("loaded").textContent), null, { timeout: 120000 });
    // The list loads its recaps after the conversations.
    await page.waitForFunction(() => !document.querySelector(".recap.loading"), null, { timeout: 120000 });
    if (shot.act) {
      await page.waitForSelector(".ref-commit", { timeout: 20000 });
      await shot.act(page);
    }
    await page.waitForTimeout(500);
    const shown = await page.textContent("body");
    if (shown.includes(projectsDir) || shown.includes(demo)) throw new Error(`${shot.name}: the real projects path leaked`);
    let clip;
    if (shot.until) {
      const box = await page.locator(shot.until).first().boundingBox();
      clip = { x: 0, y: 0, width: 1280, height: Math.ceil(box.y + box.height + 24) };
    }
    await page.screenshot({ path: `${out}/${shot.name}.png`, fullPage: !!clip, clip });
    console.log(`${out}/${shot.name}.png`);
  }
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
