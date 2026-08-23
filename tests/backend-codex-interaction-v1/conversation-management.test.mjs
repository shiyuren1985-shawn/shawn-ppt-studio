import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { ConversationIndex } from "../../server/conversations.mjs";

test("rename, soft-delete and restore remain durable and keep a valid active conversation", async (t) => {
  const dataRoot = await mkdtemp(path.join(os.tmpdir(), "studio-conversation-management-"));
  t.after(() => rm(dataRoot, { recursive: true, force: true }));
  const times = [
    "2026-08-23T01:00:00.000Z",
    "2026-08-23T01:01:00.000Z",
    "2026-08-23T01:02:00.000Z",
    "2026-08-23T01:03:00.000Z",
    "2026-08-23T01:04:00.000Z",
  ];
  const index = new ConversationIndex({ dataRoot, clock: () => times.shift() || "2026-08-23T01:05:00.000Z" });
  await index.initialize();
  const first = await index.create({ deckId: "deck", deckUid: "DECK", threadId: "thread-1" });
  const second = await index.create({ deckId: "deck", deckUid: "DECK", threadId: "thread-2", title: "第二个对话" });

  const renamed = await index.rename("DECK", second.conversation_id, "客户版标题");
  assert.equal(renamed.title, "客户版标题");
  const archived = await index.archive("DECK", second.conversation_id);
  assert.equal(archived.active_conversation_id, first.conversation_id);
  assert.deepEqual(index.list("DECK").conversations.map((item) => item.conversation_id), [first.conversation_id]);
  assert.deepEqual(index.listArchived("DECK").conversations.map((item) => item.conversation_id), [second.conversation_id]);

  const reloaded = new ConversationIndex({ dataRoot });
  await reloaded.initialize();
  assert.equal(reloaded.list("DECK").active_conversation_id, first.conversation_id);
  assert.equal(reloaded.listArchived("DECK").conversations[0].title, "客户版标题");
  const restored = await reloaded.restore("DECK", second.conversation_id);
  assert.equal(restored.archived_at, null);
  assert.equal(reloaded.list("DECK").active_conversation_id, second.conversation_id);
  assert.equal(reloaded.listArchived("DECK").conversations.length, 0);
});
