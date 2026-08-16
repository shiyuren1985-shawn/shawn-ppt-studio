import { createHash } from "node:crypto";
import { lstat, readFile, readdir, realpath, stat } from "node:fs/promises";
import path from "node:path";

import { readImageDimensions, sha256File } from "./selection-image-metadata.mjs";
import { readStudioSelection } from "./studio-selection-store.mjs";

const STATE_FILE_BY_MODE = new Map([
  ["fast_8x1_diverse", "style_run_state.json"],
  ["fast_4x3_anchored", "style_run_state.json"],
  ["selected_style_expansion", "selected_style_run_state.json"],
  ["single_image_edit", "single_image_edit_state.json"],
]);

const HISTORICAL_STATE_FILES = new Set([
  "style_run_state.json",
  "selected_style_run_state.json",
]);
const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp"]);

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function sourceCandidateId({ run_id: runId, native_candidate_id: nativeId, file_sha256: fileSha256 }) {
  return createHash("sha256")
    .update(JSON.stringify([runId, nativeId, fileSha256]))
    .digest("hex")
    .slice(0, 24);
}

function groupedCandidateId(deckUid, slideUid, fileSha256) {
  return createHash("sha256")
    .update(JSON.stringify(["studio-deduplicated-candidate", deckUid, slideUid, fileSha256]))
    .digest("hex")
    .slice(0, 24);
}

function inside(root, target) {
  const relative = path.relative(root, target);
  return relative !== "" && relative !== ".." && !relative.startsWith(`..${path.sep}`);
}

function pageId(value) {
  const match = String(value || "").match(/(\d+)/);
  return match ? `P${Number(match[1])}` : null;
}

function pageIdFromFilename(value) {
  const name = path.basename(String(value || ""), path.extname(String(value || "")));
  const match = name.match(/(?:page[_-]?P?|(?:^|[_-])P)0*(\d+)(?:$|[_-])/i);
  return match ? `P${Number(match[1])}` : null;
}

function slideForPage(deck, value) {
  const wanted = pageId(value);
  if (!wanted) return null;
  const matches = deck.outline.slides.filter((slide) => pageId(slide.page_id) === wanted);
  return matches.length === 1 ? matches[0] : null;
}

function normalizedTitle(value) {
  return String(value || "")
    .normalize("NFKC")
    .replace(/[，,。．.!！?？:：;；'‘’“”"《》<>（）()\s]/g, "")
    .toLowerCase();
}

async function historicalSlideMap(deck, snapshot, projectReal) {
  const map = new Map();
  if (snapshot?.slide_identity?.required === true) return map;
  const currentByTitle = new Map();
  for (const slide of deck.outline.slides) {
    const key = normalizedTitle(slide.title);
    if (!key) continue;
    if (currentByTitle.has(key)) currentByTitle.set(key, null);
    else currentByTitle.set(key, slide);
  }
  for (const ref of Array.isArray(snapshot?.content_contracts) ? snapshot.content_contracts : []) {
    try {
      const contractPath = path.resolve(ref?.path || "");
      if (!inside(projectReal, contractPath)) continue;
      const contractFile = await jsonFile(contractPath);
      if (ref.sha256 !== contractFile.sha256) continue;
      const sourcePageId = pageId(contractFile.document.page_id);
      const slide = currentByTitle.get(normalizedTitle(contractFile.document.title));
      if (sourcePageId && slide) map.set(sourcePageId, slide);
    } catch {
      // Older snapshots may not retain every content contract file.
    }
  }
  return map;
}

function identityMatches(identity, deck, slideUid, expectedPageId) {
  if (
    !identity ||
    identity.required !== true ||
    identity.deck_uid !== deck.outline.deck_uid ||
    path.resolve(identity.source_path || "") !== deck.outline.path
  ) return false;
  return Object.entries(identity.slide_uids || {}).some(
    ([candidatePageId, candidateSlideUid]) =>
      pageId(candidatePageId) === pageId(expectedPageId) && candidateSlideUid === slideUid,
  );
}

function identityAllowsHistoricalPage(identity, deck, slide) {
  if (!identity || identity.required !== true) return true;
  return identityMatches(identity, deck, slide.slide_uid, slide.page_id);
}

async function jsonFile(filePath) {
  const lexical = path.resolve(filePath);
  const [real, info, bytes, link] = await Promise.all([
    realpath(lexical),
    stat(lexical),
    readFile(lexical),
    lstat(lexical),
  ]);
  if (real !== lexical || !info.isFile() || link.isSymbolicLink()) throw new Error("not canonical file");
  const document = JSON.parse(bytes.toString("utf8"));
  if (!document || typeof document !== "object" || Array.isArray(document)) throw new Error("invalid JSON");
  return { path: real, bytes, sha256: sha256(bytes), document };
}

async function verifiedProjectRoot(outputReal, projectDir, statePath) {
  if (!path.isAbsolute(projectDir || "")) throw new Error("project path is not absolute");
  const projectReal = await realpath(projectDir);
  if (!inside(outputReal, projectReal) || !inside(projectReal, statePath)) {
    throw new Error("project is outside output root");
  }
  return projectReal;
}

async function verifiedSnapshot(state, projectReal) {
  if (!state.source_snapshot_path && !state.source_snapshot_sha256) return null;
  const snapshotPath = path.resolve(state.source_snapshot_path || "");
  if (snapshotPath !== path.join(projectReal, "state", "source_snapshot.json")) {
    throw new Error("snapshot path is not canonical");
  }
  const snapshotFile = await jsonFile(snapshotPath);
  if (state.source_snapshot_sha256 !== snapshotFile.sha256) throw new Error("snapshot hash mismatch");
  if (
    snapshotFile.document.run_id && snapshotFile.document.run_id !== state.run_id ||
    snapshotFile.document.run_mode && snapshotFile.document.run_mode !== state.run_mode
  ) throw new Error("snapshot identity mismatch");
  return snapshotFile.document;
}

async function verifiedCandidateFile({ candidatePath, originRoot, sha256: expectedSha256, width, height }) {
  const lexical = path.resolve(candidatePath || "");
  const [candidateReal, candidateInfo, candidateLink] = await Promise.all([
    realpath(lexical),
    stat(lexical),
    lstat(lexical),
  ]);
  if (
    candidateReal !== lexical ||
    !candidateInfo.isFile() ||
    candidateLink.isSymbolicLink() ||
    !inside(originRoot, candidateReal)
  ) throw new Error("candidate path is not canonical");
  const [actualSha256, dimensions] = await Promise.all([
    sha256File(candidateReal),
    readImageDimensions(candidateReal, candidateInfo.size),
  ]);
  if (
    !dimensions?.width ||
    !dimensions?.height ||
    expectedSha256 !== undefined && (
      typeof expectedSha256 !== "string" || expectedSha256 !== actualSha256
    ) ||
    Number.isFinite(width) && width !== dimensions.width ||
    Number.isFinite(height) && height !== dimensions.height
  ) throw new Error("candidate file does not match recorded state");
  return { path: candidateReal, info: candidateInfo, sha256: actualSha256, dimensions };
}

function candidateRecord({
  runId,
  runMode,
  catalogPath,
  catalogKind,
  projectRoot,
  nativeId,
  file,
  slide,
  sourcePageId = null,
  lineage = {},
}) {
  const result = {
    candidate_id: null,
    native_candidate_id: nativeId,
    run_id: runId,
    run_mode: runMode,
    handoff_path: catalogPath,
    catalog_kind: catalogKind,
    project_root: projectRoot,
    origin_root: path.join(projectRoot, "origin_image"),
    file_sha256: file.sha256,
    path: file.path,
    slide_uid: slide.slide_uid,
    page_id: slide.page_id,
    source_page_id: pageId(sourcePageId) || slide.page_id,
    width: file.dimensions.width,
    height: file.dimensions.height,
    size_bytes: file.info.size,
    generated_at: new Date(file.info.mtimeMs).toISOString(),
    derivation_kind: lineage.derivation_kind || "generated",
    parent_candidate_id: lineage.parent_candidate_id || null,
    selection_ref: {
      run_id: runId,
      handoff_path: catalogPath,
      native_candidate_id: nativeId,
    },
  };
  result.candidate_id = sourceCandidateId(result);
  return result;
}

async function verifyHandoff(deck, handoffPath, outputReal) {
  const handoffFile = await jsonFile(handoffPath);
  const handoff = handoffFile.document;
  if (
    !STATE_FILE_BY_MODE.has(handoff.run_mode) ||
    typeof handoff.run_id !== "string" ||
    !handoff.run_id ||
    handoff.pipeline_status !== "completed" ||
    !["candidate_ready", "accepted"].includes(handoff.status)
  ) throw new Error("handoff is not candidate-ready");

  const projectReal = await verifiedProjectRoot(outputReal, handoff.project_dir, handoffPath);
  if (handoffPath !== path.join(projectReal, "state", "handoff.json")) {
    throw new Error("handoff path is not canonical");
  }
  const statePath = path.resolve(handoff.state_ref?.path || "");
  const snapshotPath = path.resolve(handoff.source_snapshot_ref?.path || "");
  if (
    path.dirname(statePath) !== path.join(projectReal, "state") ||
    path.basename(statePath) !== STATE_FILE_BY_MODE.get(handoff.run_mode) ||
    snapshotPath !== path.join(projectReal, "state", "source_snapshot.json")
  ) throw new Error("handoff refs are not canonical");
  const [stateFile, snapshotFile] = await Promise.all([jsonFile(statePath), jsonFile(snapshotPath)]);
  const state = stateFile.document;
  const snapshot = snapshotFile.document;
  if (
    handoff.state_ref.sha256 !== stateFile.sha256 ||
    handoff.source_snapshot_ref.sha256 !== snapshotFile.sha256 ||
    state.run_id !== handoff.run_id ||
    state.run_mode !== handoff.run_mode ||
    state.status !== "completed" ||
    snapshot.run_id !== handoff.run_id ||
    snapshot.run_mode !== handoff.run_mode ||
    state.source_snapshot_path !== snapshotPath ||
    state.source_snapshot_sha256 !== snapshotFile.sha256
  ) throw new Error("handoff refs do not match state");

  const slides = new Map(deck.outline.slides.map((slide) => [slide.slide_uid, slide]));
  const originRoot = path.join(projectReal, "origin_image");
  const candidates = [];
  for (const candidate of Array.isArray(handoff.candidates) ? handoff.candidates : []) {
    try {
      const slide = slides.get(candidate?.slide_uid);
      const nativeId = typeof candidate?.candidate_id === "string" ? candidate.candidate_id : "";
      if (
        !slide ||
        !nativeId ||
        candidate.deck_uid !== deck.outline.deck_uid ||
        pageId(candidate.page_id) !== pageId(slide.page_id) ||
        !identityMatches(handoff.slide_identity, deck, slide.slide_uid, slide.page_id) ||
        !identityMatches(snapshot.slide_identity, deck, slide.slide_uid, slide.page_id) ||
        !["candidate_ready", "accepted"].includes(candidate.status)
      ) throw new Error("candidate identity mismatch");
      if (
        handoff.run_mode === "fast_8x1_diverse" && pageId(state.anchor_page_id) !== pageId(slide.page_id) ||
        handoff.run_mode === "fast_4x3_anchored" &&
          ![state.anchor_page_id, ...(state.follower_page_ids || [])].some((item) => pageId(item) === pageId(slide.page_id)) ||
        handoff.run_mode === "selected_style_expansion" &&
          !Object.keys(state.pages || {}).some((item) => pageId(item) === pageId(slide.page_id)) ||
        handoff.run_mode === "single_image_edit" &&
          (state.identity?.deck_uid !== deck.outline.deck_uid ||
            state.identity?.slide_uid !== slide.slide_uid ||
            pageId(state.identity?.page_id) !== pageId(slide.page_id))
      ) throw new Error("state identity mismatch");
      const file = await verifiedCandidateFile({
        candidatePath: candidate.path,
        originRoot,
        sha256: candidate.sha256,
        width: candidate.width,
        height: candidate.height,
      });
      candidates.push(candidateRecord({
        runId: handoff.run_id,
        runMode: handoff.run_mode,
        catalogPath: handoffPath,
        catalogKind: "handoff",
        projectRoot: projectReal,
        nativeId,
        file,
        slide,
        sourcePageId: candidate.page_id,
        lineage: {
          derivation_kind: candidate.derivation_kind || handoff.lineage?.derivation_kind,
          parent_candidate_id: candidate.parent_candidate_id || handoff.lineage?.parent_candidate_id,
        },
      }));
    } catch {
      // One missing or changed image does not invalidate the other candidates.
    }
  }
  return candidates;
}

function historicalRows(state) {
  if (state.run_mode === "selected_style_expansion") {
    return Object.entries(state.pages || {}).map(([key, record]) => ({
      page_id: record?.page_id || key,
      status: record?.status,
      path: record?.final_path,
      sha256: record?.source_sha256,
      width: record?.source_width,
      height: record?.source_height,
      native_id: record?.candidate_id || record?.tool_call_id || `page:${pageId(record?.page_id || key)}`,
      derivation_kind: "selected_style_expansion",
      parent_candidate_id: null,
    }));
  }
  if (["fast_8x1_diverse", "fast_4x3_anchored"].includes(state.run_mode)) {
    const rows = [];
    for (const [styleId, style] of Object.entries(state.styles || {})) {
      for (const [key, record] of Object.entries(style?.pages || {})) {
        rows.push({
          page_id: key,
          status: record?.status,
          path: record?.final_path,
          sha256: record?.source_sha256,
          width: record?.source_width,
          height: record?.source_height,
          native_id: record?.candidate_id || record?.tool_call_id || `style:${styleId}:page:${pageId(key)}`,
          derivation_kind: "generated",
          parent_candidate_id: null,
        });
      }
    }
    return rows;
  }
  return [];
}

async function verifyHistoricalState(deck, statePath, outputReal) {
  const stateFile = await jsonFile(statePath);
  const state = stateFile.document;
  if (
    !HISTORICAL_STATE_FILES.has(path.basename(statePath)) ||
    STATE_FILE_BY_MODE.get(state.run_mode) !== path.basename(statePath) ||
    typeof state.run_id !== "string" ||
    !state.run_id ||
    !["completed", "attention_required"].includes(state.status) ||
    state.status === "attention_required" && state.run_mode !== "selected_style_expansion"
  ) throw new Error("state is not a completed historical run");
  const projectReal = await verifiedProjectRoot(outputReal, state.project_dir, statePath);
  if (statePath !== path.join(projectReal, "state", path.basename(statePath))) {
    throw new Error("state path is not canonical");
  }
  const snapshot = await verifiedSnapshot(state, projectReal);
  const identity = snapshot?.slide_identity;
  const historicalSlides = await historicalSlideMap(deck, snapshot, projectReal);
  const originRoot = path.join(projectReal, "origin_image");
  const candidates = [];
  for (const row of historicalRows(state)) {
    try {
      const slide = historicalSlides.get(pageId(row.page_id)) || slideForPage(deck, row.page_id);
      if (
        !slide ||
        !["candidate_ready", "accepted"].includes(row.status) ||
        !identityAllowsHistoricalPage(identity, deck, slide)
      ) throw new Error("historical page identity mismatch");
      const file = await verifiedCandidateFile({
        candidatePath: row.path,
        originRoot,
        sha256: row.sha256,
        width: row.width,
        height: row.height,
      });
      candidates.push(candidateRecord({
        runId: state.run_id,
        runMode: state.run_mode,
        catalogPath: statePath,
        catalogKind: "state",
        projectRoot: projectReal,
        nativeId: String(row.native_id),
        file,
        slide,
        sourcePageId: row.page_id,
        lineage: row,
      }));
    } catch {
      // Only accepted, hash-matching files from the bound project are restored.
    }
  }
  return candidates;
}

async function verifyDeliveryImages(deck, runRoot, outputReal, pageOverrides = new Map()) {
  const name = path.basename(runRoot);
  const manifestPath = path.join(runRoot, "state", "final_selection_manifest.json");
  let catalogPath = null;
  try {
    catalogPath = (await jsonFile(manifestPath)).path;
  } catch {
    if (!/(?:^|[_-])final(?:[_-]|$)/i.test(name)) return [];
  }
  const projectReal = await realpath(runRoot);
  if (!inside(outputReal, projectReal)) throw new Error("delivery project is outside output root");
  const originRoot = path.join(projectReal, "origin_image");
  const entries = await readdir(originRoot, { withFileTypes: true });
  const candidates = [];
  for (const entry of entries) {
    try {
      if (!entry.isFile() || entry.isSymbolicLink() || !IMAGE_EXTENSIONS.has(path.extname(entry.name).toLowerCase())) {
        continue;
      }
      const sourcePageId = pageIdFromFilename(entry.name);
      const slide = pageOverrides.get(sourcePageId) || slideForPage(deck, sourcePageId);
      if (!slide) continue;
      const file = await verifiedCandidateFile({
        candidatePath: path.join(originRoot, entry.name),
        originRoot,
      });
      candidates.push(candidateRecord({
        runId: `delivery:${name}`,
        runMode: "final_delivery",
        catalogPath: catalogPath || file.path,
        catalogKind: "delivery",
        projectRoot: projectReal,
        nativeId: `delivery:${entry.name}`,
        file,
        slide,
        sourcePageId,
        lineage: { derivation_kind: "final_delivery" },
      }));
    } catch {
      // An unreadable delivery image does not hide verified siblings.
    }
  }
  return candidates;
}

async function verifyManifestSources(deck, runRoot, outputReal, pageOverrides = new Map()) {
  const runReal = await realpath(runRoot);
  if (
    !inside(outputReal, runReal) ||
    !/(?:^|[_-])final(?:[_-]|$)/i.test(path.basename(runReal))
  ) throw new Error("final selection manifest is outside an aggregation run");
  const manifestPath = path.join(runReal, "state", "final_selection_manifest.json");
  const manifestFile = await jsonFile(manifestPath);
  if (manifestFile.path !== manifestPath) throw new Error("final selection manifest is not canonical");
  const manifest = manifestFile.document;
  if (
    manifest.status !== "complete" ||
    manifest.record_kind !== "accepted_latest_page_aggregation" ||
    !Array.isArray(manifest.page_order) ||
    !path.isAbsolute(manifest.base_project || "")
  ) throw new Error("final selection manifest is not complete");
  const candidates = [];
  for (const rawPageId of manifest.page_order) {
    try {
      const sourcePageId = pageId(rawPageId);
      const sourcePageKey = sourcePageId?.slice(1).padStart(2, "0");
      const sourceProject =
        manifest.explicit_resets?.[sourcePageKey]?.project ||
        manifest.overrides?.[sourcePageKey]?.project ||
        manifest.base_project;
      if (!sourcePageId || !path.isAbsolute(sourceProject || "")) continue;
      const projectReal = await realpath(sourceProject);
      if (!inside(outputReal, projectReal)) continue;
      const originRoot = path.join(projectReal, "origin_image");
      const matches = (await readdir(originRoot, { withFileTypes: true })).filter((entry) => (
        entry.isFile() &&
        !entry.isSymbolicLink() &&
        IMAGE_EXTENSIONS.has(path.extname(entry.name).toLowerCase()) &&
        pageIdFromFilename(entry.name) === sourcePageId
      ));
      if (matches.length !== 1) continue;
      const slide = pageOverrides.get(sourcePageId) || slideForPage(deck, sourcePageId);
      if (!slide) continue;
      const file = await verifiedCandidateFile({
        candidatePath: path.join(originRoot, matches[0].name),
        originRoot,
      });
      candidates.push(candidateRecord({
        runId: `manifest:${path.basename(runRoot)}:${sourcePageId}`,
        runMode: "final_selection_manifest",
        catalogPath: manifestFile.path,
        catalogKind: "manifest",
        projectRoot: projectReal,
        nativeId: `manifest:${sourcePageId}:${matches[0].name}`,
        file,
        slide,
        sourcePageId,
        lineage: { derivation_kind: "accepted_latest_manifest" },
      }));
    } catch {
      // A missing historical source invalidates only that manifest page.
    }
  }
  return candidates;
}

function refKey(ref) {
  return JSON.stringify([ref.run_id, path.resolve(ref.handoff_path), ref.native_candidate_id]);
}

function deduplicateCandidates(deck, candidates) {
  const groups = new Map();
  for (const candidate of candidates) {
    const key = JSON.stringify([candidate.slide_uid, candidate.file_sha256]);
    if (!groups.has(key)) groups.set(key, []);
    const sources = groups.get(key);
    if (!sources.some((source) => source.path === candidate.path)) sources.push(candidate);
  }
  const result = [];
  for (const sources of groups.values()) {
    const priority = { handoff: 4, state: 3, manifest: 2, delivery: 1 };
    sources.sort((left, right) => (
      (priority[right.catalog_kind] || 0) - (priority[left.catalog_kind] || 0) ||
      right.generated_at.localeCompare(left.generated_at)
    ));
    const representative = { ...sources[0] };
    representative.candidate_id = groupedCandidateId(
      deck.outline.deck_uid,
      representative.slide_uid,
      representative.file_sha256,
    );
    representative.duplicate_source_count = sources.length;
    representative.duplicate_sources = sources.map((source) => ({ ...source }));
    result.push(representative);
  }
  result.sort((left, right) => right.generated_at.localeCompare(left.generated_at));
  return result;
}

export async function scanStudioCandidates(deck, { diagnostics = null } = {}) {
  let outputReal;
  try {
    outputReal = await realpath(deck.output_root);
  } catch {
    return [];
  }
  const entries = await readdir(outputReal, { withFileTypes: true });
  const candidates = [];
  const acceptedRoots = new Set();
  const counts = {
    runs_seen: 0,
    handoff_runs: 0,
    historical_runs: 0,
    manifest_runs: 0,
    delivery_runs: 0,
    rejected_runs: 0,
  };
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
    counts.runs_seen += 1;
    const runRoot = path.join(outputReal, entry.name);
    let accepted = false;
    const handoffPath = path.join(runRoot, "state", "handoff.json");
    try {
      const found = await verifyHandoff(deck, handoffPath, outputReal);
      if (found.length) {
        candidates.push(...found);
        counts.handoff_runs += 1;
        accepted = true;
      }
    } catch {
      // Historical runs are checked against their authoritative state below.
    }
    for (const stateName of HISTORICAL_STATE_FILES) {
      try {
        const found = await verifyHistoricalState(deck, path.join(runRoot, "state", stateName), outputReal);
        if (found.length) {
          candidates.push(...found);
          counts.historical_runs += 1;
          accepted = true;
        }
      } catch {
        // Foreign, running, incomplete and tampered state stays out of the catalog.
      }
    }
    if (accepted) acceptedRoots.add(entry.name);
    else counts.rejected_runs += 1;
  }
  const overrideTargets = new Map();
  for (const candidate of candidates.filter((item) => item.catalog_kind === "state")) {
    if (candidate.source_page_id === candidate.page_id) continue;
    if (!overrideTargets.has(candidate.source_page_id)) overrideTargets.set(candidate.source_page_id, new Map());
    overrideTargets.get(candidate.source_page_id).set(candidate.slide_uid, candidate);
  }
  const pageOverrides = new Map();
  for (const [sourcePageId, targets] of overrideTargets) {
    if (targets.size === 1) pageOverrides.set(sourcePageId, [...targets.values()][0]);
  }
  const deliveryPageOverrides = new Map([...pageOverrides].map(([sourcePageId, candidate]) => [
    sourcePageId,
    deck.outline.slides.find((slide) => slide.slide_uid === candidate.slide_uid),
  ]));
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
    try {
      const found = await verifyManifestSources(
        deck,
        path.join(outputReal, entry.name),
        outputReal,
        deliveryPageOverrides,
      );
      if (found.length) {
        candidates.push(...found);
        counts.manifest_runs += 1;
        if (!acceptedRoots.has(entry.name) && counts.rejected_runs > 0) counts.rejected_runs -= 1;
      }
    } catch {
      // Most run directories are not final selection manifests.
    }
    try {
      const found = await verifyDeliveryImages(
        deck,
        path.join(outputReal, entry.name),
        outputReal,
        deliveryPageOverrides,
      );
      if (found.length) {
        candidates.push(...found);
        counts.delivery_runs += 1;
        if (!acceptedRoots.has(entry.name) && counts.rejected_runs > 0) counts.rejected_runs -= 1;
      }
    } catch {
      // A non-delivery directory is not a catalog source.
    }
  }
  const deduplicated = deduplicateCandidates(deck, candidates);
  if (diagnostics && typeof diagnostics === "object") {
    const verifiedSourceCount = deduplicated.reduce(
      (total, candidate) => total + candidate.duplicate_sources.length,
      0,
    );
    Object.assign(diagnostics, counts, {
      verified_record_count: candidates.length,
      verified_source_count: verifiedSourceCount,
      candidate_count: deduplicated.length,
      duplicate_source_count: verifiedSourceCount - deduplicated.length,
    });
  }
  return deduplicated;
}

export async function buildStudioCatalog(deck, { diagnostics = null } = {}) {
  const [selection, candidates] = await Promise.all([
    readStudioSelection(deck),
    scanStudioCandidates(deck, { diagnostics }),
  ]);
  const bySlide = new Map();
  const byRef = new Map();
  for (const candidate of candidates) {
    if (!bySlide.has(candidate.slide_uid)) bySlide.set(candidate.slide_uid, []);
    bySlide.get(candidate.slide_uid).push(candidate);
    for (const source of candidate.duplicate_sources || [candidate]) {
      byRef.set(refKey(source.selection_ref), candidate);
    }
  }
  const pages = deck.outline.slides.map((slide) => {
    const pageSelection = selection.pages?.[slide.slide_uid];
    const selected = [];
    for (const ref of pageSelection?.selected_candidate_refs || []) {
      const candidate = byRef.get(refKey(ref));
      if (candidate?.slide_uid === slide.slide_uid && !selected.includes(candidate.candidate_id)) {
        selected.push(candidate.candidate_id);
      }
    }
    const selectedRefKeys = new Set((pageSelection?.selected_candidate_refs || []).map(refKey));
    const pool = (bySlide.get(slide.slide_uid) || []).map((candidate) => ({
      ...candidate,
      selected_source_refs: (candidate.duplicate_sources || [candidate])
        .map((source) => source.selection_ref)
        .filter((ref) => selectedRefKeys.has(refKey(ref))),
    }));
    return {
      page_id: slide.page_id,
      page_label: slide.page_label,
      order: slide.order,
      slide_uid: slide.slide_uid,
      title: slide.title,
      included: true,
      confirmed: selected.length > 0,
      resolution: selected.length ? "selected" : "missing",
      selected_candidate_ids: selected,
      selected_candidate_count: selected.length,
      baseline_candidate_id: null,
      candidates: pool.map((candidate) => ({ ...candidate, baseline: false })),
    };
  });
  return {
    catalog_contract_version: 1,
    deck_label: deck.label,
    deck_uid: deck.outline.deck_uid,
    pages,
  };
}

export async function resolveStudioSelection(deck, slideUid) {
  const slide = deck.outline.slides.find((item) => item.slide_uid === slideUid);
  if (!slide) return { slide: null, selection: null, candidates: [], stale: false };
  const [selection, candidates] = await Promise.all([
    readStudioSelection(deck),
    scanStudioCandidates(deck),
  ]);
  const refs = selection.pages?.[slideUid]?.selected_candidate_refs || [];
  const byRef = new Map();
  for (const candidate of candidates) {
    for (const source of candidate.duplicate_sources || [candidate]) {
      byRef.set(refKey(source.selection_ref), candidate);
    }
  }
  const selected = [];
  let resolvedRefCount = 0;
  for (const ref of refs) {
    const candidate = byRef.get(refKey(ref));
    if (candidate?.slide_uid !== slideUid) continue;
    resolvedRefCount += 1;
    if (!selected.includes(candidate)) selected.push(candidate);
  }
  return { slide, selection, candidates: selected, stale: refs.length > resolvedRefCount };
}
