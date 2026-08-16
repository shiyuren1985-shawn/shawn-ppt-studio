import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { TextDecoder } from "node:util";

import { HttpError } from "./errors.mjs";
import { parseDraftOutline, parseOutlineText } from "./discovery.mjs";

const UTF8 = new TextDecoder("utf-8", { fatal: true });

function publicSlide(slide) {
  const { span: _span, column_count: _columnCount, ...value } = slide;
  return value;
}

function publicDeck(deck) {
  return {
    deck_id: deck.deck_id,
    label: deck.label,
    deck_uid: deck.outline.deck_uid,
    project_root: deck.project_root || path.dirname(deck.outline.path),
    outline_path: deck.outline.path,
    outline_kind: deck.outline.outline_kind || "canonical",
    source_kind: deck.source_kind || "legacy",
    revision_id: deck.outline.revision_id,
    sha256: deck.outline.sha256,
    version_label: deck.outline.version_label,
    status_label: deck.outline.status_label,
    mtime: deck.outline.mtime,
    slide_count: deck.outline.slides.length,
    default_slide_uid: deck.outline.slides[0]?.slide_uid || null,
    output_root: deck.output_root || null,
    candidate_root: deck.candidate_roots[0]?.path || null,
    candidate_roots_paths: deck.candidate_roots.map((root) => root.path),
    slides: deck.outline.slides.map(publicSlide),
  };
}

export class ProjectDiscovery {
  constructor({ legacyDiscovery, projects }) {
    this.legacyDiscovery = legacyDiscovery;
    this.projects = projects;
    this.ready = false;
    this.lastError = null;
  }

  get decksFile() {
    return this.legacyDiscovery.decksFile;
  }

  health() {
    const legacy = this.legacyDiscovery.health();
    return {
      ready: this.projects.ready,
      deck_count: (legacy.deck_count || 0)
        + this.projects.state.projects.filter((record) => !this.projects.isHidden(record.deck_id)).length,
      legacy,
      projects: this.projects.health(),
      error: this.lastError?.message || this.projects.lastError?.message || null,
    };
  }

  async probe() {
    try {
      const result = await this.listDecks();
      this.ready = true;
      this.lastError = null;
      return result;
    } catch (error) {
      this.ready = false;
      this.lastError = error;
      return null;
    }
  }

  async listDecks() {
    let legacy = { default_deck: null, decks: [] };
    try {
      legacy = await this.legacyDiscovery.listDecks();
    } catch {
      // External legacy discovery is optional. Studio projects and their
      // conversations remain usable without an external registry.
    }
    const records = this.projects.list();
    const studio = [];
    for (const record of records.projects) studio.push(publicDeck(await this.#readStudio(record)));
    const defaultRecord = records.projects.find((item) => item.project_id === records.default_project_id);
    const visibleLegacy = legacy.decks.filter((deck) => !this.projects.isHidden(deck.deck_id));
    const legacyDefault = visibleLegacy.some((deck) => deck.deck_id === legacy.default_deck)
      ? legacy.default_deck
      : visibleLegacy[0]?.deck_id || null;
    return {
      contract_version: 3,
      default_deck: defaultRecord?.deck_id || legacyDefault || studio[0]?.deck_id || null,
      decks: [...studio, ...visibleLegacy.map((deck) => ({
        ...deck,
        project_root: path.dirname(deck.outline_path),
        outline_kind: "canonical",
        source_kind: "legacy",
        output_root: deck.candidate_root || null,
      }))],
    };
  }

  async readDeck(deckId) {
    const record = this.projects.state.projects.find((item) => item.deck_id === deckId);
    if (record) {
      if (this.projects.isHidden(deckId)) {
        throw new HttpError(404, "project is unavailable", "project_not_found");
      }
      return this.#readStudio(record);
    }
    if (this.projects.isHidden(deckId)) {
      throw new HttpError(404, "project is unavailable", "project_not_found");
    }
    try {
      const deck = await this.legacyDiscovery.readDeck(deckId);
      return { ...deck, source_kind: "legacy", project_root: path.dirname(deck.outline.path) };
    } catch {
      throw new HttpError(404, "project is unavailable", "project_not_found");
    }
  }

  async getOutline(deckId) {
    const deck = await this.readDeck(deckId);
    return {
      contract_version: 3,
      ...publicDeck(deck),
      draft_markdown: deck.outline.outline_kind === "draft" ? deck.outline.text : null,
    };
  }

  async getSlide(deckId, slideUid) {
    const deck = await this.readDeck(deckId);
    const slide = deck.outline.slides.find((candidate) => candidate.slide_uid === slideUid);
    if (!slide) throw new HttpError(404, `unknown slide_uid for ${deckId}: ${slideUid}`, "slide_not_found");
    return {
      contract_version: 3,
      deck_id: deck.deck_id,
      deck_uid: deck.outline.deck_uid,
      outline_path: deck.outline.path,
      revision_id: deck.outline.revision_id,
      sha256: deck.outline.sha256,
      slide: publicSlide(slide),
    };
  }

  async getSelectorMetadata(deckId = null) {
    const id = deckId || (await this.listDecks()).default_deck;
    const record = this.projects.state.projects.find((item) => item.deck_id === id);
    if (!record) return this.legacyDiscovery.getSelectorMetadata(id);
    throw new HttpError(409, "this project has no selector registration yet", "selector_unavailable");
  }

  async hideDeck(deckId) {
    const deck = await this.readDeck(deckId);
    await this.projects.hideDeck({ deckId, outlinePath: deck.outline.path });
    return { hidden: true, deck_id: deckId };
  }

  async restoreExistingOutline(outlinePath) {
    if (typeof outlinePath !== "string" || !path.isAbsolute(outlinePath)) return null;
    let outlineReal;
    try {
      outlineReal = await realpath(outlinePath);
    } catch {
      return null;
    }
    const studio = this.projects.state.projects.find((record) => record.outline_path === outlineReal);
    if (studio) {
      await this.projects.restoreDeck(studio.deck_id);
      return this.getOutline(studio.deck_id);
    }
    try {
      const legacy = await this.legacyDiscovery.listDecks();
      let match = null;
      for (const deck of legacy.decks) {
        try {
          if (await realpath(deck.outline_path) === outlineReal) {
            match = deck;
            break;
          }
        } catch {
          // A stale legacy entry is not a match for the file the user opened.
        }
      }
      if (!match) return null;
      await this.projects.restoreDeck(match.deck_id);
      return (await this.listDecks()).decks.find((deck) => deck.deck_id === match.deck_id) || null;
    } catch {
      return null;
    }
  }

  async #readStudio(record) {
    let bytes;
    let info;
    try {
      [bytes, info] = await Promise.all([readFile(record.outline_path), stat(record.outline_path)]);
    } catch {
      throw new HttpError(404, "project outline is unavailable", "outline_not_found");
    }
    const text = UTF8.decode(bytes);
    let outline;
    try {
      outline = parseOutlineText({
        text,
        bytes,
        outlinePath: record.outline_path,
        info,
      });
      outline.outline_kind = "canonical";
    } catch {
      outline = parseDraftOutline({
        text,
        bytes,
        outlinePath: record.outline_path,
        info,
        deckUid: record.deck_uid,
      });
    }
    return {
      deck_id: record.deck_id,
      label: record.label,
      config_path: null,
      source_kind: "studio",
      project_root: record.project_root,
      output_root: record.output_root,
      candidate_roots: [{ id: "output", path: record.output_root }],
      outline,
    };
  }
}
