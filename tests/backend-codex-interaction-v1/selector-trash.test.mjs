import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, realpath, rename, rm, writeFile } from "node:fs/promises";
import { Writable } from "node:stream";
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
  let catalogReadCount = 0;
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
      catalogReadCount += 1;
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
  assert.equal(catalogReadCount, 1);
  assert.equal(result.deleted, true);
  assert.equal(result.trashed_count, 2);
  assert.equal(existsSync(representativePath), false);
  assert.equal(existsSync(duplicatePath), false);
  assert.equal(await readFile(path.join(trashRoot, "representative.png"), "utf8"), IMAGE_BYTES);
  assert.equal(await readFile(path.join(trashRoot, "duplicate.png"), "utf8"), IMAGE_BYTES);
  assert.equal(result.catalog.pages[0].candidates.length, 0);
});

test("an image already handed to the webview keeps streaming after its path moves to Trash", async (t) => {
  const scratch = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-selector-stream-race-")));
  const outputRoot = path.join(scratch, "output");
  const candidateRoot = path.join(outputRoot, "run", "origin_image");
  await mkdir(candidateRoot, { recursive: true });
  const sourcePath = path.join(candidateRoot, "candidate.png");
  const movedPath = path.join(scratch, "candidate.png");
  const imageBytes = Buffer.alloc(4 * 1024 * 1024, 0x5a);
  await writeFile(sourcePath, imageBytes);
  const fileSha256 = createHash("sha256").update(imageBytes).digest("hex");
  t.after(() => rm(scratch, { recursive: true, force: true }));

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
  const workspace = new SelectorWorkspace({ discovery });
  workspace.snapshots.set("demo", {
    pages: [{
      slide_uid: "SLIDE_1",
      candidates: [{ candidate_id: REPRESENTATIVE, file_sha256: fileSha256 }],
    }],
  });
  workspace.candidateFiles.set("demo", new Map([[
    REPRESENTATIVE,
    { candidate_id: REPRESENTATIVE, file_sha256: fileSha256, path: sourcePath },
  ]]));

  const received = [];
  const response = new Writable({
    highWaterMark: 1024,
    write(chunk, _encoding, callback) {
      received.push(Buffer.from(chunk));
      setTimeout(callback, 1);
    },
  });
  response.headersSent = false;
  response.writeHead = (_status, headers) => {
    response.headersSent = true;
    response.headers = headers;
  };

  const finished = new Promise((resolve, reject) => {
    response.once("finish", resolve);
    response.once("error", reject);
  });
  await workspace.streamImage(response, {
    deckId: "demo",
    candidateId: REPRESENTATIVE,
    sha256: fileSha256,
  });
  await rename(sourcePath, movedPath);
  await finished;

  assert.equal(response.headers["content-length"], imageBytes.length);
  assert.deepEqual(Buffer.concat(received), imageBytes);
});
