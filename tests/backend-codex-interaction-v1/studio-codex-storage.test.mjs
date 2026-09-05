import assert from "node:assert/strict";
import { access, mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { ConversationIndex } from "../../server/conversations.mjs";
import {
  isPastConversationRetention,
  isolatedCodexEnvironment,
  retentionCutoff,
  StudioConversationLifecycle,
  studioCodexHome,
  threadIsSafeForStorageChange,
} from "../../server/studio-codex-storage.mjs";

async function exists(target) {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
}

async function findThread(root, threadId) {
  const pending = [root];
  while (pending.length) {
    const directory = pending.pop();
    let entries;
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const candidate = path.join(directory, entry.name);
      if (entry.isDirectory()) pending.push(candidate);
      else if (entry.name.endsWith(`${threadId}.jsonl`)) return candidate;
    }
  }
  return null;
}

class FileBackedFakeClient {
  constructor({ home, sourceThreads = new Map() }) {
    this.home = home;
    this.sourceThreads = sourceThreads;
    this.deleted = new Set();
    this.calls = [];
    this.ready = true;
    this.started = false;
    this.failDeleteOnce = false;
  }

  async start() { this.started = true; }
  async stop() { this.started = false; }

  async request(method, params) {
    this.calls.push({ method, params });
    if (method === "thread/read") {
      if (this.deleted.has(params.threadId)) throw new Error("thread not found");
      const configured = this.sourceThreads.get(params.threadId);
      if (configured) return { thread: { id: params.threadId, ...configured } };
      const file = await findThread(this.home, params.threadId);
      if (!file) throw Object.assign(new Error("thread not found"), { code: "thread_not_found" });
      return { thread: { id: params.threadId, path: file, status: { type: "notLoaded" }, turns: [] } };
    }
    if (method === "thread/delete") {
      if (this.failDeleteOnce) {
        this.failDeleteOnce = false;
        throw new Error("simulated delete interruption");
      }
      this.deleted.add(params.threadId);
      return {};
    }
    throw new Error(`unexpected method: ${method}`);
  }
}

async function addConversation(index, at, { deckUid, threadId, archived = false }) {
  index.clock = () => at;
  const conversation = await index.create({ deckId: deckUid.toLowerCase(), deckUid, threadId });
  if (archived) await index.archive(deckUid, conversation.conversation_id);
  return conversation;
}

test("Studio Codex home is explicit, private, and bootstraps login/config without sharing task storage", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-codex-home-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const legacyHome = path.join(root, "Main Codex Home");
  await mkdir(legacyHome, { recursive: true });
  await writeFile(path.join(legacyHome, "auth.json"), "private-auth", { mode: 0o600 });
  await writeFile(path.join(legacyHome, "config.toml"), "model = 'test'\n", { mode: 0o600 });

  const lifecycle = new StudioConversationLifecycle({
    dataRoot: root,
    executable: "codex",
    cwd: root,
    legacyHome,
  });
  await lifecycle.initialize();

  assert.equal(lifecycle.isolatedHome, studioCodexHome(root));
  assert.notEqual(lifecycle.isolatedHome, legacyHome);
  assert.equal((await readFile(path.join(lifecycle.isolatedHome, "auth.json"), "utf8")), "private-auth");
  assert.equal((await readFile(path.join(lifecycle.isolatedHome, "config.toml"), "utf8")), "model = 'test'\n");
  assert.deepEqual(isolatedCodexEnvironment({ TEST: "1" }, lifecycle.isolatedHome), {
    TEST: "1",
    CODEX_HOME: lifecycle.isolatedHome,
    CODEX_SQLITE_HOME: lifecycle.isolatedHome,
  });
});

test("retention uses last_used_at and ten complete local calendar days", () => {
  const now = new Date(2026, 7, 27, 13, 0, 0);
  assert.equal(retentionCutoff(now).getTime(), new Date(2026, 7, 17, 0, 0, 0).getTime());
  assert.equal(isPastConversationRetention(new Date(2026, 7, 17, 0, 0, 0), now), false);
  assert.equal(isPastConversationRetention(new Date(2026, 7, 16, 23, 59, 59), now), true);
  assert.equal(threadIsSafeForStorageChange({ status: { type: "notLoaded" }, turns: [] }), true);
  assert.equal(threadIsSafeForStorageChange({ status: { type: "active", activeFlags: ["waitingOnApproval"] } }), false);
  assert.equal(threadIsSafeForStorageChange({ status: { type: "unknown" } }), false);
});

test("migration verifies recent threads before deleting the main-store copy and cleanup skips active work", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-conversation-lifecycle-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const legacyHome = path.join(root, "Main Codex Home");
  const sourceDirectory = path.join(legacyHome, "sessions", "2026", "08", "26");
  await mkdir(sourceDirectory, { recursive: true });
  await writeFile(path.join(legacyHome, "auth.json"), "auth", { mode: 0o600 });
  await writeFile(path.join(legacyHome, "config.toml"), "", { mode: 0o600 });

  const index = new ConversationIndex({ dataRoot: root });
  await index.initialize();
  const recent = await addConversation(index, "2026-08-26T10:00:00.000Z", { deckUid: "RECENT", threadId: "thread-recent" });
  const archived = await addConversation(index, "2026-08-25T10:00:00.000Z", { deckUid: "ARCHIVED", threadId: "thread-archived", archived: true });
  const expired = await addConversation(index, "2026-08-16T10:00:00.000Z", { deckUid: "EXPIRED", threadId: "thread-expired", archived: true });
  const activeExpired = await addConversation(index, "2026-08-15T10:00:00.000Z", { deckUid: "ACTIVE", threadId: "thread-active" });

  const sources = new Map();
  for (const threadId of ["thread-recent", "thread-archived", "thread-expired", "thread-active"]) {
    const source = path.join(sourceDirectory, `rollout-2026-08-26T10-00-00-${threadId}.jsonl`);
    await writeFile(source, `${threadId}\n`);
    sources.set(threadId, {
      path: source,
      status: { type: threadId === "thread-active" ? "active" : "notLoaded" },
      turns: [],
    });
  }
  const legacyClient = new FileBackedFakeClient({ home: legacyHome, sourceThreads: sources });
  const lifecycle = new StudioConversationLifecycle({
    dataRoot: root,
    executable: "codex",
    cwd: root,
    legacyHome,
    clock: () => new Date(2026, 7, 27, 13, 0, 0),
    legacyClientFactory: () => legacyClient,
  });
  await lifecycle.initialize();
  const isolatedClient = new FileBackedFakeClient({ home: lifecycle.isolatedHome });
  await lifecycle.run({ conversations: index, isolatedClient });

  assert.equal(Boolean(index.get("RECENT", recent.conversation_id)), true);
  assert.equal(Boolean(index.get("ARCHIVED", archived.conversation_id)), true);
  assert.equal(await exists(path.join(lifecycle.isolatedHome, "archived_sessions", `rollout-2026-08-26T10-00-00-thread-archived.jsonl`)), true);
  assert.equal(legacyClient.deleted.has("thread-recent"), true);
  assert.equal(legacyClient.deleted.has("thread-archived"), true);
  assert.equal(legacyClient.deleted.has("thread-expired"), true);
  assert.throws(() => index.get("EXPIRED", expired.conversation_id), /not found/);
  assert.equal(Boolean(index.get("ACTIVE", activeExpired.conversation_id)), true);
  assert.equal(legacyClient.deleted.has("thread-active"), false);
  assert.equal(lifecycle.health().migration_pending_count, 0);
  assert.equal(lifecycle.health().cleanup_pending_count, 1);

  const recentDeleteCount = legacyClient.calls.filter((call) => (
    call.method === "thread/delete" && call.params.threadId === "thread-recent"
  )).length;
  await lifecycle.run({ conversations: index, isolatedClient });
  assert.equal(legacyClient.calls.filter((call) => (
    call.method === "thread/delete" && call.params.threadId === "thread-recent"
  )).length, recentDeleteCount);
});

test("a recorded remote delete is completed locally after restart without deleting twice", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-cleanup-recovery-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const legacyHome = path.join(root, "Main Codex Home");
  await mkdir(legacyHome, { recursive: true });
  const index = new ConversationIndex({ dataRoot: root });
  await index.initialize();
  const expired = await addConversation(index, "2026-08-15T10:00:00.000Z", { deckUid: "RECOVER", threadId: "thread-recover" });
  const journalPath = path.join(root, "Studio Library", "conversation-storage-lifecycle.json");
  await mkdir(path.dirname(journalPath), { recursive: true });
  await writeFile(journalPath, JSON.stringify({
    contract_version: 1,
    migrations: {},
    cleanups: {
      "thread-recover": {
        conversation_id: expired.conversation_id,
        deck_uid: "RECOVER",
        phase: "remote_deleted",
        updated_at: "2026-08-27T01:00:00.000Z",
      },
    },
  }));
  const legacyClient = new FileBackedFakeClient({ home: legacyHome });
  const lifecycle = new StudioConversationLifecycle({
    dataRoot: root,
    executable: "codex",
    cwd: root,
    legacyHome,
    clock: () => new Date(2026, 7, 27, 13, 0, 0),
    legacyClientFactory: () => legacyClient,
  });
  await lifecycle.initialize();
  await lifecycle.run({ conversations: index, isolatedClient: new FileBackedFakeClient({ home: lifecycle.isolatedHome }) });
  assert.throws(() => index.get("RECOVER", expired.conversation_id), /not found/);
  assert.equal(legacyClient.calls.some((call) => call.method === "thread/delete"), false);
  assert.equal(lifecycle.health().cleanup_pending_count, 0);
});

test("an interrupted two-store cleanup stays hidden and resumes without a half-visible record", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-cleanup-interruption-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const legacyHome = path.join(root, "Main Codex Home");
  const legacySource = path.join(legacyHome, "sessions", "2026", "08", "15", "rollout-thread-half.jsonl");
  await mkdir(path.dirname(legacySource), { recursive: true });
  await writeFile(legacySource, "legacy\n");
  const index = new ConversationIndex({ dataRoot: root });
  await index.initialize();
  const expired = await addConversation(index, "2026-08-15T10:00:00.000Z", { deckUid: "HALF", threadId: "thread-half" });
  const legacyClient = new FileBackedFakeClient({
    home: legacyHome,
    sourceThreads: new Map([["thread-half", {
      path: legacySource,
      status: { type: "notLoaded" },
      turns: [],
    }]]),
  });
  legacyClient.failDeleteOnce = true;
  const lifecycle = new StudioConversationLifecycle({
    dataRoot: root,
    executable: "codex",
    cwd: root,
    legacyHome,
    clock: () => new Date(2026, 7, 27, 13, 0, 0),
    legacyClientFactory: () => legacyClient,
  });
  await lifecycle.initialize();
  const isolatedClient = new FileBackedFakeClient({ home: lifecycle.isolatedHome });
  await assert.rejects(lifecycle.run({ conversations: index, isolatedClient }), /simulated delete interruption/);
  assert.equal(index.list("HALF").conversations.length, 0);
  assert.equal(index.allRecords().length, 1);

  await lifecycle.run({ conversations: index, isolatedClient });
  assert.equal(index.allRecords().length, 0);
  assert.equal(lifecycle.health().cleanup_pending_count, 0);
  assert.equal(legacyClient.deleted.has("thread-half"), true);
  assert.throws(() => index.get("HALF", expired.conversation_id), /not found/);
});


test("symlink aliases cannot point the isolated home at main Codex storage", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-home-alias-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const legacyHome = path.join(root, "main");
  const isolatedHome = path.join(root, "alias");
  await mkdir(legacyHome);
  await symlink(legacyHome, isolatedHome);
  const lifecycle = new StudioConversationLifecycle({ dataRoot: root, cwd: root, legacyHome, isolatedHome });
  await assert.rejects(lifecycle.initialize(), { code: "studio_codex_home_not_isolated" });
});

async function retentionFixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-retention-race-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const legacyHome = path.join(root, "main");
  await mkdir(legacyHome);
  const index = new ConversationIndex({ dataRoot: root });
  await index.initialize();
  const record = await addConversation(index, "2026-08-15T10:00:00.000Z", { deckUid: "DECK", threadId: "thread" });
  const legacyClient = new FileBackedFakeClient({ home: legacyHome });
  const lifecycle = new StudioConversationLifecycle({ dataRoot: root, cwd: root, legacyHome,
    clock: () => new Date("2026-08-27T10:00:00.000Z"), legacyClientFactory: () => legacyClient });
  await lifecycle.initialize();
  const isolatedClient = new FileBackedFakeClient({ home: lifecycle.isolatedHome });
  return { index, record, lifecycle, isolatedClient, legacyClient };
}

test("an unloaded or uncertain thread read is not proof that retained history can be deleted", async (t) => {
  const { index, record, lifecycle, isolatedClient, legacyClient } = await retentionFixture(t);
  isolatedClient.request = async () => { throw new Error("thread not loaded"); };
  await assert.rejects(lifecycle.run({ conversations: index, isolatedClient }), /thread not loaded/);
  assert.equal(index.get("DECK", record.conversation_id).conversation_id, record.conversation_id);
  assert.equal(legacyClient.deleted.size, 0);
});

test("cleanup rechecks recent use after asynchronous remote reads", async (t) => {
  const { index, record, lifecycle, isolatedClient, legacyClient } = await retentionFixture(t);
  const request = legacyClient.request.bind(legacyClient);
  legacyClient.request = async (method, params) => {
    if (method === "thread/read") {
      index.clock = () => "2026-08-27T10:00:00.000Z";
      await index.activate("DECK", record.conversation_id);
    }
    return request(method, params);
  };
  await lifecycle.run({ conversations: index, isolatedClient });
  assert.equal(index.allRecords().length, 1);
  assert.equal(legacyClient.deleted.size, 0);
  assert.equal(isolatedClient.deleted.size, 0);
});

test("cleanup skips turns still preparing before turn/started arrives", async (t) => {
  const { index, lifecycle, isolatedClient, legacyClient } = await retentionFixture(t);
  await lifecycle.run({ conversations: index, isolatedClient,
    codexInteraction: { isBusy: () => true, activeTurn: () => null } });
  assert.equal(index.allRecords().length, 1);
  assert.equal(legacyClient.calls.length, 0);
  assert.equal(isolatedClient.calls.length, 0);
});

test("index mutations cannot revive a conversation already claimed by cleanup", async (t) => {
  const { index, record } = await retentionFixture(t);
  const pendingActivation = index.activate("DECK", record.conversation_id);
  index.suppress(record.conversation_id);
  await assert.rejects(pendingActivation, { code: "conversation_not_found" });
  await assert.rejects(index.touch("DECK", record.conversation_id), { code: "conversation_not_found" });
  await assert.rejects(index.rename("DECK", record.conversation_id, "Renamed"), { code: "conversation_not_found" });
  assert.equal(index.list("DECK").conversations.length, 0);
});


test("an incomplete thread response cannot authorize deleting a local conversation", async (t) => {
  const { index, lifecycle, isolatedClient } = await retentionFixture(t);
  isolatedClient.request = async () => ({});
  await assert.rejects(lifecycle.run({ conversations: index, isolatedClient }), { code: "invalid_thread_response" });
  assert.equal(index.allRecords().length, 1);
});
