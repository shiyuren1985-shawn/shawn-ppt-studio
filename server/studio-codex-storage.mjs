import { randomUUID } from "node:crypto";
import { access, chmod, copyFile, lstat, mkdir, readFile, realpath, rename, rm, stat, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { AppServerClient } from "./app-server-client.mjs";
import { studioLibraryRoot } from "./studio-library.mjs";
import { resolveShawnSkillRoot } from "../integrations/skill-paths.mjs";

export const STUDIO_CODEX_HOME_DIRECTORY = "Studio Codex Home";
export const CONVERSATION_RETENTION_DAYS = 10;

const MIGRATION_CONTRACT_VERSION = 1;
const SAFE_THREAD_STATES = new Set(["idle", "notLoaded"]);
const CAPABILITY_FILES = ["auth.json", "config.toml"];

async function exists(target) {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
}

function nowIso(clock) {
  const value = clock();
  return value instanceof Date ? value.toISOString() : new Date(value).toISOString();
}

function asDate(value) {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date : null;
}

export function studioCodexHome(dataRoot) {
  return path.join(studioLibraryRoot(dataRoot), STUDIO_CODEX_HOME_DIRECTORY);
}

export function resolveLegacyCodexHome(env = process.env, home = os.homedir()) {
  return path.resolve(
    env.SHAWN_PPT_STUDIO_LEGACY_CODEX_HOME
      || env.CODEX_HOME
      || path.join(home, ".codex"),
  );
}

export function isolatedCodexEnvironment(baseEnv, isolatedHome) {
  return {
    ...baseEnv,
    CODEX_HOME: path.resolve(isolatedHome),
    CODEX_SQLITE_HOME: path.resolve(isolatedHome),
  };
}

export function retentionCutoff(now, days = CONVERSATION_RETENTION_DAYS) {
  const current = asDate(now);
  if (!current) throw new Error("retention clock returned an invalid date");
  const cutoff = new Date(current);
  cutoff.setHours(0, 0, 0, 0);
  cutoff.setDate(cutoff.getDate() - days);
  return cutoff;
}

export function isPastConversationRetention(lastUsedAt, now, days = CONVERSATION_RETENTION_DAYS) {
  const lastUsed = asDate(lastUsedAt);
  if (!lastUsed) return false;
  return lastUsed < retentionCutoff(now, days);
}

export function threadIsSafeForStorageChange(thread) {
  const status = typeof thread?.status === "string" ? thread.status : thread?.status?.type;
  if (!SAFE_THREAD_STATES.has(status)) return false;
  return !(thread?.turns || []).some((turn) => [
    "inProgress",
    "queued",
    "waitingOnApproval",
  ].includes(turn?.status));
}

function publicStorageHealth(instance) {
  return {
    ready: instance.ready,
    isolated: true,
    retention_days: instance.retentionDays,
    migration_pending_count: instance.migrationPendingCount,
    cleanup_pending_count: instance.cleanupPendingCount,
    last_maintenance_at: instance.lastMaintenanceAt,
    error: instance.lastError?.message || null,
    image_skill_error: instance.imageSkillError?.message || null,
  };
}

export class StudioConversationLifecycle {
  constructor({
    dataRoot,
    executable,
    cwd,
    baseEnv = process.env,
    isolatedHome = null,
    legacyHome = null,
    clock = () => new Date(),
    retentionDays = CONVERSATION_RETENTION_DAYS,
    legacyClientFactory = null,
  }) {
    this.dataRoot = path.resolve(dataRoot);
    this.executable = executable;
    this.cwd = cwd;
    this.baseEnv = baseEnv;
    this.isolatedHome = path.resolve(
      isolatedHome || baseEnv.SHAWN_PPT_STUDIO_CODEX_HOME || studioCodexHome(this.dataRoot),
    );
    this.legacyHome = path.resolve(legacyHome || resolveLegacyCodexHome(baseEnv));
    this.clock = clock;
    this.retentionDays = retentionDays;
    this.legacyClientFactory = legacyClientFactory || (() => new AppServerClient({
      executable: this.executable,
      cwd: this.cwd,
      env: isolatedCodexEnvironment(this.baseEnv, this.legacyHome),
      requestTimeoutMs: 60_000,
    }));
    this.journalPath = path.join(
      studioLibraryRoot(this.dataRoot),
      "conversation-storage-lifecycle.json",
    );
    this.journal = {
      contract_version: MIGRATION_CONTRACT_VERSION,
      migrations: {},
      cleanups: {},
    };
    this.ready = false;
    this.lastError = null;
    this.imageSkillError = null;
    this.lastMaintenanceAt = null;
    this.running = null;
  }

  get env() {
    return isolatedCodexEnvironment(this.baseEnv, this.isolatedHome);
  }

  get migrationPendingCount() {
    return Object.values(this.journal.migrations).filter((entry) => (
      !["complete", "not_required"].includes(entry.phase)
    )).length;
  }

  get cleanupPendingCount() {
    return Object.values(this.journal.cleanups).filter((entry) => entry.phase !== "complete").length;
  }

  health() {
    return publicStorageHealth(this);
  }

  async initialize() {
    if (this.isolatedHome === this.legacyHome) {
      throw Object.assign(new Error("Studio Codex storage must be separate from the main Codex home"), {
        code: "studio_codex_home_not_isolated",
      });
    }
    await mkdir(this.isolatedHome, { recursive: true, mode: 0o700 });
    const isolatedReal = await realpath(this.isolatedHome);
    const legacyReal = await realpath(this.legacyHome).catch((error) => {
      if (error?.code === "ENOENT") return this.legacyHome;
      throw error;
    });
    if (isolatedReal === legacyReal) {
      throw Object.assign(new Error("Studio Codex storage must be separate from the main Codex home"), {
        code: "studio_codex_home_not_isolated",
      });
    }
    await chmod(this.isolatedHome, 0o700).catch(() => {});
    for (const filename of CAPABILITY_FILES) {
      await this.#copyCapabilityIfMissing(filename);
    }
    this.imageSkillError = null;
    await this.#mountImageSkill().catch((error) => { this.imageSkillError = error; });
    try {
      const parsed = JSON.parse(await readFile(this.journalPath, "utf8"));
      if (
        parsed?.contract_version !== MIGRATION_CONTRACT_VERSION
        || !parsed.migrations || typeof parsed.migrations !== "object" || Array.isArray(parsed.migrations)
        || !parsed.cleanups || typeof parsed.cleanups !== "object" || Array.isArray(parsed.cleanups)
      ) {
        throw new Error("conversation storage lifecycle journal has an invalid root");
      }
      this.journal = parsed;
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      await this.#writeJournal();
    }
    this.ready = true;
    this.lastError = null;
    return this.health();
  }

  async refreshAuthenticationFromLegacy() {
    const source = path.join(this.legacyHome, "auth.json");
    if (!(await exists(source))) return false;
    await this.#atomicCopy(source, path.join(this.isolatedHome, "auth.json"), 0o600);
    return true;
  }

  run({ conversations, isolatedClient, codexInteraction = null } = {}) {
    if (this.running) return this.running;
    const operation = this.#run({ conversations, isolatedClient, codexInteraction });
    this.running = operation.finally(() => {
      this.running = null;
    });
    return this.running;
  }

  async #run({ conversations, isolatedClient, codexInteraction }) {
    if (!this.ready || !conversations?.ready || !isolatedClient?.ready) return this.health();
    let legacyClient = null;
    const legacy = async () => {
      if (!legacyClient) {
        legacyClient = this.legacyClientFactory();
        await legacyClient.start();
      }
      return legacyClient;
    };
    try {
      for (const entry of Object.values(this.journal.cleanups)) {
        if (["planned", "remote_deleted"].includes(entry.phase)) {
          conversations.suppress?.(entry.conversation_id);
        }
      }
      const records = conversations.allRecords();
      for (const record of records) {
        if (isPastConversationRetention(record.last_used_at, this.clock(), this.retentionDays)) {
          await this.#cleanupExpired({ record, conversations, isolatedClient, legacy, codexInteraction });
        } else {
          await this.#migrateRecent({ record, isolatedClient, legacy });
        }
      }
      this.lastMaintenanceAt = nowIso(this.clock);
      this.lastError = null;
      return this.health();
    } catch (error) {
      this.lastError = error;
      throw error;
    } finally {
      await legacyClient?.stop().catch(() => {});
    }
  }

  async #migrateRecent({ record, isolatedClient, legacy }) {
    const threadId = record.thread_id;
    const isolated = await this.#readThread(isolatedClient, threadId, true);
    if (isolated.found && this.journal.migrations[threadId]?.phase === "complete") return;
    let verified = isolated.found;
    let sourcePath = null;

    if (!verified) {
      const legacyClient = await legacy();
      const source = await this.#readThread(legacyClient, threadId);
      if (!source.found) {
        await this.#setMigration(record, "pending", { error: "source thread is unavailable" });
        return;
      }
      if (!threadIsSafeForStorageChange(source.thread)) {
        await this.#setMigration(record, "waiting_for_idle", { error: null });
        return;
      }
      sourcePath = source.thread.path;
      if (!sourcePath || !this.#insideLegacyHome(sourcePath)) {
        await this.#setMigration(record, "pending", { error: "source thread path is unavailable" });
        return;
      }
      const destination = this.#migrationDestination(record, sourcePath);
      await this.#atomicCopy(sourcePath, destination, 0o600);
      await this.#setMigration(record, "copied", { source_path: sourcePath, destination_path: destination, error: null });
      const copied = await this.#readThread(isolatedClient, threadId, true);
      verified = copied.found;
      if (!verified) {
        await this.#setMigration(record, "copied", { error: "isolated thread verification failed" });
        return;
      }
    }

    await this.#setMigration(record, "verified", { error: null });
    const legacyClient = await legacy();
    const source = await this.#readThread(legacyClient, threadId);
    if (source.found) {
      if (!threadIsSafeForStorageChange(source.thread)) {
        await this.#setMigration(record, "verified", { error: "source thread became active" });
        return;
      }
      await legacyClient.request("thread/delete", { threadId }, 60_000);
    }
    await this.#setMigration(record, "complete", { error: null });
  }

  async #cleanupExpired({ record, conversations, isolatedClient, legacy, codexInteraction }) {
    const threadId = record.thread_id;
    const journal = this.journal.cleanups[threadId];
    if (journal?.phase === "remote_deleted") {
      await conversations.purge(record.deck_uid, record.conversation_id);
      await this.#setCleanup(record, "complete", { error: null });
      await this.#setMigration(record, "not_required", { error: null });
      return;
    }
    if (codexInteraction?.isBusy?.(threadId) || codexInteraction?.activeTurn?.(threadId)) {
      await this.#setCleanup(record, "waiting_for_idle", { error: null });
      return;
    }

    const isolated = await this.#readThread(isolatedClient, threadId);
    const legacyClient = await legacy();
    const source = await this.#readThread(legacyClient, threadId);
    const existing = [isolated, source].filter((candidate) => candidate.found);
    if (existing.some((candidate) => !threadIsSafeForStorageChange(candidate.thread))) {
      await this.#setCleanup(record, "waiting_for_idle", { error: null });
      return;
    }

    // Remote reads can yield while the user reopens or starts work in this conversation.
    const current = conversations.allRecords().find((candidate) => (
      candidate.conversation_id === record.conversation_id && candidate.deck_uid === record.deck_uid
    ));
    if (!current) return;
    if (codexInteraction?.isBusy?.(threadId) || codexInteraction?.activeTurn?.(threadId)) {
      await this.#setCleanup(record, "waiting_for_idle", { error: null });
      return;
    }
    if (!isPastConversationRetention(current.last_used_at, this.clock(), this.retentionDays)) return;
    // Claim before the journal write yields; index mutations honor this claim.
    conversations.suppress?.(record.conversation_id);
    try {
      await this.#setCleanup(record, "planned", { error: null });
    } catch (error) {
      conversations.unsuppress?.(record.conversation_id);
      throw error;
    }
    if (isolated.found) await isolatedClient.request("thread/delete", { threadId }, 60_000);
    if (source.found) await legacyClient.request("thread/delete", { threadId }, 60_000);
    await this.#setCleanup(record, "remote_deleted", { error: null });
    await conversations.purge(record.deck_uid, record.conversation_id);
    await this.#setCleanup(record, "complete", { error: null });
    await this.#setMigration(record, "not_required", { error: null });
  }

  async #readThread(client, threadId, includeTurns = false) {
    try {
      const result = await client.request("thread/read", { threadId, includeTurns }, 60_000);
      if (result?.thread?.id !== threadId) {
        throw Object.assign(new Error("Codex thread read returned an invalid thread identity"), {
          code: "invalid_thread_response",
        });
      }
      return { found: true, thread: result.thread };
    } catch (error) {
      const message = String(error?.message || "").toLowerCase();
      if (
        error?.code === "thread_not_found"
        || /^thread(?: [^\n]+)? not found[.!]?$/.test(message)
        || message.includes("no rollout found")
      ) return { found: false, thread: null };
      throw error;
    }
  }

  #insideLegacyHome(candidate) {
    const resolved = path.resolve(candidate);
    return resolved.startsWith(`${this.legacyHome}${path.sep}`);
  }

  #migrationDestination(record, sourcePath) {
    const filename = path.basename(sourcePath);
    if (record.archived_at) return path.join(this.isolatedHome, "archived_sessions", filename);
    const relative = path.relative(path.join(this.legacyHome, "sessions"), sourcePath);
    if (relative && !relative.startsWith("..") && !path.isAbsolute(relative)) {
      return path.join(this.isolatedHome, "sessions", relative);
    }
    const created = asDate(record.created_at) || this.clock();
    const year = String(created.getFullYear());
    const month = String(created.getMonth() + 1).padStart(2, "0");
    const day = String(created.getDate()).padStart(2, "0");
    return path.join(this.isolatedHome, "sessions", year, month, day, filename);
  }

  async #copyCapabilityIfMissing(filename) {
    const source = path.join(this.legacyHome, filename);
    const destination = path.join(this.isolatedHome, filename);
    if (await exists(destination) || !(await exists(source))) return false;
    await this.#atomicCopy(source, destination, 0o600);
    return true;
  }

  async #mountImageSkill() {
    const sourceRoot = resolveShawnSkillRoot({
      codexHome: this.legacyHome,
      override: this.baseEnv.SHAWN_PPT_IMAGE_SKILL_ROOT,
    });
    const destination = path.join(this.isolatedHome, "skills", "shawn-ppt-image");
    const current = await lstat(destination).catch((error) => {
      if (error?.code === "ENOENT") return null;
      throw error;
    });
    if (current && !current.isSymbolicLink()) {
      if (current.isDirectory() && await exists(path.join(destination, "SKILL.md"))) return;
      throw new Error("Studio image skill mount is occupied by a local file or incomplete directory");
    }
    if (!(await exists(path.join(sourceRoot, "SKILL.md")))) {
      throw new Error("Studio image skill source is unavailable");
    }
    const sourceReal = await realpath(sourceRoot);
    if (current && await realpath(destination).catch(() => null) === sourceReal) return;
    await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
    // Register only the required capability in Codex's skill discovery root.
    // Keep sessions, memory, credentials and other main-home state isolated.
    const temporary = `${destination}.${process.pid}.${randomUUID()}.tmp`;
    try {
      await symlink(sourceReal, temporary, "dir");
      await rename(temporary, destination);
    } finally {
      await rm(temporary, { force: true }).catch(() => {});
    }
  }

  async #atomicCopy(source, destination, mode) {
    const sourceInfo = await stat(source);
    if (!sourceInfo.isFile()) throw new Error(`cannot copy non-file Codex resource: ${path.basename(source)}`);
    await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
    const temporary = `${destination}.${process.pid}.${randomUUID()}.tmp`;
    try {
      await copyFile(source, temporary);
      await chmod(temporary, mode);
      await rename(temporary, destination);
    } catch (error) {
      await rm(temporary, { force: true }).catch(() => {});
      throw error;
    }
  }

  async #setMigration(record, phase, extra) {
    this.journal.migrations[record.thread_id] = {
      conversation_id: record.conversation_id,
      deck_uid: record.deck_uid,
      phase,
      updated_at: nowIso(this.clock),
      ...this.journal.migrations[record.thread_id],
      ...extra,
      phase,
      updated_at: nowIso(this.clock),
    };
    await this.#writeJournal();
  }

  async #setCleanup(record, phase, extra) {
    this.journal.cleanups[record.thread_id] = {
      conversation_id: record.conversation_id,
      deck_uid: record.deck_uid,
      phase,
      updated_at: nowIso(this.clock),
      ...this.journal.cleanups[record.thread_id],
      ...extra,
      phase,
      updated_at: nowIso(this.clock),
    };
    await this.#writeJournal();
  }

  async #writeJournal() {
    await mkdir(path.dirname(this.journalPath), { recursive: true });
    const temporary = `${this.journalPath}.${process.pid}.${randomUUID()}.tmp`;
    try {
      await writeFile(temporary, `${JSON.stringify(this.journal, null, 2)}\n`, {
        encoding: "utf8",
        mode: 0o600,
        flag: "wx",
      });
      await rename(temporary, this.journalPath);
    } catch (error) {
      await rm(temporary, { force: true }).catch(() => {});
      throw error;
    }
  }
}
