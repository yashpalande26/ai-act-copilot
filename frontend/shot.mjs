import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const ROUND = process.env.ROUND ?? "r5";
const OUT = `shots/${ROUND}`;
fs.mkdirSync(OUT, { recursive: true });

const PAGES = [
  ["landing", "/", true],
  ["signin", "/signin", false],
];
const VIEWPORTS = [["390", 390, 844], ["768", 768, 1024], ["1440", 1440, 900]];
const THEMES = ["light", "dark"];

const browser = await chromium.launch();
for (const [w, width, height] of VIEWPORTS) {
  for (const theme of THEMES) {
    const ctx = await browser.newContext({
      viewport: { width, height }, colorScheme: theme, deviceScaleFactor: 2,
      reducedMotion: "reduce", // capture the settled state, not mid-reveal
    });
    const page = await ctx.newPage();
    await page.addInitScript((t) => {
      document.addEventListener("DOMContentLoaded", () => {
        if (t === "dark") document.documentElement.classList.add("dark");
      });
    }, theme);
    for (const [name, path, full] of PAGES) {
      const res = await page.goto(BASE + path, { waitUntil: "networkidle" });
      if (!res || res.status() >= 400) continue;
      await page.waitForTimeout(500);
      await page.screenshot({ path: `${OUT}/${name}-${w}-${theme}.png`, fullPage: full });
    }
    await ctx.close();
  }
}
await browser.close();
console.log("screenshots ->", OUT);
