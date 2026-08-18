import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, realpath, rename, rm, writeFile } from "node:fs/promises";
import { Writable } from "node:stream";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { SelectorWorkspace } from "../../server/selector-workspace.mjs";
import { scanStudioCandidates } from "../../server/studio-selection-catalog.mjs";

const REPRESENTATIVE = "a".repeat(24);
const DUPLICATE = "b".repeat(24);
const IMAGE_BYTES = "same-image";
const IMAGE_HASH = createHash("sha256").update(IMAGE_BYTES).digest("hex");

function png(width, height, marker) {
  const bytes = Buffer.alloc(80);
  Buffer.from("89504e470d0a1a0a0000000d49484452", "hex").copy(bytes);
  bytes.writeUInt32BE(width, 16);
  bytes.writeUInt32BE(height, 20);
  Buffer.from(marker).copy(bytes, 24, 0, 40);
  return bytes;
}

async function jsonFile(filePath, value) {
  const bytes = Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
  await writeFile(filePath, bytes);
  return createHash("sha256").update(bytes).digest("hex");
}

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

test("historical candidates follow stable slides, deduplicate, and trash every copy", async (t) => {
  const root = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-historical-selector-")));
  t.after(() => rm(root, { recursive: true, force: true }));
  const projectRoot = path.join(root, "project");
  const outputRoot = path.join(projectRoot, "output");
  const outlinePath = path.join(projectRoot, "outline.md");
  await mkdir(outputRoot, { recursive: true });
  await writeFile(outlinePath, "fixture outline");
  const deck = {
    deck_id: "historical",
    label: "Historical",
    source_kind: "studio",
    project_root: projectRoot,
    output_root: outputRoot,
    candidate_roots: [{ id: "output", path: outputRoot }],
    outline: {
      deck_uid: "HISTORICAL_DECK",
      path: outlinePath,
      slides: [
        { page_id: "P1", page_label: "P01", order: 1, slide_uid: "SLIDE_1", title: "Opening" },
        { page_id: "P2", page_label: "P02", order: 2, slide_uid: "SLIDE_NEW", title: "Inserted case" },
        { page_id: "P3", page_label: "P03", order: 3, slide_uid: "SLIDE_CLOSING", title: "Closing statement" },
      ],
    },
  };
  const runRoot = path.join(outputRoot, "old-selected-style");
  const stateDir = path.join(runRoot, "state");
  const originDir = path.join(runRoot, "origin_image");
  const contractsDir = path.join(runRoot, "content_contracts");
  await Promise.all([
    mkdir(stateDir, { recursive: true }),
    mkdir(originDir, { recursive: true }),
    mkdir(contractsDir, { recursive: true }),
  ]);
  const imageBytes = png(1600, 900, "historical-closing");
  const imageHash = createHash("sha256").update(imageBytes).digest("hex");
  const sourcePath = path.join(originDir, "style_A_page_02.png");
  await writeFile(sourcePath, imageBytes);
  const contractPath = path.join(contractsDir, "page_02.json");
  const contractSha = await jsonFile(contractPath, { page_id: "02", title: "Closing statement" });
  const snapshotPath = path.join(stateDir, "source_snapshot.json");
  const runId = "selected-style-historical";
  const snapshotSha = await jsonFile(snapshotPath, {
    run_id: runId,
    run_mode: "selected_style_expansion",
    content_contracts: [{ path: contractPath, sha256: contractSha }],
  });
  await jsonFile(path.join(stateDir, "selected_style_run_state.json"), {
    run_id: runId,
    run_mode: "selected_style_expansion",
    status: "completed",
    project_dir: runRoot,
    source_snapshot_path: snapshotPath,
    source_snapshot_sha256: snapshotSha,
    pages: {
      "02": {
        page_id: "02",
        status: "accepted",
        final_path: sourcePath,
        source_sha256: imageHash,
        source_width: 1600,
        source_height: 900,
      },
    },
  });
  const deliveryOrigin = path.join(outputRoot, "old_deck_final_20260801", "origin_image");
  await mkdir(deliveryOrigin, { recursive: true });
  const deliveryPath = path.join(deliveryOrigin, "style_A_page_02.png");
  await writeFile(deliveryPath, imageBytes);
  const manifestSourceRoot = path.join(outputRoot, "opening-one-off-edit");
  const manifestSourceOrigin = path.join(manifestSourceRoot, "origin_image");
  await mkdir(manifestSourceOrigin, { recursive: true });
  const openingBytes = png(1600, 900, "manifest-opening");
  const manifestSourcePath = path.join(manifestSourceOrigin, "style_C_page_01.png");
  const manifestDeliveryPath = path.join(deliveryOrigin, "style_C_page_01.png");
  await mkdir(path.join(outputRoot, "old_deck_final_20260801", "state"), { recursive: true });
  await Promise.all([
    writeFile(manifestSourcePath, openingBytes),
    writeFile(manifestDeliveryPath, openingBytes),
  ]);
  await jsonFile(path.join(outputRoot, "old_deck_final_20260801", "state", "final_selection_manifest.json"), {
    manifest_version: 1,
    record_kind: "accepted_latest_page_aggregation",
    status: "complete",
    page_order: ["01"],
    base_project: manifestSourceRoot,
    overrides: {},
    explicit_resets: {},
  });
  const untrustedOrigin = path.join(outputRoot, "random-copy", "origin_image");
  await mkdir(untrustedOrigin, { recursive: true });
  await writeFile(path.join(untrustedOrigin, "style_A_page_02.png"), imageBytes);

  const diagnostics = {};
  const candidates = await scanStudioCandidates(deck, { diagnostics });
  assert.equal(candidates.length, 2);
  const opening = candidates.find((candidate) => candidate.slide_uid === "SLIDE_1");
  assert.equal(opening.catalog_kind, "manifest");
  assert.equal(opening.path, manifestSourcePath);
  assert.equal(opening.duplicate_source_count, 2);
  assert.deepEqual(
    opening.duplicate_sources.map((item) => item.path).sort(),
    [manifestSourcePath, manifestDeliveryPath].sort(),
  );
  const closing = candidates.find((candidate) => candidate.slide_uid === "SLIDE_CLOSING");
  assert.equal(closing.page_id, "P3");
  assert.equal(closing.duplicate_source_count, 2);
  assert.deepEqual(
    closing.duplicate_sources.map((item) => item.path).sort(),
    [sourcePath, deliveryPath].sort(),
  );
  assert.equal(diagnostics.duplicate_source_count, 2);
  assert.equal(diagnostics.manifest_runs, 1);

  const discovery = { async readDeck() { return deck; } };
  const workspace = new SelectorWorkspace({ discovery, trashRoot: path.join(root, "Trash") });
  const catalog = await workspace.refresh(deck.deck_id);
  const candidate = catalog.pages.find((page) => page.slide_uid === "SLIDE_CLOSING").candidates[0];
  await workspace.select(deck.deck_id, "SLIDE_CLOSING", {
    candidate_id: candidate.candidate_id,
    selected: true,
  });
  const deleted = await workspace.trashCandidate(deck.deck_id, candidate.candidate_id, {
    sha256: candidate.file_sha256,
    confirmed: true,
  });
  assert.equal(deleted.trashed_count, 2);
  await assert.rejects(() => readFile(sourcePath), { code: "ENOENT" });
  await assert.rejects(() => readFile(deliveryPath), { code: "ENOENT" });
});

test("identity-less historical Fast8 follows its frozen title instead of a reused page number", async (t) => {
  const root = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-historical-title-selector-")));
  t.after(() => rm(root, { recursive: true, force: true }));
  const projectRoot = path.join(root, "project");
  const outputRoot = path.join(projectRoot, "output");
  const outlinePath = path.join(projectRoot, "outline.md");
  const runRoot = path.join(outputRoot, "old-fast8-page-11");
  const stateDir = path.join(runRoot, "state");
  const inputsDir = path.join(stateDir, "director_inputs");
  const originDir = path.join(runRoot, "origin_image");
  await Promise.all([
    mkdir(inputsDir, { recursive: true }),
    mkdir(originDir, { recursive: true }),
  ]);
  await writeFile(outlinePath, "fixture outline");
  const deck = {
    output_root: outputRoot,
    outline: {
      deck_uid: "HISTORICAL_DECK",
      path: outlinePath,
      slides: [
        { page_id: "P11", page_label: "P11", order: 11, slide_uid: "CURRENT_P11", title: "Current proposal page" },
        { page_id: "P26", page_label: "P26", order: 26, slide_uid: "E_HOUSE", title: "Is putting equipment in a building an E-House?" },
      ],
    },
  };
  const runId = "legacy-fast8-page-11";
  const sourcePath = path.join(originDir, "style_A_page_P11.png");
  const imageBytes = png(1600, 900, "legacy-e-house");
  const imageHash = createHash("sha256").update(imageBytes).digest("hex");
  await writeFile(sourcePath, imageBytes);
  const contractPath = path.join(inputsDir, "content_contract.json");
  const contractSha = await jsonFile(contractPath, {
    page_id: "P11",
    display_required: ["Is putting equipment in a building an E-House?"],
  });
  const packetPath = path.join(inputsDir, "authoritative_page_packet.md");
  const packetBytes = Buffer.from([
    "# Frozen page packet",
    "| Page | Title | Thesis |",
    "|---|---|---|",
    "| P11 | Is putting equipment in a building an E-House? | Historical content |",
    "",
  ].join("\n"));
  await writeFile(packetPath, packetBytes);
  const snapshotPath = path.join(stateDir, "source_snapshot.json");
  const snapshotSha = await jsonFile(snapshotPath, {
    run_id: runId,
    run_mode: "fast_8x1_diverse",
    page_ids: ["P11"],
    authoritative_source: {
      path: packetPath,
      sha256: createHash("sha256").update(packetBytes).digest("hex"),
    },
    content_contracts: [{ path: contractPath, sha256: contractSha }],
  });
  await jsonFile(path.join(stateDir, "style_run_state.json"), {
    run_id: runId,
    run_mode: "fast_8x1_diverse",
    status: "completed",
    project_dir: runRoot,
    source_snapshot_path: snapshotPath,
    source_snapshot_sha256: snapshotSha,
    anchor_page_id: "P11",
    styles: {
      A: {
        pages: {
          P11: {
            status: "candidate_ready",
            final_path: sourcePath,
            source_sha256: imageHash,
            source_width: 1600,
            source_height: 900,
          },
        },
      },
    },
  });

  const candidates = await scanStudioCandidates(deck);
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].source_page_id, "P11");
  assert.equal(candidates[0].page_id, "P26");
  assert.equal(candidates[0].slide_uid, "E_HOUSE");
});

test("historical identity-bound candidates remain valid after an authoritative outline path migration", async (t) => {
  const root = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-outline-alias-")));
  t.after(() => rm(root, { recursive: true, force: true }));
  const outputRoot = path.join(root, "output");
  const runRoot = path.join(outputRoot, "identity-run");
  const stateDir = path.join(runRoot, "state");
  const originDir = path.join(runRoot, "origin_image");
  await Promise.all([
    mkdir(stateDir, { recursive: true }),
    mkdir(originDir, { recursive: true }),
  ]);
  const oldOutlinePath = path.join(root, "old-outline.md");
  const newOutlinePath = path.join(root, "bilingual-outline.md");
  const deck = {
    deck_id: "outline-alias",
    label: "Outline alias",
    source_kind: "studio",
    project_root: root,
    output_root: outputRoot,
    candidate_roots: [{ id: "output", path: outputRoot }],
    outline: {
      deck_uid: "DECK_ALIAS",
      path: newOutlinePath,
      identity_aliases: [oldOutlinePath],
      slides: [{ page_id: "P1", page_label: "P01", order: 1, slide_uid: "SLIDE_STABLE", title: "双语标题" }],
    },
  };
  const imageBytes = png(1600, 900, "identity-alias");
  const imageHash = createHash("sha256").update(imageBytes).digest("hex");
  const imagePath = path.join(originDir, "style_A_page_01.png");
  await writeFile(imagePath, imageBytes);
  const runId = "identity-alias-run";
  const snapshotPath = path.join(stateDir, "source_snapshot.json");
  const snapshotSha = await jsonFile(snapshotPath, {
    run_id: runId,
    run_mode: "selected_style_expansion",
    slide_identity: {
      required: true,
      deck_uid: "DECK_ALIAS",
      source_path: oldOutlinePath,
      slide_uids: { P1: "SLIDE_STABLE" },
    },
  });
  await jsonFile(path.join(stateDir, "selected_style_run_state.json"), {
    run_id: runId,
    run_mode: "selected_style_expansion",
    status: "completed",
    project_dir: runRoot,
    source_snapshot_path: snapshotPath,
    source_snapshot_sha256: snapshotSha,
    pages: {
      "01": {
        page_id: "01",
        status: "accepted",
        final_path: imagePath,
        source_sha256: imageHash,
        source_width: 1600,
        source_height: 900,
      },
    },
  });

  const candidates = await scanStudioCandidates(deck);
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].slide_uid, "SLIDE_STABLE");
  assert.equal(candidates[0].path, imagePath);
});
