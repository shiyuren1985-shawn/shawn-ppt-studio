import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import { HttpError } from "./errors.mjs";

const CONTRACT_VERSION = 1;

function emptySelection(deck) {
  return {
    selection_contract_version: CONTRACT_VERSION,
    deck_uid: deck.outline.deck_uid,
    outline_path: deck.outline.path,
    updated_at: null,
    pages: {},
  };
}

function selectionIdentityKey(deck) {
  return createHash("sha256")
    .update(JSON.stringify(["studio-selection", deck.outline.deck_uid]))
    .digest("hex")
    .slice(0, 24);
}

function validRoot(document) {
  return Boolean(
    document &&
    typeof document === "object" &&
    !Array.isArray(document) &&
    document.selection_contract_version === CONTRACT_VERSION &&
    typeof document.deck_uid === "string" &&
    typeof document.outline_path === "string" &&
    path.isAbsolute(document.outline_path) &&
    document.pages &&
    typeof document.pages === "object" &&
    !Array.isArray(document.pages)
  );
}

function matchesDeck(document, deck) {
  const acceptedOutlinePaths = new Set([
    deck.outline.path,
    ...(Array.isArray(deck.outline.identity_aliases) ? deck.outline.identity_aliases : []),
  ].map((value) => path.resolve(value)));
  return (
    document.deck_uid === deck.outline.deck_uid &&
    acceptedOutlinePaths.has(path.resolve(document.outline_path))
  );
}

function validRef(value) {
  return Boolean(
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    typeof value.run_id === "string" &&
    value.run_id &&
    typeof value.handoff_path === "string" &&
    path.isAbsolute(value.handoff_path) &&
    typeof value.native_candidate_id === "string" &&
    value.native_candidate_id,
  );
}

function normalizedRefs(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const refs = [];
  for (const item of value) {
    if (!validRef(item)) continue;
    const ref = {
      run_id: item.run_id,
      handoff_path: path.resolve(item.handoff_path),
      native_candidate_id: item.native_candidate_id,
    };
    const key = JSON.stringify(ref);
    if (seen.has(key)) continue;
    seen.add(key);
    refs.push(ref);
  }
  return refs;
}

function validate(document, deck) {
  if (
    !document ||
    typeof document !== "object" ||
    Array.isArray(document) ||
    !validRoot(document) ||
    !matchesDeck(document, deck)
  ) {
    throw new HttpError(409, "这套 PPT 的选稿记录无法读取，请检查项目文件。", "studio_selection_invalid");
  }
  const slideUids = new Set(deck.outline.slides.map((slide) => slide.slide_uid));
  for (const [slideUid, page] of Object.entries(document.pages)) {
    if (!slideUids.has(slideUid) || !page || typeof page !== "object" || Array.isArray(page)) {
      throw new HttpError(409, "这套 PPT 的选稿记录与当前大纲不一致。", "studio_selection_invalid");
    }
    page.selected_candidate_refs = normalizedRefs(page.selected_candidate_refs);
  }
  return document;
}

export function studioSelectionPath(deck) {
  return path.join(
    deck.project_root,
    ".shawn-ppt-studio",
    "selections",
    `${selectionIdentityKey(deck)}.json`,
  );
}

export function legacyStudioSelectionPath(deck) {
  return path.join(deck.project_root, ".shawn-ppt-studio", "selection.json");
}

export async function readStudioSelection(deck) {
  const selectionPath = studioSelectionPath(deck);
  try {
    return validate(JSON.parse(await readFile(selectionPath, "utf8")), deck);
  } catch (error) {
    if (error?.code !== "ENOENT") {
      if (error instanceof HttpError) throw error;
      throw new HttpError(409, "这套 PPT 的选稿记录无法读取，请检查项目文件。", "studio_selection_invalid");
    }
  }
  try {
    const legacy = JSON.parse(await readFile(legacyStudioSelectionPath(deck), "utf8"));
    if (!validRoot(legacy)) {
      throw new HttpError(409, "这套 PPT 的选稿记录无法读取，请检查项目文件。", "studio_selection_invalid");
    }
    if (!matchesDeck(legacy, deck)) return emptySelection(deck);
    return validate(legacy, deck);
  } catch (error) {
    if (error?.code === "ENOENT") return emptySelection(deck);
    if (error instanceof HttpError) throw error;
    throw new HttpError(409, "这套 PPT 的选稿记录无法读取，请检查项目文件。", "studio_selection_invalid");
  }
}

async function atomicWrite(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, {
      encoding: "utf8",
      mode: 0o600,
      flag: "wx",
    });
    await rename(temporary, filePath);
  } catch (error) {
    await rm(temporary, { force: true }).catch(() => {});
    throw error;
  }
}

export class StudioSelectionStore {
  constructor({ clock = () => new Date().toISOString() } = {}) {
    this.clock = clock;
    this.queues = new Map();
  }

  async read(deck) {
    return readStudioSelection(deck);
  }

  async setCandidate(deck, slideUid, ref, selected) {
    if (!deck.outline.slides.some((slide) => slide.slide_uid === slideUid)) {
      throw new HttpError(404, "没有找到这一页", "slide_not_found");
    }
    if (!validRef(ref) || typeof selected !== "boolean") {
      throw new HttpError(400, "请选择一张有效图片", "invalid_selection");
    }
    const filePath = studioSelectionPath(deck);
    const prior = this.queues.get(filePath) || Promise.resolve();
    const operation = prior.then(async () => {
      const document = await readStudioSelection(deck);
      const current = normalizedRefs(document.pages[slideUid]?.selected_candidate_refs);
      const key = JSON.stringify({
        run_id: ref.run_id,
        handoff_path: path.resolve(ref.handoff_path),
        native_candidate_id: ref.native_candidate_id,
      });
      const next = current.filter((item) => JSON.stringify(item) !== key);
      if (selected) next.push(JSON.parse(key));
      const timestamp = this.clock();
      if (next.length) {
        document.pages[slideUid] = {
          confirmed: true,
          resolution: "selected",
          included: true,
          selected_candidate_refs: next,
          updated_at: timestamp,
        };
      } else {
        delete document.pages[slideUid];
      }
      document.updated_at = timestamp;
      await atomicWrite(filePath, document);
      return document;
    });
    this.queues.set(filePath, operation.catch(() => {}));
    return operation;
  }
}
