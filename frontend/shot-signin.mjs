// Sign-in page shots (public route). 390 and 1440, light and dark.
//   BASE=http://localhost:3000 node shot-signin.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/signin";
fs.mkdirSync(OUT, { recursive: true });
const VIEWPORTS = [["390", 390, 844], ["1440", 1440, 900]];
const THEMES = ["light", "dark"];

const browser = await chromium.launch();
for (const [w, width, height] of VIEWPORTS) {
  for (const theme of THEMES) {
    const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: theme, deviceScaleFactor: 2, reducedMotion: "reduce" });
    const page = await ctx.newPage();
    await page.addInitScript((t) => {
      document.addEventListener("DOMContentLoaded", () => { if (t === "dark") document.documentElement.classList.add("dark"); });
    }, theme);
    await page.goto(`${BASE}/signin`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const probe = await page.evaluate(() => ({
      h1: document.querySelector("h1")?.textContent?.trim() ?? null,
      emDash: document.body.innerText.includes("—"),
      pageScrollsX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }));
    await page.screenshot({ path: `${OUT}/signin-${w}-${theme}.png`, fullPage: true });
    console.log(JSON.stringify({ viewport: w, theme, ...probe }));
    await ctx.close();
  }
}
await browser.close();
console.log("screenshots ->", OUT);
