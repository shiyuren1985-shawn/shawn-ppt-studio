import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  legacyStudioSelectionPath,
  readStudioSelection,
  StudioSelectionStore,
  studioSelectionPath,
} from "../../server/studio-selection-store.mjs";

function deck(projectRoot, name) {
  return {
    project_root: projectRoot,
    outline: {
      deck_uid: `${name}_UID`,
      path: path.join(projectRoot, `${name}.md`),
      slides: [{ page_id: "P1", slide_uid: `${name}_SLIDE` }],
    },
  };
}

async function fixture(t) {
  const root = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-selection-isolation-")));
  t.after(() => rm(root, { recursive: true, force: true }));
  const first = deck(root, "FIRST");
  const second = deck(root, "SECOND");
  await Promise.all([
    writeFile(first.outline.path, "# First\n"),
    writeFile(second.outline.path, "# Second\n"),
  ]);
  return { root, first, second };
}

test("a foreign legacy selection in a shared outline folder is empty, not corrupt", async (t) => {
  const { first, second } = await fixture(t);
  const legacyPath = legacyStudioSelectionPath(first);
  await mkdir(path.dirname(legacyPath), { recursive: true });
  await writeFile(legacyPath, `${JSON.stringify({
    selection_contract_version: 1,
    deck_uid: first.outline.deck_uid,
    outline_path: first.outline.path,
    updated_at: null,
    pages: {},
  })}\n`);

  assert.equal((await readStudioSelection(first)).deck_uid, first.outline.deck_uid);
  const secondSelection = await readStudioSelection(second);
  assert.equal(secondSelection.deck_uid, second.outline.deck_uid);
  assert.deepEqual(secondSelection.pages, {});
});

test("two outlines in one folder persist independent scoped selections", async (t) => {
  const { first, second } = await fixture(t);
  const store = new StudioSelectionStore({ clock: () => "2026-08-22T00:00:00.000Z" });
  const firstRef = {
    run_id: "first-run",
    handoff_path: path.join(first.project_root, "output", "first", "state", "handoff.json"),
    native_candidate_id: "A-01",
  };
  const secondRef = {
    run_id: "second-run",
    handoff_path: path.join(second.project_root, "output", "second", "state", "handoff.json"),
    native_candidate_id: "B-01",
  };

  await store.setCandidate(first, first.outline.slides[0].slide_uid, firstRef, true);
  await store.setCandidate(second, second.outline.slides[0].slide_uid, secondRef, true);

  assert.notEqual(studioSelectionPath(first), studioSelectionPath(second));
  const firstStored = JSON.parse(await readFile(studioSelectionPath(first), "utf8"));
  const secondStored = JSON.parse(await readFile(studioSelectionPath(second), "utf8"));
  assert.equal(firstStored.deck_uid, first.outline.deck_uid);
  assert.equal(secondStored.deck_uid, second.outline.deck_uid);
  assert.equal(firstStored.pages[first.outline.slides[0].slide_uid].selected_candidate_refs[0].run_id, "first-run");
  assert.equal(secondStored.pages[second.outline.slides[0].slide_uid].selected_candidate_refs[0].run_id, "second-run");
});

test("a malformed legacy selection still fails closed", async (t) => {
  const { first } = await fixture(t);
  const legacyPath = legacyStudioSelectionPath(first);
  await mkdir(path.dirname(legacyPath), { recursive: true });
  await writeFile(legacyPath, "{not-json\n");
  await assert.rejects(
    () => readStudioSelection(first),
    { code: "studio_selection_invalid" },
  );
});

test("11 to 10 pages preserves removed-page selections across renumbering, writes and restoration", async (t) => {
  const { first } = await fixture(t);
  const store = new StudioSelectionStore();
  first.outline.slides = Array.from({ length: 11 }, (_, i) => ({ page_id: `P${i + 1}`, slide_uid: `UID_${i + 1}` }));
  const ref = (n) => ({ run_id: "original", handoff_path: path.join(first.project_root, "output/state/handoff.json"), native_candidate_id: `C${n}` });
  for (let n = 1; n <= 11; n++) await store.setCandidate(first, `UID_${n}`, ref(n), true);
  const before = await readFile(studioSelectionPath(first), "utf8");
  first.outline.slides = first.outline.slides.filter(s => s.slide_uid !== "UID_7")
    .map((s, i) => ({ ...s, page_id: `P${i + 1}` }));
  const read = await store.read(first);
  assert.equal(Object.keys(read.pages).length, 11);
  assert.equal(read.pages.UID_8.selected_candidate_refs[0].native_candidate_id, "C8");
  assert.equal(await readFile(studioSelectionPath(first), "utf8"), before, "reading must not mutate selection history");
  await store.setCandidate(first, "UID_1", ref(1), false);
  assert.deepEqual((await new StudioSelectionStore().read(first)).pages.UID_7, read.pages.UID_7);
  await assert.rejects(() => store.setCandidate(first, "UID_7", ref(7), true), { code: "slide_not_found" });
  first.outline.slides.push({ page_id: "P11", slide_uid: "NEW_UID" });
  assert.equal((await store.read(first)).pages.NEW_UID, undefined, "reused page numbers must not inherit selection");
  first.outline.slides.push({ page_id: "P12", slide_uid: "UID_7" });
  assert.equal((await store.read(first)).pages.UID_7.selected_candidate_refs[0].native_candidate_id, "C7");
});

test("malformed page records and foreign deck identities remain invalid", async (t) => {
  const { first, second } = await fixture(t);
  const store = new StudioSelectionStore();
  await store.setCandidate(first, first.outline.slides[0].slide_uid, {
    run_id: "run", handoff_path: path.join(first.project_root, "handoff.json"), native_candidate_id: "A",
  }, true);
  const file = studioSelectionPath(first);
  const original = JSON.parse(await readFile(file, "utf8"));
  await writeFile(file, JSON.stringify({ ...original, pages: { OLD_UID: null } }));
  await assert.rejects(() => store.read(first), { code: "studio_selection_invalid" });
  await writeFile(file, JSON.stringify({ ...original, deck_uid: second.outline.deck_uid }));
  await assert.rejects(() => store.read(first), { code: "studio_selection_invalid" });
});
