// Screenshots + a11y probe for the citation disclosure, via the dev harness at
// /dev/citations. Collapsed and expanded, 390 and 1440, light and dark.
//   BASE=http://localhost:3000 node shot-citations.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/citations";
fs.mkdirSync(OUT, { recursive: true });

const VIEWPORTS = [["390", 390, 844], ["1440", 1440, 900]];
const THEMES = ["light", "dark"];
const TRIGGER = 'button[aria-expanded]';

const browser = await chromium.launch();
const report = [];
for (const [w, width, height] of VIEWPORTS) {
  for (const theme of THEMES) {
    const ctx = await browser.newContext({
      viewport: { width, height }, colorScheme: theme, deviceScaleFactor: 2,
      reducedMotion: "reduce", // settled states, not mid-animation
    });
    const page = await ctx.newPage();
    await page.addInitScript((t) => {
      document.addEventListener("DOMContentLoaded", () => {
        if (t === "dark") document.documentElement.classList.add("dark");
      });
    }, theme);
    await page.goto(`${BASE}/dev/citations`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);

    const trigger = page.locator(TRIGGER).first();
    const tag = await trigger.evaluate((el) => el.tagName.toLowerCase());
    const before = await trigger.getAttribute("aria-expanded");
    // Radix mounts the panel only while open, so aria-controls is expected to
    // be absent here (ARIA: never reference an element that is not in the DOM)
    // and present once expanded. Both states are recorded.
    const controlsWhenClosed = await trigger.getAttribute("aria-controls");
    await page.screenshot({ path: `${OUT}/collapsed-${w}-${theme}.png`, fullPage: true });

    // Keyboard path: focus + Enter, exactly as a non-mouse user would do it.
    await trigger.focus();
    await page.keyboard.press("Enter");
    await page.waitForSelector(`${TRIGGER}[aria-expanded="true"]`);
    await page.waitForTimeout(300);
    const after = await trigger.getAttribute("aria-expanded");
    const controls = await trigger.getAttribute("aria-controls");
    const panelVisible = controls ? await page.locator(`#${controls}`).isVisible() : false;
    const links = controls
      ? await page.locator(`#${controls} a[href*="eur-lex.europa.eu"]`).count()
      : 0;
    await page.screenshot({ path: `${OUT}/expanded-${w}-${theme}.png`, fullPage: true });

    // And back again with Space.
    await page.keyboard.press("Space");
    await page.waitForSelector(`${TRIGGER}[aria-expanded="false"]`);
    const afterClose = await trigger.getAttribute("aria-expanded");

    report.push({ viewport: w, theme, tag, expandedBefore: before, expandedAfter: after,
      expandedAfterClose: afterClose, controlsClosed: controlsWhenClosed, controlsOpen: controls,
      panelVisible, eurlexLinks: links });
    await ctx.close();
  }
}
await browser.close();
console.table(report);
console.log("screenshots ->", OUT);
