import { constants as fsConstants } from "node:fs";
import { copyFile, lstat, mkdir, open, realpath, rename, unlink } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Readable } from "node:stream";

import { HttpError } from "./errors.mjs";
import {
  IMAGE_CONTENT_TYPES,
  sha256File,
  sha256FileHandle,
} from "./selection-image-metadata.mjs";
import { buildStudioCatalog } from "./studio-selection-catalog.mjs";
import { StudioSelectionStore } from "./studio-selection-store.mjs";

const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

function loopbackOrigin(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("selector origin is invalid");
  }
  if (
    parsed.protocol !== "http:" ||
    !["127.0.0.1", "localhost", "::1", "[::1]"].includes(parsed.hostname)
  ) {
    throw new Error("selector origin must be loopback HTTP");
  }
  return parsed;
}

function stringList(value) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter((item) => typeof item === "string" && item))];
}

function candidatePreviewUrl(deckId, candidate) {
  const params = new URLSearchParams({ sha256: candidate.file_sha256 });
  return `/api/selector-workspace/decks/${encodeURIComponent(deckId)}/candidates/${encodeURIComponent(candidate.candidate_id)}/image?${params.toString()}`;
}

function within(candidate, root) {
  const relative = path.relative(root, candidate);
  return relative === "" || (relative !== ".." && !relative.startsWith(`..${path.sep}`));
}

function allowedCandidateRoots(deck) {
  return (deck.candidate_roots || [])
    .map((root) => root?.path)
    .filter((value) => typeof value === "string" && path.isAbsolute(value))
    .map((value) => path.resolve(value));
}

function privateCandidateFiles(rawCatalog) {
  const files = new Map();
  for (const page of Array.isArray(rawCatalog?.pages) ? rawCatalog.pages : []) {
    for (const candidate of Array.isArray(page?.candidates) ? page.candidates : []) {
      const candidateId = String(candidate?.candidate_id || "");
      const fileSha256 = String(candidate?.file_sha256 || "");
      const sourcePath = typeof candidate?.path === "string" ? candidate.path : "";
      if (
        /^[a-f0-9]{24}$/.test(candidateId) &&
        /^[a-f0-9]{64}$/.test(fileSha256) &&
        path.isAbsolute(sourcePath)
      ) {
        const rawSources = Array.isArray(candidate.duplicate_sources) && candidate.duplicate_sources.length
          ? candidate.duplicate_sources
          : [candidate];
        const sourcesByPath = new Map();
        for (const rawSource of rawSources) {
          const rawCandidateId = String(rawSource?.candidate_id || "");
          const rawPath = typeof rawSource?.path === "string" ? rawSource.path : "";
          if (!/^[a-f0-9]{24}$/.test(rawCandidateId) || !path.isAbsolute(rawPath)) continue;
          const resolvedPath = path.resolve(rawPath);
          sourcesByPath.set(resolvedPath, {
            candidate_id: rawCandidateId,
            file_sha256: fileSha256,
            path: resolvedPath,
            project_root: typeof rawSource.project_root === "string"
              ? path.resolve(rawSource.project_root)
              : null,
            origin_root: typeof rawSource.origin_root === "string"
              ? path.resolve(rawSource.origin_root)
              : null,
            catalog_path: typeof rawSource.handoff_path === "string"
              ? path.resolve(rawSource.handoff_path)
              : null,
            run_id: typeof rawSource.run_id === "string" ? rawSource.run_id : null,
            native_candidate_id: typeof rawSource.native_candidate_id === "string"
              ? rawSource.native_candidate_id
              : null,
          });
        }
        const resolvedSourcePath = path.resolve(sourcePath);
        if (!sourcesByPath.has(resolvedSourcePath)) {
          sourcesByPath.set(resolvedSourcePath, {
            candidate_id: candidateId,
            file_sha256: fileSha256,
            path: resolvedSourcePath,
            project_root: typeof candidate.project_root === "string"
              ? path.resolve(candidate.project_root)
              : null,
            origin_root: typeof candidate.origin_root === "string"
              ? path.resolve(candidate.origin_root)
              : null,
            catalog_path: typeof candidate.handoff_path === "string"
              ? path.resolve(candidate.handoff_path)
              : null,
            run_id: typeof candidate.run_id === "string" ? candidate.run_id : null,
            native_candidate_id: typeof candidate.native_candidate_id === "string"
              ? candidate.native_candidate_id
              : null,
          });
        }
        files.set(candidateId, {
          candidate_id: candidateId,
          file_sha256: fileSha256,
          path: resolvedSourcePath,
          sources: [...sourcesByPath.values()],
          run_id: typeof candidate.run_id === "string" ? candidate.run_id : null,
          handoff_path: typeof candidate.handoff_path === "string" ? candidate.handoff_path : null,
          native_candidate_id: typeof candidate.native_candidate_id === "string"
            ? candidate.native_candidate_id
            : null,
          project_root: typeof candidate.project_root === "string"
            ? path.resolve(candidate.project_root)
            : null,
          origin_root: typeof candidate.origin_root === "string"
            ? path.resolve(candidate.origin_root)
            : null,
          selected_source_refs: Array.isArray(candidate.selected_source_refs)
            ? candidate.selected_source_refs.filter((ref) => (
              ref &&
              typeof ref.run_id === "string" &&
              typeof ref.handoff_path === "string" &&
              path.isAbsolute(ref.handoff_path) &&
              typeof ref.native_candidate_id === "string"
            )).map((ref) => ({
              run_id: ref.run_id,
              handoff_path: path.resolve(ref.handoff_path),
              native_candidate_id: ref.native_candidate_id,
            }))
            : [],
        });
      }
    }
  }
  return files;
}

async function unusedTrashPath(trashRoot, sourcePath) {
  const parsed = path.parse(sourcePath);
  for (let index = 1; index < 10_000; index += 1) {
    const suffix = index === 1 ? "" : ` ${index}`;
    const target = path.join(trashRoot, `${parsed.name}${suffix}${parsed.ext}`);
    try {
      await lstat(target);
    } catch (error) {
      if (error?.code === "ENOENT") return target;
      throw error;
    }
  }
  throw new Error("trash destination unavailable");
}

async function moveToTrash(sourcePath, trashRoot) {
  await mkdir(trashRoot, { recursive: true });
  const target = await unusedTrashPath(trashRoot, sourcePath);
  try {
    await rename(sourcePath, target);
  } catch (error) {
    if (error?.code !== "EXDEV") throw error;
    await copyFile(sourcePath, target, fsConstants.COPYFILE_EXCL);
    await unlink(sourcePath);
  }
  return target;
}

async function restoreFromTrash(targetPath, sourcePath) {
  try {
    await rename(targetPath, sourcePath);
  } catch (error) {
    if (error?.code !== "EXDEV") throw error;
    await copyFile(targetPath, sourcePath, fsConstants.COPYFILE_EXCL);
    await unlink(targetPath);
  }
}

function publicCandidate(deckId, page, candidate) {
  const selectedIds = new Set(stringList(page.selected_candidate_ids));
  const candidateId = String(candidate.candidate_id || "");
  const fileSha256 = String(candidate.file_sha256 || "");
  if (!/^[a-f0-9]{24}$/.test(candidateId) || !/^[a-f0-9]{64}$/.test(fileSha256)) {
    return null;
  }
  const selectedIndex = page.selected_candidate_ids?.indexOf(candidateId) ?? -1;
  const selected = selectedIds.has(candidateId) || (
    page.confirmed === true &&
    page.resolution === "baseline" &&
    candidate.baseline === true
  );
  return {
    candidate_id: candidateId,
    file_sha256: fileSha256,
    preview_url: candidatePreviewUrl(deckId, candidate),
    selected,
    selected_order: selectedIndex >= 0 ? selectedIndex + 1 : (selected ? 1 : null),
    previous_version: candidate.baseline === true,
    source_count: Math.max(1, Number(candidate.duplicate_source_count) || 1),
    width: Number.isFinite(candidate.width) ? candidate.width : null,
    height: Number.isFinite(candidate.height) ? candidate.height : null,
    generated_at: typeof candidate.generated_at === "string" ? candidate.generated_at : null,
  };
}

function publicPage(deckId, page) {
  const candidates = (Array.isArray(page.candidates) ? page.candidates : [])
    .map((candidate) => publicCandidate(deckId, page, candidate))
    .filter(Boolean);
  return {
    slide_uid: page.slide_uid,
    page_id: page.page_id || null,
    page_label: page.page_label || null,
    order: Number.isFinite(page.order) ? page.order : null,
    title: page.title || "未命名页面",
    included: page.included !== false,
    confirmed: page.confirmed === true,
    resolution: ["selected", "baseline", "missing"].includes(page.resolution)
      ? page.resolution
      : "missing",
    selected_candidate_ids: stringList(page.selected_candidate_ids),
    selected_count: candidates.filter((candidate) => candidate.selected).length,
    baseline_available: typeof page.baseline_candidate_id === "string" && page.baseline_candidate_id !== "",
    candidate_count: candidates.length,
    candidates,
  };
}

function normalizeCatalog(deckId, expectedDeckUid, catalog, sourceKind = "legacy") {
  if (!catalog || typeof catalog !== "object" || !Array.isArray(catalog.pages)) {
    throw new HttpError(502, "选稿服务返回的数据无法使用", "selector_invalid_catalog");
  }
  if (catalog.deck_uid !== expectedDeckUid) {
    throw new HttpError(409, "选稿记录与当前 PPT 不一致", "selector_deck_mismatch");
  }
  const pages = catalog.pages
    .map((page) => publicPage(deckId, page))
    .sort((left, right) => (left.order ?? Number.MAX_SAFE_INTEGER) - (right.order ?? Number.MAX_SAFE_INTEGER));
  return {
    contract_version: 1,
    deck_id: deckId,
    deck_uid: expectedDeckUid,
    source_kind: sourceKind === "studio" ? "studio" : "legacy",
    label: catalog.deck_label || catalog.app_name || deckId,
    refreshed_at: new Date().toISOString(),
    summary: {
      page_count: pages.length,
      included_count: pages.filter((page) => page.included).length,
      confirmed_count: pages.filter((page) => page.included && page.confirmed).length,
      pending_count: pages.filter((page) => page.included && !page.confirmed).length,
      selected_image_count: pages.reduce(
        (total, page) => total + (page.included ? page.selected_count : 0),
        0,
      ),
    },
    pages,
  };
}

async function upstreamFailure(response) {
  // The legacy service may include absolute paths or indexing details in its
  // error text. Keep those on its stderr and return only product language.
  try {
    await response.body?.cancel();
  } catch {
    // A consumed or already closed error body needs no further handling.
  }
  const clientFailure = response.status >= 400 && response.status < 500;
  return new HttpError(
    clientFailure ? 409 : 502,
    clientFailure ? "这项选择没有保存，请刷新后再试" : "选稿服务暂时无法完成请求",
    "selector_request_failed",
  );
}

export class SelectorWorkspace {
  constructor({
    discovery,
    selectorOrigin = "http://127.0.0.1:8765/",
    fetchImpl = fetch,
    trashRoot = path.join(os.homedir(), ".Trash"),
    studioSelections = new StudioSelectionStore(),
    eventLog = null,
  }) {
    this.discovery = discovery;
    this.selectorOrigin = loopbackOrigin(selectorOrigin);
    this.fetch = fetchImpl;
    this.trashRoot = path.resolve(trashRoot);
    this.studioSelections = studioSelections;
    this.eventLog = eventLog;
    this.snapshots = new Map();
    this.candidateFiles = new Map();
    this.refreshes = new Map();
  }

  #record(type, fields = {}) {
    return this.eventLog?.record(type, fields) || Promise.resolve(null);
  }

  health() {
    return {
      ready: true,
      refreshed_deck_count: this.snapshots.size,
    };
  }

  async #deck(deckId) {
    if (!this.discovery) {
      throw new HttpError(503, "PPT 列表暂时不可用", "deck_discovery_unavailable");
    }
    return this.discovery.readDeck(deckId);
  }

  async #requestJson(pathname, init = {}) {
    const target = new URL(pathname, this.selectorOrigin);
    let response;
    try {
      response = await this.fetch(target, {
        ...init,
        signal: AbortSignal.timeout(120_000),
      });
    } catch {
      throw new HttpError(503, "选稿服务暂时没有启动", "selector_unavailable");
    }
    if (!response.ok) throw await upstreamFailure(response);
    try {
      return await response.json();
    } catch {
      throw new HttpError(502, "选稿服务返回的数据无法读取", "selector_invalid_response");
    }
  }

  async #acceptCatalog(deckId, rawCatalog) {
    const deck = await this.#deck(deckId);
    const snapshot = normalizeCatalog(deckId, deck.outline.deck_uid, rawCatalog, deck.source_kind);
    this.candidateFiles.set(deckId, privateCandidateFiles(rawCatalog));
    this.snapshots.set(deckId, snapshot);
    return snapshot;
  }

  snapshot(deckId) {
    const snapshot = this.snapshots.get(deckId);
    if (!snapshot) {
      throw new HttpError(409, "请先刷新一次选稿内容", "selector_refresh_required");
    }
    return snapshot;
  }

  slide(deckId, slideUid) {
    const snapshot = this.snapshot(deckId);
    const page = snapshot.pages.find((item) => item.slide_uid === slideUid);
    if (!page) throw new HttpError(404, "没有找到这一页", "slide_not_found");
    return {
      contract_version: snapshot.contract_version,
      deck_id: snapshot.deck_id,
      deck_uid: snapshot.deck_uid,
      refreshed_at: snapshot.refreshed_at,
      page,
    };
  }

  async refresh(deckId) {
    const running = this.refreshes.get(deckId);
    if (running) return running;
    const refresh = (async () => {
      const deck = await this.#deck(deckId);
      if (deck.source_kind === "studio") {
        const diagnostics = {};
        const catalog = await buildStudioCatalog(deck, { diagnostics });
        await this.#record("selector_catalog_scan_completed", {
          deck_id: deckId,
          ...diagnostics,
        });
        return this.#acceptCatalog(deckId, catalog);
      }
      const query = new URLSearchParams({ deck: deckId });
      return this.#acceptCatalog(deckId, await this.#requestJson(`/api/catalog?${query}`));
    })();
    this.refreshes.set(deckId, refresh);
    try {
      return await refresh;
    } finally {
      if (this.refreshes.get(deckId) === refresh) this.refreshes.delete(deckId);
    }
  }

  async #mutate(deckId, pathname, body) {
    await this.#deck(deckId);
    const catalog = await this.#requestJson(pathname, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ deck_id: deckId, ...body }),
    });
    return this.#acceptCatalog(deckId, catalog);
  }

  async select(deckId, slideUid, { candidate_id: candidateId, selected }) {
    if (!/^[a-f0-9]{24}$/.test(candidateId || "") || typeof selected !== "boolean") {
      throw new HttpError(400, "请选择一张有效图片", "invalid_selection");
    }
    const page = this.slide(deckId, slideUid).page;
    if (!page.candidates.some((candidate) => candidate.candidate_id === candidateId)) {
      throw new HttpError(409, "这张图片已不在当前候选中，请刷新后再试", "candidate_not_current");
    }
    const deck = await this.#deck(deckId);
    if (deck.source_kind === "studio") {
      const source = this.candidateFiles.get(deckId)?.get(candidateId);
      if (!source?.run_id || !source?.handoff_path || !source?.native_candidate_id) {
        throw new HttpError(409, "这张图片已不在当前候选中，请刷新后再试", "candidate_not_current");
      }
      await this.studioSelections.setCandidate(
        deck,
        slideUid,
        {
          run_id: source.run_id,
          handoff_path: source.handoff_path,
          native_candidate_id: source.native_candidate_id,
        },
        selected,
      );
      return this.#acceptCatalog(deckId, await buildStudioCatalog(deck));
    }
    return this.#mutate(deckId, "/api/select", {
      slide_uid: slideUid,
      candidate_id: candidateId,
      selected,
    });
  }

  async useBaseline(deckId, slideUid) {
    const deck = await this.#deck(deckId);
    if (deck.source_kind === "studio") {
      throw new HttpError(409, "新项目没有上一版图片，请直接选择当前候选。", "baseline_unavailable");
    }
    const page = this.slide(deckId, slideUid).page;
    if (!page.baseline_available) {
      throw new HttpError(409, "这一页没有可沿用的上一版图片", "baseline_unavailable");
    }
    return this.#mutate(deckId, "/api/use-baseline", { slide_uid: slideUid });
  }

  async include(deckId, slideUid, included) {
    const deck = await this.#deck(deckId);
    if (deck.source_kind === "studio") {
      throw new HttpError(409, "新项目暂不支持排除页面。", "studio_include_unavailable");
    }
    this.slide(deckId, slideUid);
    if (typeof included !== "boolean") {
      throw new HttpError(400, "included must be a boolean", "invalid_include_value");
    }
    return this.#mutate(deckId, "/api/include-page", { slide_uid: slideUid, included });
  }

  async confirmDefaults(deckId) {
    const deck = await this.#deck(deckId);
    if (deck.source_kind === "studio") {
      throw new HttpError(409, "新项目没有上一版图片，请逐页选择当前候选。", "baseline_unavailable");
    }
    return this.#mutate(deckId, "/api/confirm-defaults", {});
  }

  #removeCandidateFromSnapshot(deckId, slideUid, candidateId, fileSha256) {
    const current = this.snapshot(deckId);
    const pages = current.pages.map((page) => {
      if (page.slide_uid !== slideUid) return page;
      const removed = page.candidates.find((candidate) => (
        candidate.candidate_id === candidateId || candidate.file_sha256 === fileSha256
      ));
      const candidates = page.candidates.filter((candidate) => (
        candidate.candidate_id !== candidateId && candidate.file_sha256 !== fileSha256
      ));
      const candidateIds = new Set(candidates.map((candidate) => candidate.candidate_id));
      const selectedCandidateIds = page.selected_candidate_ids.filter((id) => candidateIds.has(id));
      let confirmed = page.confirmed;
      let resolution = page.resolution;
      if (resolution === "selected" && selectedCandidateIds.length === 0) {
        confirmed = false;
        resolution = "missing";
      }
      if (resolution === "baseline" && removed?.previous_version === true) {
        confirmed = false;
        resolution = "missing";
      }
      return {
        ...page,
        confirmed,
        resolution,
        selected_candidate_ids: selectedCandidateIds,
        selected_count: candidates.filter((candidate) => candidate.selected).length,
        baseline_available: removed?.previous_version === true ? false : page.baseline_available,
        candidate_count: candidates.length,
        candidates,
      };
    });
    const next = {
      ...current,
      refreshed_at: new Date().toISOString(),
      summary: {
        page_count: pages.length,
        included_count: pages.filter((page) => page.included).length,
        confirmed_count: pages.filter((page) => page.included && page.confirmed).length,
        pending_count: pages.filter((page) => page.included && !page.confirmed).length,
        selected_image_count: pages.reduce(
          (total, page) => total + (page.included ? page.selected_count : 0),
          0,
        ),
      },
      pages,
    };
    this.candidateFiles.get(deckId)?.delete(candidateId);
    this.snapshots.set(deckId, next);
    return next;
  }

  async trashCandidate(deckId, candidateId, options = {}) {
    const startedAt = Date.now();
    await this.#record("selector_trash_started", {
      deck_id: deckId,
      candidate_id: candidateId,
    });
    try {
      const result = await this.#trashCandidate(deckId, candidateId, options);
      await this.#record("selector_trash_completed", {
        deck_id: deckId,
        candidate_id: candidateId,
        trashed_count: result.trashed_count,
        duration_ms: Date.now() - startedAt,
      });
      return result;
    } catch (error) {
      await this.#record("selector_trash_failed", {
        deck_id: deckId,
        candidate_id: candidateId,
        duration_ms: Date.now() - startedAt,
        error_code: error?.code || null,
        error_message: error?.message || String(error),
      });
      throw error;
    }
  }

  async #trashCandidate(deckId, candidateId, { sha256, confirmed } = {}) {
    const deck = await this.#deck(deckId);
    if (
      !/^[a-f0-9]{24}$/.test(candidateId || "") ||
      !/^[a-f0-9]{64}$/.test(sha256 || "") ||
      confirmed !== true
    ) {
      throw new HttpError(400, "请再次点击“确认删除”", "trash_confirmation_required");
    }
    const snapshot = this.snapshot(deckId);
    const currentPage = snapshot.pages.find((page) => page.candidates.some((candidate) => (
      candidate.candidate_id === candidateId && candidate.file_sha256 === sha256
    )));
    const current = currentPage?.candidates.find((candidate) => (
      candidate.candidate_id === candidateId && candidate.file_sha256 === sha256
    ));
    if (!current) {
      throw new HttpError(409, "这张图片已经不在当前候选中，请刷新后再试", "candidate_not_current");
    }
    const source = this.candidateFiles.get(deckId)?.get(candidateId);
    if (!source || source.file_sha256 !== sha256) {
      throw new HttpError(409, "这张图片已经变化，请刷新后再试", "candidate_not_current");
    }
    const sourceFiles = Array.isArray(source.sources) && source.sources.length
      ? source.sources
      : [source];
    const verifiedSources = [];
    if (deck.source_kind === "studio") {
      const handoffPath = source.handoff_path ? path.resolve(source.handoff_path) : null;
      const outputReal = await realpath(deck.output_root).catch(() => null);
      for (const item of sourceFiles) {
        const projectRoot = item.project_root || source.project_root;
        const originRoot = item.origin_root || source.origin_root;
        const [sourceReal, projectReal, originReal] = await Promise.all([
          realpath(item.path).catch(() => null),
          projectRoot ? realpath(projectRoot).catch(() => null) : null,
          originRoot ? realpath(originRoot).catch(() => null) : null,
        ]);
        const catalogPath = item.catalog_path || handoffPath;
        const catalogPathIsManifest = Boolean(
          catalogPath &&
          outputReal &&
          path.basename(catalogPath) === "final_selection_manifest.json" &&
          within(catalogPath, outputReal)
        );
        const catalogPathAllowed = Boolean(
          catalogPath && projectReal && (
            catalogPath === path.join(projectReal, "state", "handoff.json") ||
            catalogPath === path.join(projectReal, "state", "style_run_state.json") ||
            catalogPath === path.join(projectReal, "state", "selected_style_run_state.json") ||
            catalogPath === path.join(projectReal, "state", "final_selection_manifest.json") ||
            catalogPathIsManifest ||
            catalogPath === sourceReal && /(?:^|[_-])final(?:[_-]|$)/i.test(path.basename(projectReal))
          )
        );
        const allowed = Boolean(
          sourceReal &&
          sourceReal === item.path &&
          outputReal &&
          projectReal &&
          originReal &&
          within(projectReal, outputReal) &&
          catalogPathAllowed &&
          within(sourceReal, originReal) &&
          await sha256File(sourceReal) === sha256
        );
        if (!allowed) {
          throw new HttpError(409, "这张图片无法移到废纸篓", "candidate_path_not_allowed");
        }
        verifiedSources.push({ ...item, path: sourceReal });
      }
    } else {
      const roots = allowedCandidateRoots(deck);
      for (const item of sourceFiles) {
        const sourceReal = await realpath(item.path).catch(() => null);
        const allowed = Boolean(
          sourceReal &&
          sourceReal === item.path &&
          roots.some((root) => within(sourceReal, root)) &&
          await sha256File(sourceReal) === sha256
        );
        if (!allowed) {
          throw new HttpError(409, "这张图片无法移到废纸篓", "candidate_path_not_allowed");
        }
        verifiedSources.push({ ...item, path: sourceReal });
      }
    }
    for (const item of verifiedSources) {
      const info = await lstat(item.path);
      if (!info.isFile() || info.isSymbolicLink()) {
        throw new HttpError(409, "这张图片无法移到废纸篓", "candidate_path_not_allowed");
      }
    }
    let selectionRestoreCandidateId = candidateId;
    let studioSelectionRestore = [];
    if (current.selected) {
      if (
        deck.source_kind === "studio" &&
        source.selected_source_refs.length
      ) {
        studioSelectionRestore = source.selected_source_refs;
        for (const ref of studioSelectionRestore) {
          await this.studioSelections.setCandidate(deck, currentPage.slide_uid, ref, false);
        }
      } else {
        const deselectedCatalog = await this.select(deckId, currentPage.slide_uid, {
          candidate_id: candidateId,
          selected: false,
        });
        selectionRestoreCandidateId = deselectedCatalog.pages
          .find((page) => page.slide_uid === currentPage.slide_uid)
          ?.candidates.find((candidate) => candidate.file_sha256 === sha256)
          ?.candidate_id || candidateId;
      }
      await this.#record("selector_trash_selection_cleared", {
        deck_id: deckId,
        candidate_id: candidateId,
        slide_uid: currentPage.slide_uid,
      });
    }
    const orderedSources = verifiedSources.toSorted((left, right) => (
      Number(left.path === source.path) - Number(right.path === source.path)
    ));
    const moved = [];
    try {
      for (const item of orderedSources) {
        moved.push({ source: item.path, target: await moveToTrash(item.path, this.trashRoot) });
      }
    } catch {
      for (const item of moved.toReversed()) {
        await restoreFromTrash(item.target, item.source).catch(() => {});
      }
      if (current.selected) {
        if (studioSelectionRestore.length) {
          for (const ref of studioSelectionRestore) {
            await this.studioSelections.setCandidate(
              deck,
              currentPage.slide_uid,
              ref,
              true,
            ).catch(() => {});
          }
        } else {
          await this.select(deckId, currentPage.slide_uid, {
            candidate_id: selectionRestoreCandidateId,
            selected: true,
          }).catch(() => {});
        }
      }
      throw new HttpError(500, "没有移到废纸篓，请稍后再试", "trash_move_failed");
    }
    const catalog = this.#removeCandidateFromSnapshot(
      deckId,
      currentPage.slide_uid,
      candidateId,
      sha256,
    );
    const targets = moved.map((item) => item.target);
    return {
      contract_version: 1,
      deleted: true,
      trashed_count: targets.length,
      trashed_name: path.basename(targets[0]),
      trashed_names: targets.map((target) => path.basename(target)),
      catalog,
    };
  }

  async streamImage(res, { deckId, candidateId, sha256 }) {
    if (!/^[a-f0-9]{24}$/.test(candidateId || "") || !/^[a-f0-9]{64}$/.test(sha256 || "")) {
      throw new HttpError(400, "图片地址无效", "invalid_candidate_image_reference");
    }
    const snapshot = this.snapshot(deckId);
    const candidate = snapshot.pages
      .flatMap((page) => page.candidates)
      .find((item) => item.candidate_id === candidateId && item.file_sha256 === sha256);
    if (!candidate) {
      throw new HttpError(404, "图片已不在当前候选中", "candidate_image_not_found");
    }
    const deck = await this.#deck(deckId);
    if (deck.source_kind === "studio") {
      const source = this.candidateFiles.get(deckId)?.get(candidateId);
      const sourceReal = source ? await realpath(source.path).catch(() => null) : null;
      const outputReal = await realpath(deck.output_root).catch(() => null);
      const contentType = sourceReal
        ? IMAGE_CONTENT_TYPES.get(path.extname(sourceReal).toLowerCase())
        : null;
      if (
        !source ||
        source.file_sha256 !== sha256 ||
        !sourceReal ||
        sourceReal !== source.path ||
        !outputReal ||
        !within(sourceReal, outputReal) ||
        !contentType
      ) {
        throw new HttpError(404, "图片已不在当前候选中", "candidate_image_not_found");
      }
      const flags = fsConstants.O_RDONLY | (fsConstants.O_NOFOLLOW || 0);
      const handle = await open(sourceReal, flags).catch(() => null);
      if (!handle) {
        throw new HttpError(404, "图片已不在当前候选中", "candidate_image_not_found");
      }
      let handedOff = false;
      try {
        const info = await handle.stat();
        if (!info.isFile() || await sha256FileHandle(handle) !== sha256) {
          throw new HttpError(404, "图片已不在当前候选中", "candidate_image_not_found");
        }
        res.writeHead(200, {
          "content-type": contentType,
          "content-length": info.size,
          "cache-control": "no-store",
          "x-content-type-options": "nosniff",
          "content-security-policy": "default-src 'none'",
        });
        const stream = handle.createReadStream({ autoClose: true });
        stream.on("error", () => {
          if (!res.destroyed) res.destroy();
        });
        res.once("error", () => stream.destroy());
        res.once("close", () => stream.destroy());
        handedOff = true;
        stream.pipe(res);
        return;
      } finally {
        if (!handedOff) await handle.close().catch(() => {});
      }
    }
    const query = new URLSearchParams({ deck: deckId, candidate: candidateId });
    let response;
    try {
      response = await this.fetch(new URL(`/api/image?${query}`, this.selectorOrigin), {
        signal: AbortSignal.timeout(120_000),
      });
    } catch {
      throw new HttpError(503, "图片暂时无法读取", "selector_unavailable");
    }
    if (!response.ok) throw await upstreamFailure(response);
    const contentType = String(response.headers.get("content-type") || "").split(";", 1)[0];
    if (!IMAGE_TYPES.has(contentType) || !response.body) {
      throw new HttpError(502, "选稿服务返回的不是可用图片", "selector_invalid_image");
    }
    const length = response.headers.get("content-length");
    const headers = {
      "content-type": contentType,
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "content-security-policy": "default-src 'none'",
    };
    if (/^\d+$/.test(length || "")) headers["content-length"] = length;
    res.writeHead(200, headers);
    const stream = Readable.fromWeb(response.body);
    stream.on("error", () => {
      if (!res.destroyed) res.destroy();
    });
    res.once("error", () => stream.destroy());
    res.once("close", () => stream.destroy());
    stream.pipe(res);
  }
}
