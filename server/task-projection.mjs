import { createHash } from "node:crypto";
import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";

const CONTRACT_VERSION = 1;
const STATE_FILES = [
  ["style_run_state.json", "style"],
  ["selected_style_run_state.json", "selected"],
  ["single_image_edit_state.json", "single"],
];
const FINISHED = new Set(["completed", "candidate_ready", "accepted"]);
const FAILED = new Set(["failed", "error", "cancelled", "interrupted"]);

function asTime(value) {
  const time = Date.parse(typeof value === "string" ? value : "");
  return Number.isFinite(time) ? time : null;
}

function idFor(...parts) {
  return createHash("sha256").update(parts.join("\u0000")).digest("hex").slice(0, 24);
}

function entries(value) {
  if (Array.isArray(value)) return value;
  return value && typeof value === "object" ? Object.values(value) : [];
}

function pageEntries(state, kind) {
  if (kind === "single") return [state.imagegen || {}];
  if (kind === "selected") return entries(state.pages);
  return entries(state.styles).flatMap((style) => entries(style?.pages));
}

function unitDone(unit, kind) {
  if (kind === "single") return unit?.status === "completed" || Boolean(unit?.saved_path);
  return FINISHED.has(unit?.status) || Boolean(
    unit?.tool_finished_at || unit?.selected_source || unit?.final_path || unit?.completed_at,
  );
}

async function completedFast8Receipts(projectDir, state) {
  const resultsDir = path.join(projectDir, "style_jobs", "results");
  let children;
  try {
    children = await readdir(resultsDir, { withFileTypes: true });
  } catch {
    return { count: 0, updatedMs: 0 };
  }
  const completed = new Set();
  let updatedMs = 0;
  for (const child of children) {
    if (!child.isFile() || child.isSymbolicLink() || !/^worker_receipt_.*\.json$/.test(child.name)) continue;
    const receiptPath = path.join(resultsDir, child.name);
    const receipt = await readJson(receiptPath);
    const style = typeof receipt?.style === "string" ? receipt.style : "";
    const pageId = typeof receipt?.page_id === "string" ? receipt.page_id : "";
    const expectedPages = state.styles?.[style]?.pages;
    if (
      receipt?.worker_receipt_contract_version !== 1
      || receipt?.tool_status !== "completed"
      || typeof receipt?.savedPath !== "string"
      || !receipt.savedPath.trim()
      || receipt?.error
      || receipt?.failure_class
      || !expectedPages
      || !Object.prototype.hasOwnProperty.call(expectedPages, pageId)
    ) continue;
    completed.add(`${style}\u0000${pageId}`);
    const info = await stat(receiptPath).catch(() => null);
    updatedMs = Math.max(updatedMs, info?.mtimeMs || 0);
  }
  return { count: completed.size, updatedMs };
}

function firstString(...values) {
  return values.find((value) => typeof value === "string" && value.trim())?.trim() || null;
}

function collectThreadIds(value, result = new Set()) {
  if (typeof value === "string") {
    const match = value.match(/[\\/]generated_images[\\/]([^\\/]+)[\\/]/);
    if (match?.[1]) result.add(match[1]);
    return result;
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectThreadIds(item, result));
    return result;
  }
  if (value && typeof value === "object") {
    Object.values(value).forEach((item) => collectThreadIds(item, result));
  }
  return result;
}

function modeTitle(mode, pageLabel, total, pageLabels) {
  if (mode === "single_image_edit") return `${pageLabel || "当前页"} · 修图`;
  if (mode === "selected_style_expansion") return `整套作图 · ${total || pageLabels.length || 0} 页`;
  if (["fast_4x3_anchored", "full_4x3_anchored"].includes(mode)) {
    const scope = pageLabels.length > 1 ? `${pageLabels[0]}–${pageLabels.at(-1)}` : pageLabel || "当前页";
    return `${scope} · 4×3`;
  }
  if (["fast_8x1_diverse", "quick_8x1"].includes(mode)) return `${pageLabel || "当前页"} · 8×1`;
  return `${pageLabel || "PPT"} · 作图`;
}

function stageOf({ state, kind, completed, total, started, updatedAt, now, staleMs }) {
  const root = String(state.status || "").toLowerCase();
  if (FAILED.has(root)) return { status: "failed", label: "需要查看", percent: null };
  if (root === "completed") return { status: "completed", label: "已完成", percent: 100 };
  if (now - updatedAt > staleMs) {
    return { status: "attention", label: "长时间没有更新", percent: null };
  }
  if (kind === "single") {
    if (completed >= 1) return { status: "reviewing", label: "图片已生成，正在收尾", percent: null };
    if (["leased", "running", "inprogress"].includes(String(state.imagegen?.status || "").toLowerCase())) {
      return { status: "generating", label: "正在修改图片", percent: null };
    }
    return { status: "preparing", label: "准备修图", percent: null };
  }
  if (total > 0 && completed >= total) return { status: "reviewing", label: "图片已生成，正在质检", percent: null };
  if (completed > 0 || started) {
    return {
      status: "generating",
      label: `已生成 ${completed}/${total}`,
      percent: total > 0 ? Math.round((completed / total) * 100) : null,
    };
  }
  if (entries(state.scheduler?.active_actions).length > 0) {
    return { status: "queued", label: "等待图片生成", percent: 0 };
  }
  if (entries(state.scheduler?.ready_queue).length > 0) {
    return { status: "queued", label: "等待生成", percent: 0 };
  }
  return { status: "preparing", label: "准备中", percent: null };
}

function startedTime(state, kind, fileMtime) {
  if (kind === "single") return asTime(state.prepared_at) || fileMtime;
  return asTime(
    state.timing?.process_started_at
      || state.started_at
      || entries(state.styles)[0]?.pages && entries(entries(state.styles)[0]?.pages)[0]?.queued_at,
  ) || fileMtime;
}

function completedTime(state, kind) {
  if (kind === "single") return asTime(state.completed_at);
  return asTime(state.timing?.process_completed_at || state.completed_at);
}

async function readJson(filePath) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch {
    return null;
  }
}

export class TaskProjection {
  constructor({ discovery, conversations, clock = () => Date.now(), cacheMs = 1500, recentMs = 36 * 60 * 60 * 1000, staleMs = 30 * 60 * 1000, associationGraceMs = 15 * 60 * 1000 }) {
    this.discovery = discovery;
    this.conversations = conversations;
    this.clock = clock;
    this.cacheMs = cacheMs;
    this.recentMs = recentMs;
    this.staleMs = staleMs;
    this.associationGraceMs = associationGraceMs;
    this.cache = null;
    this.targets = new Map();
    this.lastError = null;
  }

  health() {
    return {
      ready: Boolean(this.discovery),
      task_count: this.cache?.payload?.tasks?.length || 0,
      error: this.lastError?.message || null,
    };
  }

  async list({ codexInteraction = null, force = false } = {}) {
    const now = this.clock();
    if (!force && this.cache && now - this.cache.createdAt < this.cacheMs) return this.cache.payload;
    try {
      const listing = await this.discovery.listDecks();
      const internal = [];
      for (const deck of listing.decks || []) {
        const roots = [...new Set([deck.output_root, ...(deck.candidate_roots_paths || [])].filter(Boolean))];
        const conversations = this.conversations?.ready ? this.conversations.records(deck.deck_uid) : [];
        const byThread = new Map(conversations.map((item) => [item.thread_id, item]));
        const active = conversations.filter((item) => codexInteraction?.activeTurn(item.thread_id));
        for (const root of roots) {
          internal.push(...await this.#scanRoot({ deck, root, conversations, byThread, active, codexInteraction, now }));
        }
      }
      const deduped = [...new Map(internal.map((task) => [task.task_id, task])).values()];
      const priority = { generating: 0, reviewing: 0, queued: 1, preparing: 1, attention: 2, failed: 2, completed: 3 };
      deduped.sort((left, right) => (priority[left.status] ?? 9) - (priority[right.status] ?? 9) || right.updatedMs - left.updatedMs);
      const activeTasks = deduped.filter((task) => {
        if (task.status === "completed") return now - task.updatedMs <= this.recentMs;
        return task.can_stop || now - task.updatedMs <= this.recentMs;
      });
      const completed = activeTasks.filter((task) => task.status === "completed").slice(0, 5);
      const tasks = [...activeTasks.filter((task) => task.status !== "completed"), ...completed];
      this.targets = new Map(tasks.filter((task) => task.threadId && task.turnId).map((task) => [task.task_id, {
        threadId: task.threadId,
        turnId: task.turnId,
      }]));
      const publicTasks = tasks.map(({ updatedMs: _updatedMs, threadId: _threadId, turnId: _turnId, ...task }) => task);
      const payload = {
        contract_version: CONTRACT_VERSION,
        active_count: publicTasks.filter((task) => ["preparing", "queued", "generating", "reviewing"].includes(task.status)).length,
        attention_count: publicTasks.filter((task) => ["attention", "failed"].includes(task.status)).length,
        tasks: publicTasks,
      };
      this.cache = { createdAt: now, payload };
      this.lastError = null;
      return payload;
    } catch (error) {
      this.lastError = error;
      throw error;
    }
  }

  interruptTarget(taskId) {
    return this.targets.get(taskId) || null;
  }

  async #scanRoot({ deck, root, conversations, byThread, active, codexInteraction, now }) {
    let children;
    try {
      children = await readdir(root, { withFileTypes: true });
    } catch {
      return [];
    }
    const tasks = [];
    for (const child of children) {
      if (!child.isDirectory() || child.isSymbolicLink()) continue;
      const stateDir = path.join(root, child.name, "state");
      for (const [filename, kind] of STATE_FILES) {
        const statePath = path.join(stateDir, filename);
        const state = await readJson(statePath);
        if (!state?.run_id) continue;
        const info = await stat(statePath).catch(() => null);
        if (!info?.isFile()) continue;
        const snapshot = kind === "single" ? null : await readJson(path.join(stateDir, "source_snapshot.json"));
        const identity = kind === "single" ? state.identity || {} : snapshot?.slide_identity || {};
        if (identity.deck_uid && identity.deck_uid !== deck.deck_uid) continue;
        const pageIds = kind === "single"
          ? [identity.page_id].filter(Boolean)
          : Array.isArray(snapshot?.page_ids) ? snapshot.page_ids : [];
        const slideUids = kind === "single"
          ? [identity.slide_uid].filter(Boolean)
          : pageIds.map((pageId) => identity.slide_uids?.[pageId]).filter(Boolean);
        const slides = slideUids.map((uid) => deck.slides.find((slide) => slide.slide_uid === uid)).filter(Boolean);
        const pageLabels = slides.map((slide) => slide.page_label).filter(Boolean);
        const pageLabel = pageLabels[0] || firstString(identity.page_id, pageIds[0]);
        const units = pageEntries(state, kind);
        const total = units.length || (kind === "single" ? 1 : pageIds.length);
        const receiptProgress = kind === "style"
          ? await completedFast8Receipts(path.dirname(stateDir), state)
          : { count: 0, updatedMs: 0 };
        const completed = Math.min(total, Math.max(
          units.filter((unit) => unitDone(unit, kind)).length,
          receiptProgress.count,
        ));
        const updatedMs = Math.max(info.mtimeMs, receiptProgress.updatedMs);
        const threadIds = [...collectThreadIds(state)];
        let conversation = threadIds.map((threadId) => byThread.get(threadId)).find(Boolean) || null;
        if (!conversation && active.length === 1 && !FINISHED.has(String(state.status || "").toLowerCase())) {
          const candidate = active[0];
          const activityMs = asTime(candidate.last_used_at);
          if (!activityMs || updatedMs >= activityMs - this.associationGraceMs) conversation = candidate;
        }
        const activeTurnId = conversation ? codexInteraction?.activeTurn(conversation.thread_id) : null;
        const activityMs = asTime(conversation?.last_used_at);
        const turnId = activeTurnId && (!activityMs || updatedMs >= activityMs - this.associationGraceMs)
          ? activeTurnId
          : null;
        const started = units.some((unit) => Boolean(
          unit?.tool_started_at
          || ["running", "leased", "inprogress"].includes(String(unit?.status || "").toLowerCase()),
        ));
        const stage = stageOf({ state, kind, completed, total, started, updatedAt: updatedMs, now, staleMs: this.staleMs });
        const startMs = startedTime(state, kind, updatedMs);
        const endMs = completedTime(state, kind) || (stage.status === "completed" ? updatedMs : now);
        tasks.push({
          task_id: idFor(deck.deck_id, state.run_id, filename),
          deck_id: deck.deck_id,
          deck_label: deck.label,
          conversation_id: conversation?.conversation_id || null,
          slide_uid: slides[0]?.slide_uid || slideUids[0] || null,
          page_label: pageLabel,
          title: modeTitle(state.run_mode, pageLabel, total, pageLabels),
          mode: state.run_mode || kind,
          status: stage.status,
          status_label: stage.label,
          completed_units: completed,
          total_units: total,
          progress_percent: stage.percent,
          elapsed_seconds: Math.max(0, Math.round((endMs - startMs) / 1000)),
          updated_at: new Date(updatedMs).toISOString(),
          can_stop: Boolean(turnId),
          can_open_conversation: Boolean(conversation),
          updatedMs,
          threadId: conversation?.thread_id || null,
          turnId: turnId || null,
        });
      }
    }
    return tasks;
  }
}
