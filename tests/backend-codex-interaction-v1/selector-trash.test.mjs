import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { SelectorWorkspace } from "../../server/selector-workspace.mjs";

const REPRESENTATIVE = "a".repeat(24);
const DUPLICATE = "b".repeat(24);
const IMAGE_BYTES = "same-image";
const IMAGE_HASH = createHash("sha256").update(IMAGE_BYTES).digest("hex");

test("one confirmed delete clears selection and trashes every source behind a deduplicated card", async (t) => {
  const scratch = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-selector-group-trash-")));
  const candidateRoot = path.join(scratch, "candidates");
  const trashRoot = path.join(scratch, "Trash");
  await mkdir(candidateRoot, { recursive: true });
  const representativePath = path.join(candidateRoot, "representative.png");
  const duplicatePath = path.join(candidateRoot, "duplicate.png");
  await Promise.all([
    writeFile(representativePath, IMAGE_BYTES),
    writeFile(duplicatePath, IMAGE_BYTES),
  ]);
  t.after(() => rm(scratch, { recursive: true, force: true }));

  let selected = true;
  let deselectCount = 0;
  const catalog = () => ({
    catalog_contract_version: 4,
    deck_label: "测试 PPT",
    deck_uid: "DECK_UID",
    pages: [{
      page_id: "P1",
      page_label: "P01",
      order: 1,
      slide_uid: "SLIDE_1",
      title: "第一页",
      included: true,
      confirmed: selected,
      resolution: selected ? "selected" : "missing",
      selected_candidate_ids: selected ? [REPRESENTATIVE] : [],
      baseline_candidate_id: null,
      candidates: existsSync(representativePath) ? [{
        candidate_id: REPRESENTATIVE,
        file_sha256: IMAGE_HASH,
        path: representativePath,
        duplicate_source_count: 2,
        duplicate_sources: [
          { candidate_id: REPRESENTATIVE, path: representativePath },
          { candidate_id: DUPLICATE, path: duplicatePath },
        ],
      }] : [],
    }],
  });
  const fetchImpl = async (target, init = {}) => {
    const url = new URL(target);
    if (init.method === "POST" && url.pathname === "/api/select") {
      const body = JSON.parse(init.body);
      assert.equal(body.candidate_id, REPRESENTATIVE);
      assert.equal(body.selected, false);
      selected = false;
      deselectCount += 1;
      return Response.json(catalog());
    }
    if ((!init.method || init.method === "GET") && url.pathname === "/api/catalog") {
      return Response.json(catalog());
    }
    return Response.json({ error: "not found" }, { status: 404 });
  };
  const discovery = {
    async readDeck() {
      return {
        deck_id: "demo",
        source_kind: "legacy",
        config_path: path.join(scratch, "config.json"),
        candidate_roots: [{ id: "fixture", path: candidateRoot }],
        outline: { deck_uid: "DECK_UID" },
      };
    },
  };
  const workspace = new SelectorWorkspace({ discovery, fetchImpl, trashRoot });
  await workspace.refresh("demo");
  const result = await workspace.trashCandidate("demo", REPRESENTATIVE, {
    sha256: IMAGE_HASH,
    confirmed: true,
  });

  assert.equal(deselectCount, 1);
  assert.equal(result.deleted, true);
  assert.equal(result.trashed_count, 2);
  assert.equal(existsSync(representativePath), false);
  assert.equal(existsSync(duplicatePath), false);
  assert.equal(await readFile(path.join(trashRoot, "representative.png"), "utf8"), IMAGE_BYTES);
  assert.equal(await readFile(path.join(trashRoot, "duplicate.png"), "utf8"), IMAGE_BYTES);
  assert.equal(result.catalog.pages[0].candidates.length, 0);
});
