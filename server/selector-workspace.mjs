import { constants as fsConstants, createReadStream } from "node:fs";
import { copyFile, lstat, mkdir, realpath, rename, unlink } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Readable } from "node:stream";

import { HttpError } from "./errors.mjs";
import { IMAGE_CONTENT_TYPES, sha256File } from "./selection-image-metadata.mjs";
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

function selectorRootFromDeck(deck) {
  let current = path.dirname(deck.config_path || "");
  while (current && current !== path.dirname(current)) {
    if (path.basename(current) === "saturated-ppt") return current;
    current = path.dirname(current);
  }
  return null;
}

function allowedCandidateRoots(deck) {
  const roots = (deck.candidate_roots || [])
    .map((root) => root?.path)
    .filter((value) => typeof value === "string" && path.isAbsolute(value))
    .map((value) => path.resolve(value));
  const selectorRoot = selectorRootFromDeck(deck);
  if (selectorRoot) roots.push(path.join(selectorRoot, "data", "baseline_extracted"));
  return roots;
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
        files.set(candidateId, {
          candidate_id: candidateId,
          file_sha256: fileSha256,
          path: path.resolve(sourcePath),
          run_id: typeof candidate.run_id === "string" ? candidate.run_id : null,
          handoff_path: typeof candidate.handoff_path === "string" ? candidate.handoff_path : null,
          native_candidate_id: typeof candidate.native_candidate_id === "string"
            ? candidate.native_candidate_id
            : null,
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
  }) {
    this.discovery = discovery;
    this.selectorOrigin = loopbackOrigin(selectorOrigin);
    this.fetch = fetchImpl;
    this.trashRoot = path.resolve(trashRoot);
    this.studioSelections = studioSelections;
    this.snapshots = new Map();
    this.candidateFiles = new Map();
    this.refreshes = new Map();
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
        return this.#acceptCatalog(deckId, await buildStudioCatalog(deck));
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

  async trashCandidate(deckId, candidateId, { sha256, confirmed } = {}) {
    const deck = await this.#deck(deckId);
    if (
      !/^[a-f0-9]{24}$/.test(candidateId || "") ||
      !/^[a-f0-9]{64}$/.test(sha256 || "") ||
      confirmed !== true
    ) {
      throw new HttpError(400, "请再次点击“确认删除”", "trash_confirmation_required");
    }
    const snapshot = this.snapshot(deckId);
    const current = snapshot.pages
      .flatMap((page) => page.candidates)
      .find((candidate) => (
        candidate.candidate_id === candidateId && candidate.file_sha256 === sha256
      ));
    if (!current) {
      throw new HttpError(409, "这张图片已经不在当前候选中，请刷新后再试", "candidate_not_current");
    }
    if (current.selected) {
      throw new HttpError(409, "这张图片已经选中，请先取消选择", "selected_candidate_cannot_be_trashed");
    }
    const source = this.candidateFiles.get(deckId)?.get(candidateId);
    if (!source || source.file_sha256 !== sha256) {
      throw new HttpError(409, "这张图片已经变化，请刷新后再试", "candidate_not_current");
    }
    const sourceReal = await realpath(source.path).catch(() => null);
    let allowed = false;
    if (deck.source_kind === "studio") {
      const handoffPath = source.handoff_path ? path.resolve(source.handoff_path) : null;
      const projectRoot = handoffPath ? path.dirname(path.dirname(handoffPath)) : null;
      const [outputReal, projectReal, originReal] = await Promise.all([
        realpath(deck.output_root).catch(() => null),
        projectRoot ? realpath(projectRoot).catch(() => null) : null,
        projectRoot ? realpath(path.join(projectRoot, "origin_image")).catch(() => null) : null,
      ]);
      allowed = Boolean(
        sourceReal &&
        sourceReal === source.path &&
        outputReal &&
        projectReal &&
        originReal &&
        within(projectReal, outputReal) &&
        handoffPath === path.join(projectReal, "state", "handoff.json") &&
        within(sourceReal, originReal) &&
        await sha256File(sourceReal) === sha256
      );
    } else {
      const roots = allowedCandidateRoots(deck);
      allowed = Boolean(
        sourceReal &&
        sourceReal === source.path &&
        roots.some((root) => within(sourceReal, root))
      );
    }
    if (!allowed) {
      throw new HttpError(409, "这张图片无法移到废纸篓", "candidate_path_not_allowed");
    }
    const info = await lstat(sourceReal);
    if (!info.isFile() || info.isSymbolicLink()) {
      throw new HttpError(409, "这张图片无法移到废纸篓", "candidate_path_not_allowed");
    }
    let target;
    try {
      target = await moveToTrash(sourceReal, this.trashRoot);
    } catch {
      throw new HttpError(500, "没有移到废纸篓，请稍后再试", "trash_move_failed");
    }
    const catalog = await this.refresh(deckId);
    return {
      contract_version: 1,
      deleted: true,
      trashed_name: path.basename(target),
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
      const info = sourceReal ? await lstat(sourceReal).catch(() => null) : null;
      if (
        !source ||
        source.file_sha256 !== sha256 ||
        !sourceReal ||
        sourceReal !== source.path ||
        !outputReal ||
        !within(sourceReal, outputReal) ||
        !info?.isFile() ||
        info.isSymbolicLink() ||
        await sha256File(sourceReal) !== sha256
      ) {
        throw new HttpError(404, "图片已不在当前候选中", "candidate_image_not_found");
      }
      const contentType = IMAGE_CONTENT_TYPES.get(path.extname(sourceReal).toLowerCase());
      if (!contentType) throw new HttpError(404, "图片已不在当前候选中", "candidate_image_not_found");
      res.writeHead(200, {
        "content-type": contentType,
        "content-length": info.size,
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
        "content-security-policy": "default-src 'none'",
      });
      createReadStream(sourceReal).pipe(res);
      return;
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
    Readable.fromWeb(response.body).pipe(res);
  }
}
