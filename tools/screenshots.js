// README screenshots of the web UI, taken against the synthetic folder from tools/demo_projects.py.
// Needs Playwright (npm i --no-save playwright && npx playwright install chromium-headless-shell).
// Usage: node tools/screenshots.js BASE_URL PROJECTS_DIR CONVERSATION_ID OUT_DIR
const { chromium } = require("playwright");

const [base, projectsDir, conv, out] = process.argv.slice(2);
if (!out) {
  console.error("usage: node tools/screenshots.js BASE_URL PROJECTS_DIR CONVERSATION_ID OUT_DIR");
  process.exit(2);
}
const SHOWN_DIR = "~/.claude/projects";

const SHOTS = [
  { name: "conversations", hash: "#/" },
  { name: "totals", hash: "#/totals", until: "main > .charts" },
  { name: "usage", hash: `#/c/${conv}` },
  { name: "last-response", hash: `#/c/${conv}/response` },
  { name: "bash", hash: `#/c/${conv}/bash` },
  { name: "files", hash: `#/c/${conv}/files` },
];

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 860 } })).newPage();
  // The synthetic folder lives in a scratch directory; show it where a real one would be.
  const escaped = JSON.stringify(projectsDir).slice(1, -1);
  await page.route("**/api/**", async (route) => {
    const response = await route.fetch();
    route.fulfill({ response, body: (await response.text()).split(escaped).join(SHOWN_DIR) });
  });
  for (const shot of SHOTS) {
    await page.goto(`${base}/${shot.hash}`);
    await page.waitForFunction(() => document.getElementById("loaded").textContent.startsWith("Loaded"), null, { timeout: 120000 });
    await page.waitForTimeout(500);
    if ((await page.textContent("body")).includes(projectsDir)) throw new Error(`${shot.name}: the real projects path leaked`);
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
