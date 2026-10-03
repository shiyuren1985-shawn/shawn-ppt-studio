import test from "node:test";
import assert from "node:assert/strict";
import { slideForIdentityPage } from "../../server/studio-selection-catalog.mjs";
import { normalizeSelectorPage } from "../../web/selector/model.js";
const slide = { slide_uid: "stable-nine", page_id: "P9" };
const deck = { outline: { path: "/outline.md", deck_uid: "deck", slides: [slide] } };
const identity = { required: true, source_path: "/outline.md", deck_uid: "deck", slide_uids: { "09-ZH": "stable-nine", "09-EN": "stable-nine" } };
test("language siblings resolve to one logical slide", () => {
  for (const key of ["09-ZH", "09-EN", "P9"]) assert.equal(slideForIdentityPage(identity, deck, key), slide);
});
test("different slide identities remain an actual conflict", () => {
  assert.equal(slideForIdentityPage({ ...identity, slide_uids: { ...identity.slide_uids, "09-EN": "other" } }, deck, "09-ZH"), null);
});
test("both languages retain independent selections and language metadata", () => {
  const candidates = ["zh", "en"].map(language => ({ candidate_id: language, language, selected: true, preview_url: `/api/selector-workspace/${language}` }));
  const page = normalizeSelectorPage({ slide_uid: slide.slide_uid, candidates, selected_candidate_ids: ["zh", "en"] });
  assert.deepEqual(page.selected_candidate_ids, ["zh", "en"]);
  assert.deepEqual(page.candidates.map(c => c.language), ["zh", "en"]);
});
