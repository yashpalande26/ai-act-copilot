// Screenshots + probe for the assessment report and questionnaire via /dev/assess.
//   BASE=http://localhost:3000 node shot-assess.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/assess";
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

    await page.goto(`${BASE}/dev/assess`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    // Open the first obligation group so the verbatim text is in the shot.
    await page.locator('button[aria-expanded="false"]').first().click();
    await page.waitForTimeout(300);
    const probe = await page.evaluate(() => ({
      groups: document.querySelectorAll('[data-slot="collapsible"]').length,
      eurlexLinks: document.querySelectorAll('a[href*="eur-lex.europa.eu"]').length,
      commentaryLabels: [...document.querySelectorAll("span")].filter((s) => s.textContent === "Commentary").length,
      hasNotLegalAdvice: document.body.innerText.toLowerCase().includes("not legal advice"),
      saysCompliant: /you are compliant/i.test(document.body.innerText),
      pageScrollsX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }));
    await page.screenshot({ path: `${OUT}/report-${w}-${theme}.png`, fullPage: true });

    await page.goto(`${BASE}/dev/assess?view=form`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const formProbe = await page.evaluate(() => ({
      radios: document.querySelectorAll('input[type="radio"]').length,
      steps: document.querySelectorAll('[aria-label="Steps"] li').length,
      pageScrollsX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }));
    await page.screenshot({ path: `${OUT}/form-${w}-${theme}.png`, fullPage: true });

    report.push({ viewport: w, theme, ...probe, formRadios: formProbe.radios, formSteps: formProbe.steps, formScrollsX: formProbe.pageScrollsX });
    await ctx.close();
  }
}
await browser.close();
console.table(report);
console.log("screenshots ->", OUT);
