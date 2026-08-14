import { createHash } from "node:crypto";
import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";

import { HttpError } from "./errors.mjs";
import {
  IMAGE_CONTENT_TYPES,
  readImageDimensions,
  sha256File,
} from "./selection-image-metadata.mjs";
import { resolveStudioSelection } from "./studio-selection-catalog.mjs";

function candidateId(filePath) {
  return createHash("sha256").update(filePath).digest("hex").slice(0, 24);
}

function isInside(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (relative !== ".." && !relative.startsWith(`..${path.sep}`));
}

function resolveSelectorPath(selectorRoot, value) {
  if (typeof value !== "string" || !value.trim()) return null;
  return path.isAbsolute(value)
    ? path.resolve(value)
    : path.resolve(selectorRoot, value);
}

async function readJson(filePath, label) {
  if (!filePath) throw new Error(`${label} path is not configured`);
  let value;
  try {
    value = JSON.parse(await readFile(filePath, "utf8"));
  } catch {
    throw new Error(`${label} is unavailable`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} is invalid`);
  }
  return value;
}

function selectorUrl(deckId, selectorOrigin) {
  const url = new URL(selectorOrigin);
  url.searchParams.set("deck", deckId);
  return url.toString();
}

function previewUrl({ deckId, slideUid, id, sha256 }) {
  const params = new URLSearchParams({
    deck_id: deckId,
    slide_uid: slideUid,
    candidate_id: id,
    sha256,
  });
  return `/api/selected-image?${params.toString()}`;
}

export class SelectionProjection {
  constructor({ discovery, selectorOrigin = "http://127.0.0.1:8765/" }) {
    this.discovery = discovery;
    this.selectorOrigin = selectorOrigin;
  }

  async #readSources(deck) {
    const selectorRoot = path.dirname(this.discovery.decksFile);
    const config = await readJson(deck.config_path, "selector deck config");
    const selection = await readJson(
      resolveSelectorPath(selectorRoot, config.selection_path),
      "selection",
    );
    const identity = await readJson(
      resolveSelectorPath(selectorRoot, config.candidate_identity_index),
      "candidate identity index",
    );
    const baseline = await readJson(
      resolveSelectorPath(selectorRoot, config.baseline_manifest),
      "baseline manifest",
    );
    return { selection, identity, baseline };
  }

  async #verifiedCandidate({ raw, deck, deckId, slideUid }) {
    const lexicalPath = path.resolve(raw.path);
    const extension = path.extname(lexicalPath).toLowerCase();
    if (!IMAGE_CONTENT_TYPES.has(extension)) throw new Error("selected file type is unsupported");

    const [fileReal, info] = await Promise.all([realpath(lexicalPath), stat(lexicalPath)]);
    if (!info.isFile()) throw new Error("selected file is unavailable");
    if (raw.source.kind === "candidate") {
      const candidateRoots = await Promise.all(deck.candidate_roots.map((root) => realpath(root.path)));
      const insideCandidateRoot = candidateRoots.some((root) => isInside(root, fileReal));
      if (!insideCandidateRoot) throw new Error("selected file is outside the registered candidate roots");
    } else if (fileReal !== await realpath(raw.allowed_exact_path)) {
      throw new Error("selected baseline file does not match its manifest");
    }

    const actualSha256 = await sha256File(fileReal);
    const dimensions = await readImageDimensions(fileReal, info.size);
    if (!dimensions?.width || !dimensions?.height) {
      throw new Error("selected image dimensions are unavailable");
    }

    const id = candidateId(raw.path);
    return {
      candidate_id: id,
      path: fileReal,
      file_sha256: actualSha256,
      width: dimensions.width,
      height: dimensions.height,
      size_bytes: info.size,
      source: raw.source,
      preview_url: previewUrl({ deckId, slideUid, id, sha256: actualSha256 }),
    };
  }

  async get(deckId, slideUid) {
    const deck = await this.discovery.readDeck(deckId);
    const slide = deck.outline.slides.find((item) => item.slide_uid === slideUid);
    if (!slide) {
      throw new HttpError(404, `unknown slide_uid for ${deckId}: ${slideUid}`, "slide_not_found");
    }

    const common = {
      contract_version: 1,
      deck_id: deckId,
      deck_uid: deck.outline.deck_uid,
      slide_uid: slideUid,
      page_id: slide.page_id,
      page_label: slide.page_label,
      title: slide.title,
      selector_url: selectorUrl(deckId, this.selectorOrigin),
    };

    if (deck.source_kind === "studio") {
      const current = await resolveStudioSelection(deck, slideUid);
      if (current.stale) {
        return {
          ...common,
          status: "unavailable",
          confirmed: true,
          resolution: "selected",
          selected_count: 0,
          selected_candidates: [],
          message: "这页的旧选稿记录仍在，但对应图片已经找不到。请在选稿页重新选择。",
        };
      }
      if (current.candidates.length === 0) {
        return {
          ...common,
          status: "empty",
          confirmed: false,
          resolution: null,
          selected_count: 0,
          selected_candidates: [],
          empty_message: "这一页还没有选定图片，先去选稿。",
        };
      }
      const selected = current.candidates.map((candidate) => ({
        candidate_id: candidate.candidate_id,
        path: candidate.path,
        file_sha256: candidate.file_sha256,
        width: candidate.width,
        height: candidate.height,
        size_bytes: candidate.size_bytes,
        source: {
          kind: "studio_handoff",
          run_id: candidate.run_id,
          run_mode: candidate.run_mode,
          handoff_path: candidate.handoff_path,
          native_candidate_id: candidate.native_candidate_id,
          derivation_kind: candidate.derivation_kind,
          parent_candidate_id: candidate.parent_candidate_id,
        },
        preview_url: previewUrl({
          deckId,
          slideUid,
          id: candidate.candidate_id,
          sha256: candidate.file_sha256,
        }),
      }));
      return {
        ...common,
        status: "selected",
        confirmed: true,
        resolution: "selected",
        selected_count: selected.length,
        selected_candidates: selected,
        message: null,
      };
    }

    let sources;
    try {
      sources = await this.#readSources(deck);
    } catch {
      return {
        ...common,
        status: "unavailable",
        confirmed: false,
        resolution: null,
        selected_count: 0,
        selected_candidates: [],
        message: "暂时无法读取这页已选的图片，请稍后重试或前往选稿页查看。",
      };
    }

    const { selection, identity, baseline } = sources;
    if (selection.deck_uid !== deck.outline.deck_uid) {
      return {
        ...common,
        status: "unavailable",
        confirmed: false,
        resolution: null,
        selected_count: 0,
        selected_candidates: [],
        message: "选稿记录与当前 PPT 不一致，请前往选稿页重新确认。",
      };
    }

    const pageState = selection.pages?.[slideUid];
    const confirmed = pageState?.confirmed === true && pageState?.included !== false;
    if (!confirmed) {
      return {
        ...common,
        status: "empty",
        confirmed: false,
        resolution: null,
        selected_count: 0,
        selected_candidates: [],
        empty_message: "这一页还没有选定图片，先去选稿。",
      };
    }

    let selectedIds = Array.isArray(pageState.selected_candidate_ids)
      ? pageState.selected_candidate_ids.filter((value) => typeof value === "string" && value)
      : [];
    if (selectedIds.length === 0 && typeof pageState.selected_candidate_id === "string") {
      selectedIds = [pageState.selected_candidate_id];
    }
    selectedIds = [...new Set(selectedIds)];

    const rawById = new Map();
    for (const [rawPath, record] of Object.entries(identity.bindings || {})) {
      if (
        record?.deck_uid !== deck.outline.deck_uid ||
        record?.slide_uid !== slideUid ||
        typeof rawPath !== "string" ||
        !path.isAbsolute(rawPath)
      ) continue;
      const normalized = path.isAbsolute(rawPath)
        ? path.resolve(rawPath)
        : path.resolve(path.dirname(this.discovery.decksFile), rawPath);
      rawById.set(candidateId(normalized), {
        path: normalized,
        source: {
          kind: "candidate",
          binding_method: record.binding_method || null,
          historical_page_id: record.historical_page_id || null,
        },
      });
    }

    const baselineItem = baseline.pages?.[slide.page_id];
    if (baselineItem?.path) {
      const baselinePath = path.isAbsolute(baselineItem.path)
        ? path.resolve(baselineItem.path)
        : path.resolve(path.dirname(this.discovery.decksFile), baselineItem.path);
      rawById.set(candidateId(baselinePath), {
        path: baselinePath,
        allowed_exact_path: baselinePath,
        source: {
          kind: "previous_deck",
          source_kind: baselineItem.source_kind || null,
        },
      });
    }

    if (selectedIds.length === 0 && pageState.resolution === "baseline" && baselineItem?.path) {
      const baselinePath = path.isAbsolute(baselineItem.path)
        ? path.resolve(baselineItem.path)
        : path.resolve(path.dirname(this.discovery.decksFile), baselineItem.path);
      selectedIds = [candidateId(baselinePath)];
    }

    if (selectedIds.length === 0) {
      return {
        ...common,
        status: "empty",
        confirmed: false,
        resolution: null,
        selected_count: 0,
        selected_candidates: [],
        empty_message: "这一页还没有选定图片，先去选稿。",
      };
    }

    // A legacy candidate id can remain in selection.json after the selector
    // catalog has stopped exposing it (for example after a UID correction).
    // Do not let that stale id hide other selections that still pass every
    // path, slide, hash and image check. A page with no verifiable ids remains
    // unavailable, and any present-but-tampered candidate still fails closed.
    const staleSelectedIds = selectedIds.filter((id) => !rawById.has(id));
    const verifiableSelectedIds = selectedIds.filter((id) => rawById.has(id));
    if (verifiableSelectedIds.length === 0) {
      return {
        ...common,
        status: "unavailable",
        confirmed: true,
        resolution: pageState.resolution || null,
        selected_count: 0,
        selected_candidates: [],
        message: "这页的旧选稿记录仍在，但对应图片已经找不到。请在选稿页重新选择。",
      };
    }

    try {
      const selected = [];
      const seenHashes = new Set();
      for (const id of verifiableSelectedIds) {
        const raw = rawById.get(id);
        const candidate = await this.#verifiedCandidate({
          raw,
          deck,
          deckId,
          slideUid,
        });
        if (candidate.candidate_id !== id) throw new Error("selected candidate identity changed");
        if (seenHashes.has(candidate.file_sha256)) continue;
        seenHashes.add(candidate.file_sha256);
        selected.push(candidate);
      }
      return {
        ...common,
        status: "selected",
        confirmed: true,
        resolution: pageState.resolution === "baseline" ? "baseline" : "selected",
        selected_count: selected.length,
        selected_candidates: selected,
        message: staleSelectedIds.length
          ? "已显示当前选中的图片；一条失效的旧记录已自动忽略。"
          : null,
      };
    } catch {
      return {
        ...common,
        status: "unavailable",
        confirmed: true,
        resolution: pageState.resolution || null,
        selected_count: 0,
        selected_candidates: [],
        message: "这页的旧选稿记录仍在，但对应图片已经找不到。请在选稿页重新选择。",
      };
    }
  }

  async resolveImage({ deckId, slideUid, candidateId: requestedId, sha256 }) {
    if (!/^[a-f0-9]{24}$/.test(requestedId || "") || !/^[a-f0-9]{64}$/.test(sha256 || "")) {
      throw new HttpError(400, "invalid selected image reference", "invalid_selected_image_reference");
    }
    const projection = await this.get(deckId, slideUid);
    if (projection.status !== "selected") {
      throw new HttpError(404, "selected image is no longer available", "selected_image_not_found");
    }
    const candidate = projection.selected_candidates.find(
      (item) => item.candidate_id === requestedId && item.file_sha256 === sha256,
    );
    if (!candidate) {
      throw new HttpError(404, "selected image is no longer selected", "selected_image_not_found");
    }
    return {
      path: candidate.path,
      content_type: IMAGE_CONTENT_TYPES.get(path.extname(candidate.path).toLowerCase()),
      size_bytes: candidate.size_bytes,
      sha256: candidate.file_sha256,
    };
  }
}
