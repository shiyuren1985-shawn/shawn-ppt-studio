import { createHash, randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";

import { studioLibraryRoot } from "./studio-library.mjs";

const CONTRACT_VERSION = 1;

function nowIso() {
  return new Date().toISOString();
}

async function sha256File(filePath) {
  const bytes = await readFile(filePath);
  return createHash("sha256").update(bytes).digest("hex");
}

function imageKey(record) {
  return [record.thread_id, record.turn_id, record.item_id, record.imported_path].join("\u0000");
}

export class LabLedger {
  constructor({ labRoot, clock = nowIso }) {
    this.runtimeRoot = studioLibraryRoot(labRoot);
    this.path = path.join(this.runtimeRoot, "lab-ledger.jsonl");
    this.clock = clock;
    this.records = [];
    this.sequence = 0;
    this.ready = false;
    this.lastError = null;
    this.writeQueue = Promise.resolve();
    this.imageKeys = new Set();
    this.recoveredTail = null;
  }

  async initialize() {
    await mkdir(this.runtimeRoot, { recursive: true });
    let text = "";
    try {
      text = await readFile(this.path, "utf8");
    } catch (error) {
      if (error?.code !== "ENOENT") {
        this.lastError = error;
        throw error;
      }
    }

    const records = [];
    const lines = text.split("\n");
    const lastNonEmpty = lines.findLastIndex((line) => line.trim());
    for (const [index, line] of lines.entries()) {
      if (!line.trim()) continue;
      let record;
      try {
        record = JSON.parse(line);
      } catch {
        if (index === lastNonEmpty && !text.endsWith("\n")) {
          const quarantinePath = `${this.path}.bad-${Date.now()}`;
          const validText = records.length
            ? `${records.map((item) => JSON.stringify(item)).join("\n")}\n`
            : "";
          const temporary = `${this.path}.${process.pid}.${randomUUID()}.tmp`;
          try {
            await writeFile(quarantinePath, line, { encoding: "utf8", mode: 0o600, flag: "wx" });
            await writeFile(temporary, validText, { encoding: "utf8", mode: 0o600, flag: "wx" });
            await rename(temporary, this.path);
          } catch (repairError) {
            await rm(temporary, { force: true }).catch(() => {});
            this.lastError = repairError;
            throw repairError;
          }
          this.recoveredTail = {
            recovered: true,
            quarantine_path: quarantinePath,
            recovered_at: this.clock(),
          };
          break;
        }
        const error = Object.assign(new Error(`lab ledger has invalid JSON at line ${index + 1}`), {
          code: "ledger_corrupt",
        });
        this.lastError = error;
        throw error;
      }
      if (!Number.isInteger(record.sequence) || record.sequence <= 0 || typeof record.type !== "string") {
        const error = Object.assign(new Error(`lab ledger has an invalid record at line ${index + 1}`), {
          code: "ledger_corrupt",
        });
        this.lastError = error;
        throw error;
      }
      records.push(record);
    }

    records.sort((left, right) => left.sequence - right.sequence);
    for (let index = 0; index < records.length; index += 1) {
      if (records[index].sequence !== index + 1) {
        const error = Object.assign(new Error("lab ledger sequence is not contiguous"), {
          code: "ledger_corrupt",
        });
        this.lastError = error;
        throw error;
      }
    }

    this.records = records;
    this.sequence = records.length;
    this.imageKeys = new Set(
      records.filter((record) => record.type === "image_imported").map(imageKey),
    );
    this.ready = true;
    this.lastError = null;
  }

  health() {
    return {
      ready: this.ready,
      path: this.path,
      record_count: this.records.length,
      error: this.lastError?.message || null,
      recovered_tail: this.recoveredTail,
    };
  }

  async #append(fields) {
    if (!this.ready) {
      throw Object.assign(new Error("lab ledger is unavailable"), { code: "ledger_unavailable" });
    }

    const operation = async () => {
      const record = {
        contract_version: CONTRACT_VERSION,
        sequence: this.sequence + 1,
        event_id: randomUUID(),
        occurred_at: this.clock(),
        ...fields,
      };
      const handle = await open(this.path, "a", 0o600);
      try {
        await handle.writeFile(`${JSON.stringify(record)}\n`, { encoding: "utf8" });
        await handle.sync();
      } finally {
        await handle.close();
      }
      this.sequence = record.sequence;
      this.records.push(record);
      if (record.type === "image_imported") this.imageKeys.add(imageKey(record));
      this.lastError = null;
      return record;
    };

    const result = this.writeQueue.then(operation);
    this.writeQueue = result.catch((error) => {
      this.ready = false;
      this.lastError = error;
    });
    return result;
  }

  async recordThread({ threadId, action }) {
    if (typeof threadId !== "string" || !threadId) return null;
    return this.#append({
      type: "thread_seen",
      thread_id: threadId,
      action: action === "resumed" ? "resumed" : "started",
    });
  }

  async recordImageImport({
    threadId,
    turnId = null,
    itemId = null,
    mode = null,
    sourcePath,
    importedPath,
    inputImagePath = null,
    revisedPrompt = null,
  }) {
    const key = imageKey({
      thread_id: threadId,
      turn_id: turnId,
      item_id: itemId,
      imported_path: importedPath,
    });
    if (this.imageKeys.has(key)) return null;

    const [info, fileSha256] = await Promise.all([stat(importedPath), sha256File(importedPath)]);
    if (!info.isFile()) {
      throw Object.assign(new Error("imported image is not a regular file"), {
        code: "invalid_imported_image",
      });
    }

    return this.#append({
      type: "image_imported",
      thread_id: threadId,
      turn_id: turnId,
      item_id: itemId,
      mode,
      source_path: sourcePath,
      imported_path: importedPath,
      input_image_path: inputImagePath,
      file_sha256: fileSha256,
      file_size: info.size,
      revised_prompt:
        typeof revisedPrompt === "string" && revisedPrompt
          ? revisedPrompt.slice(0, 4000)
          : null,
    });
  }

  importedImages(threadId) {
    return this.records
      .filter((record) => record.type === "image_imported" && record.thread_id === threadId)
      .map((record) => ({
        import_id: record.event_id,
        thread_id: record.thread_id,
        turn_id: record.turn_id,
        item_id: record.item_id,
        mode: record.mode,
        path: record.imported_path,
        input_image_path: record.input_image_path,
        file_sha256: record.file_sha256,
        file_size: record.file_size,
        revised_prompt: record.revised_prompt,
        imported_at: record.occurred_at,
        status: "completed",
      }));
  }
}
