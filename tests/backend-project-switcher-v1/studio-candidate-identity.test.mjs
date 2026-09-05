import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { scanStudioCandidates, resolveStudioSelection } from "../../server/studio-selection-catalog.mjs";
import { StudioSelectionStore } from "../../server/studio-selection-store.mjs";

const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");

async function fixture(t, { handoff = true } = {}) {
  const root = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-candidate-identity-")));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const run = path.join(output, "fixture-run");
  const stateDir = path.join(run, "state");
  const imagePath = path.join(run, "origin_image", "page_P02.png");
  await mkdir(stateDir, { recursive: true });
  await mkdir(path.dirname(imagePath), { recursive: true });
  // The metadata reader only needs an image header; this is never rendered.
  const image = Buffer.alloc(24);
  Buffer.from("89504e470d0a1a0a", "hex").copy(image);
  image.writeUInt32BE(1600, 16);
  image.writeUInt32BE(900, 20);
  await writeFile(imagePath, image);
  const deck = {
    project_root: root,
    output_root: output,
    outline: {
      deck_uid: "DECK",
      path: path.join(root, "outline.md"),
      slides: [
        { page_id: "P1", page_label: "P01", slide_uid: "FIRST", title: "First" },
        { page_id: "P2", page_label: "P02", slide_uid: "SECOND", title: "Second" },
      ],
    },
  };
  const identity = { required: true, deck_uid: "DECK", source_path: deck.outline.path, slide_uids: { P2: "SECOND" } };
  const snapshotPath = path.join(stateDir, "source_snapshot.json");
  const snapshot = JSON.stringify({ run_id: "run", run_mode: "fast_8x1_diverse", page_ids: ["P2"], slide_identity: identity });
  await writeFile(snapshotPath, snapshot);
  const statePath = path.join(stateDir, "style_run_state.json");
  const state = JSON.stringify({
    run_id: "run", run_mode: "fast_8x1_diverse", status: "completed", project_dir: run,
    source_snapshot_path: snapshotPath, source_snapshot_sha256: digest(snapshot), anchor_page_id: "P2",
    styles: { A: { pages: { P2: {
      status: "candidate_ready", candidate_id: "A-P2", final_path: imagePath,
      source_sha256: digest(image), source_width: 1600, source_height: 900,
    } } } },
  });
  await writeFile(statePath, state);
  const handoffPath = path.join(stateDir, "handoff.json");
  const writeHandoff = () => writeFile(handoffPath, JSON.stringify({
    run_id: "run", run_mode: "fast_8x1_diverse", pipeline_status: "completed", status: "candidate_ready",
    project_dir: run, slide_identity: identity,
    state_ref: { path: statePath, sha256: digest(state) },
    source_snapshot_ref: { path: snapshotPath, sha256: digest(snapshot) },
    candidates: [{
      candidate_id: "A-P2", deck_uid: "DECK", slide_uid: "SECOND", page_id: "P2", status: "candidate_ready",
      path: imagePath, sha256: digest(image), width: 1600, height: 900,
    }],
  }));
  if (handoff) await writeHandoff();
  return { deck, imagePath, writeHandoff, statePath, handoffPath };
}

for (const handoff of [true, false]) {
  test(`${handoff ? "handoff" : "historical state"} candidate follows its stable UID after page deletion and renumbering`, async (t) => {
    const { deck } = await fixture(t, { handoff });
    const original = await scanStudioCandidates(deck);
    assert.equal(original.length, 1);
    await new StudioSelectionStore().setCandidate(deck, "SECOND", original[0].selection_ref, true);
    deck.outline.slides = [{ ...deck.outline.slides[1], page_id: "P1", page_label: "P01" }];
    const renumbered = await scanStudioCandidates(deck);
    assert.equal(renumbered.length, 1, "a page-number change must not discard a verified stable-UID candidate");
    assert.equal(renumbered[0].slide_uid, "SECOND");
    assert.equal(renumbered[0].page_id, "P1");
    assert.equal(renumbered[0].source_page_id, "P2");
    const selected = await resolveStudioSelection(deck, "SECOND");
    assert.equal(selected.stale, false);
    assert.equal(selected.candidates.length, 1);
    deck.outline.slides = [{ page_id: "P2", slide_uid: "REPLACEMENT", title: "Second" }];
    assert.equal((await scanStudioCandidates(deck)).length, 0, "a reused page number or title must not acquire the removed UID's candidate");
  });
}

test("publishing a handoff retains selection refs created from the same file's completed state", async (t) => {
  const { deck, writeHandoff, statePath } = await fixture(t, { handoff: false });
  const [candidate] = await scanStudioCandidates(deck);
  assert.equal(candidate.selection_ref.handoff_path, statePath);
  await new StudioSelectionStore().setCandidate(deck, "SECOND", candidate.selection_ref, true);
  await writeHandoff();
  const selected = await resolveStudioSelection(deck, "SECOND");
  assert.equal(selected.stale, false, "the catalog source upgrade must not invalidate a prior selection of identical bytes");
  assert.equal(selected.candidates.length, 1);
  assert.equal(selected.candidates[0].duplicate_source_count, 1, "state and handoff references must not inflate the number of physical copies");
});
