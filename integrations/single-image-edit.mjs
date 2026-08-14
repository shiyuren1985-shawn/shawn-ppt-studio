import { createHash } from "node:crypto";
import { lstat, readFile, readdir, realpath, stat } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";

import {
  parseOutlineIdentity,
  sha256Bytes,
  STUDIO_APP_SERVER_TRANSPORT,
} from "./shawn-single-page.mjs";
import {
  IMAGEGEN_SKILL_PATH,
  SHAWN_SKILL_PATH,
  SHAWN_SKILL_ROOT,
  STUDIO_ROOT,
} from "./skill-paths.mjs";

export { SHAWN_SKILL_PATH } from "./skill-paths.mjs";

export const SINGLE_IMAGE_EDIT_CONTRACT_VERSION = 1;
export const SINGLE_IMAGE_EDIT_RUN_MODE = "single_image_edit";
export const SINGLE_IMAGE_EDIT_HOST_FINALIZE_STATUS = "host_finalize_required";
const CODEX_HOME = path.resolve(process.env.CODEX_HOME || path.join(homedir(), ".codex"));
export const SINGLE_IMAGE_EDIT_CONTROL_PLANE = path.join(
  SHAWN_SKILL_ROOT,
  "scripts",
  "single_image_edit_control_plane_v1.py",
);
export const CODEX_GENERATED_IMAGES_ROOT = path.join(CODEX_HOME, "generated_images");
export const DEFAULT_MONITORING_ROOT = path.resolve(
  process.env.SHAWN_PPT_IMAGE_MONITORING_ROOT ||
    path.join(path.dirname(STUDIO_ROOT), "monitoring", "shawn-ppt-image"),
);
export const SINGLE_IMAGE_EDIT_ORCHESTRATION_CONTRACT = Object.freeze({
  contract_version: 1,
  transport: STUDIO_APP_SERVER_TRANSPORT,
  executor_location: "root_turn",
  child_executor_count: 0,
  success_sequence: Object.freeze(["prepare", "claim", "imagegen", "complete"]),
  failure_sequence: Object.freeze(["prepare", "claim", "imagegen_failed", "release"]),
  slot_registry: "existing_central_cap5",
});

const REVISION_PATTERN = /^sha256:([0-9a-f]{64})$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const PAGE_ID_PATTERN = /^P0*([1-9]\d{0,2})$/i;

export class SingleImageEditContractError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "SingleImageEditContractError";
    this.code = code;
  }
}

function fail(code, message) {
  throw new SingleImageEditContractError(code, message);
}

function requireString(value, name, maxLength = 8_000) {
  if (typeof value !== "string" || value.trim() === "") {
    fail("invalid_input", `${name} must be a non-empty string`);
  }
  if (value.length > maxLength || value.includes("\0")) {
    fail("invalid_input", `${name} is not a valid bounded string`);
  }
  return value.trim();
}

function requireAbsoluteNormalized(value, name) {
  const text = requireString(value, name, 4_096);
  if (!path.isAbsolute(text) || path.resolve(text) !== text) {
    fail("invalid_path", `${name} must be an absolute normalized path`);
  }
  return text;
}

function relativeWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return (
    relative === "" ||
    (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative))
  );
}

function canonicalPageId(value) {
  const match = String(value ?? "").trim().match(PAGE_ID_PATTERN);
  if (!match) fail("invalid_page_id", `invalid canonical page id: ${value}`);
  return `P${String(Number(match[1])).padStart(2, "0")}`;
}

function normalizeRevision(value) {
  const revision = requireString(value, "expected_revision", 80).toLowerCase();
  const match = revision.match(REVISION_PATTERN);
  if (!match) fail("invalid_revision", "expected_revision must use sha256:<64 lowercase hex>");
  return { revision, sha256: match[1] };
}

function normalizeIso(value) {
  const text = requireString(value, "request_started_at", 64);
  const parsed = Date.parse(text);
  if (!Number.isFinite(parsed)) fail("invalid_timestamp", "request_started_at is invalid");
  return new Date(parsed).toISOString();
}

function hashText(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function requireObject(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail("invalid_input", `${name} must be an object`);
  }
  return value;
}

function requireSha256(value, name) {
  const text = requireString(value, name, 64).toLowerCase();
  if (!SHA256_PATTERN.test(text)) fail("invalid_input", `${name} must be a SHA-256 digest`);
  return text;
}

function pngDimensions(bytes, label) {
  if (
    !Buffer.isBuffer(bytes) ||
    bytes.length < 24 ||
    bytes.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a" ||
    bytes.subarray(12, 16).toString("ascii") !== "IHDR"
  ) {
    fail("invalid_image", `${label} must be a PNG image`);
  }
  const width = bytes.readUInt32BE(16);
  const height = bytes.readUInt32BE(20);
  if (width < 1000 || height < 500 || Math.abs(width / height - 16 / 9) > 0.03) {
    fail("invalid_image", `${label} must be a usable 16:9 slide image`);
  }
  return { width, height };
}

function normalizeCanonicalParent(input, context, expected) {
  const parentInput = requireObject(input.parent, "parent");
  const handoffPath = requireAbsoluteNormalized(parentInput.handoff_path, "parent.handoff_path");
  const candidateId = requireString(parentInput.candidate_id, "parent.candidate_id", 256);
  const handoff = requireObject(context.parent_handoff, "parent_handoff");
  const verification = requireObject(context.parent_verification, "parent_verification");
  const handoffSha256 = requireSha256(verification.handoff_sha256, "parent handoff sha256");
  if (verification.handoff_real_path !== handoffPath) {
    fail("parent_handoff_unverified", "parent handoff real path does not match the request");
  }
  if (handoff.status !== "candidate_ready" && handoff.status !== "accepted") {
    fail("parent_handoff_not_ready", "parent handoff is not candidate-ready");
  }
  const projectDir = requireAbsoluteNormalized(handoff.project_dir, "parent project_dir");
  if (handoffPath !== path.join(projectDir, "state", "handoff.json")) {
    fail("parent_handoff_unverified", "parent handoff is not canonical for project_dir");
  }
  if (!relativeWithin(expected.candidate_root, projectDir) || projectDir === expected.candidate_root) {
    fail("parent_handoff_unverified", "parent project is outside the approved candidate root");
  }
  for (const [name, ref, actualHash] of [
    ["state_ref", handoff.state_ref, verification.state_sha256],
    ["source_snapshot_ref", handoff.source_snapshot_ref, verification.snapshot_sha256],
  ]) {
    requireObject(ref, `parent ${name}`);
    if (requireSha256(ref.sha256, `parent ${name}.sha256`) !== actualHash) {
      fail("parent_handoff_unverified", `parent ${name} hash is invalid`);
    }
    const refPath = requireAbsoluteNormalized(ref.path, `parent ${name}.path`);
    if (!relativeWithin(projectDir, refPath)) {
      fail("parent_handoff_unverified", `parent ${name} path is outside its project`);
    }
  }
  const identity = requireObject(handoff.slide_identity, "parent slide_identity");
  if (
    identity.deck_uid !== expected.deck_uid ||
    Object.entries(identity.slide_uids || {}).filter(
      ([pageId, slideUid]) =>
        canonicalPageId(pageId) === expected.page_id && slideUid === expected.slide_uid,
    ).length !== 1
  ) {
    fail("parent_identity_mismatch", "parent handoff identity does not match the edit scope");
  }
  const candidates = (handoff.candidates || []).filter(
    (candidate) => candidate && candidate.candidate_id === candidateId,
  );
  if (candidates.length !== 1) {
    fail("parent_candidate_missing", "parent candidate must occur exactly once in its handoff");
  }
  const candidate = candidates[0];
  const candidatePath = requireAbsoluteNormalized(candidate.path, "parent candidate path");
  const candidateSha256 = requireSha256(candidate.sha256, "parent candidate sha256");
  const actualDimensions = verification.candidate_dimensions;
  if (
    verification.candidate_real_path !== candidatePath ||
    verification.candidate_sha256 !== candidateSha256 ||
    !verification.candidate_is_regular ||
    actualDimensions?.width !== candidate.width ||
    actualDimensions?.height !== candidate.height ||
    !relativeWithin(path.join(projectDir, "origin_image"), candidatePath) ||
    candidate.deck_uid !== expected.deck_uid ||
    candidate.slide_uid !== expected.slide_uid ||
    canonicalPageId(candidate.page_id) !== expected.page_id
  ) {
    fail("parent_candidate_unverified", "parent candidate path, hash, or identity is invalid");
  }
  return {
    candidate_id: candidateId,
    path: candidatePath,
    sha256: candidateSha256,
    width: candidate.width ?? null,
    height: candidate.height ?? null,
    source_run_id: requireString(handoff.run_id, "parent run_id", 256),
    handoff_path: handoffPath,
    handoff_sha256: handoffSha256,
  };
}

function normalizeDirectParent(input, context, expected) {
  const refs = requireObject(input.direct_parent_refs, "direct_parent_refs");
  const expectedKeys = [
    "deck_uid",
    "slide_uid",
    "candidate_id",
    "path",
    "sha256",
    "width",
    "height",
    "source_revision_status",
  ];
  if (
    Object.keys(refs).length !== expectedKeys.length ||
    expectedKeys.some((name) => !Object.hasOwn(refs, name))
  ) {
    fail("invalid_direct_parent_refs", "direct_parent_refs has unsupported or missing fields");
  }
  if (refs.deck_uid !== expected.deck_uid || refs.slide_uid !== expected.slide_uid) {
    fail("parent_identity_mismatch", "direct parent deck/slide UID does not match the edit scope");
  }
  const sourceRevisionStatus = requireString(
    refs.source_revision_status,
    "direct_parent_refs.source_revision_status",
    32,
  );
  if (sourceRevisionStatus !== "unrecorded") {
    fail(
      "invalid_source_revision_status",
      "direct parent source_revision_status must be unrecorded without canonical source evidence",
    );
  }
  const candidatePath = requireAbsoluteNormalized(refs.path, "direct_parent_refs.path");
  const candidateSha256 = requireSha256(refs.sha256, "direct_parent_refs.sha256");
  const width = refs.width;
  const height = refs.height;
  if (
    !Number.isInteger(width) ||
    !Number.isInteger(height) ||
    width < 1000 ||
    height < 500 ||
    Math.abs(width / height - 16 / 9) > 0.03
  ) {
    fail("invalid_direct_parent_refs", "direct parent dimensions must describe a usable 16:9 slide");
  }
  const verification = requireObject(context.direct_parent_verification, "direct_parent_verification");
  if (
    verification.candidate_real_path !== candidatePath ||
    verification.candidate_sha256 !== candidateSha256 ||
    verification.candidate_is_regular !== true ||
    verification.candidate_is_symlink !== false ||
    verification.candidate_dimensions?.width !== width ||
    verification.candidate_dimensions?.height !== height
  ) {
    fail("parent_candidate_unverified", "direct parent path, hash, or dimensions changed");
  }
  return {
    candidate_id: requireString(refs.candidate_id, "direct_parent_refs.candidate_id", 256),
    path: candidatePath,
    sha256: candidateSha256,
    width,
    height,
    source_kind: "direct_selection",
    source_revision_status: sourceRevisionStatus,
    source_run_id: null,
    handoff_path: null,
    handoff_sha256: null,
  };
}

function normalizeParent(input, context, expected) {
  const hasCanonical = input.parent !== undefined && input.parent !== null;
  const hasDirect = input.direct_parent_refs !== undefined && input.direct_parent_refs !== null;
  if (hasCanonical === hasDirect) {
    fail("parent_required", "exactly one of parent or direct_parent_refs is required");
  }
  return hasDirect
    ? normalizeDirectParent(input, context, expected)
    : normalizeCanonicalParent(input, context, expected);
}

/** Pure compilation; all read-only filesystem evidence is supplied in context. */
export function compileSingleImageEditRequest(input, context) {
  requireObject(input, "input");
  requireObject(context, "context");
  const deckUid = requireString(input.deck_uid, "deck_uid", 256);
  const slideUid = requireString(input.slide_uid, "slide_uid", 256);
  const outlinePath = requireAbsoluteNormalized(input.outline_path, "outline_path");
  const expectedRevision = normalizeRevision(input.expected_revision);
  const userRequest = requireString(input.user_request, "user_request", 8_000);
  const outlineMarkdown = requireString(context.outline_markdown, "outline_markdown", 2_000_000);
  const outlineSha256 = requireSha256(context.outline_sha256, "outline_sha256");
  if (outlineSha256 !== expectedRevision.sha256) {
    fail("outline_revision_conflict", "authoritative outline revision has changed");
  }
  const identity = parseOutlineIdentity(outlineMarkdown);
  if (identity.deck_uid !== deckUid) {
    fail("deck_uid_mismatch", "requested deck UID differs from the authoritative outline");
  }
  const pageMatches = Object.entries(identity.slide_uids).filter(([, value]) => value === slideUid);
  if (pageMatches.length !== 1) {
    fail("slide_uid_mismatch", "requested slide UID must occur exactly once in the outline");
  }
  const pageId = canonicalPageId(pageMatches[0][0]);
  const candidateRoot = requireAbsoluteNormalized(context.candidate_root, "candidate_root");
  if (!Array.isArray(context.approved_candidate_roots) || context.approved_candidate_roots.length === 0) {
    fail("approved_candidate_roots_missing", "approved_candidate_roots must be non-empty");
  }
  const approvedCandidateRoots = context.approved_candidate_roots.map((value, index) =>
    requireAbsoluteNormalized(value, `approved_candidate_roots[${index}]`),
  );
  if (!approvedCandidateRoots.some((root) => relativeWithin(root, candidateRoot))) {
    fail("candidate_root_not_approved", "candidate_root is not explicitly approved");
  }
  const parent = normalizeParent(input, context, {
    candidate_root: candidateRoot,
    deck_uid: deckUid,
    slide_uid: slideUid,
    page_id: pageId,
  });
  const requestStartedAt = normalizeIso(context.request_started_at);
  const userRequestSha256 = hashText(userRequest);
  const executeKey = hashText(
    JSON.stringify({
      deck_uid: deckUid,
      slide_uid: slideUid,
      page_id: pageId,
      outline_sha256: outlineSha256,
      parent_candidate_id: parent.candidate_id,
      ...(parent.source_kind ? { parent_source_kind: parent.source_kind } : {}),
      parent_path: parent.path,
      parent_sha256: parent.sha256,
      user_request_sha256: userRequestSha256,
      request_started_at: requestStartedAt,
    }),
  );
  const date = requestStartedAt.slice(0, 10).replaceAll("-", "");
  const taskName = `${pageId}_single_image_edit_${date}_${executeKey.slice(0, 16)}`;
  const projectDir = path.join(candidateRoot, taskName);
  const monitoringRoot = requireAbsoluteNormalized(
    context.monitoring_root ?? DEFAULT_MONITORING_ROOT,
    "monitoring_root",
  );
  return {
    contract_version: SINGLE_IMAGE_EDIT_CONTRACT_VERSION,
    transport: STUDIO_APP_SERVER_TRANSPORT,
    run_mode: SINGLE_IMAGE_EDIT_RUN_MODE,
    identity: { deck_uid: deckUid, slide_uid: slideUid, page_id: pageId },
    source: {
      outline_path: outlinePath,
      expected_revision: expectedRevision.revision,
      sha256: outlineSha256,
    },
    parent,
    request: {
      user_request: userRequest,
      user_request_sha256: userRequestSha256,
      request_started_at: requestStartedAt,
      execute_key: executeKey,
    },
    runtime: {
      candidate_root: candidateRoot,
      approved_candidate_roots: approvedCandidateRoots,
      generated_images_root: CODEX_GENERATED_IMAGES_ROOT,
      monitoring_root: monitoringRoot,
      control_plane_path: SINGLE_IMAGE_EDIT_CONTROL_PLANE,
      task_name: taskName,
      project_dir: projectDir,
      state_path: path.join(projectDir, "state", "single_image_edit_state.json"),
      handoff_path: path.join(projectDir, "state", "handoff.json"),
    },
  };
}

async function requireRealFile(filePath, label) {
  const [resolved, linkInfo, info, bytes] = await Promise.all([
    realpath(filePath),
    lstat(filePath),
    stat(filePath),
    readFile(filePath),
  ]).catch((error) => fail("missing_file", `${label} is unavailable: ${error.message}`));
  if (resolved !== filePath || linkInfo.isSymbolicLink() || !info.isFile()) {
    fail("invalid_file", `${label} must be a real non-symlink file`);
  }
  return { resolved, linkInfo, info, bytes, sha256: sha256Bytes(bytes) };
}

export async function loadAndCompileSingleImageEditRequest(input, context = {}) {
  const outlinePath = requireAbsoluteNormalized(input?.outline_path, "outline_path");
  const hasCanonical = input?.parent !== undefined && input?.parent !== null;
  const hasDirect = input?.direct_parent_refs !== undefined && input?.direct_parent_refs !== null;
  if (hasCanonical === hasDirect) {
    fail("parent_required", "exactly one of parent or direct_parent_refs is required");
  }
  const outlineFile = await requireRealFile(outlinePath, "outline");
  if (hasDirect) {
    const direct = requireObject(input.direct_parent_refs, "direct_parent_refs");
    const candidatePath = requireAbsoluteNormalized(direct.path, "direct_parent_refs.path");
    const candidateFile = await requireRealFile(candidatePath, "direct parent candidate");
    const candidateDimensions = pngDimensions(candidateFile.bytes, "direct parent candidate");
    return compileSingleImageEditRequest(input, {
      ...context,
      outline_markdown: outlineFile.bytes.toString("utf8"),
      outline_sha256: outlineFile.sha256,
      direct_parent_verification: {
        candidate_real_path: candidateFile.resolved,
        candidate_sha256: candidateFile.sha256,
        candidate_is_regular: candidateFile.info.isFile(),
        candidate_is_symlink: candidateFile.linkInfo.isSymbolicLink(),
        candidate_dimensions: candidateDimensions,
      },
    });
  }
  const parentInput = requireObject(input.parent, "parent");
  const handoffPath = requireAbsoluteNormalized(parentInput.handoff_path, "parent.handoff_path");
  const handoffFile = await requireRealFile(handoffPath, "parent handoff");
  let handoff;
  try {
    handoff = JSON.parse(handoffFile.bytes.toString("utf8"));
  } catch (error) {
    fail("invalid_parent_handoff", `parent handoff is invalid JSON: ${error.message}`);
  }
  const stateRef = requireObject(handoff.state_ref, "parent state_ref");
  const snapshotRef = requireObject(handoff.source_snapshot_ref, "parent source_snapshot_ref");
  const candidate = (handoff.candidates || []).find(
    (item) => item && item.candidate_id === parentInput.candidate_id,
  );
  if (!candidate) fail("parent_candidate_missing", "parent candidate is not in the handoff");
  const [stateFile, snapshotFile, candidateFile] = await Promise.all([
    requireRealFile(requireAbsoluteNormalized(stateRef.path, "parent state_ref.path"), "parent state"),
    requireRealFile(
      requireAbsoluteNormalized(snapshotRef.path, "parent source_snapshot_ref.path"),
      "parent source snapshot",
    ),
    requireRealFile(requireAbsoluteNormalized(candidate.path, "parent candidate path"), "parent candidate"),
  ]);
  const candidateDimensions = pngDimensions(candidateFile.bytes, "parent candidate");
  return compileSingleImageEditRequest(input, {
    ...context,
    outline_markdown: outlineFile.bytes.toString("utf8"),
    outline_sha256: outlineFile.sha256,
    parent_handoff: handoff,
    parent_verification: {
      handoff_real_path: handoffFile.resolved,
      handoff_sha256: handoffFile.sha256,
      state_sha256: stateFile.sha256,
      snapshot_sha256: snapshotFile.sha256,
      candidate_real_path: candidateFile.resolved,
      candidate_sha256: candidateFile.sha256,
      candidate_is_regular: candidateFile.info.isFile(),
      candidate_dimensions: candidateDimensions,
    },
  });
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'"'"'`)}'`;
}

function prepareCommand(compiled) {
  const values = [
    ["--candidate-root", compiled.runtime.candidate_root],
    ["--outline-path", compiled.source.outline_path],
    ["--expected-revision", compiled.source.expected_revision],
    ["--deck-uid", compiled.identity.deck_uid],
    ["--slide-uid", compiled.identity.slide_uid],
    ["--page-id", compiled.identity.page_id],
    ["--user-request-sha256", compiled.request.user_request_sha256],
    ["--request-started-at", compiled.request.request_started_at],
    ["--execute-key", compiled.request.execute_key],
  ];
  if (compiled.parent.source_kind === "direct_selection") {
    values.splice(6, 0, [
      "--direct-parent-refs-json",
      JSON.stringify({
        deck_uid: compiled.identity.deck_uid,
        slide_uid: compiled.identity.slide_uid,
        candidate_id: compiled.parent.candidate_id,
        path: compiled.parent.path,
        sha256: compiled.parent.sha256,
        width: compiled.parent.width,
        height: compiled.parent.height,
        source_revision_status: compiled.parent.source_revision_status,
      }),
    ]);
  } else {
    values.splice(
      6,
      0,
      ["--parent-handoff-path", compiled.parent.handoff_path],
      ["--parent-handoff-sha256", compiled.parent.handoff_sha256],
      ["--parent-candidate-id", compiled.parent.candidate_id],
    );
  }
  return ["python3", shellQuote(compiled.runtime.control_plane_path), "prepare"]
    .concat(values.flatMap(([flag, value]) => [flag, shellQuote(value)]))
    .join(" ");
}

function executionPrompt(compiled) {
  const hostFinalizeMarker = JSON.stringify({
    contract_version: SINGLE_IMAGE_EDIT_CONTRACT_VERSION,
    status: SINGLE_IMAGE_EDIT_HOST_FINALIZE_STATUS,
    state_path: compiled.runtime.state_path,
  });
  const orchestration = JSON.stringify(SINGLE_IMAGE_EDIT_ORCHESTRATION_CONTRACT, null, 2);
  return [
    "$shawn-ppt-image Perform exactly one formal single-image edit using the supplied parent image.",
    `This is the strictly scoped programmatic transport transport=${STUDIO_APP_SERVER_TRANSPORT}. The same marker is present in model-visible application context. Apply only the installed Shawn skill's Studio App Server compatibility exception; do not generalize it to another transport.`,
    "The root turn is the one and only mechanical single-image-edit executor. Do not spawn an image-execution child Agent or any per-image worker. Execute the canonical prepare -> claim -> ImageGen once -> complete/release sequence directly in this root turn. Do not create or modify state by hand.",
    "First run the exact canonical prepare command below. If it returns completed/candidate_ready, do not call ImageGen again and return its verified native refs.",
    `<canonical_prepare_command>${prepareCommand(compiled)}</canonical_prepare_command>`,
    `If prepare returns prepared, run: python3 ${shellQuote(compiled.runtime.control_plane_path)} claim --state ${shellQuote(compiled.runtime.state_path)} --wait-seconds 600`,
    "Only after claim returns status=claimed, call $imagegen exactly once as an edit of the supplied localImage. This claim reuses the existing shared central ImageGen cap5 registry; do not add another semaphore or call ImageGen without it.",
    "Apply only request.user_request. Preserve every unrequested fact, title, object, visual relationship, crop, and 16:9 slide structure. Never overwrite the parent image.",
    "Wait for the imageGeneration terminal result. Do not copy, move, resize, rename, or inspect generated_images with shell commands.",
    `If imageGeneration completed and its exact savedPath is visible to you, run: python3 ${shellQuote(compiled.runtime.control_plane_path)} complete --state ${shellQuote(compiled.runtime.state_path)} --saved-path '<exact ImageGen savedPath>'`,
    `If imageGeneration completed but its savedPath is not visible to you, DO NOT guess a path and DO NOT run release. Return exactly this host-finalize marker so the host can pass its observed completed savedPath to the same canonical complete command: ${hostFinalizeMarker}`,
    `Run this release command only if imageGeneration explicitly failed or was cancelled and there is no completed imageGeneration result: python3 ${shellQuote(compiled.runtime.control_plane_path)} release --state ${shellQuote(compiled.runtime.state_path)}`,
    "The canonical complete/release commands are the only components allowed to import the result or mutate edit state and the shared lease. Do not add a Judge or Reviewer and do not change selection.",
    "Do not call generatedImage(...), image(...), open the result, or forward an image payload into the root conversation. Use only the exact savedPath exposed by imageGeneration or the host-finalize marker. The local parent input is edit context only.",
    "The final assistant message must be either the complete JSON object returned by canonical complete/verify, or the exact host-finalize marker above when and only when a completed result exists but its savedPath is invisible. Do not return image payloads, logs, prompts, or commentary after it.",
    "If any hard gate fails, fail the turn instead of guessing or creating partial refs.",
    "<single_image_edit_orchestration_contract_json>",
    orchestration,
    "</single_image_edit_orchestration_contract_json>",
    "<single_image_edit_input_json>",
    JSON.stringify(compiled, null, 2),
    "</single_image_edit_input_json>",
  ].join("\n");
}

function canonicalCommandSpec(compiled, action, extraArgs = []) {
  return {
    command: "python3",
    args: [
      compiled.runtime.control_plane_path,
      action,
      "--state",
      compiled.runtime.state_path,
      ...extraArgs,
    ],
  };
}

/**
 * Build the host-only canonical recovery plan for one already-completed
 * imageGeneration savedPath.  This function is pure: it does not execute the
 * commands or read/write state.  The caller must still parse the control-plane
 * JSON and run verifySingleImageEditNativeRefs after a successful complete.
 */
export function buildSingleImageEditHostFinalizePlan(compiled, { saved_path } = {}) {
  if (
    compiled?.contract_version !== SINGLE_IMAGE_EDIT_CONTRACT_VERSION ||
    compiled?.run_mode !== SINGLE_IMAGE_EDIT_RUN_MODE ||
    compiled?.runtime?.control_plane_path !== SINGLE_IMAGE_EDIT_CONTROL_PLANE
  ) {
    fail("invalid_compiled_request", "compiled single-image-edit request is invalid");
  }
  const savedPath = requireAbsoluteNormalized(saved_path, "saved_path");
  if (!relativeWithin(CODEX_GENERATED_IMAGES_ROOT, savedPath) || savedPath === CODEX_GENERATED_IMAGES_ROOT) {
    fail("invalid_saved_path", "saved_path must be below Codex generated_images");
  }
  const complete = canonicalCommandSpec(compiled, "complete", ["--saved-path", savedPath]);
  return {
    contract_version: SINGLE_IMAGE_EDIT_CONTRACT_VERSION,
    kind: "single_image_edit_host_finalize",
    state_path: compiled.runtime.state_path,
    saved_path: savedPath,
    attempt_complete: complete,
    recover_only_if_error_code: "imagegen_slot_not_claimed",
    recovery_commands: [
      canonicalCommandSpec(compiled, "claim", ["--wait-seconds", "600"]),
      complete,
    ],
    release_on_failure: canonicalCommandSpec(compiled, "release"),
  };
}

export function buildSingleImageEditAppServerTurn(compiled, { thread_id } = {}) {
  const threadId = requireString(thread_id, "thread_id", 256);
  if (
    compiled?.contract_version !== SINGLE_IMAGE_EDIT_CONTRACT_VERSION ||
    compiled?.run_mode !== SINGLE_IMAGE_EDIT_RUN_MODE ||
    compiled?.transport !== STUDIO_APP_SERVER_TRANSPORT
  ) {
    fail("invalid_compiled_request", "compiled single-image-edit request is invalid");
  }
  return {
    threadId,
    cwd: compiled.runtime.candidate_root,
    approvalPolicy: "never",
    sandboxPolicy: {
      type: "workspaceWrite",
      writableRoots: [compiled.runtime.candidate_root, compiled.runtime.monitoring_root],
      networkAccess: true,
    },
    additionalContext: {
      shawn_ppt_studio_transport: {
        kind: "application",
        value: `transport=${STUDIO_APP_SERVER_TRANSPORT}`,
      },
    },
    input: [
      { type: "text", text: executionPrompt(compiled) },
      { type: "localImage", path: compiled.parent.path },
      { type: "skill", name: "imagegen", path: IMAGEGEN_SKILL_PATH },
      { type: "skill", name: "shawn-ppt-image", path: SHAWN_SKILL_PATH },
    ],
  };
}

export function parseSingleImageEditNativeRefs(value) {
  let document = value;
  if (typeof value === "string") {
    const trimmed = value.trim();
    const fenced = trimmed.match(/^```json\s*\n([\s\S]*?)\n```$/i);
    try {
      document = JSON.parse(fenced ? fenced[1].trim() : trimmed);
    } catch {
      fail("invalid_native_refs", "final response must be one complete JSON object or JSON fence");
    }
  }
  requireObject(document, "native refs response");
  if (document.contract_version !== SINGLE_IMAGE_EDIT_CONTRACT_VERSION) {
    fail("invalid_native_refs", "native refs contract_version is invalid");
  }
  const refs = requireObject(document.native_refs, "native_refs");
  const names = ["project_dir", "state_path", "handoff_path", "run_id"];
  if (
    Object.keys(document).some((key) => !["contract_version", "status", "idempotent", "native_refs"].includes(key)) ||
    Object.keys(refs).length !== names.length ||
    names.some((name) => !Object.hasOwn(refs, name))
  ) {
    fail("invalid_native_refs", "native refs contain unsupported or missing fields");
  }
  return {
    project_dir: requireAbsoluteNormalized(refs.project_dir, "project_dir"),
    state_path: requireAbsoluteNormalized(refs.state_path, "state_path"),
    handoff_path: requireAbsoluteNormalized(refs.handoff_path, "handoff_path"),
    run_id: requireString(refs.run_id, "run_id", 256),
  };
}

async function readJson(filePath, label) {
  const file = await requireRealFile(filePath, label);
  try {
    return { payload: JSON.parse(file.bytes.toString("utf8")), ...file };
  } catch (error) {
    fail("invalid_native_refs", `${label} is invalid JSON: ${error.message}`);
  }
}

function sameIdentity(identity, compiled) {
  return (
    identity?.deck_uid === compiled.identity.deck_uid &&
    identity?.slide_uid === compiled.identity.slide_uid &&
    canonicalPageId(identity?.page_id) === compiled.identity.page_id
  );
}

function handoffIdentityMatches(identity, compiled) {
  return (
    identity?.required === true &&
    identity?.deck_uid === compiled.identity.deck_uid &&
    identity?.source_path === compiled.source.outline_path &&
    identity?.source_sha256 === compiled.source.sha256 &&
    Object.entries(identity?.slide_uids || {}).filter(
      ([pageId, slideUid]) =>
        canonicalPageId(pageId) === compiled.identity.page_id &&
        slideUid === compiled.identity.slide_uid,
    ).length === 1
  );
}

export async function verifySingleImageEditNativeRefs(refsValue, compiled) {
  if (compiled?.run_mode !== SINGLE_IMAGE_EDIT_RUN_MODE) {
    fail("invalid_compiled_request", "expected compiled single-image-edit request");
  }
  const refs = parseSingleImageEditNativeRefs(
    refsValue?.native_refs
      ? refsValue
      : { contract_version: SINGLE_IMAGE_EDIT_CONTRACT_VERSION, native_refs: refsValue },
  );
  if (
    refs.project_dir !== compiled.runtime.project_dir ||
    refs.state_path !== compiled.runtime.state_path ||
    refs.handoff_path !== compiled.runtime.handoff_path ||
    refs.run_id !== `single-edit-${compiled.request.execute_key.slice(0, 24)}`
  ) {
    fail("native_refs_mismatch", "native refs do not match the compiled deterministic run");
  }
  const [stateFile, handoffFile, snapshotFile, parentFile] = await Promise.all([
    readJson(refs.state_path, "single image edit state"),
    readJson(refs.handoff_path, "single image edit handoff"),
    readJson(path.join(refs.project_dir, "state", "source_snapshot.json"), "source snapshot"),
    requireRealFile(compiled.parent.path, "parent candidate"),
  ]);
  const state = stateFile.payload;
  const handoff = handoffFile.payload;
  const snapshot = snapshotFile.payload;
  if (
    state.run_id !== refs.run_id ||
    state.run_mode !== SINGLE_IMAGE_EDIT_RUN_MODE ||
    state.status !== "completed" ||
    state.project_dir !== refs.project_dir ||
    !sameIdentity(state.identity, compiled) ||
    state.source_outline?.path !== compiled.source.outline_path ||
    state.source_outline?.revision !== compiled.source.expected_revision ||
    state.source_outline?.sha256 !== compiled.source.sha256 ||
    JSON.stringify(state.parent_candidate) !== JSON.stringify(compiled.parent) ||
    state.request?.execute_key !== compiled.request.execute_key ||
    state.request?.user_request_sha256 !== compiled.request.user_request_sha256 ||
    state.source_snapshot_path !== snapshotFile.resolved ||
    state.source_snapshot_sha256 !== snapshotFile.sha256
  ) {
    fail("native_state_mismatch", "single-image-edit state does not match the compiled request");
  }
  if (
    snapshot.run_id !== refs.run_id ||
    snapshot.run_mode !== SINGLE_IMAGE_EDIT_RUN_MODE ||
    !handoffIdentityMatches(snapshot.slide_identity, compiled)
  ) {
    fail("source_identity_mismatch", "source snapshot identity does not match the request");
  }
  if (
    parentFile.sha256 !== compiled.parent.sha256 ||
    handoff.run_id !== refs.run_id ||
    handoff.run_mode !== SINGLE_IMAGE_EDIT_RUN_MODE ||
    handoff.pipeline_status !== "completed" ||
    handoff.status !== "candidate_ready" ||
    handoff.project_dir !== refs.project_dir ||
    handoff.state_ref?.path !== refs.state_path ||
    handoff.state_ref?.sha256 !== stateFile.sha256 ||
    handoff.source_snapshot_ref?.path !== snapshotFile.resolved ||
    handoff.source_snapshot_ref?.sha256 !== snapshotFile.sha256 ||
    !handoffIdentityMatches(handoff.slide_identity, compiled) ||
    handoff.user_selection?.selected !== false ||
    handoff.lineage?.derivation_kind !== "single_image_edit" ||
    handoff.lineage?.parent_candidate_id !== compiled.parent.candidate_id ||
    handoff.lineage?.parent_sha256 !== compiled.parent.sha256 ||
    handoff.lineage?.source_run_id !== compiled.parent.source_run_id ||
    (compiled.parent.source_kind === "direct_selection" &&
      (handoff.lineage?.parent_source_kind !== "direct_selection" ||
        handoff.lineage?.source_revision_status !== compiled.parent.source_revision_status))
  ) {
    fail("handoff_mismatch", "single-image-edit handoff is not canonical for the request");
  }
  if (!Array.isArray(handoff.candidates) || handoff.candidates.length !== 1) {
    fail("handoff_mismatch", "single-image-edit handoff must contain exactly one candidate");
  }
  const candidate = handoff.candidates[0];
  const candidateFile = await requireRealFile(candidate.path, "edited candidate");
  const candidateDimensions = pngDimensions(candidateFile.bytes, "edited candidate");
  const originDir = path.join(refs.project_dir, "origin_image");
  const originEntries = await readdir(originDir, { withFileTypes: true });
  if (
    originEntries.filter((entry) => entry.isFile()).length !== 1 ||
    !relativeWithin(originDir, candidateFile.resolved) ||
    candidateFile.resolved === compiled.parent.path ||
    candidateFile.sha256 === compiled.parent.sha256 ||
    candidate.sha256 !== candidateFile.sha256 ||
    candidate.width !== candidateDimensions.width ||
    candidate.height !== candidateDimensions.height ||
    candidate.derivation_kind !== "single_image_edit" ||
    candidate.parent_candidate_id !== compiled.parent.candidate_id ||
    candidate.parent_path !== compiled.parent.path ||
    candidate.parent_sha256 !== compiled.parent.sha256 ||
    candidate.source_run_id !== compiled.parent.source_run_id ||
    (compiled.parent.source_kind === "direct_selection" &&
      (candidate.parent_source_kind !== "direct_selection" ||
        candidate.source_revision_status !== compiled.parent.source_revision_status)) ||
    candidate.source_outline_revision !== compiled.source.expected_revision ||
    candidate.user_request_sha256 !== compiled.request.user_request_sha256 ||
    candidate.deck_uid !== compiled.identity.deck_uid ||
    candidate.slide_uid !== compiled.identity.slide_uid ||
    canonicalPageId(candidate.page_id) !== compiled.identity.page_id ||
    candidate.status !== "candidate_ready"
  ) {
    fail("candidate_mismatch", "edited candidate path, lineage, identity, or hash is invalid");
  }
  return {
    contract_version: SINGLE_IMAGE_EDIT_CONTRACT_VERSION,
    status: "verified",
    native_refs: refs,
    candidate: {
      candidate_id: candidate.candidate_id,
      path: candidate.path,
      sha256: candidate.sha256,
      width: candidate.width,
      height: candidate.height,
      derivation_kind: candidate.derivation_kind,
      parent_candidate_id: candidate.parent_candidate_id,
    },
  };
}
