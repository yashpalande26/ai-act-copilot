// Screenshots + a11y probe for the history rail (1440) and drawer (390), via
// the dev harness at /dev/history. Light and dark.
//   BASE=http://localhost:3000 node shot-history.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/history";
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
    await page.goto(`${BASE}/dev/history`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);

    const row = { viewport: w, theme };
    if (width < 768) {
      const trigger = page.getByRole("button", { name: "Menu", exact: true });
      row.triggerExpandedBefore = await trigger.getAttribute("aria-expanded");
      await page.screenshot({ path: `${OUT}/drawer-closed-${w}-${theme}.png`, fullPage: false });
      await trigger.focus();
      await page.keyboard.press("Enter");
      await page.waitForSelector('[role="dialog"][aria-modal="true"]');
      row.focusOnOpen = await page.evaluate(() => document.activeElement?.getAttribute("aria-label"));
      row.currentItems = await page.locator('[role="dialog"] [aria-current="page"]').count();
      await page.screenshot({ path: `${OUT}/drawer-open-${w}-${theme}.png`, fullPage: false });
      await page.keyboard.press("Escape");
      await page.waitForSelector('[role="dialog"]', { state: "detached" });
      row.focusAfterClose = await page.evaluate(() => document.activeElement?.textContent?.trim());
      row.triggerExpandedAfter = await trigger.getAttribute("aria-expanded");
    } else {
      row.currentItems = await page.locator('aside [aria-current="page"]').count();
      row.newChatFocusable = await page.getByRole("button", { name: "New", exact: true }).evaluate((el) => {
        el.focus(); return document.activeElement === el;
      });
      await page.screenshot({ path: `${OUT}/rail-${w}-${theme}.png`, fullPage: false });
    }
    report.push(row);
    await ctx.close();
  }
}
await browser.close();
console.table(report);
console.log("screenshots ->", OUT);
