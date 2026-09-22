// The assessment screens inside the signed-in app shell (harness with
// &shell=1): describe, questionnaire, report. 390 and 1440, light and dark.
//   BASE=http://localhost:3000 node shot-shell.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/shell";
fs.mkdirSync(OUT, { recursive: true });
const VIEWPORTS = [["390", 390, 844], ["1440", 1440, 900]];
const THEMES = ["light", "dark"];
const VIEWS = ["describe", "form", "report"];

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
    for (const view of VIEWS) {
      await page.goto(`${BASE}/dev/assess?view=${view}&shell=1`, { waitUntil: "networkidle" });
      await page.waitForTimeout(300);
      const probe = await page.evaluate(() => ({
        sidebar: !!document.querySelector('aside[aria-label="Navigation"]'),
        menuButton: !!document.querySelector('button[aria-label="Menu"]'),
        emDash: document.body.innerText.includes("\u2014"),
        pageScrollsX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      }));
      await page.screenshot({ path: `${OUT}/${view}-${w}-${theme}.png`, fullPage: view !== "report" });
      report.push({ view, viewport: w, theme, ...probe });
    }
    await ctx.close();
  }
}
await browser.close();
for (const r of report) console.log(JSON.stringify(r));
console.log("screenshots ->", OUT);
