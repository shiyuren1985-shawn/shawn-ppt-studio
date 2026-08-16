import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import http from "node:http";
import { test } from "node:test";

import { createLabHttpServer } from "../../server/http-server.mjs";

class FakeAppServer extends EventEmitter {
  constructor() {
    super();
    this.ready = true;
    this.pid = 123;
    this.account = { type: "chatgpt" };
    this.calls = [];
    this.approvalResponses = [];
    this.serverRequests = new Map();
    this.thread = { id: "thread-1", status: { type: "idle" }, turns: [] };
  }
  subscribe(listener) {
    this.on("notification", listener);
    return () => this.off("notification", listener);
  }
  subscribeServerRequests(listener) {
    this.on("serverRequest", listener);
    return () => this.off("serverRequest", listener);
  }
  async request(method, params) {
    this.calls.push({ method, params });
    if (method === "thread/resume") return { thread: this.thread };
    if (method === "thread/read") return { thread: this.thread };
    if (method === "turn/start") {
      setTimeout(() => {
        this.emit("notification", {
          method: "turn/started",
          params: {
            threadId: "thread-1",
            turn: { id: "turn-1", status: "inProgress", items: [] },
          },
        });
        this.emit("notification", {
          method: "item/agentMessage/delta",
          params: {
            threadId: "thread-1",
            turnId: "turn-1",
            itemId: "message-1",
            delta: "正在处理。",
          },
        });
      }, 5);
      return { turn: { id: "turn-1", status: "inProgress", items: [] } };
    }
    if (method === "turn/steer") return { turnId: params.expectedTurnId };
    if (method === "turn/interrupt") {
      setTimeout(() => {
        const turn = { id: params.turnId, status: "interrupted", items: [] };
        this.thread.turns.push(turn);
        this.emit("notification", {
          method: "turn/completed",
          params: { threadId: params.threadId, turn },
        });
      }, 5);
      return {};
    }
    throw new Error(`unexpected method: ${method}`);
  }
  serverRequest(requestId) { return this.serverRequests.get(String(requestId)) || null; }
  respondToServerRequest(requestId, result) {
    const key = String(requestId);
    if (!this.serverRequests.has(key)) throw new Error("approval request is not active");
    this.approvalResponses.push({ requestId: key, result });
    this.serverRequests.delete(key);
  }
  emitServerRequest(request) {
    this.serverRequests.set(String(request.requestId ?? request.id), request);
    this.emit("serverRequest", request);
  }
}

function writeHeaders() {
  return {
    "content-type": "application/json",
    "x-shawn-ppt-studio": "1",
  };
}

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return `http://127.0.0.1:${server.address().port}`;
}

async function waitForText(reader, pattern) {
  const decoder = new TextDecoder();
  let text = "";
  while (!pattern.test(text)) {
    const { done, value } = await reader.read();
    if (done) break;
    text += decoder.decode(value, { stream: true });
  }
  return text;
}

function fixtureContext() {
  const client = new FakeAppServer();
  const studioRuleState = { rules: ["测试中的全局长期规则"] };
  const deck = {
    deck_id: "fixture",
    label: "Fixture",
    candidate_roots: [{ path: "/tmp/shawn-studio/candidates" }],
    outline: {
      deck_uid: "TEST_DECK",
      path: "/tmp/shawn-studio/outline/outline.md",
      revision_id: "sha256:test",
      text: "---\ndeck_uid: TEST_DECK\n---\n| P1 | Title | Body |",
      slides: [{ slide_uid: "SLIDE_1", page_label: "P01" }],
    },
  };
  const context = {
    client,
    codeRoot: "/tmp/shawn-studio",
    dataRoot: "/tmp/shawn-studio",
    labRoot: "/tmp/shawn-studio",
    monitoringRoot: "/tmp/shawn-studio/monitoring",
    overviewPython: "/tmp/shawn-studio/runtime/python3",
    pathPolicy: {
      imageRoot: "/tmp/shawn-studio/runtime/images",
      requireReferenceImage: async (value) => value,
    },
    discovery: {
      readDeck: async () => deck,
      health: () => ({ ready: true }),
    },
    conversations: {
      ready: true,
      threadIdFor: () => "thread-1",
      get: () => ({ conversation_id: "conversation-1", title: "Test" }),
      touch: async () => ({ conversation_id: "conversation-1", title: "Test" }),
      health: () => ({ ready: true }),
    },
    selectionProjection: {
      get: async () => ({
        status: "selected",
        confirmed: true,
        selected_candidates: [{
          candidate_id: "candidate-1",
          path: "/tmp/shawn-studio/candidates/p01.png",
          file_sha256: "abc",
          width: 1672,
          height: 941,
        }],
      }),
    },
    production: {
      health: () => ({ ready: true }),
      create: () => { throw new Error("hidden production worker must not be called"); },
      execute: () => { throw new Error("hidden production worker must not be called"); },
    },
    candidateEdits: {
      health: () => ({ ready: true }),
      create: () => { throw new Error("hidden edit worker must not be called"); },
      execute: () => { throw new Error("hidden edit worker must not be called"); },
    },
    studioRules: {
      ready: true,
      list: () => ({ contract_version: 1, rules: [...studioRuleState.rules], updated_at: null }),
      replace: async (rules) => {
        studioRuleState.rules = [...rules];
        return { contract_version: 1, rules: [...studioRuleState.rules], updated_at: null };
      },
      rememberFromMessage: async (message) => {
        const match = String(message || "").match(/^\s*记住[，,:：]\s*(.+)$/s);
        if (!match) return { remembered: false, added: false, rule: null, rules: [...studioRuleState.rules] };
        const rule = match[1].trim();
        const added = !studioRuleState.rules.includes(rule);
        if (added) studioRuleState.rules.push(rule);
        return { remembered: true, added, rule, rules: [...studioRuleState.rules] };
      },
      health: () => ({ ready: true, rule_count: studioRuleState.rules.length, error: null }),
    },
  };
  return { client, context };
}

test("HTTP uses start, steer and interrupt on one official turn", async () => {
  const { client, context } = fixtureContext();
  const server = createLabHttpServer(context);
  const baseUrl = await listen(server);
  try {
    const startResponse = await fetch(
      `${baseUrl}/api/decks/fixture/conversations/conversation-1/messages`,
      {
        method: "POST",
        headers: { ...writeHeaders(), accept: "text/event-stream" },
        body: JSON.stringify({ message: "修改 P01 并作图", current_slide_uid: "SLIDE_1" }),
      },
    );
    assert.equal(startResponse.status, 200);
    const reader = startResponse.body.getReader();
    const initial = await waitForText(reader, /item\/agentMessage\/delta/);
    assert.match(initial, /event: codex/);
    assert.match(initial, /"delta":"正在处理。"/);

    const steer = await fetch(
      `${baseUrl}/api/decks/fixture/conversations/conversation-1/steer`,
      {
        method: "POST",
        headers: writeHeaders(),
        body: JSON.stringify({ message: "方向调整，只改标题", expected_turn_id: "turn-1" }),
      },
    );
    assert.equal(steer.status, 202);

    const interrupt = await fetch(
      `${baseUrl}/api/decks/fixture/conversations/conversation-1/interrupt`,
      {
        method: "POST",
        headers: writeHeaders(),
        body: JSON.stringify({ turn_id: "turn-1" }),
      },
    );
    assert.equal(interrupt.status, 202);
    const remainder = await waitForText(reader, /turn\/completed/);
    assert.match(remainder, /"status":"interrupted"/);

    assert.deepEqual(client.calls.map((call) => call.method), [
      "thread/resume",
      "turn/start",
      "turn/steer",
      "turn/interrupt",
    ]);
    const started = client.calls.find((call) => call.method === "turn/start").params;
    assert.equal(Object.hasOwn(started, "outputSchema"), false);
    assert.deepEqual(started.input.filter((item) => item.type === "skill").map((item) => item.name), [
      "shawn-ppt-image",
      "imagegen",
    ]);
    assert.match(started.input.find((item) => item.type === "text").text, /测试中的全局长期规则/);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("HTTP exposes editable rules and remember messages persist before dispatch", async () => {
  const { client, context } = fixtureContext();
  const server = createLabHttpServer(context);
  const baseUrl = await listen(server);
  try {
    const initialResponse = await fetch(`${baseUrl}/api/studio-rules`);
    assert.equal(initialResponse.status, 200);
    assert.deepEqual((await initialResponse.json()).rules, ["测试中的全局长期规则"]);

    const saveResponse = await fetch(`${baseUrl}/api/studio-rules`, {
      method: "PUT",
      headers: writeHeaders(),
      body: JSON.stringify({ rules: ["保存后的长期规则"] }),
    });
    assert.equal(saveResponse.status, 200);
    assert.deepEqual((await saveResponse.json()).rules, ["保存后的长期规则"]);

    const rememberResponse = await fetch(
      `${baseUrl}/api/decks/fixture/conversations/conversation-1/messages`,
      {
        method: "POST",
        headers: { ...writeHeaders(), accept: "text/event-stream" },
        body: JSON.stringify({ message: "记住，新加入的长期规则", current_slide_uid: "SLIDE_1" }),
      },
    );
    assert.equal(rememberResponse.status, 200);
    const reader = rememberResponse.body.getReader();
    const events = await waitForText(reader, /studio_rule_saved/);
    assert.match(events, /"added":true/);
    assert.match(events, /新加入的长期规则/);
    await reader.cancel();

    const started = client.calls.find((call) => call.method === "turn/start").params;
    const prompt = started.input.find((item) => item.type === "text").text;
    assert.match(prompt, /保存后的长期规则/);
    assert.match(prompt, /新加入的长期规则/);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("history returns typed App Server items instead of a messages-only projection", async () => {
  const { client, context } = fixtureContext();
  client.thread.turns = [{
    id: "turn-history",
    status: "completed",
    items: [{ id: "command-1", type: "commandExecution", status: "completed", command: "test" }],
  }];
  const server = createLabHttpServer(context);
  const baseUrl = await listen(server);
  try {
    const response = await fetch(
      `${baseUrl}/api/decks/fixture/conversations/conversation-1`,
    );
    const body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.turns[0].items[0].type, "commandExecution");
    assert.equal(body.thread.id, "thread-1");
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("approval resolution is recorded and reconnect replay omits the resolved actionable request", async () => {
  const { client, context } = fixtureContext();
  const server = createLabHttpServer(context);
  const baseUrl = await listen(server);
  try {
    client.emitServerRequest({
      id: 71,
      requestId: "71",
      method: "item/commandExecution/requestApproval",
      params: {
        threadId: "thread-1",
        turnId: "turn-approval",
        itemId: "command-approval",
        availableDecisions: ["acceptForSession", "decline"],
      },
    });

    const response = await fetch(`${baseUrl}/api/codex/approvals/71`, {
      method: "POST",
      headers: writeHeaders(),
      body: JSON.stringify({ decision: "acceptForSession" }),
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { resolved: true, decision: "acceptForSession" });
    assert.deepEqual(client.approvalResponses, [{
      requestId: "71",
      result: { decision: "acceptForSession" },
    }]);

    const controller = new AbortController();
    const replayResponse = await fetch(
      `${baseUrl}/api/decks/fixture/conversations/conversation-1/events?turn_id=turn-approval&after=0`,
      { signal: controller.signal },
    );
    assert.equal(replayResponse.status, 200);
    const reader = replayResponse.body.getReader();
    const replay = await waitForText(reader, /approval_resolution/);
    assert.match(replay, /event: approval_resolution/);
    assert.match(replay, /"resolved":true/);
    assert.doesNotMatch(replay, /event: approval\r?\n/);
    controller.abort();
    await reader.cancel().catch(() => {});
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("disconnecting the workspace SSE only detaches the viewer and does not interrupt the turn", async () => {
  const { client, context } = fixtureContext();
  const server = createLabHttpServer(context);
  const baseUrl = await listen(server);
  try {
    const controller = new AbortController();
    const response = await fetch(
      `${baseUrl}/api/decks/fixture/conversations/conversation-1/messages`,
      {
        method: "POST",
        headers: { ...writeHeaders(), accept: "text/event-stream" },
        body: JSON.stringify({ message: "开始长任务", current_slide_uid: "SLIDE_1" }),
        signal: controller.signal,
      },
    );
    const reader = response.body.getReader();
    await waitForText(reader, /item\/agentMessage\/delta/);
    controller.abort();
    await reader.cancel().catch(() => {});
    await new Promise((resolve) => setTimeout(resolve, 20));

    assert.equal(context.codexInteraction.activeTurn("thread-1"), "turn-1");
    assert.equal(client.calls.some((call) => call.method === "turn/interrupt"), false);
    client.emit("notification", {
      method: "turn/completed",
      params: { threadId: "thread-1", turn: { id: "turn-1", status: "completed", items: [] } },
    });
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
