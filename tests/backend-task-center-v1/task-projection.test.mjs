import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, utimes, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { TaskProjection } from "../../server/task-projection.mjs";
import { TaskAssociationIndex } from "../../server/task-associations.mjs";

test("an explicit image request appears immediately and is replaced by its formal run", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-task-request-bridge-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  await mkdir(output, { recursive: true });
  const requestStartedAt = "2026-08-23T01:00:00.000Z";
  const now = Date.parse("2026-08-23T01:00:20.000Z");
  const associations = new TaskAssociationIndex({ dataRoot: root });
  await associations.initialize();
  await associations.rememberImageRequest("DECK_REQUEST", requestStartedAt, "conversation-1", {
    title: "P06 · 8×1",
    modeHint: "fast_8x1",
    slideUid: "SLIDE_06",
  });
  await associations.rememberRequest("DECK_REQUEST", requestStartedAt, "conversation-1");
  const discovery = { async listDecks() { return { decks: [{
    deck_id: "deck-request", deck_uid: "DECK_REQUEST", label: "测试项目",
    output_root: output, candidate_roots_paths: [output],
    slides: [{ page_id: "P06", slide_uid: "SLIDE_06", page_label: "P06" }],
  }] }; } };
  const conversations = { ready: true, records() { return [{
    conversation_id: "conversation-1", thread_id: "thread-1", last_used_at: requestStartedAt,
  }]; } };
  const relay = {
    activeTurn: () => "turn-1",
    latestTurn: () => ({ turnId: "turn-1", status: "inProgress", startedAtMs: Date.parse(requestStartedAt) }),
  };
  const projection = new TaskProjection({ discovery, conversations, associations, clock: () => now, cacheMs: 0 });
  let result = await projection.list({ codexInteraction: relay, force: true });
  assert.equal(result.active_count, 1);
  assert.equal(result.tasks.length, 1);
  assert.equal(result.tasks[0].title, "P06 · 8×1");
  assert.equal(result.tasks[0].status, "preparing");
  assert.equal(result.tasks[0].status_label, "正在准备作图");
  assert.equal(result.tasks[0].can_open_conversation, true);

  const stateDir = path.join(output, "formal-fast8", "state");
  await mkdir(stateDir, { recursive: true });
  await writeFile(path.join(stateDir, "source_snapshot.json"), JSON.stringify({
    page_ids: ["P06"],
    slide_identity: { deck_uid: "DECK_REQUEST", slide_uids: { P06: "SLIDE_06" } },
  }));
  await writeFile(path.join(stateDir, "preflight_manifest.json"), JSON.stringify({
    request_started_at: requestStartedAt,
    page_ids: ["P06"],
  }));
  await writeFile(path.join(stateDir, "style_run_state.json"), JSON.stringify({
    run_id: "formal-fast8",
    run_mode: "fast_8x1_diverse",
    status: "running",
    scheduler: { active_actions: [], ready_queue: [{ page_id: "P06" }] },
    styles: {},
  }));
  result = await projection.list({ codexInteraction: relay, force: true });
  assert.equal(result.active_count, 1);
  assert.equal(result.tasks.length, 1, "the provisional request is not duplicated after formal state exists");
  assert.equal(result.tasks[0].mode, "fast_8x1_diverse");
});

test("a selected-style subset names the actual pages during preparation", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-selected-preparing-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const stateDir = path.join(output, "selected-run", "state");
  await mkdir(stateDir, { recursive: true });
  await writeFile(path.join(stateDir, "source_snapshot.json"), JSON.stringify({
    page_ids: ["P01", "P02"],
    slide_identity: {
      deck_uid: "DECK_SELECTED",
      slide_uids: { P01: "SLIDE_01", P02: "SLIDE_02" },
    },
  }));
  await writeFile(path.join(stateDir, "selected_style_run_state.json"), JSON.stringify({
    run_id: "selected-run",
    run_mode: "selected_style_expansion",
    status: "running",
    scheduler: { active_actions: [], ready_queue: [], recovery_queue: [] },
    pages: { P01: { status: "pending" }, P02: { status: "pending" } },
  }));
  const discovery = { async listDecks() { return { decks: [{
    deck_id: "deck-selected", deck_uid: "DECK_SELECTED", label: "测试项目",
    output_root: output, candidate_roots_paths: [output],
    slides: [
      { page_id: "P01", slide_uid: "SLIDE_01", page_label: "P01" },
      { page_id: "P02", slide_uid: "SLIDE_02", page_label: "P02" },
      { page_id: "P03", slide_uid: "SLIDE_03", page_label: "P03" },
    ],
  }] }; } };
  const conversations = { ready: true, records() { return [{
    conversation_id: "conversation-1", thread_id: "thread-1", last_used_at: null,
  }]; } };
  const relay = {
    activeTurn: () => "turn-1",
    latestTurn: () => ({ turnId: "turn-1", status: "inProgress", startedAtMs: Date.now() }),
  };
  const projection = new TaskProjection({ discovery, conversations, cacheMs: 0 });
  const result = await projection.list({ codexInteraction: relay, force: true });
  assert.equal(result.tasks[0].title, "P01、P02 · 作图");
  assert.equal(result.tasks[0].status, "preparing");
  assert.equal(result.tasks[0].status_label, "正在准备页面任务");
});

test("a whole-deck selected-style run keeps the whole-deck title", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-selected-whole-deck-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const stateDir = path.join(output, "selected-run", "state");
  await mkdir(stateDir, { recursive: true });
  await writeFile(path.join(stateDir, "source_snapshot.json"), JSON.stringify({
    page_ids: ["P01", "P02"],
    slide_identity: {
      deck_uid: "DECK_SELECTED",
      slide_uids: { P01: "SLIDE_01", P02: "SLIDE_02" },
    },
  }));
  await writeFile(path.join(stateDir, "selected_style_run_state.json"), JSON.stringify({
    run_id: "selected-run",
    run_mode: "selected_style_expansion",
    status: "completed",
    pages: { P01: { status: "accepted" }, P02: { status: "accepted" } },
  }));
  const discovery = { async listDecks() { return { decks: [{
    deck_id: "deck-selected", deck_uid: "DECK_SELECTED", label: "测试项目",
    output_root: output, candidate_roots_paths: [output],
    slides: [
      { page_id: "P01", slide_uid: "SLIDE_01", page_label: "P01" },
      { page_id: "P02", slide_uid: "SLIDE_02", page_label: "P02" },
    ],
  }] }; } };
  const projection = new TaskProjection({
    discovery,
    conversations: { ready: true, records() { return []; } },
    cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: null });
  assert.equal(result.tasks[0].title, "整套作图 · 2 页");
});

test("a later selected-style state absorbs the provisional request from the same conversation", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-selected-request-bridge-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const stateDir = path.join(output, "selected-run", "state");
  await mkdir(stateDir, { recursive: true });
  const requestStartedAt = "2026-08-23T15:30:00.000Z";
  const processStartedAt = "2026-08-23T16:00:00.000Z";
  const associations = new TaskAssociationIndex({ dataRoot: root });
  await associations.initialize();
  await associations.rememberImageRequest("DECK_SELECTED", requestStartedAt, "conversation-1", {
    title: "4 页作图",
    modeHint: "image_generation",
    slideUid: "SLIDE_15",
  });
  await writeFile(path.join(stateDir, "source_snapshot.json"), JSON.stringify({
    page_ids: ["15", "16", "19", "27"],
    slide_identity: {
      deck_uid: "DECK_SELECTED",
      slide_uids: {
        15: "SLIDE_15", 16: "SLIDE_16", 19: "SLIDE_19", 27: "SLIDE_27",
      },
    },
  }));
  await writeFile(path.join(stateDir, "selected_style_run_state.json"), JSON.stringify({
    run_id: "selected-run",
    run_mode: "selected_style_expansion",
    status: "running",
    timing: { process_started_at: processStartedAt },
    style_anchor: "/Users/test/.codex/generated_images/thread-1/style.png",
    scheduler: { active_actions: [], ready_queue: [] },
    pages: {
      15: { status: "pending" }, 16: { status: "pending" },
      19: { status: "pending" }, 27: { status: "pending" },
    },
  }));
  const slides = [15, 16, 19, 27, 28].map((page) => ({
    page_id: String(page), slide_uid: `SLIDE_${page}`, page_label: `P${page}`,
  }));
  const discovery = { async listDecks() { return { decks: [{
    deck_id: "deck-selected", deck_uid: "DECK_SELECTED", label: "测试项目",
    output_root: output, candidate_roots_paths: [output], slides,
  }] }; } };
  const conversations = { ready: true, records() { return [{
    conversation_id: "conversation-1", thread_id: "thread-1", last_used_at: processStartedAt,
  }]; } };
  const projection = new TaskProjection({
    discovery, conversations, associations,
    clock: () => Date.parse("2026-08-23T16:01:00.000Z"), cacheMs: 0,
  });
  const result = await projection.list({
    codexInteraction: {
      activeTurn() { return "turn-1"; },
      latestTurn() { return { turnId: "turn-1", status: "inProgress", startedAtMs: Date.parse(processStartedAt) }; },
    },
  });
  assert.equal(result.active_count, 1);
  assert.equal(result.tasks.length, 1);
  assert.equal(result.tasks[0].title, "P15、P16、P19、P27 · 作图");
  assert.equal(result.tasks[0].mode, "selected_style_expansion");
});

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
    pending_approval_count: 0,
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

test("preflight page identity labels a preparing Fast8 before source snapshot exists", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-task-preflight-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const stateDir = path.join(output, "fresh-run", "state");
  await mkdir(stateDir, { recursive: true });
  await writeFile(path.join(stateDir, "preflight_manifest.json"), JSON.stringify({ page_ids: ["P24"] }));
  await writeFile(path.join(stateDir, "style_run_state.json"), JSON.stringify({
    run_id: "fresh-p24", run_mode: "fast_8x1_diverse", status: "running",
    scheduler: { active_actions: [], ready_queue: [] }, styles: {},
  }));
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "si", deck_uid: "SI_TASKS", label: "SI Playbook", output_root: output,
      slides: [{ page_id: "P24", slide_uid: "SI_P24", page_label: "P24" }],
    }] }; } },
    conversations: { ready: true, records() { return []; } },
    clock: () => Date.now(), cacheMs: 0,
  });
  const task = (await projection.list()).tasks[0];
  assert.equal(task.page_label, "P24");
  assert.equal(task.slide_uid, "SI_P24");
  assert.equal(task.title, "P24 · 8×1");
  assert.equal(task.status, "preparing");
  assert.equal(task.total_units, 8);
});

test("a formal Fast8 suppresses an abandoned preflight from the same request", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-task-preflight-successor-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const outlinePath = path.join(root, "outline.md");
  const preflightDir = path.join(output, ".fast8_preflight");
  const stateDir = path.join(output, "fresh-p24-v2", "state");
  const requestStartedAt = "2026-08-15T12:57:54.631Z";
  const requestMs = Date.parse(requestStartedAt);
  await mkdir(preflightDir, { recursive: true });
  await mkdir(stateDir, { recursive: true });
  await writeFile(outlinePath, "# P24\n");
  await writeFile(path.join(preflightDir, "fresh-p24.json"), JSON.stringify({
    fast8_preflight_manifest_version: 1,
    run_mode: "fast_8x1_diverse",
    task_name: "fresh-p24",
    page_ids: ["P24"],
    request_started_at: requestStartedAt,
    required_files: [outlinePath],
  }));
  await writeFile(path.join(stateDir, "preflight_manifest.json"), JSON.stringify({
    fast8_preflight_manifest_version: 1,
    run_mode: "fast_8x1_diverse",
    task_name: "fresh-p24-v2",
    page_ids: ["P24"],
    request_started_at: requestStartedAt,
    required_files: [outlinePath],
  }));
  await writeFile(path.join(stateDir, "style_run_state.json"), JSON.stringify({
    run_id: "fresh-p24-v2",
    run_mode: "fast_8x1_diverse",
    status: "running",
    scheduler: { active_actions: [], ready_queue: [] },
    styles: {},
  }));
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "si", deck_uid: "SI_TASKS", label: "SI Playbook",
      outline_path: outlinePath, output_root: output,
      slides: [{ page_id: "P24", slide_uid: "SI_P24", page_label: "P24" }],
    }] }; } },
    conversations: { ready: true, records() { return [{
      conversation_id: "conversation-live", thread_id: "thread-live", last_used_at: requestStartedAt,
    }]; } },
    clock: () => requestMs + 30_000,
    cacheMs: 0,
  });
  const relay = {
    activeTurn(threadId) { return threadId === "thread-live" ? "turn-live" : null; },
    latestTurn(threadId) {
      return threadId === "thread-live"
        ? { turnId: "turn-live", status: "inProgress", startedAtMs: requestMs }
        : null;
    },
  };
  const result = await projection.list({ codexInteraction: relay });
  assert.equal(result.active_count, 1);
  assert.equal(result.tasks.length, 1);
  assert.equal(result.tasks[0].status, "preparing");
  assert.equal(result.tasks[0].total_units, 8);
});

test("preflight-only Fast8 is visible before the formal state exists", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-task-preflight-only-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const outlinePath = path.join(root, "outline.md");
  const preflightDir = path.join(output, ".fast8_preflight");
  const manifestPath = path.join(preflightDir, "fresh-p24.json");
  const requestMs = Date.parse("2026-08-15T12:57:54.631Z");
  await mkdir(preflightDir, { recursive: true });
  await writeFile(outlinePath, "# P24\n");
  await writeFile(manifestPath, JSON.stringify({
    fast8_preflight_manifest_version: 1,
    run_mode: "fast_8x1_diverse",
    task_name: "fresh-p24",
    page_ids: ["P24"],
    request_started_at: "2026-08-15T12:57:54.631Z",
    required_files: [outlinePath],
    slide_identity_file: outlinePath,
  }));
  const relay = {
    client: { serverRequests: new Map() },
    activeTurn(threadId) { return threadId === "thread-live" ? "turn-live" : null; },
    latestTurn(threadId) {
      return threadId === "thread-live"
        ? { turnId: "turn-live", status: "inProgress", startedAtMs: requestMs }
        : null;
    },
  };
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "si", deck_uid: "SI_TASKS", label: "SI Playbook",
      outline_path: outlinePath, output_root: output,
      slides: [{ page_id: "P24", slide_uid: "SI_P24", page_label: "P24" }],
    }] }; } },
    conversations: { ready: true, records() { return [{
      conversation_id: "conversation-live", thread_id: "thread-live",
      last_used_at: "2026-08-15T12:57:54.631Z",
    }]; } },
    clock: () => requestMs + 30_000,
    cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: relay });
  assert.equal(result.active_count, 1);
  assert.equal(result.tasks.length, 1);
  assert.equal(result.tasks[0].title, "P24 · 8×1");
  assert.equal(result.tasks[0].status, "preparing");
  assert.equal(result.tasks[0].status_label, "正在准备正式任务");
  assert.equal(result.tasks[0].completed_units, 0);
  assert.equal(result.tasks[0].total_units, 8);
  assert.equal(result.tasks[0].can_stop, true);
});

test("preflight-only Fast8 shows an exact initialization approval", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-task-preflight-approval-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const outlinePath = path.join(root, "outline.md");
  const preflightDir = path.join(output, ".fast8_preflight");
  const manifestPath = path.join(preflightDir, "approval-p24.json");
  const requestMs = Date.parse("2026-08-15T12:57:54.631Z");
  await mkdir(preflightDir, { recursive: true });
  await writeFile(outlinePath, "# P24\n");
  await writeFile(manifestPath, JSON.stringify({
    fast8_preflight_manifest_version: 1,
    run_mode: "fast_8x1_diverse",
    task_name: "approval-p24",
    page_ids: ["P24"],
    request_started_at: "2026-08-15T12:57:54.631Z",
    required_files: [{ path: outlinePath }],
  }));
  const relay = {
    client: { serverRequests: new Map([["approval", {
      method: "item/commandExecution/requestApproval",
      params: {
        threadId: "thread-live",
        turnId: "turn-live",
        command: `python3 init_task_dir.py --preflight-manifest '${manifestPath}' --overview-python /runtime/python3`,
      },
    }]]) },
    activeTurn(threadId) { return threadId === "thread-live" ? "turn-live" : null; },
    latestTurn(threadId) {
      return threadId === "thread-live"
        ? { turnId: "turn-live", status: "inProgress", startedAtMs: requestMs }
        : null;
    },
  };
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "si", deck_uid: "SI_TASKS", label: "SI Playbook",
      outline_path: outlinePath, output_root: output,
      slides: [{ page_id: "P24", slide_uid: "SI_P24", page_label: "P24" }],
    }] }; } },
    conversations: { ready: true, records() { return [{
      conversation_id: "conversation-live", thread_id: "thread-live",
      last_used_at: "2026-08-15T12:57:54.631Z",
    }]; } },
    clock: () => requestMs + 30_000,
    cacheMs: 0,
  });
  const task = (await projection.list({ codexInteraction: relay })).tasks[0];
  assert.equal(task.status, "waiting_permission");
  assert.equal(task.pending_approval_count, 1);
});

test("preflight-only Fast8 without a live turn is never reported as active", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-task-preflight-orphan-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const outlinePath = path.join(root, "outline.md");
  const preflightDir = path.join(output, ".fast8_preflight");
  await mkdir(preflightDir, { recursive: true });
  await writeFile(outlinePath, "# P24\n");
  await writeFile(path.join(preflightDir, "orphan-p24.json"), JSON.stringify({
    fast8_preflight_manifest_version: 1,
    run_mode: "fast_8x1_diverse",
    task_name: "orphan-p24",
    page_ids: ["P24"],
    request_started_at: "2026-08-15T12:57:54.631Z",
    required_files: [outlinePath],
  }));
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "si", deck_uid: "SI_TASKS", label: "SI Playbook",
      outline_path: outlinePath, output_root: output,
      slides: [{ page_id: "P24", slide_uid: "SI_P24", page_label: "P24" }],
    }] }; } },
    conversations: { ready: true, records() { return []; } },
    clock: () => Date.parse("2026-08-15T12:58:24.631Z"),
    cacheMs: 0,
  });
  const result = await projection.list();
  assert.equal(result.active_count, 0);
  assert.equal(result.attention_count, 1);
  assert.equal(result.tasks[0].status, "attention");
  assert.equal(result.tasks[0].status_label, "初始化未完成");
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

test("a live active turn with pending approvals is counted as waiting for permission", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const statePath = path.join(output, "fast-run", "state", "style_run_state.json");
  await writeFile(statePath, JSON.stringify({
    run_id: "approval-task", run_mode: "fast_8x1_diverse", status: "running",
    scheduler: { active_actions: [{ page_id: "P06" }], ready_queue: [] },
    styles: Object.fromEntries("ABCDEFGH".split("").map((slot) => [slot, {
      pages: { P06: { status: "leased" } },
    }])),
  }));
  const relay = {
    client: { serverRequests: new Map([
      ["approval-1", { method: "item/commandExecution/requestApproval", params: {
        threadId: "thread-live", turnId: "turn-live", command: `python3 control.py claim --state '${statePath}'`,
      } }],
      ["approval-2", { method: "item/permissions/requestApproval", params: { threadId: "thread-live", turnId: "turn-live" } }],
      ["other-turn", { method: "item/fileChange/requestApproval", params: { threadId: "thread-live", turnId: "turn-old" } }],
      ["not-approval", { method: "item/tool/requestInput", params: { threadId: "thread-live", turnId: "turn-live" } }],
    ]) },
    activeTurn(threadId) { return threadId === "thread-live" ? "turn-live" : null; },
  };
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output,
      slides: [{ slide_uid: "SLIDE_06", page_label: "P06" }],
    }] }; } },
    conversations: { ready: true, records() { return [{
      conversation_id: "conversation-live", thread_id: "thread-live",
    }]; } },
    clock: () => Date.now(),
    cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: relay });
  assert.equal(result.active_count, 1);
  assert.equal(result.attention_count, 0);
  assert.equal(result.tasks[0].status, "waiting_permission");
  assert.equal(result.tasks[0].status_label, "等待允许操作");
  assert.equal(result.tasks[0].pending_approval_count, 1);
  assert.equal(result.tasks[0].can_stop, true);
});

test("a file-change approval inside the run project is shown as waiting permission", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const statePath = path.join(output, "fast-run", "state", "style_run_state.json");
  const itemId = "file-change-preflight";
  const relay = {
    client: { serverRequests: new Map([["approval-file", {
      method: "item/fileChange/requestApproval",
      params: { threadId: "thread-live", turnId: "turn-live", itemId },
    }]]) },
    activeTurn(threadId) { return threadId === "thread-live" ? "turn-live" : null; },
    records(threadId, turnId) {
      if (threadId !== "thread-live" || turnId !== "turn-live") return [];
      return [{
        method: "item/started",
        params: { item: { id: itemId, type: "fileChange", changes: [{ path: path.join(path.dirname(path.dirname(statePath)), "state", "preflight_manifest.json") }] } },
      }];
    },
  };
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output,
      slides: [{ page_id: "P06", slide_uid: "SLIDE_06", page_label: "P06" }],
    }] }; } },
    conversations: { ready: true, records() { return [{ conversation_id: "conversation-live", thread_id: "thread-live" }]; } },
    clock: () => Date.now(), cacheMs: 0,
  });
  const task = (await projection.list({ codexInteraction: relay })).tasks[0];
  assert.equal(task.status, "waiting_permission");
  assert.equal(task.pending_approval_count, 1);
});

test("tasks in one turn count only approvals for their own exact state", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const firstStatePath = path.join(output, "fast-run", "state", "style_run_state.json");
  const secondStateDir = path.join(output, "second-run", "state");
  const secondStatePath = path.join(secondStateDir, "style_run_state.json");
  await mkdir(secondStateDir, { recursive: true });
  await writeFile(path.join(secondStateDir, "source_snapshot.json"), JSON.stringify({
    page_ids: ["P07"],
    slide_identity: { deck_uid: "DECK_TASKS", slide_uids: { P07: "SLIDE_07" } },
  }));
  await writeFile(secondStatePath, JSON.stringify({
    run_id: "second-task", run_mode: "fast_8x1_diverse", status: "running",
    scheduler: { active_actions: [{ page_id: "P07" }], ready_queue: [] },
    styles: Object.fromEntries("ABCDEFGH".split("").map((slot) => [slot, {
      pages: { P07: { status: "leased" } },
    }])),
  }));
  const relay = {
    client: { serverRequests: new Map([
      ["first-state", {
        method: "item/commandExecution/requestApproval",
        params: { threadId: "thread-live", turnId: "turn-live", command: `python3 control.py receipt --state '${firstStatePath}'` },
      }],
      ["second-state", {
        method: "item/commandExecution/requestApproval",
        params: { threadId: "thread-live", turnId: "turn-live", command: `python3 control.py receipt --state '${secondStatePath}'` },
      }],
      ["help", {
        method: "item/commandExecution/requestApproval",
        params: { threadId: "thread-live", turnId: "turn-live", command: "python3 control.py --help" },
      }],
    ]) },
    activeTurn(threadId) { return threadId === "thread-live" ? "turn-live" : null; },
  };
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output,
      slides: [
        { slide_uid: "SLIDE_06", page_label: "P06" },
        { slide_uid: "SLIDE_07", page_label: "P07" },
      ],
    }] }; } },
    conversations: { ready: true, records() { return [{
      conversation_id: "conversation-live", thread_id: "thread-live",
    }]; } },
    clock: () => Date.now(),
    cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: relay });
  assert.equal(result.active_count, 2);
  const byPage = new Map(result.tasks.map((task) => [task.page_label, task]));
  assert.equal(byPage.get("P06").status, "waiting_permission");
  assert.equal(byPage.get("P06").pending_approval_count, 1);
  assert.equal(byPage.get("P07").status, "waiting_permission");
  assert.equal(byPage.get("P07").pending_approval_count, 1);
});

test("an exact state command approval associates an old run with its new active turn", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const statePath = path.join(output, "fast-run", "state", "style_run_state.json");
  await writeFile(statePath, JSON.stringify({
    run_id: "continued-old-run", run_mode: "fast_8x1_diverse", status: "running",
    scheduler: { active_actions: [{ page_id: "P06", leased_at: "2026-08-14T00:20:00Z" }], ready_queue: [] },
    styles: Object.fromEntries("ABCDEFGH".split("").map((slot) => [slot, {
      pages: { P06: { status: "leased" } },
    }])),
  }));
  const oldTime = new Date("2026-08-14T00:30:00Z");
  await utimes(statePath, oldTime, oldTime);
  const request = {
    id: 81,
    requestId: "81",
    method: "item/commandExecution/requestApproval",
    params: {
      threadId: "thread-new-turn",
      turnId: "turn-new",
      itemId: "command-receipt",
      command: `python3 '/opt/shawn-ppt-image/scripts/fast8_control_plane_v1.py' receipt --state '${statePath}' --ticket '/tmp/ticket.json'`,
      availableDecisions: ["accept", "acceptForSession", "decline"],
    },
  };
  const relay = {
    client: { serverRequests: new Map([["81", request]]) },
    activeTurn(threadId) { return threadId === "thread-new-turn" ? "turn-new" : null; },
  };
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output,
      slides: [{ slide_uid: "SLIDE_06", page_label: "P06" }],
    }] }; } },
    conversations: { ready: true, records() { return [{
      conversation_id: "conversation-new-turn",
      thread_id: "thread-new-turn",
      last_used_at: "2026-08-14T01:05:00Z",
    }]; } },
    clock: () => Date.parse("2026-08-14T01:10:00Z"),
    cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: relay });
  assert.equal(result.active_count, 1);
  assert.equal(result.attention_count, 0);
  assert.equal(result.tasks[0].conversation_id, "conversation-new-turn");
  assert.equal(result.tasks[0].status, "waiting_permission");
  assert.equal(result.tasks[0].pending_approval_count, 1);
  assert.equal(result.tasks[0].can_stop, true);
});

test("a command approval for another state does not associate an old run", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const statePath = path.join(output, "fast-run", "state", "style_run_state.json");
  await writeFile(statePath, JSON.stringify({
    run_id: "unrelated-old-run", run_mode: "fast_8x1_diverse", status: "running",
    scheduler: { active_actions: [{ page_id: "P06" }], ready_queue: [] },
    styles: Object.fromEntries("ABCDEFGH".split("").map((slot) => [slot, {
      pages: { P06: { status: "leased" } },
    }])),
  }));
  const oldTime = new Date("2026-08-14T00:30:00Z");
  await utimes(statePath, oldTime, oldTime);
  const relay = {
    client: { serverRequests: new Map([["82", {
      id: 82,
      requestId: "82",
      method: "item/commandExecution/requestApproval",
      params: {
        threadId: "thread-new-turn",
        turnId: "turn-new",
        itemId: "command-other-state",
        command: `python3 control.py receipt --state '${path.join(root, "other", "state", "style_run_state.json")}'`,
        availableDecisions: ["accept", "decline"],
      },
    }]]) },
    activeTurn(threadId) { return threadId === "thread-new-turn" ? "turn-new" : null; },
  };
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output, slides: [],
    }] }; } },
    conversations: { ready: true, records() { return [{
      conversation_id: "conversation-new-turn",
      thread_id: "thread-new-turn",
      last_used_at: "2026-08-14T01:05:00Z",
    }]; } },
    clock: () => Date.parse("2026-08-14T01:10:00Z"),
    cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: relay });
  assert.equal(result.active_count, 0);
  assert.equal(result.attention_count, 1);
  assert.equal(result.tasks[0].conversation_id, null);
  assert.equal(result.tasks[0].status, "attention");
  assert.equal(result.tasks[0].pending_approval_count, 0);
  assert.equal(result.tasks[0].can_stop, false);
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

test("a running canonical task without a live turn or receipts becomes stalled", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const statePath = path.join(output, "fast-run", "state", "style_run_state.json");
  await writeFile(statePath, JSON.stringify({
    run_id: "stalled-task", run_mode: "fast_8x1_diverse", status: "running",
    scheduler: { active_actions: [{ page_id: "P06", leased_at: "2026-08-14T00:20:00Z" }], ready_queue: [] },
    styles: Object.fromEntries("ABCDEFGH".split("").map((slot) => [slot, {
      pages: { P06: { status: "leased" } },
    }])),
  }));
  const staleTime = new Date("2026-08-14T00:30:00Z");
  await utimes(statePath, staleTime, staleTime);
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{ deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output, slides: [] }] }; } },
    conversations: { ready: true, records() { return []; } },
    clock: () => Date.parse("2026-08-14T01:10:00Z"), cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: { activeTurn() { return null; } } });
  const task = result.tasks[0];
  assert.equal(task.status, "attention");
  assert.equal(task.status_label, "任务已停滞");
  assert.equal(task.pending_approval_count, 0);
  assert.equal(task.completed_units, 0);
  assert.equal(task.can_stop, false);
  assert.equal(result.active_count, 0);
  assert.equal(result.attention_count, 1);
});

test("a newer completed run hides an older stalled run for the same page and mode", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const oldStatePath = path.join(output, "fast-run", "state", "style_run_state.json");
  await writeFile(oldStatePath, JSON.stringify({
    run_id: "superseded-stalled", run_mode: "fast_8x1_diverse", status: "running",
    scheduler: { active_actions: [{ page_id: "P06" }], ready_queue: [] },
    styles: Object.fromEntries("ABCDEFGH".split("").map((slot) => [slot, {
      pages: { P06: { status: "leased" } },
    }])),
  }));
  const oldTime = new Date("2026-08-14T00:30:00Z");
  await utimes(oldStatePath, oldTime, oldTime);

  const completedStateDir = path.join(output, "completed-run", "state");
  await mkdir(completedStateDir, { recursive: true });
  await writeFile(path.join(completedStateDir, "source_snapshot.json"), JSON.stringify({
    page_ids: ["P06"],
    slide_identity: { deck_uid: "DECK_TASKS", slide_uids: { P06: "SLIDE_06" } },
  }));
  const completedStatePath = path.join(completedStateDir, "style_run_state.json");
  await writeFile(completedStatePath, JSON.stringify({
    run_id: "replacement-completed", run_mode: "fast_8x1_diverse", status: "completed",
    timing: { process_completed_at: "2026-08-14T01:05:00Z" },
    scheduler: { active_actions: [], ready_queue: [] },
    styles: Object.fromEntries("ABCDEFGH".split("").map((slot) => [slot, {
      pages: { P06: { status: "candidate_ready", final_path: `${slot}.png` } },
    }])),
  }));
  const completedTime = new Date("2026-08-14T01:05:00Z");
  await utimes(completedStatePath, completedTime, completedTime);

  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output,
      slides: [{ slide_uid: "SLIDE_06", page_label: "P06" }],
    }] }; } },
    conversations: { ready: true, records() { return []; } },
    clock: () => Date.parse("2026-08-14T01:10:00Z"), cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: { activeTurn() { return null; } } });
  assert.equal(result.active_count, 0);
  assert.equal(result.attention_count, 0);
  assert.equal(result.tasks.length, 1);
  assert.equal(result.tasks[0].status, "completed");
  assert.equal(result.tasks[0].completed_units, 8);
});

test("an interrupted latest turn immediately marks its associated run stopped", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const statePath = path.join(output, "fast-run", "state", "style_run_state.json");
  const startedAtMs = Date.parse("2026-08-14T01:05:00Z");
  const startedAt = new Date(startedAtMs);
  await utimes(statePath, startedAt, startedAt);
  const relay = {
    activeTurn() { return null; },
    latestTurn(threadId) {
      return threadId === "thread-stopped"
        ? { turnId: "turn-stopped", status: "interrupted", startedAtMs, completedAtMs: startedAtMs + 60_000 }
        : null;
    },
  };
  const projection = new TaskProjection({
    discovery: { async listDecks() { return { decks: [{
      deck_id: "deck", deck_uid: "DECK_TASKS", label: "测试", output_root: output,
      slides: [{ page_id: "P06", slide_uid: "SLIDE_06", page_label: "P06" }],
    }] }; } },
    conversations: { ready: true, records() { return [{
      conversation_id: "conversation-stopped", thread_id: "thread-stopped", last_used_at: "2026-08-14T01:06:00Z",
    }]; } },
    clock: () => Date.parse("2026-08-14T01:07:00Z"), cacheMs: 0,
  });
  const result = await projection.list({ codexInteraction: relay });
  assert.equal(result.active_count, 0);
  assert.equal(result.attention_count, 1);
  assert.equal(result.tasks[0].status, "attention");
  assert.equal(result.tasks[0].status_label, "任务已停止");
  assert.equal(result.tasks[0].conversation_id, "conversation-stopped");
});

test("a task keeps its source conversation across concurrent turns, completion, and restart", async (t) => {
  const { root, output } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(output, "fast-run", "state");
  const statePath = path.join(stateDir, "style_run_state.json");
  const requestMs = Date.parse("2026-08-15T15:15:20.000Z");
  await writeFile(path.join(stateDir, "preflight_manifest.json"), JSON.stringify({
    request_started_at: new Date(requestMs).toISOString(),
    page_ids: ["P06"],
  }));
  await writeFile(statePath, JSON.stringify({
    run_id: "persistent-conversation-task",
    run_mode: "fast_8x1_diverse",
    status: "running",
    scheduler: { active_actions: [{ page_id: "P06" }], ready_queue: [] },
    styles: Object.fromEntries("ABCDEFGH".split("").map((slot) => [slot, {
      pages: { P06: { status: "running" } },
    }])),
  }));
  const stateTime = new Date(requestMs + 60_000);
  await utimes(statePath, stateTime, stateTime);

  const discovery = { async listDecks() { return { decks: [{
    deck_id: "deck-tasks", deck_uid: "DECK_TASKS", label: "客户提案",
    output_root: output,
    slides: [{ page_id: "P06", slide_uid: "SLIDE_06", page_label: "P06" }],
  }] }; } };
  const records = [
    { conversation_id: "conversation-source", thread_id: "thread-source", last_used_at: new Date(requestMs).toISOString() },
    { conversation_id: "conversation-new", thread_id: "thread-new", last_used_at: new Date(requestMs + 120_000).toISOString() },
  ];
  const conversations = { ready: true, records() { return records; } };
  const relay = {
    activeTurn(threadId) { return threadId === "thread-source" ? "turn-source" : "turn-new"; },
    latestTurn(threadId) {
      return threadId === "thread-source"
        ? { turnId: "turn-source", status: "inProgress", startedAtMs: requestMs }
        : { turnId: "turn-new", status: "inProgress", startedAtMs: requestMs + 120_000 };
    },
  };
  const dataRoot = path.join(root, "studio-data");
  const firstIndex = new TaskAssociationIndex({ dataRoot, clock: () => "2026-08-15T15:16:30.000Z" });
  await firstIndex.initialize();
  await firstIndex.rememberRequest(
    "DECK_TASKS",
    new Date(requestMs).toISOString(),
    "conversation-source",
  );
  const firstProjection = new TaskProjection({
    discovery, conversations, associations: firstIndex,
    clock: () => requestMs + 180_000, cacheMs: 0,
  });
  const running = (await firstProjection.list({ codexInteraction: relay })).tasks[0];
  assert.equal(running.conversation_id, "conversation-source");
  assert.equal(running.can_open_conversation, true);
  assert.equal(running.can_stop, true);
  assert.equal(running.status, "generating");
  assert.match(await readFile(firstIndex.path, "utf8"), /conversation-source/);

  await writeFile(statePath, JSON.stringify({
    run_id: "persistent-conversation-task",
    run_mode: "fast_8x1_diverse",
    status: "completed",
    scheduler: { active_actions: [], ready_queue: [] },
    styles: Object.fromEntries("ABCDEFGH".split("").map((slot) => [slot, {
      pages: { P06: { status: "candidate_ready", final_path: `${slot}.png` } },
    }])),
  }));
  const completedTime = new Date(requestMs + 240_000);
  await utimes(statePath, completedTime, completedTime);

  const restartedIndex = new TaskAssociationIndex({ dataRoot });
  await restartedIndex.initialize();
  const restartedProjection = new TaskProjection({
    discovery, conversations, associations: restartedIndex,
    clock: () => requestMs + 300_000, cacheMs: 0,
  });
  const completed = (await restartedProjection.list({
    codexInteraction: { activeTurn() { return null; }, latestTurn() { return null; } },
  })).tasks[0];
  assert.equal(completed.status, "completed");
  assert.equal(completed.conversation_id, "conversation-source");
  assert.equal(completed.can_open_conversation, true);
});

test("the Studio host records a request binding before starting its turn", async () => {
  const httpSource = await readFile(new URL("../../server/http-server.mjs", import.meta.url), "utf8");
  const serverSource = await readFile(new URL("../../server/server.mjs", import.meta.url), "utf8");
  const start = httpSource.indexOf("async function streamWorkspaceTurn");
  const end = httpSource.indexOf("async function serveConversationImage", start);
  const workspaceTurn = httpSource.slice(start, end);
  assert.match(workspaceTurn, /associations\?\.rememberRequest/);
  assert.ok(
    workspaceTurn.indexOf("rememberRequest")
      < workspaceTurn.lastIndexOf("startTurnWithArchivedRecovery"),
  );
  assert.match(serverSource, /new TaskAssociationIndex\(\{ dataRoot \}\)/);
});
