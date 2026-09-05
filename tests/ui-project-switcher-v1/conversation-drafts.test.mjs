import assert from "node:assert/strict";
import test from "node:test";

import { createConversationDraftStore } from "../../web/conversation-drafts.js";

const routeA = { deckId: "deck-a", conversationId: "conversation-a", epoch: 1 };
const routeB = { deckId: "deck-b", conversationId: "conversation-b", epoch: 2 };
const attachment = (name) => ({ name, path: `/references/${name}.png` });

test("switching projects preserves each unsent request and its attachments", () => {
  const drafts = createConversationDraftStore();
  drafts.save(routeA, { text: "修改 A 的封面", attachments: [attachment("a")] });
  assert.deepEqual(drafts.read(routeB), { text: "", attachments: [] });
  drafts.save(routeB, { text: "  保留 B 的文字\n", attachments: [attachment("b")] });

  assert.deepEqual(drafts.read({ ...routeA, epoch: 3 }), {
    text: "修改 A 的封面", attachments: [attachment("a")],
  });
  assert.deepEqual(drafts.read(routeB), {
    text: "  保留 B 的文字\n", attachments: [attachment("b")],
  });
});

test("late uploads return to the originating conversation without overwriting newer text", async () => {
  const drafts = createConversationDraftStore();
  drafts.save(routeA, { text: "最初的 A", attachments: [] });
  const token = drafts.beginUpload(routeA);
  let finishUpload;
  const upload = new Promise((resolve) => { finishUpload = resolve; })
    .then((items) => drafts.completeUpload(token, items));
  drafts.save(routeB, { text: "B 的请求", attachments: [attachment("b")] });
  drafts.save({ ...routeA, epoch: 3 }, { text: "修订后的 A", attachments: [] });
  finishUpload([attachment("a")]);
  assert.equal(await upload, true);

  assert.deepEqual(drafts.read(routeA), { text: "修订后的 A", attachments: [attachment("a")] });
  assert.deepEqual(drafts.read(routeB), { text: "B 的请求", attachments: [attachment("b")] });
  assert.equal(drafts.completeUpload(token, [attachment("duplicate")]), false);
});

test("sending clears only that conversation, including when conversation ids repeat across projects", () => {
  const drafts = createConversationDraftStore();
  const sameDeck = { ...routeA, conversationId: "conversation-b" };
  const sameConversationId = { ...routeB, conversationId: routeA.conversationId };
  for (const route of [routeA, sameDeck, sameConversationId]) {
    drafts.save(route, { text: `${route.deckId}/${route.conversationId}`, attachments: [attachment(route.deckId)] });
  }
  drafts.clear(routeA);
  assert.deepEqual(drafts.read(routeA), { text: "", attachments: [] });
  assert.equal(drafts.read(sameDeck).text, "deck-a/conversation-b");
  assert.equal(drafts.read(sameConversationId).text, "deck-b/conversation-a");
});

test("concurrent upload batches keep only their own composer pending until all batches finish", () => {
  const drafts = createConversationDraftStore();
  const first = drafts.beginUpload(routeA);
  const second = drafts.beginUpload(routeA);
  const other = drafts.beginUpload(routeB);
  assert.equal(drafts.hasPendingUploads(routeA), true);
  drafts.completeUpload(first, [attachment("a1")]);
  assert.equal(drafts.hasPendingUploads(routeA), true);
  drafts.completeUpload(second, [attachment("a2")]);
  assert.equal(drafts.hasPendingUploads(routeA), false);
  assert.equal(drafts.hasPendingUploads(routeB), true);
  drafts.completeUpload(other, []);
  assert.equal(drafts.hasPendingUploads(routeB), false);
  assert.deepEqual(drafts.read(routeA).attachments, [attachment("a1"), attachment("a2")]);
});

test("composer edits cannot mutate another saved snapshot and absent routes cannot collect drafts", () => {
  const drafts = createConversationDraftStore();
  const original = { text: "A", attachments: [attachment("a")] };
  drafts.save(routeA, original);
  original.attachments[0].name = "mutated input";
  const visible = drafts.read(routeA);
  visible.attachments[0].name = "mutated output";
  visible.attachments.push(attachment("extra"));
  assert.deepEqual(drafts.read(routeA), { text: "A", attachments: [attachment("a")] });
  const absent = { deckId: "deck-a", conversationId: "" };
  drafts.save(absent, original);
  assert.equal(drafts.beginUpload(absent), null);
  assert.deepEqual(drafts.read(absent), { text: "", attachments: [] });
});
