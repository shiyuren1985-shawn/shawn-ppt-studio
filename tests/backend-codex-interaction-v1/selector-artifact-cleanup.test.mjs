import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { SelectorWorkspace } from "../../server/selector-workspace.mjs";

const CANDIDATE_ID = "c".repeat(24);

async function fixture(t, { retained = true } = {}) {
  const scratch = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-artifact-trash-")));
  t.after(() => rm(scratch, { recursive: true, force: true }));
  const outputRoot = path.join(scratch, "output");
  const projectRoot = path.join(outputRoot, "run-fast8");
  const originRoot = path.join(projectRoot, "origin_image");
  const statePath = path.join(projectRoot, "state", "style_run_state.json");
  const artifactPath = path.join(projectRoot, "style_jobs", "seat_A", "prompt.json");
  const sharedPath = path.join(projectRoot, "content_contracts", "page_P24.json");
  const unrelatedEmpty = path.join(projectRoot, "reserved", "future-output");
  const candidatePath = path.join(originRoot, "style_A_page_P24.png");
  const retainedPath = path.join(originRoot, "style_H_page_P24.png");
  await Promise.all([
    mkdir(path.dirname(statePath), { recursive: true }),
    mkdir(path.dirname(artifactPath), { recursive: true }),
    mkdir(path.dirname(sharedPath), { recursive: true }),
    mkdir(unrelatedEmpty, { recursive: true }),
    mkdir(originRoot, { recursive: true }),
  ]);
  const bytes = Buffer.from("candidate-A");
  await Promise.all([
    writeFile(candidatePath, bytes),
    writeFile(statePath, "{}"),
    writeFile(artifactPath, "{}"),
    writeFile(sharedPath, "{}"),
    ...(retained ? [writeFile(retainedPath, "candidate-H")] : []),
  ]);
  const hash = createHash("sha256").update(bytes).digest("hex");
  const discovery = {
    async readDeck() {
      return {
        deck_id: "demo",
        source_kind: "studio",
        output_root: outputRoot,
        outline: { deck_uid: "DECK_UID" },
      };
    },
  };
  const snapshot = {
    contract_version: 1,
    deck_id: "demo",
    deck_uid: "DECK_UID",
    refreshed_at: new Date().toISOString(),
    summary: {
      page_count: 1,
      included_count: 1,
      confirmed_count: 0,
      pending_count: 1,
      selected_image_count: 0,
    },
    pages: [{
      slide_uid: "SLIDE_P24",
      included: true,
      confirmed: false,
      resolution: "missing",
      selected_candidate_ids: [],
      selected_count: 0,
      baseline_available: false,
      candidates: [{
        candidate_id: CANDIDATE_ID,
        file_sha256: hash,
        selected: false,
      }],
    }],
  };
  const candidate = {
    candidate_id: CANDIDATE_ID,
    file_sha256: hash,
    path: candidatePath,
    project_root: projectRoot,
    origin_root: originRoot,
    handoff_path: statePath,
    selected_source_refs: [],
    sources: [{
      candidate_id: CANDIDATE_ID,
      file_sha256: hash,
      path: candidatePath,
      project_root: projectRoot,
      origin_root: originRoot,
      catalog_path: statePath,
    }],
  };
  return {
    scratch,
    outputRoot,
    projectRoot,
    originRoot,
    statePath,
    artifactPath,
    sharedPath,
    unrelatedEmpty,
    candidatePath,
    retainedPath,
    hash,
    discovery,
    snapshot,
    candidate,
  };
}

function seed(workspace, value) {
  workspace.snapshots.set("demo", value.snapshot);
  workspace.candidateFiles.set("demo", new Map([[CANDIDATE_ID, value.candidate]]));
}

test("partial cleanup trashes only the deleted candidate artifacts and prunes its empty folder", async (t) => {
  const value = await fixture(t);
  const trashRoot = path.join(value.scratch, "Trash");
  const workspace = new SelectorWorkspace({
    discovery: value.discovery,
    trashRoot,
    artifactCleanupPlanner: async ({ projectRoot, candidatePaths }) => ({
      candidate_artifact_cleanup_plan_version: 1,
      project_root: projectRoot,
      strategy: "partial",
      delete_candidate_paths: candidatePaths,
      retained_candidate_paths: [value.retainedPath],
      targets: [
        { path: value.candidatePath, kind: "file", reason: "candidate_image" },
        { path: value.artifactPath, kind: "file", reason: "candidate_artifact" },
      ],
      prune_roots: [projectRoot],
    }),
  });
  seed(workspace, value);

  const result = await workspace.trashCandidate("demo", CANDIDATE_ID, {
    sha256: value.hash,
    confirmed: true,
  });

  assert.equal(result.trashed_count, 1);
  assert.equal(result.trashed_artifact_count, 2);
  assert.equal(existsSync(value.candidatePath), false);
  assert.equal(existsSync(value.artifactPath), false);
  assert.equal(existsSync(path.dirname(value.artifactPath)), false);
  assert.equal(existsSync(value.retainedPath), true);
  assert.equal(existsSync(value.sharedPath), true);
  assert.equal(existsSync(value.statePath), true);
  assert.equal(existsSync(value.unrelatedEmpty), true);
});

test("unsafe cleanup target outside the run fails before anything moves", async (t) => {
  const value = await fixture(t);
  const outsidePath = path.join(value.scratch, "must-stay.txt");
  await writeFile(outsidePath, "keep");
  const workspace = new SelectorWorkspace({
    discovery: value.discovery,
    trashRoot: path.join(value.scratch, "Trash"),
    artifactCleanupPlanner: async ({ projectRoot, candidatePaths }) => ({
      candidate_artifact_cleanup_plan_version: 1,
      project_root: projectRoot,
      strategy: "partial",
      delete_candidate_paths: candidatePaths,
      retained_candidate_paths: [value.retainedPath],
      targets: [
        { path: value.candidatePath, kind: "file" },
        { path: outsidePath, kind: "file" },
      ],
    }),
  });
  seed(workspace, value);

  await assert.rejects(
    workspace.trashCandidate("demo", CANDIDATE_ID, {
      sha256: value.hash,
      confirmed: true,
    }),
    { code: "candidate_cleanup_plan_unsafe" },
  );
  assert.equal(existsSync(value.candidatePath), true);
  assert.equal(existsSync(value.artifactPath), true);
  assert.equal(existsSync(outsidePath), true);
});

test("deleting the final candidate trashes its complete run but keeps sibling runs", async (t) => {
  const value = await fixture(t, { retained: false });
  const siblingRun = path.join(value.outputRoot, "run-keep");
  await mkdir(siblingRun, { recursive: true });
  await writeFile(path.join(siblingRun, "keep.txt"), "keep");
  const workspace = new SelectorWorkspace({
    discovery: value.discovery,
    trashRoot: path.join(value.scratch, "Trash"),
    artifactCleanupPlanner: async ({ projectRoot, candidatePaths }) => ({
      candidate_artifact_cleanup_plan_version: 1,
      project_root: projectRoot,
      strategy: "whole_run",
      delete_candidate_paths: candidatePaths,
      retained_candidate_paths: [],
      targets: [{ path: projectRoot, kind: "directory", reason: "last_candidate_run" }],
    }),
  });
  seed(workspace, value);

  const result = await workspace.trashCandidate("demo", CANDIDATE_ID, {
    sha256: value.hash,
    confirmed: true,
  });

  assert.deepEqual(result.cleanup_strategies, ["whole_run"]);
  assert.equal(existsSync(value.projectRoot), false);
  assert.equal(existsSync(path.join(siblingRun, "keep.txt")), true);
});
