// Feature probes: the delete menu + confirm dialog (/dev/history) and the
// scope notice / refusal copy (/dev/citations). 390 and 1440, light and dark.
//   BASE=http://localhost:3000 node shot-scope-delete.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = "shots/scope-delete";
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

    // --- scope notice and refusal copy
    await page.goto(`${BASE}/dev/citations`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const scope = await page.evaluate(() => {
      const s = document.querySelector('[data-testid="scope-notice"]');
      const r = document.querySelector('[data-testid="refusal"]');
      const t = (el) => el?.textContent ?? "";
      return {
        scopeShown: !!s, refusalShown: !!r,
        scopeSaysNotGeneralChatbot: /not a general chatbot/.test(t(s)),
        scopeExamples: (t(s).match(/\?/g) ?? []).length >= 3,
        scopeHasAssessRoute: !!s?.querySelector('a[href^="/app/assess"]'),
        scopeNotLegalAdvice: /not legal advice/i.test(t(s)),
        refusalKeepsRetrievalLead: /retrieved provisions did not contain enough/.test(t(r)),
        refusalHasExamplesAndRoute: /You can ask/.test(t(r)) && !!r?.querySelector('a[href^="/app/assess"]'),
        emDash: document.body.innerText.includes("\u2014"),
        pageScrollsX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      };
    });
    await page.locator('[data-testid="scope-notice"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${OUT}/scope-${w}-${theme}.png`, fullPage: true });

    // --- delete menu + confirm
    await page.goto(`${BASE}/dev/history`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    if (width < 768) {
      await page.getByRole("button", { name: "Menu", exact: true }).click();
      await page.waitForSelector('[role="dialog"][aria-modal="true"]');
    }
    const rowsBefore = await page.locator('nav[aria-label="Past chats"] li').count();
    await page.getByRole("button", { name: /Options for chat: Is an AI system/ }).first().click();
    await page.getByRole("menuitem", { name: "Delete chat" }).click();
    await page.waitForSelector('[data-testid="delete-chat-dialog"]');
    const dialog = await page.evaluate(() => {
      const d = document.querySelector('[data-testid="delete-chat-dialog"]');
      return {
        role: d?.getAttribute("role"), modal: d?.getAttribute("aria-modal"),
        focusInside: !!d?.contains(document.activeElement),
        text: d?.textContent?.slice(0, 120) ?? "",
      };
    });
    await page.screenshot({ path: `${OUT}/confirm-${w}-${theme}.png`, fullPage: false });
    // Escape cancels...
    await page.keyboard.press("Escape");
    await page.waitForSelector('[data-testid="delete-chat-dialog"]', { state: "detached" });
    const afterEscape = await page.locator('nav[aria-label="Past chats"] li').count();
    // ...and confirming deletes.
    await page.getByRole("button", { name: /Options for chat: Is an AI system/ }).first().click();
    await page.getByRole("menuitem", { name: "Delete chat" }).click();
    await page.getByTestId("confirm-delete").click();
    await page.waitForSelector('[data-testid="delete-chat-dialog"]', { state: "detached" });
    await page.waitForTimeout(150);
    const rowsAfter = await page.locator('nav[aria-label="Past chats"] li').count();
    // Delete the rest: the empty state must appear.
    for (let i = 0; i < 6; i++) {
      const opt = page.getByRole("button", { name: /^Options for chat:/ }).first();
      if (!(await opt.count())) break;
      await opt.click();
      await page.getByRole("menuitem", { name: "Delete chat" }).click();
      await page.getByTestId("confirm-delete").click();
      await page.waitForSelector('[data-testid="delete-chat-dialog"]', { state: "detached" });
      await page.waitForTimeout(100);
    }
    const emptyState = await page.evaluate(() => /No chats yet/.test(document.body.innerText));
    await page.screenshot({ path: `${OUT}/deleted-empty-${w}-${theme}.png`, fullPage: false });

    console.log(JSON.stringify({ viewport: w, theme, ...scope, dialog, rowsBefore, afterEscape, rowsAfter, emptyState }));
    await ctx.close();
  }
}
await browser.close();
console.log("screenshots ->", OUT);
