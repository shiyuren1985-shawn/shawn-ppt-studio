import { readFile, realpath } from "node:fs/promises";
import path from "node:path";

import { HttpError } from "./errors.mjs";

function isInside(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (relative !== ".." && !relative.startsWith(`..${path.sep}`));
}

function conflict(message, code) {
  throw new HttpError(409, message, code);
}

async function readHandoff(filePath) {
  try {
    const document = JSON.parse(await readFile(filePath, "utf8"));
    if (!document || typeof document !== "object" || Array.isArray(document)) throw new Error();
    return document;
  } catch {
    return null;
  }
}

async function resolveCanonicalParent(deck, selected) {
  let selectedReal;
  try {
    selectedReal = await realpath(selected.path);
  } catch {
    conflict("这张已选图片暂时无法读取，请重新选稿。", "selected_candidate_unavailable");
  }

  const roots = [];
  for (const root of deck.candidate_roots || []) {
    try {
      roots.push({ configured: path.resolve(root.path), real: await realpath(root.path) });
    } catch {
      // One unavailable historical root must not hide another valid one.
    }
  }
  const owner = roots.find((root) => isInside(root.real, selectedReal));
  const outputRoot = owner || roots[0];
  if (!outputRoot) {
    conflict("这套 PPT 还没有可用的图片输出目录。", "candidate_root_missing");
  }

  if (owner) {
    const originDir = path.dirname(selectedReal);
    const projectDir = path.dirname(originDir);
    if (
      path.basename(originDir) === "origin_image" &&
      projectDir !== owner.real &&
      isInside(owner.real, projectDir)
    ) {
      const handoffPath = path.join(projectDir, "state", "handoff.json");
      const handoff = await readHandoff(handoffPath);
      const matches = (Array.isArray(handoff?.candidates) ? handoff.candidates : []).filter(
        (candidate) =>
          candidate &&
          typeof candidate.candidate_id === "string" &&
          path.resolve(candidate.path || "") === selectedReal &&
          (candidate.sha256 || candidate.file_sha256) === selected.file_sha256 &&
          candidate.deck_uid === deck.outline.deck_uid &&
          candidate.slide_uid === selected.slide_uid,
      );
      if (matches.length === 1) {
        return {
          mode: "handoff",
          candidate_root: owner.configured,
          handoff_path: handoffPath,
          source_candidate_id: matches[0].candidate_id,
          style_slot: matches[0].style_slot || null,
        };
      }
    }
  }

  return {
    mode: "direct",
    candidate_root: outputRoot.configured,
    source_candidate_id: selected.candidate_id,
    style_slot: null,
    direct_parent_refs: {
      deck_uid: deck.outline.deck_uid,
      slide_uid: selected.slide_uid,
      candidate_id: selected.candidate_id,
      path: selectedReal,
      sha256: selected.file_sha256,
      width: selected.width,
      height: selected.height,
      source_revision_status: selected.source_revision_status || "unrecorded",
    },
  };
}

export class SelectedImageEditParentResolver {
  constructor({ discovery, selectionProjection }) {
    this.discovery = discovery;
    this.selectionProjection = selectionProjection;
  }

  async resolveCurrent({ deckId, slideUid, candidateId, expectedPath = null, expectedSha256 = null }) {
    if (!this.selectionProjection) {
      throw new HttpError(503, "selected image service is unavailable", "selection_projection_unavailable");
    }
    const projection = await this.selectionProjection.get(deckId, slideUid);
    if (projection.status !== "selected" || projection.confirmed !== true) {
      conflict("这张图片还没有正式选定，请先去选稿。", "selected_candidate_not_confirmed");
    }
    const matches = projection.selected_candidates.filter(
      (candidate) => candidate.candidate_id === candidateId,
    );
    if (matches.length !== 1) {
      conflict("这张图片已不在当前正式选稿中，请重新选择。", "selected_candidate_not_confirmed");
    }
    const selected = { ...matches[0], slide_uid: projection.slide_uid };
    if (
      (expectedPath && selected.path !== expectedPath) ||
      (expectedSha256 && selected.file_sha256 !== expectedSha256)
    ) {
      conflict("这张已选图片已发生变化，请重新创建修改任务。", "selected_candidate_changed");
    }
    return this.#resolve({ deckId, slideUid, selected });
  }

  async resolveRecorded({
    deckId,
    slideUid,
    candidateId,
    path: selectedPath,
    fileSha256,
    width,
    height,
    sourceRevisionStatus = "unrecorded",
  }) {
    const selected = {
      candidate_id: candidateId,
      path: selectedPath,
      file_sha256: fileSha256,
      width,
      height,
      source_revision_status: sourceRevisionStatus,
      slide_uid: slideUid,
    };
    return this.#resolve({ deckId, slideUid, selected });
  }

  async #resolve({ deckId, slideUid, selected }) {
    const deck = await this.discovery.readDeck(deckId);
    const slide = deck.outline.slides.find((item) => item.slide_uid === slideUid);
    if (!slide) throw new HttpError(404, "unknown slide", "slide_not_found");
    const canonical = await resolveCanonicalParent(deck, selected);
    return {
      source: {
        deck_id: deckId,
        deck_uid: deck.outline.deck_uid,
        slide_uid: slideUid,
        page_id: slide.page_id,
        outline_path: deck.outline.path,
        expected_revision: deck.outline.revision_id,
      },
      selection: {
        candidate_id: selected.candidate_id,
        path: selected.path,
        file_sha256: selected.file_sha256,
        width: selected.width,
        height: selected.height,
        source_revision_status: selected.source_revision_status || "unrecorded",
      },
      parent: canonical,
      deck,
    };
  }
}
