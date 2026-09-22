// Screenshots + probe of the in-flight turn indicator via /dev/pending.
//   BASE=http://localhost:3000 node shot-pending.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/pending";
fs.mkdirSync(OUT, { recursive: true });
const VIEWPORTS = [["390", 390, 844], ["1440", 1440, 900]];
const THEMES = ["light", "dark"];
const browser = await chromium.launch();
const report = [];
for (const [w, width, height] of VIEWPORTS) {
  for (const theme of THEMES) {
    for (const motion of ["reduce", "no-preference"]) {
      const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: theme, deviceScaleFactor: 2, reducedMotion: motion });
      const page = await ctx.newPage();
      await page.addInitScript((t) => {
        document.addEventListener("DOMContentLoaded", () => { if (t === "dark") document.documentElement.classList.add("dark"); });
      }, theme);
      const row = { viewport: w, theme, motion };
      for (const phase of ["bar", "early", "late"]) {
        await page.goto(`${BASE}/dev/pending?phase=${phase}`, { waitUntil: "networkidle" });
        await page.waitForTimeout(250);
        const status = page.getByTestId("pending-turn");
        row[`${phase}_role`] = await status.getAttribute("role");
        row[`${phase}_live`] = await status.getAttribute("aria-live");
        row[`${phase}_phase`] = await status.getAttribute("data-phase");
        row[`${phase}_text`] = (await status.innerText()).trim().slice(0, 60);
        row[`${phase}_anim`] = await page.evaluate(() => getComputedStyle(document.querySelector(".pending-sweep")).animationName);
        row[`${phase}_scrollX`] = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
        if (motion === "reduce") await page.screenshot({ path: `${OUT}/${phase}-${w}-${theme}.png`, fullPage: false });
      }
      // clears on response
      await page.getByTestId("resolve").click();
      await page.waitForTimeout(150);
      row.clearedOnResolve = (await page.getByTestId("pending-turn").count()) === 0;
      row.answerShown = await page.getByText("Article 3, point (4)").first().isVisible();
      row.emDash = (await page.content()).includes("\u2014");
      report.push(row);
      console.log(JSON.stringify(row));
      await ctx.close();
    }
  }
}
await browser.close();
fs.writeFileSync(`${OUT}/probe.json`, JSON.stringify(report, null, 2));
