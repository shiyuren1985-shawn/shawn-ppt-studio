import { randomUUID } from "node:crypto";
import { mkdir, readFile, realpath, rename, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";

import { HttpError } from "./errors.mjs";

const CONTRACT_VERSION = 1;
const MARKDOWN_EXTENSIONS = new Set([".md", ".markdown"]);

function nowIso() {
  return new Date().toISOString();
}

function safeLabel(value, fallback) {
  const clean = typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  return (clean || fallback).slice(0, 100);
}

function publicRecord(record) {
  return {
    project_id: record.project_id,
    deck_id: record.deck_id,
    deck_uid: record.deck_uid,
    label: record.label,
    project_root: record.project_root,
    outline_path: record.outline_path,
    output_root: record.output_root,
    source_kind: "studio",
    created_at: record.created_at,
    updated_at: record.updated_at,
  };
}

async function atomicJson(filePath, value) {
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

function blankOutline(deckUid, label) {
  return [
    "---",
    `deck_uid: ${deckUid}`,
    "slide_uids:",
    "---",
    "",
    `# ${label}`,
    "",
    "> 状态：草稿",
    "",
  ].join("\n");
}

export class StudioProjectRegistry {
  constructor({ dataRoot, clock = nowIso }) {
    this.runtimeRoot = path.join(path.resolve(dataRoot), "runtime");
    this.path = path.join(this.runtimeRoot, "projects.json");
    this.clock = clock;
    this.state = {
      contract_version: CONTRACT_VERSION,
      default_project_id: null,
      projects: [],
      hidden_decks: [],
    };
    this.ready = false;
    this.lastError = null;
    this.writeQueue = Promise.resolve();
  }

  async initialize() {
    await mkdir(this.runtimeRoot, { recursive: true });
    let parsed = null;
    try {
      parsed = JSON.parse(await readFile(this.path, "utf8"));
    } catch (error) {
      if (error?.code !== "ENOENT") {
        throw Object.assign(new Error("project registry is not valid JSON"), {
          code: "project_registry_corrupt",
        });
      }
    }
    if (parsed && !Array.isArray(parsed.hidden_decks)) parsed.hidden_decks = [];
    if (parsed) this.#validate(parsed);
    this.state = parsed || this.state;
    this.ready = true;
    this.lastError = null;
  }

  health() {
    return {
      ready: this.ready,
      path: this.path,
      project_count: this.state.projects.length,
      visible_project_count: this.state.projects.filter((record) => !this.isHidden(record.deck_id)).length,
      error: this.lastError?.message || null,
    };
  }

  list({ includeHidden = false } = {}) {
    if (!this.ready) throw new HttpError(503, "project registry is unavailable", "project_registry_unavailable");
    const hidden = new Set(this.state.hidden_decks.map((entry) => entry.deck_id));
    return {
      contract_version: CONTRACT_VERSION,
      default_project_id: this.state.default_project_id,
      projects: this.state.projects
        .filter((record) => includeHidden || !hidden.has(record.deck_id))
        .map(publicRecord),
    };
  }

  isHidden(deckId) {
    return this.state.hidden_decks.some((entry) => entry.deck_id === deckId);
  }

  async hideDeck({ deckId, outlinePath }) {
    if (typeof deckId !== "string" || !deckId.trim()) {
      throw new HttpError(400, "deck_id is required", "invalid_project_id");
    }
    if (typeof outlinePath !== "string" || !path.isAbsolute(outlinePath)) {
      throw new HttpError(400, "outline_path must be absolute", "invalid_outline_path");
    }
    if (this.isHidden(deckId)) return { hidden: true, deck_id: deckId, already_hidden: true };
    const timestamp = this.clock();
    await this.#mutate((state) => {
      state.hidden_decks.push({ deck_id: deckId, outline_path: outlinePath, hidden_at: timestamp });
      const hiddenProject = state.projects.find((record) => record.deck_id === deckId);
      if (hiddenProject?.project_id === state.default_project_id) {
        const hiddenIds = new Set(state.hidden_decks.map((entry) => entry.deck_id));
        state.default_project_id = state.projects.find((record) => !hiddenIds.has(record.deck_id))?.project_id || null;
      }
    });
    return { hidden: true, deck_id: deckId, already_hidden: false };
  }

  async restoreDeck(deckId) {
    if (!this.isHidden(deckId)) return false;
    await this.#mutate((state) => {
      state.hidden_decks = state.hidden_decks.filter((entry) => entry.deck_id !== deckId);
      const project = state.projects.find((record) => record.deck_id === deckId);
      if (project) state.default_project_id = project.project_id;
    });
    return true;
  }

  get(deckId) {
    const record = this.state.projects.find((item) => item.deck_id === deckId);
    if (!record) throw new HttpError(404, `unknown project: ${deckId}`, "project_not_found");
    return { ...record };
  }

  async createBlank({ folderPath, label = null }) {
    const root = await this.#directory(folderPath);
    const projectLabel = safeLabel(label, path.basename(root));
    const deckUid = `STUDIO_${randomUUID()}`;
    const outlinePath = path.join(root, "PPT大纲.md");
    try {
      await writeFile(outlinePath, blankOutline(deckUid, projectLabel), {
        encoding: "utf8",
        flag: "wx",
      });
    } catch (error) {
      if (error?.code === "EEXIST") {
        throw new HttpError(409, "outline file already exists", "project_file_exists");
      }
      throw error;
    }
    const outputRoot = path.join(root, "output");
    try {
      await mkdir(outputRoot, { recursive: true });
      return await this.#register({
        label: projectLabel,
        projectRoot: root,
        outlinePath,
        outputRoot,
        deckUid,
      });
    } catch (error) {
      await rm(outlinePath, { force: true }).catch(() => {});
      throw error;
    }
  }

  async openExisting({ outlinePath, label = null }) {
    if (typeof outlinePath !== "string" || !path.isAbsolute(outlinePath)) {
      throw new HttpError(400, "outline_path must be absolute", "invalid_outline_path");
    }
    if (!MARKDOWN_EXTENSIONS.has(path.extname(outlinePath).toLowerCase())) {
      throw new HttpError(400, "outline must be a Markdown file", "invalid_outline_path");
    }
    let outlineReal;
    let info;
    try {
      [outlineReal, info] = await Promise.all([realpath(outlinePath), stat(outlinePath)]);
    } catch {
      throw new HttpError(404, "outline file was not found", "outline_not_found");
    }
    if (!info.isFile()) throw new HttpError(400, "outline must be a file", "invalid_outline_path");
    const duplicate = this.state.projects.find((item) => item.outline_path === outlineReal);
    if (duplicate) {
      const restored = await this.restoreDeck(duplicate.deck_id);
      return { ...publicRecord(duplicate), already_registered: true, restored };
    }
    const text = await readFile(outlineReal, "utf8");
    const canonicalUid = text.match(/^deck_uid:\s*(.+?)\s*$/m)?.[1]?.trim() || null;
    const deckUid = canonicalUid || `STUDIO_${randomUUID()}`;
    const outputRoot = path.join(path.dirname(outlineReal), "output");
    const registered = await this.#register({
      label: safeLabel(label, path.basename(outlineReal, path.extname(outlineReal))),
      projectRoot: path.dirname(outlineReal),
      outlinePath: outlineReal,
      outputRoot,
      deckUid,
    });
    return { ...registered, already_registered: false };
  }

  async #directory(value) {
    if (typeof value !== "string" || !path.isAbsolute(value)) {
      throw new HttpError(400, "folder_path must be absolute", "invalid_project_root");
    }
    try {
      const [root, info] = await Promise.all([realpath(value), stat(value)]);
      if (!info.isDirectory()) throw new Error("not directory");
      return root;
    } catch {
      throw new HttpError(404, "project folder was not found", "project_root_not_found");
    }
  }

  async #register({ label, projectRoot, outlinePath, outputRoot, deckUid }) {
    if (this.state.projects.some((item) => item.outline_path === outlinePath)) {
      throw new HttpError(409, "outline is already registered", "project_already_registered");
    }
    const timestamp = this.clock();
    const id = randomUUID();
    const record = {
      project_id: id,
      deck_id: `studio-${id}`,
      deck_uid: deckUid,
      label,
      project_root: projectRoot,
      outline_path: outlinePath,
      output_root: outputRoot,
      created_at: timestamp,
      updated_at: timestamp,
    };
    await this.#mutate((state) => {
      state.projects.push(record);
      state.default_project_id = record.project_id;
    });
    return publicRecord(record);
  }

  async #mutate(change) {
    if (!this.ready) throw new HttpError(503, "project registry is unavailable", "project_registry_unavailable");
    const operation = async () => {
      const next = structuredClone(this.state);
      await change(next);
      this.#validate(next);
      await atomicJson(this.path, next);
      this.state = next;
      this.lastError = null;
    };
    const result = this.writeQueue.then(operation);
    this.writeQueue = result.catch((error) => { this.lastError = error; });
    await result;
    return undefined;
  }

  #validate(state) {
    if (
      !state ||
      state.contract_version !== CONTRACT_VERSION ||
      !Array.isArray(state.projects) ||
      !Array.isArray(state.hidden_decks)
    ) {
      throw Object.assign(new Error("project registry has an invalid root"), { code: "project_registry_corrupt" });
    }
    const ids = new Set();
    const outlines = new Set();
    for (const record of state.projects) {
      if (
        !record ||
        typeof record.project_id !== "string" ||
        typeof record.deck_id !== "string" ||
        typeof record.deck_uid !== "string" ||
        typeof record.label !== "string" ||
        !path.isAbsolute(record.project_root) ||
        !path.isAbsolute(record.outline_path) ||
        !path.isAbsolute(record.output_root) ||
        ids.has(record.project_id) ||
        outlines.has(record.outline_path)
      ) throw Object.assign(new Error("project registry has an invalid project"), { code: "project_registry_corrupt" });
      ids.add(record.project_id);
      outlines.add(record.outline_path);
    }
    if (state.default_project_id && !ids.has(state.default_project_id)) {
      throw Object.assign(new Error("project registry has an invalid default"), { code: "project_registry_corrupt" });
    }
    const hiddenIds = new Set();
    for (const entry of state.hidden_decks) {
      if (
        !entry ||
        typeof entry.deck_id !== "string" ||
        !path.isAbsolute(entry.outline_path) ||
        typeof entry.hidden_at !== "string" ||
        hiddenIds.has(entry.deck_id)
      ) throw Object.assign(new Error("project registry has an invalid hidden deck"), { code: "project_registry_corrupt" });
      hiddenIds.add(entry.deck_id);
    }
  }
}
