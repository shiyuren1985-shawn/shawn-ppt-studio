import { createHash } from "node:crypto";
import { lstat, readFile, readdir, realpath, stat } from "node:fs/promises";
import path from "node:path";

import { readImageDimensions, sha256File } from "./selection-image-metadata.mjs";
import { readStudioSelection } from "./studio-selection-store.mjs";

const STATE_FILE_BY_MODE = new Map([
  ["fast_8x1_diverse", "style_run_state.json"],
  ["single_image_edit", "single_image_edit_state.json"],
]);

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function publicCandidateId({ run_id: runId, native_candidate_id: nativeId, file_sha256: fileSha256 }) {
  return createHash("sha256")
    .update(JSON.stringify([runId, nativeId, fileSha256]))
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

async function jsonFile(filePath) {
  const [real, info, bytes, link] = await Promise.all([
    realpath(filePath),
    stat(filePath),
    readFile(filePath),
    lstat(filePath),
  ]);
  if (real !== filePath || !info.isFile() || link.isSymbolicLink()) throw new Error("not canonical file");
  const document = JSON.parse(bytes.toString("utf8"));
  if (!document || typeof document !== "object" || Array.isArray(document)) throw new Error("invalid JSON");
  return { path: real, bytes, sha256: sha256(bytes), document };
}

async function verifyHandoff(deck, handoffPath, outputReal) {
  const handoffFile = await jsonFile(handoffPath);
  const handoff = handoffFile.document;
  if (
    !STATE_FILE_BY_MODE.has(handoff.run_mode) ||
    typeof handoff.run_id !== "string" ||
    !handoff.run_id ||
    handoff.pipeline_status !== "completed" ||
    !["candidate_ready", "accepted"].includes(handoff.status) ||
    !path.isAbsolute(handoff.project_dir)
  ) throw new Error("handoff is not candidate-ready");

  const projectReal = await realpath(handoff.project_dir);
  if (!inside(outputReal, projectReal) || handoffPath !== path.join(projectReal, "state", "handoff.json")) {
    throw new Error("handoff project is outside output root");
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
        (handoff.run_mode === "fast_8x1_diverse" && pageId(state.anchor_page_id) !== pageId(slide.page_id)) ||
        (handoff.run_mode === "single_image_edit" &&
          (state.identity?.deck_uid !== deck.outline.deck_uid ||
            state.identity?.slide_uid !== slide.slide_uid ||
            pageId(state.identity?.page_id) !== pageId(slide.page_id)))
      ) throw new Error("state identity mismatch");
      const candidatePath = path.resolve(candidate.path || "");
      const [candidateReal, candidateInfo, candidateLink] = await Promise.all([
        realpath(candidatePath),
        stat(candidatePath),
        lstat(candidatePath),
      ]);
      if (
        candidateReal !== candidatePath ||
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
        candidate.sha256 !== actualSha256 ||
        candidate.width !== dimensions.width ||
        candidate.height !== dimensions.height
      ) throw new Error("candidate file does not match handoff");
      const result = {
        candidate_id: null,
        native_candidate_id: nativeId,
        run_id: handoff.run_id,
        run_mode: handoff.run_mode,
        handoff_path: handoffPath,
        file_sha256: actualSha256,
        path: candidateReal,
        slide_uid: slide.slide_uid,
        page_id: slide.page_id,
        width: dimensions.width,
        height: dimensions.height,
        size_bytes: candidateInfo.size,
        generated_at: new Date(candidateInfo.mtimeMs).toISOString(),
        derivation_kind: candidate.derivation_kind || handoff.lineage?.derivation_kind || "generated",
        parent_candidate_id: candidate.parent_candidate_id || handoff.lineage?.parent_candidate_id || null,
        selection_ref: {
          run_id: handoff.run_id,
          handoff_path: handoffPath,
          native_candidate_id: nativeId,
        },
      };
      result.candidate_id = publicCandidateId(result);
      candidates.push(result);
    } catch {
      // A missing or changed image invalidates only that candidate. The formal
      // handoff/state stay untouched and other candidates from the run remain usable.
    }
  }
  return candidates;
}

export async function scanStudioCandidates(deck) {
  let outputReal;
  try {
    outputReal = await realpath(deck.output_root);
  } catch {
    return [];
  }
  const entries = await readdir(outputReal, { withFileTypes: true });
  const candidates = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
    const handoffPath = path.join(outputReal, entry.name, "state", "handoff.json");
    try {
      candidates.push(...await verifyHandoff(deck, handoffPath, outputReal));
    } catch {
      // Incomplete, historical, foreign, or tampered runs are not candidates.
    }
  }
  candidates.sort((left, right) => right.generated_at.localeCompare(left.generated_at));
  return candidates;
}

function refKey(ref) {
  return JSON.stringify([ref.run_id, path.resolve(ref.handoff_path), ref.native_candidate_id]);
}

export async function buildStudioCatalog(deck) {
  const [selection, candidates] = await Promise.all([
    readStudioSelection(deck),
    scanStudioCandidates(deck),
  ]);
  const bySlide = new Map();
  const byRef = new Map();
  for (const candidate of candidates) {
    if (!bySlide.has(candidate.slide_uid)) bySlide.set(candidate.slide_uid, []);
    bySlide.get(candidate.slide_uid).push(candidate);
    byRef.set(refKey(candidate.selection_ref), candidate);
  }
  const pages = deck.outline.slides.map((slide) => {
    const pageSelection = selection.pages?.[slide.slide_uid];
    const selected = [];
    for (const ref of pageSelection?.selected_candidate_refs || []) {
      const candidate = byRef.get(refKey(ref));
      if (candidate?.slide_uid === slide.slide_uid) selected.push(candidate.candidate_id);
    }
    const pool = bySlide.get(slide.slide_uid) || [];
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
  const byRef = new Map(candidates.map((candidate) => [refKey(candidate.selection_ref), candidate]));
  const selected = refs.map((ref) => byRef.get(refKey(ref))).filter(
    (candidate) => candidate?.slide_uid === slideUid,
  );
  return { slide, selection, candidates: selected, stale: refs.length > selected.length };
}
