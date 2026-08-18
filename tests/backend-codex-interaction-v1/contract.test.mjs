import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import path from "node:path";
import { test } from "node:test";

import {
  approvalResult,
  CodexInteractionRelay,
  publicApprovalRequest,
} from "../../server/codex-interaction.mjs";
import {
  buildWorkspaceSteerInput,
  buildWorkspaceTurn,
  STUDIO_COMMUNICATION_RULES,
  threadStartParams,
} from "../../server/turns.mjs";

class FakeClient extends EventEmitter {
  subscribe(listener) {
    this.on("notification", listener);
    return () => this.off("notification", listener);
  }
  subscribeServerRequests(listener) {
    this.on("serverRequest", listener);
    return () => this.off("serverRequest", listener);
  }
}

const root = "/tmp/shawn-ppt-studio-codex-contract";
const deck = {
  deck_id: "fixture",
  outline: {
    deck_uid: "TEST_DECK",
    path: `${root}/outline/outline.md`,
    revision_id: "sha256:test",
    text: "---\ndeck_uid: TEST_DECK\nslide_uids:\n  P1: SLIDE_1\n---\n| P1 | Title | Body |\nPRIVATE_WHOLE_OUTLINE_SENTINEL",
    slides: [{ slide_uid: "SLIDE_1", page_id: "P1", page_label: "P01", title: "Title", markdown: "| P1 | Title | Body |" }],
  },
  candidate_roots: [{ path: `${root}/candidates` }],
};

test("workspace turn is one natural Codex turn with official skills and no proposal schema", async () => {
  const built = await buildWorkspaceTurn(
    { message: "把 P01 标题改短，然后生成一张新图", current_slide_uid: "SLIDE_1" },
    {
      dataRoot: root,
      deck,
      conversationId: "conversation-1",
      threadId: "thread-1",
      monitoringRoot: `${root}/monitoring`,
      overviewPython: `${root}/runtime/python3`,
      requestStartedAt: "2026-08-15T05:09:18.123Z",
      pathPolicy: { requireReferenceImage: async (value) => value },
      confirmedSelections: [{
        display_label: "P01",
        slide_uid: "SLIDE_1",
        candidate_id: "candidate-1",
        path: `${root}/candidates/p01.png`,
        file_sha256: "abc",
        width: 1672,
        height: 941,
      }],
      studioRules: ["正常回复不显示哈希", "客户大纲不要出现内部审核语言"],
    },
  );

  assert.equal(built.params.threadId, "thread-1");
  assert.equal(built.params.approvalPolicy, "on-request");
  assert.equal(built.params.sandboxPolicy.type, "workspaceWrite");
  assert.equal(Object.hasOwn(built.params, "outputSchema"), false);
  assert.deepEqual(
    built.params.input.filter((item) => item.type === "skill").map((item) => item.name),
    ["shawn-ppt-image", "imagegen"],
  );
  const text = built.params.input.find((item) => item.type === "text").text;
  assert.match(text, /Respond naturally\. Do not emit JSON/);
  assert.match(text, /global Shawn PPT Studio requirements for every project and every conversation/);
  assert.match(text, /editable Studio long-term rules apply to every project and every conversation/);
  assert.match(text, /正常回复不显示哈希/);
  assert.match(text, /客户大纲不要出现内部审核语言/);
  assert.match(text, /concise final answer led by the actual outcome/);
  assert.match(text, /confirmed_selected_image_refs:.*file_sha256/s);
  assert.match(text, /authoritative_outline_path:/);
  assert.match(text, /candidate_output_roots:/);
  assert.match(text, /role=primary_style_reference/);
  assert.match(text, /style_anchor_only is an approval scope, never an asset role/);
  assert.match(text, /perform one bounded read-only input enumeration/);
  assert.match(text, /directly referenced page-level asset index/);
  assert.match(text, /Register every mandatory ImageGen logo, product image, or photo/);
  assert.match(text, /do not scan unrelated pages, collect optional\/planning assets/);
  assert.match(text, /first state-mutating command must then build the preflight manifest/);
  assert.match(text, /never use a distinct slide identity sidecar/);
  assert.match(text, /never pass --slide-identity-file again; init reads/);
  assert.match(text, /studio_request_started_at: 2026-08-15T05:09:18\.123Z/);
  assert.match(text, /--request-started-at/);
  assert.match(text, /--tone light or --tone dark/);
  assert.match(text, /studio_overview_python: \/tmp\/shawn-ppt-studio-codex-contract\/runtime\/python3/);
  assert.match(text, /use the exact studio_overview_python/);
  assert.match(text, /Never search for another Python, create a virtual environment, run pip\/uv\/conda/);
  assert.match(text, /currently_viewed_slide:.*Body/s);
  assert.doesNotMatch(text, /PRIVATE_WHOLE_OUTLINE_SENTINEL/);
  assert.ok(built.params.sandboxPolicy.writableRoots.includes(path.join(root, "monitoring")));
});

test("workspace turn fails before dispatch when the host runtime is not bound", async () => {
  await assert.rejects(
    buildWorkspaceTurn(
      { message: "生成 P01" },
      {
        dataRoot: root,
        deck,
        conversationId: "conversation-1",
        threadId: "thread-1",
        pathPolicy: { requireReferenceImage: async (value) => value },
      },
    ),
    (error) => error?.statusCode === 503 && error?.code === "overview_runtime_unavailable",
  );
});

test("global Studio communication rules also apply when a new Codex thread is created", () => {
  const params = threadStartParams(root, ["所有项目都要遵守的用户规则"]);
  for (const rule of STUDIO_COMMUNICATION_RULES) {
    assert.match(params.developerInstructions, new RegExp(rule.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(params.developerInstructions, /所有项目都要遵守的用户规则/);
  assert.doesNotMatch(params.developerInstructions, /settings panel|toggle/i);
});

test("steer input accepts text and local images without turn-level overrides", async () => {
  const built = await buildWorkspaceSteerInput(
    { message: "方向调整：只改 P01", reference_images: [`${root}/ref.png`] },
    {
      pathPolicy: { requireReferenceImage: async (value) => value },
      studioRules: ["回复保持简洁"],
    },
  );
  assert.deepEqual(built.input, [
    {
      type: "text",
      text: [
        "[SHAWN_PPT_STUDIO_USER_MESSAGE]",
        "方向调整：只改 P01",
        "[/SHAWN_PPT_STUDIO_USER_MESSAGE]",
        "The following editable Studio long-term rules apply to every project and every conversation. Treat them as persistent user requirements:",
        "1. 回复保持简洁",
      ].join("\n"),
    },
    { type: "localImage", path: `${root}/ref.png` },
  ]);
});

test("relay preserves official notification method, params, delta and completion", () => {
  const client = new FakeClient();
  const relay = new CodexInteractionRelay({ client });
  const records = [];
  relay.subscribe({ threadId: "thread-1", listener: (record) => records.push(record) });
  client.emit("notification", {
    method: "turn/started",
    params: { threadId: "thread-1", turn: { id: "turn-1", status: "inProgress", items: [] } },
  });
  client.emit("notification", {
    method: "item/agentMessage/delta",
    params: {
      threadId: "thread-1",
      turnId: "turn-1",
      itemId: "message-1",
      delta: "正在修改大纲。",
    },
  });
  client.emit("notification", {
    method: "turn/completed",
    params: { threadId: "thread-1", turn: { id: "turn-1", status: "completed", items: [] } },
  });

  assert.deepEqual(records.map((record) => record.method), [
    "turn/started",
    "item/agentMessage/delta",
    "turn/completed",
  ]);
  assert.equal(records[1].params.delta, "正在修改大纲。");
  assert.equal(records[1].params.itemId, "message-1");
  assert.equal(relay.activeTurn("thread-1"), null);
  assert.equal(relay.latestTurn("thread-1").status, "completed");
  assert.deepEqual(relay.records("thread-1", "turn-1", records[0].sequence).length, 2);
  relay.close();
});

test("relay normalizes App Server epoch-second turn timestamps", () => {
  const client = new FakeClient();
  const relay = new CodexInteractionRelay({ client });
  client.emit("notification", {
    method: "turn/started",
    params: { threadId: "thread-seconds", turn: { id: "turn-seconds", status: "inProgress", startedAt: 1_786_768_006 } },
  });
  assert.equal(relay.latestTurn("thread-seconds").startedAtMs, 1_786_768_006_000);
  client.emit("notification", {
    method: "turn/completed",
    params: { threadId: "thread-seconds", turn: { id: "turn-seconds", status: "interrupted", completedAt: 1_786_768_881 } },
  });
  assert.equal(relay.latestTurn("thread-seconds").completedAtMs, 1_786_768_881_000);
  relay.close();
});

test("thread history snapshots restore terminal and active turn state after restart", () => {
  const client = new FakeClient();
  const relay = new CodexInteractionRelay({ client });
  relay.observeThreadSnapshot({
    id: "thread-restored",
    turns: [{ id: "turn-stopped", status: "interrupted", startedAt: 1_786_768_006, completedAt: 1_786_768_881 }],
  });
  assert.equal(relay.activeTurn("thread-restored"), null);
  assert.deepEqual(relay.latestTurn("thread-restored"), {
    turnId: "turn-stopped",
    status: "interrupted",
    startedAtMs: 1_786_768_006_000,
    completedAtMs: 1_786_768_881_000,
  });
  relay.observeThreadSnapshot({
    id: "thread-restored",
    turns: [{ id: "turn-active", status: "inProgress", startedAt: 1_786_768_999 }],
  });
  assert.equal(relay.activeTurn("thread-restored"), "turn-active");
  relay.close();
});

test("relay keeps ImageGen status and path but never forwards image payloads", () => {
  const client = new FakeClient();
  const relay = new CodexInteractionRelay({ client });
  const records = [];
  relay.subscribe({ threadId: "thread-1", listener: (record) => records.push(record) });
  client.emit("notification", {
    method: "item/completed",
    params: {
      threadId: "thread-1",
      turnId: "turn-1",
      item: {
        id: "image-1",
        type: "imageGeneration",
        status: "completed",
        savedPath: "/tmp/generated.png",
        revisedPrompt: "clean slide",
        result: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB",
      },
    },
  });

  assert.deepEqual(records[0].params.item, {
    id: "image-1",
    type: "imageGeneration",
    status: "completed",
    savedPath: "/tmp/generated.png",
    revisedPrompt: "clean slide",
  });
  assert.doesNotMatch(JSON.stringify(records[0]), /iVBOR/);
  relay.close();
});

test("approval projection exposes official choices and passes decisions through", () => {
  const request = {
    id: 42,
    requestId: "42",
    method: "item/commandExecution/requestApproval",
    params: {
      threadId: "thread-1",
      turnId: "turn-1",
      itemId: "command-1",
      command: "test command",
      availableDecisions: ["accept", "acceptForSession", "decline"],
    },
  };
  const publicValue = publicApprovalRequest(request);
  assert.deepEqual(publicValue.choices.map((choice) => choice.decision), [
    "accept",
    "acceptForSession",
    "decline",
  ]);
  assert.deepEqual(approvalResult(request, "acceptForSession"), {
    decision: "acceptForSession",
  });
  assert.throws(() => approvalResult(request, "cancel"), /not available/);
});

test("resolved approvals publish a resolution and are not actionable on replay", () => {
  const client = new FakeClient();
  const relay = new CodexInteractionRelay({ client });
  const live = [];
  relay.subscribe({ threadId: "thread-1", turnId: "turn-1", listener: (record) => live.push(record) });
  const request = {
    id: 44,
    method: "item/fileChange/requestApproval",
    params: {
      threadId: "thread-1",
      turnId: "turn-1",
      itemId: "file-change-1",
      availableDecisions: ["accept", "decline"],
    },
  };

  client.emit("serverRequest", request);
  assert.equal(live[0].event, "approval");
  assert.deepEqual(live[0].choices.map((choice) => choice.decision), ["accept", "decline"]);

  const resolution = relay.resolveApproval(request, "accept");
  assert.equal(resolution.event, "approval_resolution");
  assert.equal(resolution.request_id, "44");
  assert.equal(resolution.resolved, true);
  assert.equal(resolution.decision, "accept");
  assert.deepEqual(live.map((record) => record.event), ["approval", "approval_resolution"]);

  client.emit("serverRequest", {
    ...request,
    params: {
      ...request.params,
      itemId: "file-change-2",
    },
  });

  const replay = relay.records("thread-1", "turn-1", 0);
  assert.deepEqual(replay.map((record) => record.event), ["approval_resolution", "approval"]);
  assert.equal(replay.find((record) => record.event === "approval").item_id, "file-change-2");
  assert.equal(replay.some((record) => record.event === "approval" && record.item_id === "file-change-1"), false);
  relay.close();
});

test("permission approval grants only the requested subset at official scope", () => {
  const request = {
    id: 43,
    method: "item/permissions/requestApproval",
    params: {
      threadId: "thread-1",
      turnId: "turn-1",
      itemId: "permissions-1",
      permissions: { network: { hosts: ["example.com"] } },
    },
  };
  assert.deepEqual(approvalResult(request, "grantForSession"), {
    permissions: { network: { hosts: ["example.com"] } },
    scope: "session",
  });
  assert.deepEqual(approvalResult(request, "decline"), {
    permissions: {},
    scope: "turn",
  });
});
