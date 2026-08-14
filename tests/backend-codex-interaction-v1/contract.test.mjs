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
    text: "---\ndeck_uid: TEST_DECK\nslide_uids:\n  P1: SLIDE_1\n---\n| P1 | Title | Body |",
    slides: [{ slide_uid: "SLIDE_1", page_label: "P01" }],
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
  assert.match(text, /confirmed_selected_image_refs:.*file_sha256/s);
  assert.match(text, /Authoritative outline begins/);
  assert.ok(built.params.sandboxPolicy.writableRoots.includes(path.join(root, "monitoring")));
});

test("steer input accepts text and local images without turn-level overrides", async () => {
  const built = await buildWorkspaceSteerInput(
    { message: "方向调整：只改 P01", reference_images: [`${root}/ref.png`] },
    { pathPolicy: { requireReferenceImage: async (value) => value } },
  );
  assert.deepEqual(built.input, [
    { type: "text", text: "方向调整：只改 P01" },
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
  assert.deepEqual(relay.records("thread-1", "turn-1", records[0].sequence).length, 2);
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
