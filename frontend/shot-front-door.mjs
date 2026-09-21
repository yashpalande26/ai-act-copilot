// Landing page shots + probe: the assessment must be the dominant action and
// the chat must remain reachable. Signed-out view (the public page).
//   BASE=http://localhost:3000 node shot-front-door.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/front-door";
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
    await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
    await page.waitForTimeout(400);

    const probe = await page.evaluate(() => {
      const primary = document.querySelector("[data-primary-cta]");
      const secondary = document.querySelector("[data-secondary-cta]");
      const firstHeroLink = document.querySelector("main section a");
      const chatLinks = [...document.querySelectorAll('a[href="/signin"], a[href="/app"]')].length;
      const assessLinks = [...document.querySelectorAll("a")].filter((a) => a.getAttribute("href")?.includes("assess")).length;
      const h1 = document.querySelector("h1")?.textContent?.trim();
      const text = document.body.innerText;
      return {
        h1,
        primaryHref: primary?.getAttribute("href"),
        primaryText: primary?.textContent?.trim(),
        primaryIsFirstHeroLink: primary === firstHeroLink,
        secondaryHref: secondary?.getAttribute("href"),
        assessLinks,
        chatLinks,
        heroCardQuotesAnnexIII: text.includes("anx_III.pt_4.sub_a"),
        hasNotLegalAdvice: text.toLowerCase().includes("not legal advice"),
        emDashes: (text.match(/—/g) || []).length,
        pageScrollsX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      };
    });
    await page.screenshot({ path: `${OUT}/landing-${w}-${theme}.png`, fullPage: true });
    await page.screenshot({ path: `${OUT}/hero-${w}-${theme}.png`, fullPage: false });
    report.push({ viewport: w, theme, ...probe });
    await ctx.close();
  }
}
await browser.close();
console.table(report);
console.log("screenshots ->", OUT);
