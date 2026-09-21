// Screenshots + probes for the free-text entry screen and the pre-filled
// questionnaire via /dev/assess?view=describe|extracted.
//   BASE=http://localhost:3000 node shot-extract.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/extract";
fs.mkdirSync(OUT, { recursive: true });

const VIEWPORTS = [["390", 390, 844], ["1440", 1440, 900]];
const THEMES = ["light", "dark"];

const browser = await chromium.launch();
const report = [];
for (const [w, width, height] of VIEWPORTS) {
  for (const theme of THEMES) {
    const ctx = await browser.newContext({
      viewport: { width, height }, colorScheme: theme, deviceScaleFactor: 2, reducedMotion: "reduce",
    });
    const page = await ctx.newPage();
    await page.addInitScript((t) => {
      document.addEventListener("DOMContentLoaded", () => {
        if (t === "dark") document.documentElement.classList.add("dark");
      });
    }, theme);

    // 1. Describe screen: empty state, then with text typed.
    await page.goto(`${BASE}/dev/assess?view=describe`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const describeEmpty = await page.evaluate(() => {
      const btn = [...document.querySelectorAll("button")].find((b) => /Pre-fill/.test(b.textContent ?? ""));
      return {
        textarea: !!document.querySelector("textarea"),
        prefillDisabledWhenEmpty: !!btn?.disabled,
        overPromises: /substantially pre-filled|fully pre-filled|filled in for you/i.test(document.body.innerText),
        saysHeadStart: /head start/i.test(document.body.innerText),
        emDash: document.body.innerText.includes("—"),
        pageScrollsX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      };
    });
    await page.screenshot({ path: `${OUT}/describe-empty-${w}-${theme}.png`, fullPage: true });
    await page.fill("textarea", "We are a Dutch logistics company. Our data team built a model that forecasts pallet volumes per warehouse.");
    await page.waitForTimeout(150);
    const describeTyped = await page.evaluate(() => {
      const btn = [...document.querySelectorAll("button")].find((b) => /Pre-fill/.test(b.textContent ?? ""));
      return { prefillEnabledWhenTyped: !btn?.disabled };
    });
    await page.screenshot({ path: `${OUT}/describe-typed-${w}-${theme}.png`, fullPage: true });

    // 2. Pre-filled questionnaire (real run-4 output for the HR-tech case).
    await page.goto(`${BASE}/dev/assess?view=extracted`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const extractedFirst = await page.evaluate(() => {
      const text = document.body.innerText;
      const groups = [...document.querySelectorAll('[role="group"]')];
      const nullBooleans = groups.filter((g) => {
        const radios = g.querySelectorAll('[role="radiogroup"] input[type="radio"]');
        return radios.length === 2 && ![...radios].some((r) => r.checked);
      }).length;
      return {
        inferredBadges: (text.match(/Inferred from your description/g) ?? []).length,
        toConfirmBadges: (text.match(/To confirm: not in your description/g) ?? []).length,
        pendingCards: document.querySelectorAll('[role="group"][data-pending]').length,
        unansweredBooleanGroups: nullBooleans,
        stepCounts: [...document.querySelectorAll('[aria-label="Steps"] li')].map((li) => li.textContent.trim()),
        introShown: /head start/i.test(text),
        emDash: text.includes("—"),
        pageScrollsX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      };
    });
    // Open the first inferred badge so the quote is in the shot.
    const badge = page.locator("button", { hasText: "Inferred from your description" }).first();
    if (await badge.count()) await badge.click();
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${OUT}/extracted-step1-${w}-${theme}.png`, fullPage: true });

    // Walk to the last step: the build button must be disabled while
    // anything is still to confirm.
    for (let i = 0; i < 12; i++) {
      const next = page.locator("button", { hasText: /^Next$/ });
      if (!(await next.count())) break;
      await next.click();
      await page.waitForTimeout(120);
    }
    const lastStep = await page.evaluate(() => {
      const btn = document.querySelector('[data-testid="build-report"]');
      const status = [...document.querySelectorAll('[role="status"]')].map((s) => s.textContent.trim()).join(" | ");
      return { buildDisabled: !!btn?.disabled, status };
    });
    await page.screenshot({ path: `${OUT}/extracted-last-${w}-${theme}.png`, fullPage: true });

    report.push({ viewport: w, theme, ...describeEmpty, ...describeTyped, ...extractedFirst, ...lastStep });
    await ctx.close();
  }
}
await browser.close();
for (const r of report) console.log(JSON.stringify(r));
console.log("screenshots ->", OUT);
