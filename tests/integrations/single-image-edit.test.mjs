import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, realpath, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import zlib from "node:zlib";

import {
  CODEX_GENERATED_IMAGES_ROOT,
  DEFAULT_MONITORING_ROOT,
  SINGLE_IMAGE_EDIT_CONTROL_PLANE,
  SINGLE_IMAGE_EDIT_HOST_FINALIZE_STATUS,
  SINGLE_IMAGE_EDIT_ORCHESTRATION_CONTRACT,
  SingleImageEditContractError,
  buildSingleImageEditAppServerTurn,
  buildSingleImageEditHostFinalizePlan,
  compileSingleImageEditRequest,
  loadAndCompileSingleImageEditRequest,
  parseSingleImageEditNativeRefs,
  verifySingleImageEditNativeRefs,
} from "../../integrations/single-image-edit.mjs";
import { STUDIO_APP_SERVER_TRANSPORT } from "../../integrations/shawn-single-page.mjs";


const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");

test("single-image edit adapter never embeds the legacy Lab root", async () => {
  const source = await readFile(
    new URL("../../integrations/single-image-edit.mjs", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(source, /\/Users\/shawn\/AI\/Image-PPT\/ppt-ai-lab/);
});

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let index = 0; index < 8; index += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const name = Buffer.from(type, "ascii");
  const size = Buffer.alloc(4);
  size.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([name, data])));
  return Buffer.concat([size, name, data, checksum]);
}

function png(width, height, rgb) {
  const signature = Buffer.from("89504e470d0a1a0a", "hex");
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr.set([8, 2, 0, 0, 0], 8);
  // Avoid material fixture size: repeat a correctly sized constant scanline.
  const scanline = Buffer.concat([Buffer.from([0]), Buffer.alloc(width * 3)]);
  for (let index = 0; index < width; index += 1) {
    scanline[1 + index * 3] = rgb[0];
    scanline[2 + index * 3] = rgb[1];
    scanline[3 + index * 3] = rgb[2];
  }
  return Buffer.concat([
    signature,
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(Buffer.concat(Array(height).fill(scanline)), { level: 1 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

async function jsonFile(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const bytes = Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
  await writeFile(filePath, bytes);
  return hash(bytes);
}

async function fixture(t) {
  const root = await realpath(await mkdtemp(path.join(os.tmpdir(), "ppt-single-image-edit-")));
  t.after(() => rm(root, { recursive: true, force: true }));
  const candidateRoot = path.join(root, "output");
  await mkdir(candidateRoot);
  const outlinePath = path.join(root, "outline.md");
  const outline = [
    "---",
    "deck_uid: EPC_DECK",
    "slide_identity_required: true",
    "slide_uids:",
    "  P05: EPC_SLIDE_5",
    "---",
    "| P05 | Test | Test | Low | Test | Open |",
    "",
  ].join("\n");
  await writeFile(outlinePath, outline);
  const outlineSha = hash(Buffer.from(outline));
  const parentProject = path.join(candidateRoot, "P05_parent");
  const parentStatePath = path.join(parentProject, "state", "style_run_state.json");
  const parentSnapshotPath = path.join(parentProject, "state", "source_snapshot.json");
  const parentPath = path.join(parentProject, "origin_image", "style_A_page_P05.png");
  await mkdir(path.dirname(parentPath), { recursive: true });
  const parentBytes = png(1200, 675, [20, 30, 40]);
  await writeFile(parentPath, parentBytes);
  const stateSha = await jsonFile(parentStatePath, { run_id: "fast8-parent", status: "completed" });
  const snapshotSha = await jsonFile(parentSnapshotPath, { run_id: "fast8-parent" });
  const parentHandoffPath = path.join(parentProject, "state", "handoff.json");
  const parentHandoff = {
    handoff_contract_version: 1,
    run_id: "fast8-parent",
    run_mode: "fast_8x1_diverse",
    project_dir: parentProject,
    pipeline_status: "completed",
    status: "candidate_ready",
    state_ref: { path: parentStatePath, sha256: stateSha },
    source_snapshot_ref: { path: parentSnapshotPath, sha256: snapshotSha },
    slide_identity: {
      required: true,
      deck_uid: "EPC_DECK",
      slide_uids: { P05: "EPC_SLIDE_5" },
      source_path: outlinePath,
      source_sha256: outlineSha,
    },
    candidates: [{
      candidate_id: "A-P05",
      style_slot: "A",
      page_id: "P05",
      path: parentPath,
      sha256: hash(parentBytes),
      width: 1200,
      height: 675,
      status: "candidate_ready",
      deck_uid: "EPC_DECK",
      slide_uid: "EPC_SLIDE_5",
    }],
    user_selection: { selected: false },
  };
  const parentHandoffSha = await jsonFile(parentHandoffPath, parentHandoff);
  const input = {
    deck_uid: "EPC_DECK",
    slide_uid: "EPC_SLIDE_5",
    outline_path: outlinePath,
    expected_revision: `sha256:${outlineSha}`,
    user_request: "只把主视觉强调色改为暖橙，其他内容保持不变。",
    parent: { handoff_path: parentHandoffPath, candidate_id: "A-P05" },
  };
  const context = {
    candidate_root: candidateRoot,
    approved_candidate_roots: [candidateRoot],
    request_started_at: "2026-08-12T14:00:00.000Z",
  };
  return {
    root,
    candidateRoot,
    outline,
    outlineSha,
    outlinePath,
    parentHandoff,
    parentHandoffPath,
    parentHandoffSha,
    parentStatePath,
    parentSnapshotPath,
    parentPath,
    parentBytes,
    stateSha,
    snapshotSha,
    input,
    context,
  };
}

function directInput(data, overrides = {}) {
  return {
    deck_uid: data.input.deck_uid,
    slide_uid: data.input.slide_uid,
    outline_path: data.input.outline_path,
    expected_revision: data.input.expected_revision,
    user_request: data.input.user_request,
    direct_parent_refs: {
      deck_uid: data.input.deck_uid,
      slide_uid: data.input.slide_uid,
      candidate_id: "legacy-confirmed-P05",
      path: data.parentPath,
      sha256: hash(data.parentBytes),
      width: 1200,
      height: 675,
      source_revision_status: "unrecorded",
      ...overrides,
    },
  };
}

test("loadAndCompile binds current outline, verified parent handoff, and deterministic execute", async (t) => {
  const data = await fixture(t);
  const compiled = await loadAndCompileSingleImageEditRequest(data.input, data.context);
  assert.equal(compiled.identity.page_id, "P05");
  assert.equal(compiled.parent.candidate_id, "A-P05");
  assert.equal(compiled.parent.source_run_id, "fast8-parent");
  assert.equal(compiled.parent.handoff_sha256, data.parentHandoffSha);
  assert.equal(compiled.request.user_request_sha256, hash(Buffer.from(data.input.user_request)));
  assert.match(compiled.request.execute_key, /^[0-9a-f]{64}$/);
  assert.equal(compiled.runtime.candidate_root, data.candidateRoot);
  assert.ok(compiled.runtime.project_dir.startsWith(`${data.candidateRoot}${path.sep}`));
  assert.equal(compiled.runtime.control_plane_path, SINGLE_IMAGE_EDIT_CONTROL_PLANE);
  assert.equal(compiled.transport, STUDIO_APP_SERVER_TRANSPORT);
});

test("App Server turn uses candidate root, one local parent, imagegen, and no output schema", async (t) => {
  const data = await fixture(t);
  const compiled = await loadAndCompileSingleImageEditRequest(data.input, data.context);
  const turn = buildSingleImageEditAppServerTurn(compiled, { thread_id: "thread-edit-1" });
  assert.equal(turn.cwd, data.candidateRoot);
  assert.deepEqual(turn.sandboxPolicy.writableRoots, [
    data.candidateRoot,
    DEFAULT_MONITORING_ROOT,
  ]);
  assert.equal(turn.outputSchema, undefined);
  assert.deepEqual(turn.additionalContext, {
    shawn_ppt_studio_transport: {
      kind: "application",
      value: "transport=studio_app_server_v1",
    },
  });
  assert.deepEqual(
    turn.input.filter((item) => item.type === "localImage").map((item) => item.path),
    [data.parentPath],
  );
  assert.deepEqual(
    turn.input.filter((item) => item.type === "skill").map((item) => item.name),
    ["imagegen", "shawn-ppt-image"],
  );
  const prompt = turn.input[0].text;
  assert.match(prompt, /transport=studio_app_server_v1/);
  assert.match(prompt, /root turn is the one and only mechanical single-image-edit executor/);
  assert.match(prompt, /Do not spawn an image-execution child Agent or any per-image worker/);
  assert.match(prompt, /prepare -> claim -> ImageGen once -> complete\/release/);
  assert.match(prompt, /single_image_edit_control_plane_v1\.py' prepare/);
  assert.match(prompt, /claim --state/);
  assert.match(prompt, /shared central ImageGen cap5/);
  assert.match(prompt, /release --state/);
  assert.match(prompt, /call \$imagegen exactly once/);
  assert.match(prompt, /do not change selection/i);
  assert.match(prompt, /completed but its savedPath is not visible to you, DO NOT guess a path and DO NOT run release/);
  assert.match(prompt, new RegExp(SINGLE_IMAGE_EDIT_HOST_FINALIZE_STATUS));
  assert.match(prompt, /release command only if imageGeneration explicitly failed or was cancelled and there is no completed/);
  assert.match(prompt, /Do not call generatedImage\(\.\.\.\), image\(\.\.\.\), open the result/);
  assert.doesNotMatch(prompt, /turn cannot call complete, run/);
  assert.throws(
    () => buildSingleImageEditAppServerTurn({ ...compiled, transport: "other" }, { thread_id: "forged" }),
    (error) => error instanceof SingleImageEditContractError && error.code === "invalid_compiled_request",
  );
});

test("Studio single-image edit root keeps canonical claim and terminal ordering", () => {
  const completed = SINGLE_IMAGE_EDIT_ORCHESTRATION_CONTRACT.success_sequence;
  const failed = SINGLE_IMAGE_EDIT_ORCHESTRATION_CONTRACT.failure_sequence;
  assert.equal(SINGLE_IMAGE_EDIT_ORCHESTRATION_CONTRACT.transport, STUDIO_APP_SERVER_TRANSPORT);
  assert.equal(SINGLE_IMAGE_EDIT_ORCHESTRATION_CONTRACT.executor_location, "root_turn");
  assert.equal(SINGLE_IMAGE_EDIT_ORCHESTRATION_CONTRACT.child_executor_count, 0);
  assert.equal(SINGLE_IMAGE_EDIT_ORCHESTRATION_CONTRACT.slot_registry, "existing_central_cap5");
  assert.ok(completed.indexOf("claim") < completed.indexOf("imagegen"));
  assert.ok(failed.indexOf("claim") < failed.indexOf("imagegen_failed"));
  assert.equal(completed.includes("release"), false);
  assert.equal(failed.includes("complete"), false);
});

test("host finalize plan uses only canonical complete, conditional reclaim, and release", async (t) => {
  const data = await fixture(t);
  const compiled = await loadAndCompileSingleImageEditRequest(directInput(data), data.context);
  const savedPath = path.join(CODEX_GENERATED_IMAGES_ROOT, "host-visible-edit.png");
  const plan = buildSingleImageEditHostFinalizePlan(compiled, { saved_path: savedPath });
  assert.equal(plan.contract_version, 1);
  assert.equal(plan.kind, "single_image_edit_host_finalize");
  assert.equal(plan.recover_only_if_error_code, "imagegen_slot_not_claimed");
  assert.deepEqual(plan.attempt_complete, {
    command: "python3",
    args: [
      SINGLE_IMAGE_EDIT_CONTROL_PLANE,
      "complete",
      "--state",
      compiled.runtime.state_path,
      "--saved-path",
      savedPath,
    ],
  });
  assert.deepEqual(plan.recovery_commands, [
    {
      command: "python3",
      args: [
        SINGLE_IMAGE_EDIT_CONTROL_PLANE,
        "claim",
        "--state",
        compiled.runtime.state_path,
        "--wait-seconds",
        "600",
      ],
    },
    plan.attempt_complete,
  ]);
  assert.deepEqual(plan.release_on_failure, {
    command: "python3",
    args: [
      SINGLE_IMAGE_EDIT_CONTROL_PLANE,
      "release",
      "--state",
      compiled.runtime.state_path,
    ],
  });
  assert.throws(
    () => buildSingleImageEditHostFinalizePlan(compiled, { saved_path: "/tmp/forged.png" }),
    (error) => error instanceof SingleImageEditContractError && error.code === "invalid_saved_path",
  );
});

test("confirmed direct parent compiles without inventing a handoff or source revision", async (t) => {
  const data = await fixture(t);
  const compiled = await loadAndCompileSingleImageEditRequest(directInput(data), data.context);
  assert.deepEqual(compiled.parent, {
    candidate_id: "legacy-confirmed-P05",
    path: data.parentPath,
    sha256: hash(data.parentBytes),
    width: 1200,
    height: 675,
    source_kind: "direct_selection",
    source_revision_status: "unrecorded",
    source_run_id: null,
    handoff_path: null,
    handoff_sha256: null,
  });
  const turn = buildSingleImageEditAppServerTurn(compiled, { thread_id: "thread-direct-edit" });
  assert.deepEqual(turn.input.filter((item) => item.type === "localImage"), [
    { type: "localImage", path: data.parentPath },
  ]);
  assert.match(turn.input[0].text, /--direct-parent-refs-json/);
  assert.doesNotMatch(turn.input[0].text, /--parent-handoff-path/);
});

test("direct parent rejects changed bytes, symlinks, and forged identity", async (t) => {
  const data = await fixture(t);
  const stale = directInput(data);
  await writeFile(data.parentPath, png(1200, 675, [250, 1, 1]));
  await assert.rejects(
    () => loadAndCompileSingleImageEditRequest(stale, data.context),
    (error) => error instanceof SingleImageEditContractError && error.code === "parent_candidate_unverified",
  );

  const realPath = path.join(data.root, "legacy-real.png");
  const linkPath = path.join(data.root, "legacy-link.png");
  const realBytes = png(1200, 675, [20, 30, 40]);
  await writeFile(realPath, realBytes);
  const { symlink } = await import("node:fs/promises");
  await symlink(realPath, linkPath);
  await assert.rejects(
    () =>
      loadAndCompileSingleImageEditRequest(
        directInput(data, { path: linkPath, sha256: hash(realBytes) }),
        data.context,
      ),
    (error) => error instanceof SingleImageEditContractError && error.code === "invalid_file",
  );

  await assert.rejects(
    () =>
      loadAndCompileSingleImageEditRequest(
        directInput(data, { deck_uid: "OTHER_DECK" }),
        data.context,
      ),
    (error) => error instanceof SingleImageEditContractError && error.code === "parent_identity_mismatch",
  );
});

test("pure compile rejects unapproved root and forged parent evidence", async (t) => {
  const data = await fixture(t);
  const context = {
    ...data.context,
    outline_markdown: data.outline,
    outline_sha256: data.outlineSha,
    parent_handoff: data.parentHandoff,
    parent_verification: {
      handoff_real_path: data.parentHandoffPath,
      handoff_sha256: data.parentHandoffSha,
      state_sha256: data.stateSha,
      snapshot_sha256: data.snapshotSha,
      candidate_real_path: data.parentPath,
      candidate_sha256: hash(data.parentBytes),
      candidate_is_regular: true,
      candidate_dimensions: { width: 1200, height: 675 },
    },
  };
  assert.throws(
    () => compileSingleImageEditRequest(data.input, {
      ...context,
      approved_candidate_roots: [path.join(data.root, "other")],
    }),
    (error) => error instanceof SingleImageEditContractError && error.code === "candidate_root_not_approved",
  );
  assert.throws(
    () => compileSingleImageEditRequest(data.input, {
      ...context,
      parent_verification: { ...context.parent_verification, candidate_sha256: "0".repeat(64) },
    }),
    (error) => error instanceof SingleImageEditContractError && error.code === "parent_candidate_unverified",
  );
});

async function writeCompletedRun(compiled) {
  await mkdir(path.join(compiled.runtime.project_dir, "state"), { recursive: true });
  await mkdir(path.join(compiled.runtime.project_dir, "origin_image"), { recursive: true });
  const snapshot = {
    source_snapshot_contract_version: 1,
    run_id: `single-edit-${compiled.request.execute_key.slice(0, 24)}`,
    project_dir: compiled.runtime.project_dir,
    run_mode: "single_image_edit",
    page_ids: [compiled.identity.page_id],
    authoritative_source: { path: compiled.source.outline_path, sha256: compiled.source.sha256 },
    slide_identity: {
      required: true,
      deck_uid: compiled.identity.deck_uid,
      slide_uids: { [compiled.identity.page_id]: compiled.identity.slide_uid },
      source_path: compiled.source.outline_path,
      source_sha256: compiled.source.sha256,
    },
  };
  const snapshotPath = path.join(compiled.runtime.project_dir, "state", "source_snapshot.json");
  const snapshotSha = await jsonFile(snapshotPath, snapshot);
  const candidatePath = path.join(
    compiled.runtime.project_dir,
    "origin_image",
    `single_edit_${compiled.request.execute_key.slice(0, 16)}_page_${compiled.identity.page_id}.png`,
  );
  const candidateBytes = png(1200, 675, [230, 90, 20]);
  await writeFile(candidatePath, candidateBytes);
  const candidate = {
    candidate_id: `edit-${compiled.request.execute_key.slice(0, 24)}-${compiled.identity.page_id}`,
    style_slot: "EDIT",
    page_id: compiled.identity.page_id,
    role: "single_image_edit",
    path: candidatePath,
    width: 1200,
    height: 675,
    size_bytes: candidateBytes.length,
    sha256: hash(candidateBytes),
    status: "candidate_ready",
    deck_uid: compiled.identity.deck_uid,
    slide_uid: compiled.identity.slide_uid,
    derivation_kind: "single_image_edit",
    parent_candidate_id: compiled.parent.candidate_id,
    parent_path: compiled.parent.path,
    parent_sha256: compiled.parent.sha256,
    source_run_id: compiled.parent.source_run_id,
    source_outline_revision: compiled.source.expected_revision,
    user_request_sha256: compiled.request.user_request_sha256,
  };
  if (compiled.parent.source_kind === "direct_selection") {
    candidate.parent_source_kind = "direct_selection";
    candidate.source_revision_status = compiled.parent.source_revision_status;
  }
  const state = {
    single_image_edit_state_contract_version: 1,
    run_id: snapshot.run_id,
    run_mode: "single_image_edit",
    status: "completed",
    project_dir: compiled.runtime.project_dir,
    candidate_root: compiled.runtime.candidate_root,
    identity: compiled.identity,
    source_outline: {
      path: compiled.source.outline_path,
      revision: compiled.source.expected_revision,
      sha256: compiled.source.sha256,
    },
    source_snapshot_path: snapshotPath,
    source_snapshot_sha256: snapshotSha,
    parent_candidate: compiled.parent,
    request: {
      user_request_sha256: compiled.request.user_request_sha256,
      request_started_at: compiled.request.request_started_at,
      execute_key: compiled.request.execute_key,
    },
    imagegen: { status: "completed" },
    candidate,
    events: [],
    completed_at: "2026-08-12T14:01:00.000Z",
  };
  const stateSha = await jsonFile(compiled.runtime.state_path, state);
  const handoff = {
    handoff_contract_version: 1,
    run_id: state.run_id,
    run_mode: "single_image_edit",
    project_dir: compiled.runtime.project_dir,
    pipeline_status: "completed",
    status: "candidate_ready",
    state_ref: { path: compiled.runtime.state_path, sha256: stateSha },
    source_snapshot_ref: { path: snapshotPath, sha256: snapshotSha },
    slide_identity: snapshot.slide_identity,
    lineage: {
      derivation_kind: "single_image_edit",
      parent_candidate_id: compiled.parent.candidate_id,
      parent_sha256: compiled.parent.sha256,
      source_run_id: compiled.parent.source_run_id,
      ...(compiled.parent.source_kind === "direct_selection"
        ? {
            parent_source_kind: "direct_selection",
            source_revision_status: compiled.parent.source_revision_status,
          }
        : {}),
    },
    candidates: [candidate],
    user_selection: { selected: false },
  };
  await jsonFile(compiled.runtime.handoff_path, handoff);
  return { candidatePath, candidate, state, handoff };
}

test("verify accepts one canonical edited candidate and rejects extra origin files", async (t) => {
  const data = await fixture(t);
  const compiled = await loadAndCompileSingleImageEditRequest(data.input, data.context);
  const completed = await writeCompletedRun(compiled);
  const response = {
    contract_version: 1,
    status: "candidate_ready",
    native_refs: {
      project_dir: compiled.runtime.project_dir,
      state_path: compiled.runtime.state_path,
      handoff_path: compiled.runtime.handoff_path,
      run_id: `single-edit-${compiled.request.execute_key.slice(0, 24)}`,
    },
  };
  const verified = await verifySingleImageEditNativeRefs(response, compiled);
  assert.equal(verified.status, "verified");
  assert.equal(verified.candidate.path, completed.candidatePath);
  assert.equal(verified.candidate.parent_candidate_id, "A-P05");

  await writeFile(path.join(compiled.runtime.project_dir, "origin_image", "extra_page_P05.png"), "x");
  await assert.rejects(
    () => verifySingleImageEditNativeRefs(response, compiled),
    (error) => error instanceof SingleImageEditContractError && error.code === "candidate_mismatch",
  );
});

test("verify accepts a direct-parent candidate with explicit unrecorded lineage", async (t) => {
  const data = await fixture(t);
  const compiled = await loadAndCompileSingleImageEditRequest(directInput(data), data.context);
  const completed = await writeCompletedRun(compiled);
  const refs = {
    contract_version: 1,
    status: "candidate_ready",
    native_refs: {
      project_dir: compiled.runtime.project_dir,
      state_path: compiled.runtime.state_path,
      handoff_path: compiled.runtime.handoff_path,
      run_id: `single-edit-${compiled.request.execute_key.slice(0, 24)}`,
    },
  };
  const verified = await verifySingleImageEditNativeRefs(refs, compiled);
  assert.equal(verified.candidate.path, completed.candidatePath);
  assert.equal(completed.handoff.lineage.source_revision_status, "unrecorded");
  assert.equal(completed.handoff.lineage.parent_source_kind, "direct_selection");
});

test("native refs parser accepts final fenced JSON but never guesses from progress prose", () => {
  const payload = {
    contract_version: 1,
    native_refs: {
      project_dir: "/tmp/project",
      state_path: "/tmp/project/state/single_image_edit_state.json",
      handoff_path: "/tmp/project/state/handoff.json",
      run_id: "single-edit-test",
    },
  };
  assert.deepEqual(
    parseSingleImageEditNativeRefs(`\`\`\`json\n${JSON.stringify(payload)}\n\`\`\``),
    payload.native_refs,
  );
  assert.throws(
    () => parseSingleImageEditNativeRefs(`done ${JSON.stringify(payload)}`),
    (error) => error instanceof SingleImageEditContractError && error.code === "invalid_native_refs",
  );
});


test("host finalize accepts only the isolated artifact root supplied by its host", async (t) => {
  const data = await fixture(t);
  const compiled = await loadAndCompileSingleImageEditRequest(directInput(data), data.context);
  const generatedImagesRoot = path.join(data.root, "Studio Codex Home", "generated_images");
  const savedPath = path.join(generatedImagesRoot, "host-visible.png");
  const plan = buildSingleImageEditHostFinalizePlan(compiled, { saved_path: savedPath }, { generatedImagesRoot });
  assert.equal(plan.saved_path, savedPath);
  assert.throws(() => buildSingleImageEditHostFinalizePlan(compiled,
    { saved_path: path.join(CODEX_GENERATED_IMAGES_ROOT, "main-home.png") }, { generatedImagesRoot }),
    { code: "invalid_saved_path" });
});
