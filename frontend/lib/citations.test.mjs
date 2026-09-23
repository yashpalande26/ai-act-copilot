// node --experimental-strip-types --test lib/citations.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { covers, effectiveReferences, referencesIn, splitCitations } from "./citations.ts";

test("reads the label grammar the answers use into citation ids", () => {
  assert.deepEqual(referencesIn("see Article 50, paragraph 1 and Article 6(2)."), ["art_50.par_1", "art_6.par_2"]);
  assert.deepEqual(referencesIn("(Article 16, point (a))"), ["art_16.pt_a"]);
  assert.deepEqual(referencesIn("Article 5, paragraph 1, point (c) forbids it"), ["art_5.par_1.pt_c"]);
  assert.deepEqual(referencesIn("listed in Annex III, point 5(b)"), ["anx_III.pt_5.sub_b"]);
  assert.deepEqual(referencesIn("Annex I, Section A, point 4"), ["anx_I.sec_A.pt_4"]);
  assert.deepEqual(referencesIn("the reason is in Recital 58 and Recital 31"), ["rec_31", "rec_58"]);
  assert.deepEqual(referencesIn("Article 4a, paragraph 1"), ["art_4a.par_1"]);
  assert.deepEqual(referencesIn("Annex III, points 5(b) and (c)"), ["anx_III.pt_5.sub_b"]);
  assert.deepEqual(referencesIn("no provision named here"), []);
});

test("a reference covers the same provision, its children and its parents", () => {
  assert.equal(covers("art_16", "art_16.pt_a"), true);
  assert.equal(covers("art_6.par_2", "art_6"), true);
  assert.equal(covers("art_6", "art_60"), false);
  assert.equal(covers("anx_III.pt_5.sub_b", "anx_III.pt_5.sub_a"), false);
});

test("splits the served context into cited and other, keeping the server order", () => {
  const c = (id, label) => ({ citation_id: id, citation_label: label, quoted_text: "t" });
  const served = [
    c("anx_III.pt_5.sub_b", "Annex III, point 5(b)"),
    c("art_5.par_1.pt_c", "Article 5, paragraph 1, point (c)"),
    c("art_4.par_1", "Article 4, paragraph 1"),
    c("rec_58", "Recital 58"),
    c("rec_31", "Recital 31"),
  ];
  const answer =
    "Creditworthiness scoring is listed in Annex III, point 5(b) because such systems can determine access to essential services (Recital 58).";
  const { used, other } = splitCitations(answer, served);
  assert.deepEqual(
    used.map((x) => x.citation_id),
    ["anx_III.pt_5.sub_b", "rec_58"],
  );
  assert.deepEqual(
    other.map((x) => x.citation_id),
    ["art_5.par_1.pt_c", "art_4.par_1", "rec_31"],
  );
});

test("an answer that names nothing leaves every citation in other", () => {
  const served = [{ citation_id: "art_4.par_1", citation_label: "Article 4, paragraph 1", quoted_text: "t" }];
  const { used, other } = splitCitations("None of the retrieved provisions names this use.", served);
  assert.equal(used.length, 0);
  assert.equal(other.length, 1);
});

test("a bare root mention does not pull in the siblings of the point the answer named", () => {
  assert.deepEqual(effectiveReferences(["anx_III", "anx_III.pt_5.sub_b", "art_6"]), ["anx_III.pt_5.sub_b", "art_6"]);
  const c = (id) => ({ citation_id: id, citation_label: id, quoted_text: "t" });
  const served = [c("anx_III.pt_5.sub_b"), c("anx_III.pt_5.sub_a"), c("anx_III.pt_5.sub_c"), c("art_6.par_2")];
  const answer = "Listed in Annex III, point 5(b). The Annex III entry carries the exception; Article 6 makes the list binding.";
  const { used, other } = splitCitations(answer, served);
  assert.deepEqual(used.map((x) => x.citation_id), ["anx_III.pt_5.sub_b", "art_6.par_2"]);
  assert.deepEqual(other.map((x) => x.citation_id), ["anx_III.pt_5.sub_a", "anx_III.pt_5.sub_c"]);
});
