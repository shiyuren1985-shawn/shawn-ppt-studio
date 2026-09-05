import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { TaskProjection } from "../../server/task-projection.mjs";

test("a completed image run cannot stop a later turn in its conversation", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-completed-task-stop-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const stateDir = path.join(output, "finished", "state");
  await mkdir(stateDir, { recursive: true });
  await writeFile(path.join(stateDir, "source_snapshot.json"), JSON.stringify({
    page_ids: ["P1"], slide_identity: { deck_uid: "DECK", slide_uids: { P1: "SLIDE" } },
  }));
  await writeFile(path.join(stateDir, "style_run_state.json"), JSON.stringify({
    run_id: "finished", run_mode: "fast_8x1_diverse", status: "completed",
    styles: { A: { pages: { P1: {
      status: "candidate_ready", final_path: "/tmp/generated_images/thread-1/A.png",
    } } } },
  }));
  const conversation = { conversation_id: "conversation-1", thread_id: "thread-1", last_used_at: new Date().toISOString() };
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "deck", deck_uid: "DECK", label: "Deck", output_root: output,
      slides: [{ page_id: "P1", page_label: "P01", slide_uid: "SLIDE" }],
    }] }; } },
    conversations: { ready: true, records() { return [conversation]; } },
    cacheMs: 0,
  });
  const { tasks } = await projection.list({ codexInteraction: {
    activeTurn() { return "new-unrelated-turn"; },
    latestTurn() { return { turnId: "new-unrelated-turn", status: "inProgress", startedAtMs: Date.now() }; },
  } });
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].status, "completed");
  assert.equal(tasks[0].can_open_conversation, true);
  assert.equal(tasks[0].can_stop, false, "completed task cards must not expose interruption of a later conversation turn");
  assert.equal(projection.interruptTarget(tasks[0].task_id), null);
});
