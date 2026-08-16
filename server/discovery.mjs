import { createHash } from "node:crypto";
import { readFile, realpath, stat } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { TextDecoder } from "node:util";

import { HttpError } from "./errors.mjs";

const UTF8 = new TextDecoder("utf-8", { fatal: true });
const FRONTMATTER_END = /\n---\s*\r?\n/;
const TABLE_ROW = /^(?<prefix>\|\s*)(?<page>P?0*\d+)\s*\|(?<rest>.*)$/;
const VERSION_RE = /^>\s*版本[：:]\s*([^｜|\n]+)/m;
const STATUS_RE = /^>\s*状态[：:]\s*([^\n]+)/m;

const STUDIO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const DEFAULT_DECKS_FILE = path.resolve(
  path.join(STUDIO_ROOT, ".studio-projects-only.json"),
);

function revisionOf(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function normalizedPageId(value) {
  const match = String(value ?? "").trim().match(/^P?0*(\d+)$/i);
  if (!match || Number(match[1]) <= 0) {
    throw new Error(`invalid page id: ${value}`);
  }
  return `P${Number(match[1])}`;
}

export function splitTableCells(line) {
  const stripped = line.trim();
  if (!stripped.startsWith("|") || !stripped.endsWith("|")) return [];
  return stripped.slice(1, -1).split("|").map((cell) => cell.trim());
}

function cleanTableCell(value) {
  return String(value ?? "").replaceAll("**", "").trim();
}

function isPageHeader(value) {
  return /^(?:页码|页面|page(?:\s*id)?)$/i.test(cleanTableCell(value));
}

function subtitleColumnIndex(headers) {
  return headers.findIndex((header) => /^(?:副标题|subtitle)$/i.test(cleanTableCell(header)));
}

export function parseOutlineText({ text, bytes, outlinePath, info }) {
  if (!text.startsWith("---\n") && !text.startsWith("---\r\n")) {
    throw new Error("outline is missing YAML front matter");
  }
  const match = FRONTMATTER_END.exec(text.slice(3));
  if (!match) throw new Error("outline front matter is not closed");
  const closeStart = 3 + match.index;
  const bodyStart = 3 + match.index + match[0].length;
  const frontmatter = text.slice(text.indexOf("\n") + 1, closeStart);
  const deckMatch = frontmatter.match(/^deck_uid:\s*(.+?)\s*$/m);
  if (!deckMatch) throw new Error("outline is missing deck_uid");

  const slideUids = {};
  let inSlideUids = false;
  for (const line of frontmatter.split(/\r?\n/)) {
    if (/^slide_uids:\s*$/.test(line)) {
      inSlideUids = true;
      continue;
    }
    if (!inSlideUids) continue;
    const item = line.match(/^\s{2}(P?0*\d+):\s*(\S.*?)\s*$/);
    if (item) {
      slideUids[normalizedPageId(item[1])] = item[2];
      continue;
    }
    if (line && !line.startsWith(" ")) inSlideUids = false;
  }
  if (new Set(Object.values(slideUids)).size !== Object.values(slideUids).length) {
    throw new Error("outline has duplicate slide_uid values");
  }

  const rows = new Map();
  let activeHeaders = [];
  let offset = 0;
  for (const rawLine of text.match(/.*(?:\n|$)/g) ?? []) {
    if (rawLine === "") continue;
    const line = rawLine.replace(/\r?\n$/, "");
    const cells = splitTableCells(line);
    if (cells.length >= 2 && isPageHeader(cells[0])) activeHeaders = cells;
    const rowMatch = TABLE_ROW.exec(line);
    if (rowMatch) {
      let pageId;
      try {
        pageId = normalizedPageId(rowMatch.groups.page);
      } catch {
        pageId = null;
      }
      if (pageId && slideUids[pageId] && cells.length >= 2) {
        if (rows.has(pageId)) throw new Error(`outline has duplicate page row: ${pageId}`);
        const subtitleIndex = subtitleColumnIndex(activeHeaders);
        const subtitle = subtitleIndex >= 0 ? cleanTableCell(cells[subtitleIndex]) : "";
        rows.set(pageId, {
          page_id: pageId,
          page_label: `P${String(Number(pageId.slice(1))).padStart(2, "0")}`,
          order: Number(pageId.slice(1)),
          slide_uid: slideUids[pageId],
          title: cleanTableCell(cells[1]),
          subtitle: subtitle || null,
          markdown: line,
          span: [offset, offset + rawLine.length],
          column_count: cells.length,
        });
      }
    }
    offset += rawLine.length;
  }

  const missing = Object.keys(slideUids).filter((pageId) => !rows.has(pageId));
  if (missing.length) throw new Error(`outline table is missing UID pages: ${missing.join(", ")}`);

  const slides = [...rows.values()].sort((left, right) => left.order - right.order);
  const sha256 = revisionOf(bytes);
  return {
    path: path.resolve(outlinePath),
    deck_uid: deckMatch[1].trim(),
    sha256,
    revision_id: `sha256:${sha256}`,
    version_label: text.match(VERSION_RE)?.[1]?.trim() || null,
    status_label: text.match(STATUS_RE)?.[1]?.trim() || null,
    mtime: new Date(info.mtimeMs).toISOString(),
    size: info.size,
    slides,
    slide_uids: slideUids,
    text,
    bytes,
    body_start: bodyStart,
  };
}

export function parseDraftOutline({ text, bytes, outlinePath, info, deckUid }) {
  const sha256 = revisionOf(bytes);
  return {
    path: path.resolve(outlinePath),
    deck_uid: deckUid,
    sha256,
    revision_id: `sha256:${sha256}`,
    version_label: null,
    status_label: "草稿",
    mtime: new Date(info.mtimeMs).toISOString(),
    size: info.size,
    slides: [],
    slide_uids: {},
    text,
    bytes,
    body_start: 0,
    outline_kind: "draft",
  };
}

function publicSlide(slide) {
  const { span: _span, column_count: _columnCount, ...publicValue } = slide;
  return publicValue;
}

function publicDeck(deck) {
  return {
    deck_id: deck.deck_id,
    label: deck.label,
    deck_uid: deck.outline.deck_uid,
    outline_path: deck.outline.path,
    revision_id: deck.outline.revision_id,
    sha256: deck.outline.sha256,
    version_label: deck.outline.version_label,
    status_label: deck.outline.status_label,
    mtime: deck.outline.mtime,
    slide_count: deck.outline.slides.length,
    default_slide_uid: deck.outline.slides[0]?.slide_uid || null,
    candidate_root: deck.candidate_roots[0]?.path || null,
    candidate_roots_paths: deck.candidate_roots.map((root) => root.path),
    slides: deck.outline.slides.map(publicSlide),
  };
}

function expandUser(value) {
  if (value === "~") return homedir();
  if (value.startsWith(`~${path.sep}`)) return path.join(homedir(), value.slice(2));
  return value;
}

export class DeckDiscovery {
  constructor({ decksFile = DEFAULT_DECKS_FILE }) {
    this.decksFile = path.resolve(decksFile);
    this.ready = false;
    this.lastError = null;
    this.lastCheckedAt = null;
    this.deckCount = null;
  }

  health() {
    return {
      ready: this.ready,
      decks_file: this.decksFile,
      deck_count: this.deckCount,
      checked_at: this.lastCheckedAt,
      error: this.lastError?.message || null,
    };
  }

  async probe() {
    try {
      const result = await this.listDecks();
      return result;
    } catch (error) {
      return null;
    }
  }

  async #readRegistry() {
    const [registryReal, registryText] = await Promise.all([
      realpath(this.decksFile),
      readFile(this.decksFile, "utf8"),
    ]);
    let registry;
    try {
      registry = JSON.parse(registryText);
    } catch {
      throw new Error("decks registry is not valid JSON");
    }
    if (!Array.isArray(registry.decks) || registry.decks.length === 0) {
      throw new Error("decks registry has no decks");
    }
    return { registry, registryReal };
  }

  async #readDeck(entry, registryReal) {
    if (!entry || typeof entry.id !== "string" || typeof entry.config !== "string") {
      throw new Error("deck registry entry is invalid");
    }
    const registryRoot = path.dirname(registryReal);
    const configCandidate = path.resolve(registryRoot, entry.config);
    const configReal = await realpath(configCandidate);
    const relativeConfig = path.relative(registryRoot, configReal);
    if (relativeConfig === ".." || relativeConfig.startsWith(`..${path.sep}`)) {
      throw new Error(`deck config escapes registry directory: ${entry.id}`);
    }
    let config;
    try {
      config = JSON.parse(await readFile(configReal, "utf8"));
    } catch {
      throw new Error(`deck config is not valid JSON: ${entry.id}`);
    }
    if (typeof config.outline_source !== "string" || !config.outline_source) {
      throw new Error(`deck config has no outline_source: ${entry.id}`);
    }
    const outlineCandidate = path.isAbsolute(config.outline_source)
      ? config.outline_source
      : path.resolve(path.dirname(configReal), config.outline_source);
    const outlineReal = await realpath(outlineCandidate);
    const [bytes, info] = await Promise.all([readFile(outlineReal), stat(outlineReal)]);
    if (!info.isFile()) throw new Error(`outline is not a regular file: ${entry.id}`);
    const text = UTF8.decode(bytes);
    const outline = parseOutlineText({ text, bytes, outlinePath: outlineReal, info });
    if (config.candidate_roots !== undefined && !Array.isArray(config.candidate_roots)) {
      throw new Error(`deck config candidate_roots must be an array: ${entry.id}`);
    }
    const candidateRoots = [];
    const candidateRootIds = new Set();
    const candidateRootPaths = new Set();
    for (const item of config.candidate_roots || []) {
      if (
        !item ||
        typeof item !== "object" ||
        typeof item.id !== "string" ||
        !item.id.trim() ||
        typeof item.path !== "string" ||
        !item.path.trim()
      ) {
        throw new Error(`deck config has an invalid candidate root: ${entry.id}`);
      }
      const rootId = item.id.trim();
      if (candidateRootIds.has(rootId)) {
        throw new Error(`deck config has duplicate candidate root id: ${entry.id}/${rootId}`);
      }
      const configured = expandUser(item.path.trim());
      const candidate = path.isAbsolute(configured)
        ? path.resolve(configured)
        : path.resolve(registryRoot, configured);
      const [rootReal, rootInfo] = await Promise.all([realpath(candidate), stat(candidate)]);
      if (!path.isAbsolute(rootReal) || rootReal !== candidate || !rootInfo.isDirectory()) {
        throw new Error(`candidate root must be a real absolute directory: ${entry.id}/${rootId}`);
      }
      if (candidateRootPaths.has(rootReal)) {
        throw new Error(`deck config has duplicate candidate root path: ${entry.id}/${rootId}`);
      }
      candidateRootIds.add(rootId);
      candidateRootPaths.add(rootReal);
      candidateRoots.push({ id: rootId, path: rootReal });
    }
    return {
      deck_id: entry.id,
      label: typeof entry.label === "string" ? entry.label : config.deck_label || entry.id,
      config_path: configReal,
      candidate_roots: candidateRoots,
      outline,
    };
  }

  async #load() {
    try {
      const { registry, registryReal } = await this.#readRegistry();
      const decks = [];
      const ids = new Set();
      for (const entry of registry.decks) {
        if (ids.has(entry.id)) throw new Error(`duplicate deck id: ${entry.id}`);
        ids.add(entry.id);
        decks.push(await this.#readDeck(entry, registryReal));
      }
      this.ready = true;
      this.lastError = null;
      this.lastCheckedAt = new Date().toISOString();
      this.deckCount = decks.length;
      return { registry, decks };
    } catch (error) {
      this.ready = false;
      this.lastError = error;
      this.lastCheckedAt = new Date().toISOString();
      this.deckCount = null;
      throw new HttpError(503, error.message, "deck_discovery_unavailable");
    }
  }

  async listDecks() {
    const { registry, decks } = await this.#load();
    return {
      contract_version: 2,
      default_deck: registry.default_deck || decks[0].deck_id,
      decks: decks.map(publicDeck),
    };
  }

  async readDeck(deckId) {
    const { decks } = await this.#load();
    const deck = decks.find((candidate) => candidate.deck_id === deckId);
    if (!deck) throw new HttpError(404, `unknown deck: ${deckId}`, "deck_not_found");
    return deck;
  }

  async getOutline(deckId) {
    const deck = await this.readDeck(deckId);
    return { contract_version: 2, ...publicDeck(deck) };
  }

  async getSlide(deckId, slideUid) {
    const deck = await this.readDeck(deckId);
    const slide = deck.outline.slides.find((candidate) => candidate.slide_uid === slideUid);
    if (!slide) {
      throw new HttpError(404, `unknown slide_uid for ${deckId}: ${slideUid}`, "slide_not_found");
    }
    return {
      contract_version: 2,
      deck_id: deck.deck_id,
      deck_uid: deck.outline.deck_uid,
      outline_path: deck.outline.path,
      revision_id: deck.outline.revision_id,
      sha256: deck.outline.sha256,
      slide: publicSlide(slide),
    };
  }

  async getSelectorMetadata(deckId = null) {
    let resolvedDeckId = deckId;
    if (!resolvedDeckId) {
      const { registry, decks } = await this.#load();
      resolvedDeckId = registry.default_deck || decks[0]?.deck_id;
    }
    const deck = await this.readDeck(resolvedDeckId);
    const candidateRoot = deck.candidate_roots[0]?.path;
    if (!candidateRoot) {
      throw new HttpError(
        409,
        `deck has no registered candidate root: ${resolvedDeckId}`,
        "candidate_root_missing",
      );
    }
    const selector = new URL("http://127.0.0.1:8765/");
    selector.searchParams.set("deck", resolvedDeckId);
    return {
      contract_version: 1,
      deck_id: resolvedDeckId,
      deck_uid: deck.outline.deck_uid,
      selector_url: selector.toString(),
      candidate_root: candidateRoot,
    };
  }
}
