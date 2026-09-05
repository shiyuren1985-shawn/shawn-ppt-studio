import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { TaskProjection } from "../../server/task-projection.mjs";

test("a completed tool call without a delivered image remains artifact recovery until the source is available", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-artifact-recovery-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const stateDir = path.join(output, "run", "state");
  await mkdir(stateDir, { recursive: true });
  await writeFile(path.join(stateDir, "source_snapshot.json"), JSON.stringify({ page_ids: ["P1"], slide_identity: { deck_uid: "DECK", slide_uids: { P1: "SLIDE" } } }));
  const state = {
    run_id: "run", run_mode: "selected_style_expansion", status: "running",
    pages: { P1: { status: "recovery_pending", tool_finished_at: new Date().toISOString(), selected_source: null, failure_reason: "artifact_handoff_unresolved", recovery_required: true, recovery_status: "queued" } },
    scheduler: { active_actions: [{ page_id: "P1", action: "recover_artifact" }] },
  };
  const statePath = path.join(stateDir, "selected_style_run_state.json");
  await writeFile(statePath, JSON.stringify(state));
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{ deck_id: "deck", deck_uid: "DECK", label: "Deck", output_root: output, slides: [{ page_id: "P1", page_label: "P01", slide_uid: "SLIDE" }] }] }; } },
    conversations: { ready: true, records() { return [{ conversation_id: "conversation", thread_id: "thread", last_used_at: new Date().toISOString() }]; } }, cacheMs: 0,
  });
  const relay = { activeTurn() { return "turn"; }, latestTurn() { return { turnId: "turn", status: "inProgress", startedAtMs: Date.now() }; } };
  let task = (await projection.list({ codexInteraction: relay })).tasks[0];
  assert.equal(task.completed_units, 0);
  assert.equal(task.status, "preparing");
  assert.equal(task.status_label, "正在找回图片文件");
  assert.equal(task.progress_percent, null);
  task = (await projection.list()).tasks[0];
  assert.equal(task.status, "attention");
  assert.match(task.status_label, /图片文件尚未取回/);
  state.pages.P1 = { status: "candidate_ready", selected_source: "/tmp/delivered.png", tool_finished_at: new Date().toISOString() };
  state.scheduler.active_actions = [];
  await writeFile(statePath, JSON.stringify(state));
  task = (await projection.list({ codexInteraction: relay })).tasks[0];
  assert.equal(task.completed_units, 1);
  assert.equal(task.status, "reviewing");
  state.status = "completed";
  state.pages.P1 = { ...state.pages.P1, status: "accepted", final_path: "/tmp/delivered.png", recovery_required: true, recovery_status: "recovered" };
  await writeFile(statePath, JSON.stringify(state));
  task = (await projection.list()).tasks[0];
  assert.equal(task.status, "completed", "canonical recovered source takes precedence over the retained historical recovery flag");
  assert.equal(task.completed_units, 1);
  assert.equal(task.progress_percent, 100);
});

test("a new image request replaces an older provisional request in the same conversation", async () => {
  const now = Date.parse("2026-09-05T00:30:00Z");
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{ deck_id: "deck", deck_uid: "DECK", label: "Deck", slides: [{ page_id: "P1", slide_uid: "SLIDE", page_label: "P01" }] }] }; } },
    conversations: { ready: true, records() { return [{ conversation_id: "conversation", thread_id: "thread" }]; } },
    associations: { imageRequests() { return [
      { conversation_id: "conversation", request_started_at: "2026-09-05T00:21:00Z", title: "P01 · 8×1", mode_hint: "fast_8x1", slide_uid: "SLIDE" },
      { conversation_id: "conversation", request_started_at: "2026-09-05T00:29:59Z", title: "P01 · 作图", mode_hint: "image_generation", slide_uid: "SLIDE" },
    ]; } }, clock: () => now, cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: {
    activeTurn() { return "new-turn"; }, latestTurn() { return { turnId: "new-turn", status: "inProgress", startedAtMs: now - 1000 }; },
  } });
  assert.equal(result.tasks.length, 1);
  assert.equal(result.tasks[0].title, "P01 · 作图");
  assert.equal(result.active_count, 1);
  projection.associations.imageRequests = () => [{ conversation_id: "conversation", request_started_at: "2026-09-05T00:21:00Z", title: "old request", mode_hint: "image_generation", slide_uid: "SLIDE" }];
  const oldOnly = await projection.list({ codexInteraction: {
    activeTurn() { return "new-turn"; }, latestTurn() { return { turnId: "new-turn", status: "inProgress", startedAtMs: now - 1000 }; },
  } });
  assert.equal(oldOnly.active_count, 0);
  assert.equal(oldOnly.tasks[0].can_stop, false, "an old provisional request cannot interrupt an unrelated later turn");
  assert.equal(oldOnly.tasks[0].status, "attention");
});
