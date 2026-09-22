// Screenshots + probes for the chat -> assessment funnel.
//   /dev/citations            answer turn + refusal turn, each with the CTA
//   /dev/assess?view=describe the describe box pre-filled from ?describe=
// The product page /app/assess needs a signed-in session, so the pre-fill is
// verified on the same DescribeScreen component through the same prop the
// page passes (initialText), using the exact href the CTA emitted.
//   BASE=http://localhost:3000 node shot-funnel.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/funnel";
fs.mkdirSync(OUT, { recursive: true });

const VIEWPORTS = [["390", 390, 844], ["1440", 1440, 900]];
const THEMES = ["light", "dark"];
const QUESTION = "What obligations apply to providers of high-risk AI systems?";

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

    await page.goto(`${BASE}/dev/citations`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const chat = await page.evaluate((q) => {
      const answer = document.querySelector('[data-testid="assess-cta-answer"] a');
      const refusal = document.querySelector('[data-testid="assess-cta-refusal"] a');
      const expected = `/app/assess?describe=${encodeURIComponent(q)}`;
      const text = document.body.innerText;
      return {
        answerCta: !!answer,
        refusalCta: !!refusal,
        answerHrefCarriesQuestion: answer?.getAttribute("href") === expected,
        refusalHrefCarriesQuestion: refusal?.getAttribute("href") === expected,
        ctaCount: document.querySelectorAll('[data-testid^="assess-cta"]').length,
        answerStillRendered: /Providers must ensure their high-risk AI systems/.test(text),
        refusalStillRendered: /The copilot declined to answer/.test(text),
        systemNote: !!document.querySelector('[data-testid="system-description-note"]'),
        systemCta: !!document.querySelector('[data-testid="assess-cta-system"] a[href^="/app/assess"]'),
        systemNoteHonest: /decided by the assessment, not here/.test(text),
        systemNoVerdict: !/your system is (not )?high-risk/i.test(text),
        emDash: text.includes("—"),
        pageScrollsX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
        href: answer?.getAttribute("href") ?? null,
      };
    }, QUESTION);
    await page.screenshot({ path: `${OUT}/chat-${w}-${theme}.png`, fullPage: true });

    // Follow the carried text into the describe screen (same component, same prop).
    const qs = chat.href ? chat.href.split("?")[1] : "";
    await page.goto(`${BASE}/dev/assess?view=describe&${qs}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const describe = await page.evaluate((q) => {
      const ta = document.querySelector("textarea");
      const btn = [...document.querySelectorAll("button")].find((b) => /Pre-fill/.test(b.textContent ?? ""));
      return {
        prefilled: ta?.value === q,
        counter: [...document.querySelectorAll("p")].find((p) => /\/ 4,000/.test(p.textContent ?? ""))?.textContent?.trim() ?? null,
        prefillEnabled: !btn?.disabled,
        emDash: document.body.innerText.includes("—"),
      };
    }, QUESTION);
    await page.screenshot({ path: `${OUT}/describe-prefilled-${w}-${theme}.png`, fullPage: true });

    report.push({ viewport: w, theme, ...chat, ...describe });
    await ctx.close();
  }
}
await browser.close();
for (const r of report) console.log(JSON.stringify(r));
console.log("screenshots ->", OUT);
