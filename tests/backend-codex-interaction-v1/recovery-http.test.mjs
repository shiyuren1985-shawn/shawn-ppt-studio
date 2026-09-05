import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import http from "node:http";
import { test } from "node:test";
import { createLabHttpServer } from "../../server/http-server.mjs";

const headers = { "content-type": "application/json", "x-shawn-ppt-studio": "1" };
const route = "/api/decks/demo/conversations/chat";

async function fixture(t) {
  const client = new EventEmitter();
  Object.assign(client, {
    ready: true, calls: [],
    subscribe(fn) { this.on("notification", fn); return () => this.off("notification", fn); },
    subscribeServerRequests(fn) { this.on("serverRequest", fn); return () => this.off("serverRequest", fn); },
    async start() { this.calls.push("start"); this.ready = true; },
    async request(method) {
      this.calls.push(method);
      if (method === "thread/resume") {
        await this.resumeGate;
        return { thread: { id: "thread", turns: [] } };
      }
      if (method === "turn/start") {
        this.emit("notification", { method: "turn/started", params: {
          threadId: "thread", turn: { id: "turn", status: "inProgress" },
        } });
        return { turn: { id: "turn" } };
      }
      return {};
    },
  });
  const context = {
    client, dataRoot: "/tmp/studio-recovery-test",
    monitoringRoot: "/tmp/studio-recovery-test/monitoring", overviewPython: "/fixture/python",
    pathPolicy: { requireReferenceImage: async value => value },
    discovery: { readDeck: async () => ({
      deck_id: "demo", label: "Demo", candidate_roots: [], outline: {
        path: "/tmp/studio-recovery-test/outline.md", deck_uid: "DEMO", revision_id: "r1", slides: [],
      },
    }) },
    conversations: {
      ready: true, threadIdFor: () => "thread", get: () => ({ archived_at: null }),
      touch: async () => ({}), activate: async () => ({}), archive: async () => ({}),
    },
  };
  const server = createLabHttpServer(context);
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(async () => {
    context.codexInteraction.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  const base = `http://127.0.0.1:${server.address().port}`;
  return { client, context, base,
    send: (url, body = {}) => fetch(`${base}${url}`, { method: "POST", headers, body: JSON.stringify(body) }),
  };
}

test("sending reserves the conversation before slow resume, preventing deletion and duplicate submission", async t => {
  const { client, context, base, send } = await fixture(t);
  let release;
  client.resumeGate = new Promise(resolve => { release = resolve; });
  const sending = send(`${route}/messages`, { message: "继续大纲" });
  while (!client.calls.includes("thread/resume")) await new Promise(resolve => setImmediate(resolve));
  assert.equal(context.codexInteraction.isBusy("thread"), true);
  const removed = await fetch(`${base}${route}`, { method: "DELETE", headers });
  assert.equal(removed.status, 409);
  assert.equal((await removed.json()).error.code, "conversation_active");
  const duplicate = await send(`${route}/messages`, { message: "重复发送" });
  assert.equal(duplicate.status, 409);
  assert.equal(client.calls.filter(method => method === "thread/resume").length, 1);
  release();
  const response = await sending;
  assert.equal(response.status, 200);
  await response.body.cancel();
  assert.equal(client.calls.filter(method => method === "turn/start").length, 1);
});

test("App Server loss closes SSE, releases busy state, and next explicit message restarts the client", async t => {
  const { client, context, send } = await fixture(t);
  const response = await send(`${route}/messages`, { message: "继续" });
  const body = response.text();
  client.ready = false;
  client.emit("appServerError", Object.assign(new Error("exited"), { code: "app_server_exited" }));
  const events = await body;
  assert.match(events, /event: error/);
  assert.match(events, /"terminal":true/);
  assert.doesNotMatch(events, /turn\/completed/);
  assert.equal(context.codexInteraction.isBusy("thread"), false);
  const next = await send(`${route}/messages`, { message: "检查结果后继续" });
  assert.equal(next.status, 200);
  assert.equal(client.calls.filter(method => method === "start").length, 1);
  await next.body.cancel();
});

test("a request preparing selections cannot dispatch into a replaced App Server connection", async t => {
  const { client, context, send } = await fixture(t);
  client.child = { connection: 1 };
  const originalRead = context.discovery.readDeck;
  context.discovery.readDeck = async () => {
    const deck = await originalRead();
    deck.outline.slides = [{ slide_uid: "PAGE", page_label: "P01" }];
    return deck;
  };
  let release;
  let reading = false;
  context.selectionProjection = { get: async () => {
    reading = true;
    await new Promise(resolve => { release = resolve; });
    return { status: "unselected" };
  } };
  const pending = send(`${route}/messages`, { message: "继续" });
  while (!reading) await new Promise(resolve => setImmediate(resolve));
  client.ready = false;
  client.emit("appServerError", new Error("disconnected while preparing"));
  client.child = { connection: 2 };
  const duplicate = await send(`${route}/messages`, { message: "再试一次" });
  assert.equal(duplicate.status, 409);
  assert.equal(context.codexInteraction.isBusy("thread"), true);
  release();
  assert.equal((await pending).status, 503);
  assert.equal(context.codexInteraction.isBusy("thread"), false);
  assert.equal(client.calls.includes("turn/start"), false);
});

test("replay closes even if the cursor already consumed the completion event", async t => {
  const { client, context, base } = await fixture(t);
  client.emit("notification", { method: "turn/completed", params: {
    threadId: "thread", turn: { id: "turn", status: "completed" },
  } });
  const last = context.codexInteraction.records("thread", "turn").at(-1).sequence;
  const response = await fetch(`${base}${route}/events?turn_id=turn&after=${last}`, {
    signal: AbortSignal.timeout(1500),
  });
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "");
});

test("a delayed snapshot cannot revive a completed turn or displace a newer live turn", async t => {
  const { client, context } = await fixture(t);
  client.emit("notification", { method: "turn/completed", params: {
    threadId: "thread", turn: { id: "old", status: "completed" },
  } });
  const relay = context.codexInteraction;
  relay.observeThreadSnapshot({ id: "thread", turns: [{ id: "old", status: "inProgress" }] });
  assert.equal(relay.activeTurn("thread"), null);
  assert.equal(relay.latestTurn("thread").status, "completed");
  assert.equal(relay.markStarting("thread"), true);
  client.emit("notification", { method: "turn/started", params: {
    threadId: "thread", turn: { id: "new", status: "inProgress" },
  } });
  relay.observeThreadSnapshot({ id: "thread", turns: [{ id: "older", status: "completed" }] });
  assert.equal(relay.activeTurn("thread"), "new");
  assert.equal(relay.latestTurn("thread").turnId, "new");
});

test("server-resolved approvals disappear from reconnect replay", async t => {
  const { client, context } = await fixture(t);
  const request = { id: 7, method: "item/commandExecution/requestApproval", params: {
    threadId: "thread", turnId: "turn", itemId: "item", availableDecisions: ["accept", "decline"],
  } };
  client.emit("serverRequest", request);
  client.emit("serverRequestResolved", { request, reason: "server_resolved" });
  const records = context.codexInteraction.records("thread", "turn");
  assert.equal(records.filter(record => record.event === "approval").length, 0);
  assert.equal(records.at(-1).event, "approval_resolution");
});

test("unsupported interactive requests get an explicit error instead of waiting invisibly", async t => {
  const { client, context } = await fixture(t);
  const replies = [];
  client.rejectServerRequest = (id, error) => replies.push({ id, error });
  client.emit("serverRequest", { id: 8, method: "item/tool/requestUserInput", params: {
    threadId: "thread", turnId: "turn", itemId: "question",
    questions: [{ id: "q", question: "Which direction?" }],
  } });
  assert.equal(replies.length, 1);
  assert.equal(replies[0].id, 8);
  assert.equal(replies[0].error.code, -32601);
  assert.match(replies[0].error.message, /normal text reply/);
  const record = context.codexInteraction.records("thread", "turn").at(-1);
  assert.equal(record.code, "unsupported_interactive_request");
  assert.notEqual(record.terminal, true);
  assert.equal(context.codexInteraction.isStreamFinished("thread", "turn"), false);
});

test("malformed JSON shapes fail at the request boundary instead of dispatching", async t => {
  const { client, send } = await fixture(t);
  for (const body of [null, [], 1, "hello"]) {
    const response = await send(`${route}/messages`, body);
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error.code, "invalid_json_object");
  }
  assert.deepEqual(client.calls, []);
});

test("loopback API rejects remote origins and browser writes lacking the existing request header", async t => {
  const { base, client } = await fixture(t);
  for (const requestHeaders of [
    { ...headers, origin: "https://example.com" },
    { "content-type": "application/json", origin: base, "sec-fetch-site": "same-origin" },
  ]) {
    const response = await fetch(`${base}${route}/messages`, {
      method: "POST", headers: requestHeaders, body: JSON.stringify({ message: "no" }),
    });
    assert.equal(response.status, 403);
  }
  const hostStatus = await new Promise((resolve, reject) => {
    const req = http.request(`${base}${route}/messages`, {
      method: "POST", headers: { ...headers, host: "attacker.example" },
    }, response => { response.resume(); resolve(response.statusCode); });
    req.on("error", reject);
    req.end(JSON.stringify({ message: "no" }));
  });
  assert.equal(hostStatus, 403);
  assert.deepEqual(client.calls, []);
});

test("an image removed between validation and streaming cannot crash the HTTP bridge", async t => {
  const { context, base } = await fixture(t);
  context.selectionProjection = { resolveImage: async () => ({
    path: "/this-fixture-path-does-not-exist/removed.png", content_type: "image/png", size_bytes: 10,
  }) };
  await assert.rejects(async () => {
    const response = await fetch(`${base}/api/selected-image?deck_id=demo&slide_uid=PAGE`);
    await response.arrayBuffer();
  });
  assert.equal((await fetch(`${base}/api/health`)).status, 200);
});
