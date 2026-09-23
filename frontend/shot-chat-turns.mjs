// Screenshots + probe of the chat panel via /dev/chat-turns: the CTA rule
// (only grounded answers and system explanations carry it) and the panel
// layout (fills the viewport, list scrolls, composer anchored, no dead space).
//   BASE=http://localhost:3000 OUT=shots/chat-turns node shot-chat-turns.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = process.env.OUT ?? "shots/chat-turns";
fs.mkdirSync(OUT, { recursive: true });
const VIEWPORTS = [["390", 390, 844], ["1440", 1440, 900]];
const THEMES = ["light", "dark"];
const THREADS = ["short", "lanes", "long"];
const browser = await chromium.launch();
const report = [];
for (const [w, width, height] of VIEWPORTS) {
  for (const theme of THEMES) {
    const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: theme, deviceScaleFactor: 2, reducedMotion: "reduce" });
    const page = await ctx.newPage();
    await page.addInitScript((t) => {
      document.addEventListener("DOMContentLoaded", () => { if (t === "dark") document.documentElement.classList.add("dark"); });
    }, theme);
    for (const thread of THREADS) {
      await page.goto(`${BASE}/dev/chat-turns?thread=${thread}`, { waitUntil: "networkidle" });
      await page.waitForTimeout(300);
      const layout = await page.evaluate(() => {
        const doc = document.documentElement;
        const composer = document.querySelector("form textarea")?.closest("form")?.parentElement?.parentElement;
        const list = composer?.previousElementSibling;
        const cb = composer?.getBoundingClientRect();
        const lb = list?.getBoundingClientRect();
        return {
          documentScrolls: doc.scrollHeight > doc.clientHeight + 1,
          composerBottom: cb ? Math.round(cb.bottom) : null,
          viewportHeight: window.innerHeight,
          composerAnchored: cb ? Math.abs(cb.bottom - window.innerHeight) <= 1 : null,
          listHeight: lb ? Math.round(lb.height) : null,
          listScrollable: list ? list.scrollHeight > list.clientHeight + 1 : null,
          listOverflowY: list ? getComputedStyle(list).overflowY : null,
          horizontalScroll: doc.scrollWidth > doc.clientWidth,
        };
      });
      const cta = {
        answer: await page.getByTestId("assess-cta-answer").count(),
        system: await page.getByTestId("assess-cta-system").count(),
        refusal: await page.getByTestId("assess-cta-refusal").count(),
        social: await page.getByTestId("social-turn").count(),
        clarifying: await page.getByTestId("clarifying-turn").count(),
        scope: await page.getByTestId("scope-notice").count(),
        refusalTurns: await page.getByTestId("refusal").count(),
      };
      const row = { viewport: w, theme, thread, ...layout, cta, emDash: (await page.content()).includes("—") };
      report.push(row);
      console.log(JSON.stringify(row));
      await page.screenshot({ path: `${OUT}/${thread}-${w}-${theme}.png`, fullPage: false });
      if (thread === "lanes") {
        // the whole thread, scrolled inside the list, for the CTA check
        await page.evaluate(() => { const l = document.querySelector("form")?.parentElement?.parentElement?.previousElementSibling; if (l) l.scrollTop = l.scrollHeight; });
        await page.waitForTimeout(150);
        await page.screenshot({ path: `${OUT}/${thread}-end-${w}-${theme}.png`, fullPage: false });
      }
    }
    await ctx.close();
  }
}
await browser.close();
fs.writeFileSync(`${OUT}/probe.json`, JSON.stringify(report, null, 2));
