// node --experimental-strip-types --test lib/timeline.test.mjs
// Prototype B date rule: Article 113(c) names (i) 2 December 2027 for Annex III
// and (ii) 2 August 2028 for Annex I; the record's route must pick the right one.
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import { buildIcs, buildTimeline, routeOf, selectDates } from "./timeline.ts";

const report = JSON.parse(fs.readFileSync(new URL("./fixtures/assessment-report.json", import.meta.url), "utf8"));
const annexI = structuredClone(report);
annexI.decision = { ...annexI.decision, product_route: true, high_risk_basis: null };

test("route is read from the record's own decision", () => {
  assert.equal(routeOf(report), "annex_iii");
  assert.equal(routeOf(annexI), "annex_i");
  assert.equal(routeOf({ ...report, decision: { ...report.decision, high_risk_basis: null } }), "unknown");
});

test("an Annex III record gets 2 December 2027 for every Article 113(c) group", () => {
  const { dated, undated } = buildTimeline(report);
  assert.ok(dated.length >= 7);
  for (const e of dated) {
    assert.equal(e.dates.length, 1, e.key);
    assert.equal(e.dates[0].iso, "2027-12-02", e.key);
    assert.equal(e.resolved, true);
  }
  assert.deepEqual(undated.map((e) => e.key).sort(), ["ai_literacy", "transparency_1"]);
});

test("an Annex I (product route) record gets 2 August 2028 instead", () => {
  const { dated } = buildTimeline(annexI);
  for (const e of dated) {
    assert.equal(e.dates[0].iso, "2028-08-02", e.key);
    assert.equal(e.resolved, true);
  }
});

test("an unknown route keeps every date and says so; a single-date text resolves", () => {
  const text = report.obligations.find((g) => g.key === "provider_core").applies_from.text;
  const both = selectDates(text, "unknown");
  assert.deepEqual(both.dates.map((d) => d.iso), ["2027-12-02", "2028-08-02"]);
  assert.equal(both.resolved, false);
  assert.deepEqual(selectDates("Articles 102 to 110 shall apply from 27 July 2026.", "unknown"), {
    dates: [{ iso: "2026-07-27", label: "27 July 2026" }],
    resolved: true,
  });
});

test("the .ics uses the same selected date and keeps the notice", () => {
  const ics3 = buildIcs(report, "00000000-0000-4000-8000-000000000000", report.headline_text);
  const ics1 = buildIcs(annexI, "00000000-0000-4000-8000-000000000000", report.headline_text);
  assert.ok(/DTSTART;VALUE=DATE:20271202/.test(ics3));
  assert.ok(!/20280802/.test(ics3));
  assert.ok(/DTSTART;VALUE=DATE:20280802/.test(ics1));
  assert.ok(!/20271202/.test(ics1));
  assert.ok(/not legal advice/.test(ics3));
  assert.ok(!/\u2014/.test(ics3 + ics1));
});
