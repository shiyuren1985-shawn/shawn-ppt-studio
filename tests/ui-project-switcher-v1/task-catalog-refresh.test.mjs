import assert from "node:assert/strict";
import test from "node:test";

import { createTaskCatalogRefreshTracker } from "../../web/task-catalog-refresh.js";

function task(taskId, deckId, status) {
  return { task_id: taskId, deck_id: deckId, status };
}

test("refreshes each affected deck once when an observed task completes", async () => {
  const refreshed = [];
  const observe = createTaskCatalogRefreshTracker({
    refreshCatalog: async (deckId) => refreshed.push(deckId),
  });

  assert.deepEqual(await observe([
    task("fast8-a", "deck-a", "generating"),
    task("fast8-b", "deck-a", "preparing"),
    task("old", "deck-b", "completed"),
  ]), []);
  assert.deepEqual(refreshed, [], "initial history must not trigger a bulk rescan");

  assert.deepEqual(await observe([
    task("fast8-a", "deck-a", "completed"),
    task("fast8-b", "deck-a", "completed"),
    task("old", "deck-b", "completed"),
  ]), ["deck-a"]);
  assert.deepEqual(refreshed, ["deck-a"]);

  assert.deepEqual(await observe([
    task("fast8-a", "deck-a", "completed"),
    task("fast8-b", "deck-a", "completed"),
  ]), []);
  assert.deepEqual(refreshed, ["deck-a"], "completed tasks must not refresh repeatedly");
});

test("does not refresh failed tasks or tasks first seen after completion", async () => {
  const refreshed = [];
  const observe = createTaskCatalogRefreshTracker({
    refreshCatalog: async (deckId) => refreshed.push(deckId),
  });

  await observe([task("failed", "deck-a", "generating")]);
  assert.deepEqual(await observe([
    task("failed", "deck-a", "failed"),
    task("late-history", "deck-b", "completed"),
  ]), []);
  assert.deepEqual(refreshed, []);
});

test("retries a completed task catalog when the first refresh fails", async () => {
  let attempts = 0;
  const observe = createTaskCatalogRefreshTracker({
    refreshCatalog: async () => {
      attempts += 1;
      if (attempts === 1) throw new Error("temporary scan error");
    },
  });

  await observe([task("fast8", "deck-a", "generating")]);
  await assert.rejects(
    observe([task("fast8", "deck-a", "completed")]),
    /selector catalog refresh failed/,
  );
  assert.equal(attempts, 1);

  assert.deepEqual(await observe([task("fast8", "deck-a", "completed")]), ["deck-a"]);
  assert.equal(attempts, 2);
  assert.deepEqual(await observe([task("fast8", "deck-a", "completed")]), []);
});
