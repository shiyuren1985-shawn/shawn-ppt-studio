import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { resolveEditCandidateForTurn } from "../../server/http-server.mjs";
import { SelectorWorkspace } from "../../server/selector-workspace.mjs";

test("a selector edit binds the exact retained candidate without changing selection", async () => {
  const root = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), "studio-edit-candidate-")));
  const outputRoot = path.join(root, "output");
  const imagePath = path.join(outputRoot, "P07", "candidate.png");
  const content = Buffer.from("candidate image bytes");
  const sha256 = createHash("sha256").update(content).digest("hex");
  const candidateId = "a".repeat(24);
  await fs.mkdir(path.dirname(imagePath), { recursive: true });
  await fs.writeFile(imagePath, content);
  const deck = {
    deck_id: "deck-1",
    source_kind: "studio",
    output_root: outputRoot,
    outline: { slides: [{ slide_uid: "SLIDE_7" }, { slide_uid: "SLIDE_8" }] },
  };
  const workspace = new SelectorWorkspace({ discovery: { readDeck: async () => deck } });
  const page = {
    slide_uid: "SLIDE_7",
    selected_candidate_ids: [],
    candidates: [{ candidate_id: candidateId, file_sha256: sha256 }],
  };
  workspace.snapshots.set(deck.deck_id, { pages: [page] });
  workspace.candidateFiles.set(deck.deck_id, new Map([[candidateId, {
    path: imagePath,
    file_sha256: sha256,
    run_id: "RUN_7",
    handoff_path: path.join(outputRoot, "P07", "handoff.json"),
    native_candidate_id: "P07-A",
  }]]));
  try {
    const request = { edit_candidate: { slide_uid: "SLIDE_7", candidate_id: candidateId, sha256 } };
    const resolved = await resolveEditCandidateForTurn({ selectorWorkspace: workspace }, deck, request);
    assert.deepEqual(resolved, {
      slide_uid: "SLIDE_7", selector_candidate_id: candidateId,
      parent_candidate_id: "P07-A", parent_handoff_path: path.join(outputRoot, "P07", "handoff.json"),
      source_run_id: "RUN_7", file_sha256: sha256, path: imagePath,
    });
    assert.deepEqual(page.selected_candidate_ids, [], "opening the edit composer never selects the source image");
    const source = workspace.candidateFiles.get(deck.deck_id).get(candidateId);
    source.native_candidate_id = null;
    await assert.rejects(
      workspace.resolveEditCandidate(deck.deck_id, request.edit_candidate),
      { code: "edit_parent_not_ready" },
    );
    source.native_candidate_id = "P07-A";
    await assert.rejects(
      workspace.resolveEditCandidate(deck.deck_id, { ...request.edit_candidate, slide_uid: "SLIDE_8" }),
      { code: "candidate_image_not_found" },
    );
    await assert.rejects(
      workspace.resolveEditCandidate(deck.deck_id, { ...request.edit_candidate, sha256: "b".repeat(64) }),
      { code: "candidate_image_not_found" },
    );
    await fs.writeFile(imagePath, "changed image bytes");
    await assert.rejects(
      workspace.resolveEditCandidate(deck.deck_id, request.edit_candidate),
      { code: "candidate_image_not_found" },
    );
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
