// Screenshots + layout probe for the admin trace viewer via /dev/traces.
//   BASE=http://localhost:3000 node shot-traces.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/traces";
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

    await page.goto(`${BASE}/dev/traces`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const probe = await page.evaluate(() => ({
      used: document.querySelectorAll('tr[data-used="true"]').length,
      cut: document.querySelectorAll('tr[data-used="false"]').length,
      downweighted: document.querySelectorAll('tr[data-downweighted="true"]').length,
      boundaryRows: [...document.querySelectorAll("td")].filter((td) => td.textContent?.trim() === "context boundary").length,
      pageScrollsX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      tableScrollsX: [...document.querySelectorAll(".overflow-x-auto")].some((el) => el.scrollWidth > el.clientWidth),
    }));
    await page.screenshot({ path: `${OUT}/detail-${w}-${theme}.png`, fullPage: true });

    await page.goto(`${BASE}/dev/traces?view=list`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const rows = await page.locator("tbody tr").count();
    await page.screenshot({ path: `${OUT}/list-${w}-${theme}.png`, fullPage: true });

    report.push({ viewport: w, theme, ...probe, listRows: rows });
    await ctx.close();
  }
}
await browser.close();
console.table(report);
console.log("screenshots ->", OUT);
