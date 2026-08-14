import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, utimes, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { TaskProjection } from "../../server/task-projection.mjs";

async function fixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-task-center-"));
  const output = path.join(root, "output");
  await mkdir(path.join(output, "fast-run", "state"), { recursive: true });
  await writeFile(path.join(output, "fast-run", "state", "source_snapshot.json"), JSON.stringify({
    page_ids: ["P06"],
    slide_identity: { deck_uid: "DECK_TASKS", slide_uids: { P06: "SLIDE_06" } },
  }));
  await writeFile(path.join(output, "fast-run", "state", "style_run_state.json"), JSON.stringify({
    run_id: "fast-task",
    run_mode: "fast_8x1_diverse",
    status: "running",
    scheduler: { active_actions: [{ page_id: "P06" }], ready_queue: [] },
    styles: Object.fromEntries("ABCDEFGH".split("").map((slot, index) => [slot, {
      pages: { P06: index < 4 ? {
        status: "candidate_ready",
        selected_source: `/Users/test/.codex/generated_images/thread-live/${slot}.png`,
        tool_finished_at: "2026-08-14T01:05:00Z",
      } : { status: "running" } },
    }])),
  }));
  return { root, output };
}

test("projects canonical image state into human task progress without paths", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const discovery = {
    async listDecks() {
      return { decks: [{
        deck_id: "deck-tasks", deck_uid: "DECK_TASKS", label: "客户提案",
        output_root: output, candidate_roots_paths: [output],
        slides: [{ slide_uid: "SLIDE_06", page_label: "P06", title: "整体能力" }],
      }] };
    },
  };
  const conversations = {
    ready: true,
    records() { return [{ conversation_id: "conversation-live", thread_id: "thread-live" }]; },
  };
  const relay = { activeTurn(threadId) { return threadId === "thread-live" ? "turn-live" : null; } };
  const projection = new TaskProjection({
    discovery, conversations, clock: () => Date.parse("2026-08-14T01:10:00Z"), cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: relay });
  assert.equal(result.active_count, 1);
  assert.equal(result.tasks.length, 1);
  assert.deepEqual(result.tasks[0], {
    task_id: result.tasks[0].task_id,
    deck_id: "deck-tasks",
    deck_label: "客户提案",
    conversation_id: "conversation-live",
    slide_uid: "SLIDE_06",
    page_label: "P06",
    title: "P06 · 8×1",
    mode: "fast_8x1_diverse",
    status: "generating",
    status_label: "已生成 4/8",
    completed_units: 4,
    total_units: 8,
    progress_percent: 50,
    elapsed_seconds: result.tasks[0].elapsed_seconds,
    updated_at: result.tasks[0].updated_at,
    can_stop: true,
    can_open_conversation: true,
  });
  assert.ok(projection.interruptTarget(result.tasks[0].task_id));
  assert.doesNotMatch(JSON.stringify(result), /generated_images|fast-task|thread-live|turn-live|\/output/);
});

test("preparation and review stages never invent percentages", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const statePath = path.join(output, "fast-run", "state", "style_run_state.json");
  await writeFile(statePath, JSON.stringify({
    run_id: "review-task", run_mode: "fast_8x1_diverse", status: "running",
    scheduler: { active_actions: [], ready_queue: [] },
    styles: Object.fromEntries("ABCDEFGH".split("").map((slot) => [slot, {
      pages: { P06: { status: "candidate_ready", final_path: `${slot}.png` } },
    }])),
  }));
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{ deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output, slides: [] }] }; } },
    conversations: { ready: true, records() { return []; } },
    clock: () => Date.now(), cacheMs: 0,
  });
  const task = (await projection.list()).tasks[0];
  assert.equal(task.status, "reviewing");
  assert.equal(task.progress_percent, null);
  assert.equal(task.status_label, "图片已生成，正在质检");
});

test("unfinished Fast8 runs count only successful worker receipts before settle", async (t) => {
  for (let receiptCount = 1; receiptCount <= 7; receiptCount += 1) {
    await t.test(`${receiptCount}/8 completed receipts`, async (t) => {
      const { root, output } = await fixture();
      t.after(() => rm(root, { recursive: true, force: true }));
      const statePath = path.join(output, "fast-run", "state", "style_run_state.json");
      await writeFile(statePath, JSON.stringify({
        run_id: `receipt-progress-${receiptCount}`,
        run_mode: "fast_8x1_diverse",
        status: "running",
        scheduler: { active_actions: [{ page_id: "P06" }], ready_queue: [] },
        styles: Object.fromEntries("ABCDEFGH".split("").map((slot) => [slot, {
          pages: { P06: { status: "running" } },
        }])),
      }));
      const resultsDir = path.join(output, "fast-run", "style_jobs", "results");
      await mkdir(resultsDir, { recursive: true });
      for (const slot of "ABCDEFGH".slice(0, receiptCount)) {
        await writeFile(path.join(resultsDir, `worker_receipt_${slot}.json`), JSON.stringify({
          worker_receipt_contract_version: 1,
          style: slot,
          page_id: "P06",
          tool_status: "completed",
          savedPath: `/generated/${slot}.png`,
          error: null,
          failure_class: null,
        }));
      }
      await writeFile(path.join(resultsDir, "worker_receipt_failed.json"), JSON.stringify({
        worker_receipt_contract_version: 1,
        style: "H",
        page_id: "P06",
        tool_status: "failed",
        savedPath: null,
        error: "imagegen_backend_failed",
      }));
      await writeFile(path.join(resultsDir, "worker_receipt_empty.json"), "{}");
      await writeFile(path.join(resultsDir, "worker_receipt_missing_artifact.json"), JSON.stringify({
        worker_receipt_contract_version: 1,
        style: "H",
        page_id: "P06",
        tool_status: "completed",
        savedPath: null,
        error: "artifact_handoff_unresolved",
        failure_class: "artifact_missing",
      }));
      const projection = new TaskProjection({
        discovery: { async listDecks() { return { decks: [{
          deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output,
          slides: [{ slide_uid: "SLIDE_06", page_label: "P06" }],
        }] }; } },
        conversations: { ready: true, records() { return []; } },
        clock: () => Date.now(),
        cacheMs: 0,
      });
      const task = (await projection.list()).tasks[0];
      assert.equal(task.completed_units, receiptCount);
      assert.equal(task.total_units, 8);
      assert.equal(task.status, "generating");
      assert.equal(task.status_label, `已生成 ${receiptCount}/8`);
      assert.equal(task.progress_percent, Math.round((receiptCount / 8) * 100));
    });
  }
});

test("an old run from the same conversation never becomes part of the current active turn", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const oldRoot = path.join(output, "old-run", "state");
  await mkdir(oldRoot, { recursive: true });
  const oldState = path.join(oldRoot, "selected_style_run_state.json");
  await writeFile(oldState, JSON.stringify({
    run_id: "old-selected", run_mode: "selected_style_expansion", status: "running",
    pages: { P01: { status: "candidate_ready", selected_source: "/Users/test/.codex/generated_images/thread-live/old.png" } },
  }));
  const oldTime = new Date("2026-08-09T01:00:00Z");
  await utimes(oldState, oldTime, oldTime);
  const now = Date.parse("2026-08-14T01:10:00Z");
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{ deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output, slides: [] }] }; } },
    conversations: { ready: true, records() { return [{ conversation_id: "current", thread_id: "thread-live", last_used_at: "2026-08-14T00:55:00Z" }]; } },
    clock: () => now, cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: { activeTurn() { return "current-turn"; } } });
  assert.equal(result.tasks.some((task) => task.title === "整套作图 · 1 页"), false);
});

test("a current active task with no canonical update for 30 minutes asks for attention", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const statePath = path.join(output, "fast-run", "state", "style_run_state.json");
  const staleTime = new Date("2026-08-14T00:30:00Z");
  await utimes(statePath, staleTime, staleTime);
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{ deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output, slides: [] }] }; } },
    conversations: { ready: true, records() { return [{ conversation_id: "current", thread_id: "thread-live", last_used_at: "2026-08-14T00:20:00Z" }]; } },
    clock: () => Date.parse("2026-08-14T01:10:00Z"), cacheMs: 0,
  });
  const task = (await projection.list({ codexInteraction: { activeTurn() { return "current-turn"; } } })).tasks[0];
  assert.equal(task.status, "attention");
  assert.equal(task.status_label, "长时间没有更新");
  assert.equal(task.can_stop, true);
});
