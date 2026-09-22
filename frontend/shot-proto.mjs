// Prototype probes + shots: Act glossary and assessment timeline via /dev/proto.
import { chromium } from "playwright";
import fs from "node:fs";
const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/proto"; fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
for (const [w, width, height] of [["390", 390, 844], ["1440", 1440, 900]]) {
  for (const theme of ["light", "dark"]) {
    const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: theme, deviceScaleFactor: 2, reducedMotion: "reduce" });
    const page = await ctx.newPage();
    await page.addInitScript((t) => { document.addEventListener("DOMContentLoaded", () => { if (t === "dark") document.documentElement.classList.add("dark"); }); }, theme);
    await page.goto(`${BASE}/dev/proto?view=glossary`, { waitUntil: "networkidle" }); await page.waitForTimeout(300);
    const before = await page.locator('[data-testid="definition"]').count();
    await page.fill('[data-testid="glossary-search"]', "deep fake"); await page.waitForTimeout(250);
    const g = await page.evaluate(() => ({
      defs: document.querySelectorAll('[data-testid="definition"]').length,
      verbatim: /‘deep fake’ means/.test(document.body.innerText),
      eurlex: document.querySelectorAll('a[href*="eur-lex.europa.eu"]').length,
      emDash: document.body.innerText.includes("—"),
      scrollX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }));
    await page.screenshot({ path: `${OUT}/glossary-${w}-${theme}.png`, fullPage: true });
    await page.goto(`${BASE}/dev/proto?view=timeline`, { waitUntil: "networkidle" }); await page.waitForTimeout(300);
    const t = await page.evaluate(() => ({
      entries: document.querySelectorAll('[data-testid="timeline-entry"]').length,
      datedText: (document.body.innerText.match(/Applies from \d{1,2} \w+ \d{4}/g) ?? []).slice(0, 3),
      undated: /Application date not captured in this corpus/.test(document.body.innerText),
      ics: !!document.querySelector('[data-testid="ics-link"]'),
      notLegalAdvice: /not legal advice/i.test(document.body.innerText),
      emDash: document.body.innerText.includes("—"),
      scrollX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }));
    await page.screenshot({ path: `${OUT}/timeline-${w}-${theme}.png`, fullPage: true });
    console.log(JSON.stringify({ viewport: w, theme, glossaryBefore: before, ...Object.fromEntries(Object.entries(g).map(([k, v]) => ["g_" + k, v])), ...Object.fromEntries(Object.entries(t).map(([k, v]) => ["t_" + k, v])) }));
    await ctx.close();
  }
}
await browser.close();
