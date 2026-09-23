// Screenshots + probe of the chat panel via /dev/chat-turns: the CTA rule
// (only grounded answers and system explanations carry it), the citation
// scope (cited provisions first, the rest behind "other retrieved") and the
// panel layout (fills the viewport, list scrolls, composer anchored).
//   BASE=http://localhost:3000 OUT=shots/chat-turns node shot-chat-turns.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = process.env.OUT ?? "shots/chat-turns";
fs.mkdirSync(OUT, { recursive: true });
const VIEWPORTS = [["390", 390, 844], ["1440", 1440, 900]];
const THEMES = ["light", "dark"];
const THREADS = ["short", "lanes", "long", "grounded", "empty", "loading"];
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
          composerAnchored: cb ? Math.abs(cb.bottom - window.innerHeight) <= 1 : null,
          listHeight: lb ? Math.round(lb.height) : null,
          listScrollable: list ? list.scrollHeight > list.clientHeight + 1 : null,
          horizontalScroll: doc.scrollWidth > doc.clientWidth,
        };
      });
      const cta = {
        answer: await page.getByTestId("assess-cta-answer").count(),
        system: await page.getByTestId("assess-cta-system").count(),
        social: await page.getByTestId("social-turn").count(),
        clarifying: await page.getByTestId("clarifying-turn").count(),
        scope: await page.getByTestId("scope-notice").count(),
        refusalTurns: await page.getByTestId("refusal").count(),
      };
      const citations = {
        counts: await page.getByTestId("citations-count").allTextContents(),
        otherCounts: await page.getByTestId("citations-other-count").allTextContents(),
      };
      const row = { viewport: w, theme, thread, ...layout, cta, citations, emDash: (await page.content()).includes("—") };
      report.push(row);
      console.log(JSON.stringify(row));
      await page.screenshot({ path: `${OUT}/${thread}-${w}-${theme}.png`, fullPage: false });
      if (thread === "lanes") {
        await page.evaluate(() => { const l = document.querySelector("form")?.parentElement?.parentElement?.previousElementSibling; if (l) l.scrollTop = l.scrollHeight; });
        await page.waitForTimeout(150);
        await page.screenshot({ path: `${OUT}/${thread}-end-${w}-${theme}.png`, fullPage: false });
      }
      if (thread === "grounded") {
        // open the first answer's cited provisions, then the "other retrieved" expander
        const triggers = page.getByRole("button", { name: /cited provisions|retrieved provisions/i });
        await triggers.first().click();
        await page.waitForTimeout(250);
        await page.evaluate(() => { const l = document.querySelector("form")?.parentElement?.parentElement?.previousElementSibling; if (l) l.scrollTop = 0; });
        await page.screenshot({ path: `${OUT}/${thread}-open-${w}-${theme}.png`, fullPage: false });
        const used = await page.getByTestId("citations-used").first().locator("li").count();
        const other = page.getByRole("button", { name: /other retrieved provisions/i }).first();
        await other.click();
        await page.waitForTimeout(250);
        const otherN = await page.getByTestId("citations-other").first().locator("li").count();
        await other.scrollIntoViewIfNeeded();
        await page.evaluate(() => { const l = document.querySelector("form")?.parentElement?.parentElement?.previousElementSibling; if (l) l.scrollTop -= 120; });
        await page.waitForTimeout(150);
        await page.screenshot({ path: `${OUT}/${thread}-other-${w}-${theme}.png`, fullPage: false });
        report.push({ viewport: w, theme, thread: "grounded-open", used, other: otherN });
        console.log(JSON.stringify({ viewport: w, theme, thread: "grounded-open", used, other: otherN }));
        // keyboard: Tab from the composer reaches the disclosure and the CTA with a visible ring
        if (w === "1440") {
          // keyboard focus, not programmatic: focus-visible only shows for the keyboard
          await page.getByTestId("answer-card").first().click({ position: { x: 20, y: 60 } });
          for (let i = 0; i < 12; i++) {
            await page.keyboard.press("Tab");
            const onTrigger = await page.evaluate(() => /cited provisions|retrieved provisions/i.test(document.activeElement?.textContent ?? ""));
            if (onTrigger) break;
          }
          const ring = await page.evaluate(() => {
            const el = document.activeElement;
            const cs = el ? getComputedStyle(el) : null;
            return cs ? { tag: el.tagName, outline: cs.outlineStyle, boxShadow: cs.boxShadow.slice(0, 60) } : null;
          });
          console.log(JSON.stringify({ focusRing: ring }));
        }
      }
    }
    await ctx.close();
  }
}
await browser.close();
fs.writeFileSync(`${OUT}/probe.json`, JSON.stringify(report, null, 2));
