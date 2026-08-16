import { appendFile, mkdir, rename, rm, stat } from "node:fs/promises";
import path from "node:path";

const CONTRACT_VERSION = 1;
const DEFAULT_MAX_BYTES = 5 * 1024 * 1024;

function cleanFields(fields) {
  if (!fields || typeof fields !== "object" || Array.isArray(fields)) return {};
  return Object.fromEntries(Object.entries(fields).filter(([, value]) => value !== undefined));
}

export class RuntimeEventLog {
  constructor({
    dataRoot,
    clock = () => new Date().toISOString(),
    maxBytes = DEFAULT_MAX_BYTES,
  }) {
    this.runtimeRoot = path.join(path.resolve(dataRoot), "runtime");
    this.path = path.join(this.runtimeRoot, "studio-events.jsonl");
    this.rotatedPath = `${this.path}.1`;
    this.clock = clock;
    this.maxBytes = maxBytes;
    this.writeQueue = Promise.resolve();
    this.lastError = null;
  }

  async initialize() {
    await mkdir(this.runtimeRoot, { recursive: true });
  }

  async #rotateIfNeeded(nextBytes) {
    const currentBytes = await stat(this.path).then((info) => info.size).catch((error) => {
      if (error?.code === "ENOENT") return 0;
      throw error;
    });
    if (currentBytes + nextBytes <= this.maxBytes) return;
    await rm(this.rotatedPath, { force: true });
    await rename(this.path, this.rotatedPath).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });
  }

  record(type, fields = {}) {
    if (typeof type !== "string" || !type) return Promise.resolve(null);
    const operation = this.writeQueue.then(async () => {
      const record = {
        contract_version: CONTRACT_VERSION,
        occurred_at: this.clock(),
        process_id: process.pid,
        type,
        ...cleanFields(fields),
      };
      const line = `${JSON.stringify(record)}\n`;
      await this.#rotateIfNeeded(Buffer.byteLength(line));
      await appendFile(this.path, line, { encoding: "utf8", mode: 0o600 });
      this.lastError = null;
      return record;
    });
    this.writeQueue = operation.catch((error) => {
      this.lastError = error;
    });
    return operation.catch(() => null);
  }
}
