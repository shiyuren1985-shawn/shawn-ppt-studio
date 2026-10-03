import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { StudioConversationLifecycle } from "../../server/studio-codex-storage.mjs";
import { AppServerClient } from "../../server/app-server-client.mjs";
import { requireConversationClient } from "../../server/http-server.mjs";

test("dispatch reload coalesces concurrent requests and leaves active/preparing turns untouched", async () => {
  let syncs = 0, stops = 0;
  const context = {
    client: { ready: true, async stop() { stops++; }, async start() {} },
    conversationLifecycle: { ready: true, async refreshAuthenticationFromLegacy() { syncs++; return true; } },
    codexInteraction: { activeEntries: () => [], startingThreads: new Set() },
  };
  await Promise.all([requireConversationClient(context), requireConversationClient(context)]);
  assert.equal(syncs, 1);
  assert.equal(stops, 1);
  context.codexInteraction.startingThreads.add("preparing");
  await requireConversationClient(context);
  assert.equal(stops, 1);
  context.codexInteraction.startingThreads.clear();
  context.codexInteraction.activeEntries = () => [{ threadId: "running" }];
  await requireConversationClient(context);
  assert.equal(syncs, 1);
  assert.equal(stops, 1);
});

test("renewed main login replaces stale copy but never downgrades or switches Studio account", async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-auth-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const legacyHome = path.join(root, "main");
  await mkdir(legacyHome);
  const auth = (day, account = "same") => JSON.stringify({ last_refresh: `2026-09-${day}T00:00:00Z`, tokens: { account_id: account, access_token: `test-${day}` } });
  const source = path.join(legacyHome, "auth.json");
  await writeFile(source, auth("01"));
  const lifecycle = new StudioConversationLifecycle({ dataRoot: root, legacyHome, cwd: root, executable: "codex" });
  await lifecycle.initialize();
  const target = path.join(lifecycle.isolatedHome, "auth.json");
  assert.equal(await lifecycle.refreshAuthenticationFromLegacy(), false);
  await writeFile(source, auth("09"));
  assert.equal(await lifecycle.refreshAuthenticationFromLegacy(), true);
  assert.equal(await readFile(target, "utf8"), auth("09"));
  await writeFile(source, auth("02"));
  assert.equal(await lifecycle.refreshAuthenticationFromLegacy(), false);
  await writeFile(source, auth("10", "different"));
  assert.equal(await lifecycle.refreshAuthenticationFromLegacy(), false);
  assert.equal(await readFile(target, "utf8"), auth("09"));
});

test("expired cached account refreshes once across concurrent sends and invalidates misleading login", async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-auth-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const token = `test.${Buffer.from(JSON.stringify({ exp: 1 })).toString("base64url")}.test`;
  await writeFile(path.join(root, "auth.json"), JSON.stringify({ tokens: { access_token: token } }));
  const client = new AppServerClient({ executable: "unused", cwd: root, env: { CODEX_HOME: root } });
  client.account = { type: "chatgpt" };
  let calls = 0;
  client.request = async (method, params) => {
    calls++;
    assert.equal(method, "account/read");
    assert.equal(params.refreshToken, true);
    throw new Error("Your access token could not be refreshed. Please log out and sign in again.");
  };
  const results = await Promise.allSettled([client.prepareAuthentication(), client.prepareAuthentication()]);
  assert.equal(calls, 1);
  assert.ok(results.every(result => result.reason?.code === "authentication_required"));
  assert.equal(client.account, null);
  client.request = async () => ({ account: { type: "chatgpt" } });
  await client.prepareAuthentication();
  assert.equal(client.account.type, "chatgpt");
});
