import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, writeFile, realpath, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Writable } from "node:stream";
import { once } from "node:events";
import { buildStudioCatalog, scanStudioCandidates } from "../../server/studio-selection-catalog.mjs";
import { SelectionProjection } from "../../server/selection-projection.mjs";
import { studioSelectionPath } from "../../server/studio-selection-store.mjs";
import { SelectorWorkspace } from "../../server/selector-workspace.mjs";
import { normalizeCandidate } from "../../web/selector/model.js";
import { normalizeSelection } from "../../web/model.js";

const sha = bytes => createHash("sha256").update(bytes).digest("hex");
async function fixture(t) {
  const root = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-generated-")));
  t.after(() => rm(root, { recursive: true, force: true }));
  const project = path.join(root, "output", "run");
  const source = path.join(root, "generated_images", "thread", "image.png");
  await mkdir(path.dirname(source), { recursive: true });
  await mkdir(path.join(project, "state"), { recursive: true });
  const png = Buffer.alloc(80);
  Buffer.from("89504e470d0a1a0a0000000d49484452", "hex").copy(png);
  png.writeUInt32BE(1600, 16); png.writeUInt32BE(900, 20);
  await writeFile(source, png);
  const deck = { source_kind: "studio", label: "Test", project_root: root, output_root: path.join(root, "output"), outline: { path: path.join(root, "outline.md"), deck_uid: "deck", slides: [{ page_id: "P14", slide_uid: "new-slide", order: 14, title: "New" }] } };
  const snapshot = JSON.stringify({ run_id: "run", run_mode: "selected_style_expansion", slide_identity: { required: true, deck_uid: "deck", source_path: deck.outline.path, slide_uids: { "01": "new-slide" } } });
  const snapshotPath = path.join(project, "state", "source_snapshot.json");
  await writeFile(snapshotPath, snapshot);
  const record = { page_id: "01", status: "generated", selected_source: source, source_sha256: sha(png), file_validated_at: "2026-09-15", tool_call_id: "receipt" };
  const state = { run_id: "run", run_mode: "selected_style_expansion", status: "running", project_dir: project, source_snapshot_path: snapshotPath, source_snapshot_sha256: sha(snapshot), pages: { "01": record } };
  const statePath = path.join(project, "state", "selected_style_run_state.json");
  const save = () => writeFile(statePath, JSON.stringify(state));
  await save();
  return { root, deck, state, record, save, source };
}

test("generated state-bound image is visible and selectable before Judge, with stable UID after insertion", async t => {
  const f = await fixture(t);
  const candidates = await scanStudioCandidates(f.deck);
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].slide_uid, "new-slide");
  assert.equal(candidates[0].page_id, "P14");
  assert.equal(candidates[0].path, f.source);
  assert.equal(candidates[0].review_pending, true);
  const scanEvents = [];
  const workspace = new SelectorWorkspace({
    discovery: { readDeck: async () => f.deck },
    eventLog: { async record(type, fields) { scanEvents.push({ type, ...fields }); } },
  });
  const catalog = await workspace.refresh("deck");
  assert.equal(scanEvents[0].type, "selector_catalog_scan_completed");
  assert.ok(scanEvents[0].duration_ms >= 0);
  assert.equal(scanEvents[0].visible_slide_count, 1);
  assert.equal(scanEvents[0].unresolved_selection_page_count, 0);
  const c = catalog.pages[0].candidates[0];
  assert.equal(normalizeCandidate(c).review_pending, true);
  const response = new Writable({ write(_chunk, _encoding, done) { done(); } });
  response.writeHead = status => assert.equal(status, 200);
  const finished = once(response, "finish");
  await workspace.streamImage(response, { deckId: "deck", candidateId: c.candidate_id, sha256: c.file_sha256 });
  await finished;
  const selected = await workspace.select("deck", "new-slide", { candidate_id: c.candidate_id, selected: true });
  assert.equal(selected.pages[0].selected_count, 1);
  assert.equal((await workspace.refresh("deck")).pages[0].selected_count, 1);
  // Finishing a run can keep the same physical source; it must not lose selection.
  f.state.status = "completed";
  f.record.status = "accepted";
  f.record.final_path = f.source;
  await f.save();
  const finalized = await workspace.refresh("deck");
  assert.equal(finalized.pages[0].selected_count, 1);
  assert.equal(finalized.pages[0].candidates[0].review_pending, false);
});

test("an obsolete selected reference cannot hide a newer valid Studio selection in the outline", async t => {
  const f = await fixture(t);
  const discovery = { readDeck: async () => f.deck };
  const workspace = new SelectorWorkspace({ discovery });
  const candidate = (await workspace.refresh("deck")).pages[0].candidates[0];
  await workspace.select("deck", "new-slide", { candidate_id: candidate.candidate_id, selected: true });
  const selectionPath = studioSelectionPath(f.deck);
  const selection = JSON.parse(await readFile(selectionPath, "utf8"));
  const valid = selection.pages["new-slide"].selected_candidate_refs[0];
  const obsolete = {
    run_id: "old-run",
    handoff_path: path.join(f.root, "output", "removed-run", "state", "handoff.json"),
    native_candidate_id: "old-candidate",
  };
  selection.pages["new-slide"].selected_candidate_refs = [obsolete, valid];
  await writeFile(selectionPath, JSON.stringify(selection));

  const catalogDiagnostics = {};
  const catalog = await buildStudioCatalog(f.deck, { diagnostics: catalogDiagnostics });
  assert.equal(catalog.pages[0].selected_candidate_count, 1);
  assert.equal(catalog.pages[0].unresolved_selected_ref_count, 1);
  assert.equal(catalogDiagnostics.visible_slide_count, 1);
  assert.equal(catalogDiagnostics.unresolved_selection_page_count, 1);

  const projection = new SelectionProjection({ discovery });
  const current = await projection.get("deck", "new-slide");
  assert.equal(current.status, "selected");
  assert.equal(current.confirmed, true);
  assert.equal(current.selected_count, 1);
  assert.equal(current.selected_candidates[0].candidate_id, candidate.candidate_id);
  assert.equal(normalizeSelection(current).candidates.length, 1);

  selection.pages["new-slide"].selected_candidate_refs = [obsolete];
  await writeFile(selectionPath, JSON.stringify(selection));
  const missingDiagnostics = {};
  const missingCatalog = await buildStudioCatalog(f.deck, { diagnostics: missingDiagnostics });
  assert.equal(missingCatalog.pages[0].unresolved_selected_ref_count, 1);
  assert.equal(missingDiagnostics.unresolved_selection_page_count, 1);
  const allMissing = await projection.get("deck", "new-slide");
  assert.equal(allMissing.status, "unavailable");
  assert.equal(allMissing.selected_count, 0);
});

test("missing receipt, wrong hash, missing identity, and unrelated paths stay excluded", async t => {
  const f = await fixture(t);
  const original = { ...f.record };
  for (const patch of [{ tool_call_id: null }, { source_sha256: "f".repeat(64) }, { selected_source: path.join(f.root, "private.png") }]) {
    Object.assign(f.record, original, patch); await f.save();
    assert.equal((await scanStudioCandidates(f.deck)).length, 0);
  }
  Object.assign(f.record, original); f.deck.outline.deck_uid = "other"; await f.save();
  assert.equal((await scanStudioCandidates(f.deck)).length, 0);
});

test("deleting a pending external candidate only trashes that image, retaining shared run records", async t => {
  const f = await fixture(t);
  const workspace = new SelectorWorkspace({ discovery: { readDeck: async () => f.deck }, trashRoot: path.join(f.root, "trash"), artifactCleanupPlanner: async () => { throw new Error("must not sweep an external store"); } });
  const catalog = await workspace.refresh("deck");
  const c = catalog.pages[0].candidates[0];
  await workspace.trashCandidate("deck", c.candidate_id, { sha256: c.file_sha256, confirmed: true });
  assert.equal((await scanStudioCandidates(f.deck)).length, 0);
});
