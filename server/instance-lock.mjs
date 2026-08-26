import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, rm } from "node:fs/promises";
import path from "node:path";

import { studioLibraryRoot } from "./studio-library.mjs";

const CONTRACT_VERSION = 1;

function processIsAlive(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
}

async function readLock(lockPath) {
  try {
    return JSON.parse(await readFile(lockPath, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    return {};
  }
}

export class StudioInstanceLock {
  constructor({
    dataRoot,
    pid = process.pid,
    clock = () => new Date().toISOString(),
    isProcessAlive = processIsAlive,
  }) {
    this.libraryRoot = studioLibraryRoot(dataRoot);
    this.path = path.join(this.libraryRoot, "studio-server.lock");
    this.pid = pid;
    this.clock = clock;
    this.isProcessAlive = isProcessAlive;
    this.token = randomUUID();
    this.acquired = false;
  }

  async acquire() {
    await mkdir(this.libraryRoot, { recursive: true });
    for (let attempt = 0; attempt < 3; attempt += 1) {
      let handle;
      try {
        handle = await open(this.path, "wx", 0o600);
        await handle.writeFile(`${JSON.stringify({
          contract_version: CONTRACT_VERSION,
          process_id: this.pid,
          token: this.token,
          acquired_at: this.clock(),
        })}\n`, "utf8");
        this.acquired = true;
        return;
      } catch (error) {
        if (error?.code !== "EEXIST") throw error;
        const current = await readLock(this.path);
        if (this.isProcessAlive(current?.process_id)) {
          const conflict = new Error("another Shawn PPT Studio process is already using Studio Library");
          conflict.code = "STUDIO_LIBRARY_IN_USE";
          throw conflict;
        }
        await rm(this.path, { force: true });
      } finally {
        await handle?.close().catch(() => {});
      }
    }
    const error = new Error("Studio Library lock could not be acquired");
    error.code = "STUDIO_LIBRARY_LOCK_FAILED";
    throw error;
  }

  async release() {
    if (!this.acquired) return;
    const current = await readLock(this.path);
    if (current?.token === this.token) await rm(this.path, { force: true });
    this.acquired = false;
  }
}
