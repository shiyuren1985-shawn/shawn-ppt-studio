import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { AppServerClient } from "../../server/app-server-client.mjs";

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-client-recovery-"));
  const executable = path.join(root, "fake.mjs");
  await writeFile(executable, `#!/usr/bin/env node
import readline from "node:readline";
const emit = (message) => process.stdout.write(JSON.stringify(message) + "\\n");
const lines = readline.createInterface({ input: process.stdin });
for await (const line of lines) {
  const message = JSON.parse(line);
  if (!Object.hasOwn(message, "id")) continue;
  if (message.error) emit({ method: "test/rejected", params: message });
  if (message.method === "initialize") emit({ id: message.id, result: {} });
  if (message.method === "account/read") {
    await new Promise(resolve => setTimeout(resolve, 35));
    emit({ id: message.id, result: { account: { type: "chatgpt" } } });
  }
  if (message.method === "test/crash") process.exit(1);
  if (message.method === "test/requests") {
    for (const [id, turnId] of [["a", "turn-1"], ["b", "turn-2"]]) {
      emit({ id, method: "item/fileChange/requestApproval", params: { threadId: "thread", turnId, itemId: id } });
    }
    emit({ id: message.id, result: {} });
  }
  if (message.method === "test/resolve") {
    emit({ method: "serverRequest/resolved", params: { threadId: "thread", requestId: "a" } });
    emit({ id: message.id, result: {} });
  }
  if (message.method === "test/complete") {
    emit({ method: "turn/completed", params: { threadId: "thread", turn: { id: "turn-1", status: "interrupted" } } });
    emit({ id: message.id, result: {} });
  }
  if (message.method === "test/invalid") {
    emit(null);
    emit({ id: message.id, result: {} });
  }
}
`, { mode: 0o755 });
  const client = new AppServerClient({ executable, cwd: root,
    env: { ...process.env, PATH: `${path.dirname(process.execPath)}:${process.env.PATH || ""}` } });
  t.after(async () => { await client.stop(); await rm(root, { recursive: true, force: true }); });
  return client;
}

test("concurrent starts share initialization and both await authenticated readiness", async (t) => {
  const client = await fixture(t);
  const first = client.start();
  const second = client.start();
  assert.equal(first, second);
  await second;
  assert.equal(client.ready, true);
  assert.equal(client.account.type, "chatgpt");
  await first;
});

test("unexpected exit rejects pending requests and permits a fresh connection", async (t) => {
  const client = await fixture(t);
  await client.start();
  const firstPid = client.pid;
  await assert.rejects(client.request("test/crash"), { code: "app_server_exited" });
  assert.equal(client.pid, null);
  assert.equal(client.ready, false);
  assert.equal(client.account, null);
  assert.equal(client.pending.size, 0);
  await client.start();
  assert.equal(client.ready, true);
  assert.notEqual(client.pid, firstPid);
});

test("pipe errors become connection failures instead of uncaught EventEmitter errors", async (t) => {
  const client = await fixture(t);
  await client.start();
  const failure = once(client, "appServerError");
  client.child.stdin.emit("error", Object.assign(new Error("broken pipe"), { code: "EPIPE" }));
  assert.equal((await failure)[0].code, "EPIPE");
  assert.equal(client.ready, false);
  await client.start();
  assert.equal(client.ready, true);
});

test("server resolution and turn completion invalidate only their own approval requests", async (t) => {
  const client = await fixture(t);
  const resolutions = [];
  client.on("serverRequestResolved", (event) => resolutions.push(event));
  await client.start();
  await client.request("test/requests");
  await client.request("test/resolve");
  assert.equal(client.serverRequest("a"), null);
  assert.ok(client.serverRequest("b"));
  assert.equal(resolutions[0].reason, "server_resolved");
  assert.equal(resolutions[0].request.params.turnId, "turn-1");
  assert.throws(() => client.respondToServerRequest("a", { decision: "accept" }), { code: "approval_request_not_found" });
  await client.request("test/requests");
  await client.request("test/complete");
  assert.equal(client.serverRequest("a"), null);
  assert.ok(client.serverRequest("b"));
  assert.equal(resolutions[1].reason, "turn_completed");
});

test("non-object protocol lines are reported without crashing the running client", async (t) => {
  const client = await fixture(t);
  await client.start();
  const protocolError = once(client, "protocolError");
  await client.request("test/invalid");
  assert.match((await protocolError)[0].message, /invalid message/);
  assert.equal(client.ready, true);
});


test("unsupported interactive requests receive a protocol error without granting permission", async (t) => {
  const client = await fixture(t);
  await client.start();
  await client.request("test/requests");
  const received = once(client, "notification");
  const error = { code: -32601, message: "Unsupported interactive request" };
  client.rejectServerRequest("a", error);
  const [notification] = await received;
  assert.deepEqual(notification.params, { id: "a", error });
  assert.equal(client.serverRequest("a"), null);
  assert.ok(client.serverRequest("b"));
  assert.throws(() => client.rejectServerRequest("a", error), { code: "approval_request_not_found" });
});
