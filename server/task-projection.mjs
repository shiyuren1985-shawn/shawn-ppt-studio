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

function pathWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

function fileChangeApprovalTouchesProject(codexInteraction, request, projectDir) {
  if (request?.method !== "item/fileChange/requestApproval") return false;
  const threadId = request?.params?.threadId;
  const turnId = request?.params?.turnId;
  const itemId = request?.params?.itemId;
  if (!threadId || !turnId || !itemId) return false;
  const records = codexInteraction?.records?.(threadId, turnId, 0) || [];
  const item = records
    .filter((record) => ["item/started", "item/completed"].includes(record?.method))
    .map((record) => record?.params?.item)
    .find((candidate) => candidate?.id === itemId && candidate?.type === "fileChange");
  return (item?.changes || []).some((change) => {
    const changedPath = typeof change?.path === "string" ? path.normalize(change.path) : null;
    return changedPath && path.isAbsolute(changedPath) && pathWithin(projectDir, changedPath);
  });
}

function pendingApprovalCount(codexInteraction, threadId, turnId, statePath, projectDir) {
  if (!threadId || !turnId) return 0;
  const requests = codexInteraction?.client?.serverRequests;
  if (!requests || typeof requests.values !== "function") return 0;
  const expected = path.normalize(statePath);
  let count = 0;
  for (const request of requests.values()) {
    if (request?.params?.threadId !== threadId || request?.params?.turnId !== turnId) continue;
    if (
      (request?.method === "item/commandExecution/requestApproval" && approvalStatePath(request) === expected)
      || fileChangeApprovalTouchesProject(codexInteraction, request, projectDir)
    ) count += 1;
  }
  return count;
}

function commandValue(value) {
  if (typeof value === "string") return value;
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) return value.join(" ");
  return "";
}

function unquote(value) {
  if (value.startsWith("'") && value.endsWith("'")) return value.slice(1, -1);
  if (value.startsWith('"') && value.endsWith('"')) {
    return value.slice(1, -1).replace(/\\(["\\$`])/g, "$1");
  }
  return value.replace(/\\([\\\s])/g, "$1");
}

function approvalStatePath(request) {
  if (request?.method !== "item/commandExecution/requestApproval") return null;
  const command = commandValue(request?.params?.command);
  const match = command.match(/(?:^|\s)--state(?:=|\s+)("(?:[^"\\]|\\.)*"|'[^']*'|(?:\\.|[^\s])+)/);
  if (!match) return null;
  const referenced = unquote(match[1]);
  return path.isAbsolute(referenced) ? path.normalize(referenced) : null;
}

function approvalReferencesState(codexInteraction, threadId, turnId, statePath, projectDir) {
  return pendingApprovalCount(codexInteraction, threadId, turnId, statePath, projectDir) > 0;
}

function commandFlagPath(request, flag) {
  if (request?.method !== "item/commandExecution/requestApproval") return null;
  const command = commandValue(request?.params?.command);
  const escaped = flag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = command.match(new RegExp(`(?:^|\\s)${escaped}(?:=|\\s+)("(?:[^"\\\\]|\\\\.)*"|'[^']*'|(?:\\\\.|[^\\s])+)`));
  if (!match) return null;
  const referenced = unquote(match[1]);
  return path.isAbsolute(referenced) ? path.normalize(referenced) : null;
}

function pendingPreflightApprovalCount(codexInteraction, threadId, turnId, manifestPath) {
  if (!threadId || !turnId) return 0;
  const requests = codexInteraction?.client?.serverRequests;
  if (!requests || typeof requests.values !== "function") return 0;
  const expected = path.normalize(manifestPath);
  let count = 0;
  for (const request of requests.values()) {
    if (request?.params?.threadId !== threadId || request?.params?.turnId !== turnId) continue;
    if (commandFlagPath(request, "--preflight-manifest") === expected) count += 1;
  }
  return count;
}

function preflightBelongsToDeck(preflight, deck) {
  const authority = firstString(deck?.outline_path, deck?.outline?.path);
  if (!authority) return true;
  const expected = path.normalize(authority);
  const files = Array.isArray(preflight?.required_files) ? preflight.required_files : [];
  const candidates = [
    ...files.map((item) => typeof item === "string" ? item : item?.path),
    typeof preflight?.slide_identity_file === "string"
      ? preflight.slide_identity_file
      : preflight?.slide_identity_file?.path,
  ].filter((value) => typeof value === "string" && path.isAbsolute(value));
  return candidates.some((value) => path.normalize(value) === expected);
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

function stageOf({ state, kind, completed, total, started, updatedAt, now, staleMs, hasLiveTurn, pendingApprovals, terminalTurnStatus }) {
  const root = String(state.status || "").toLowerCase();
  if (FAILED.has(root)) return { status: "failed", label: "需要查看", percent: null };
  if (root === "completed") return { status: "completed", label: "已完成", percent: 100 };
  if (hasLiveTurn && pendingApprovals > 0) {
    return {
      status: "waiting_permission",
      label: "等待允许操作",
      percent: total > 0 ? Math.round((completed / total) * 100) : null,
    };
  }
  if (!hasLiveTurn && ["interrupted", "failed"].includes(terminalTurnStatus)) {
    return {
      status: "attention",
      label: terminalTurnStatus === "interrupted" ? "任务已停止" : "任务需要查看",
      percent: null,
    };
  }
  if (!hasLiveTurn && now - updatedAt > staleMs) {
    return { status: "attention", label: "任务已停滞", percent: null };
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
          internal.push(...await this.#scanPreflightRoot({ deck, root, conversations, active, codexInteraction, now }));
        }
      }
      const deduped = [...new Map(internal.map((task) => [task.task_id, task])).values()];
      const formalRequests = deduped.filter((task) => task.sourceKind === "state" && task.requestStartedMs);
      const withoutSupersededPreflights = deduped.filter((task) => {
        if (task.sourceKind !== "preflight" || !task.requestStartedMs) return true;
        return !formalRequests.some((formal) => (
          formal.deck_id === task.deck_id
          && formal.mode === task.mode
          && (formal.slide_uid || formal.page_label) === (task.slide_uid || task.page_label)
          && Math.abs(formal.requestStartedMs - task.requestStartedMs) <= 1000
        ));
      });
      const completedByScope = new Map();
      for (const task of withoutSupersededPreflights) {
        if (task.status !== "completed") continue;
        const scope = `${task.deck_id}\u0000${task.slide_uid || ""}\u0000${task.mode}`;
        completedByScope.set(scope, Math.max(completedByScope.get(scope) || 0, task.updatedMs));
      }
      const currentTasks = withoutSupersededPreflights.filter((task) => {
        if (task.status !== "attention" || task.can_stop) return true;
        const scope = `${task.deck_id}\u0000${task.slide_uid || ""}\u0000${task.mode}`;
        return (completedByScope.get(scope) || 0) <= task.updatedMs;
      });
      const priority = { waiting_permission: 0, generating: 0, reviewing: 0, queued: 1, preparing: 1, attention: 2, failed: 2, completed: 3 };
      currentTasks.sort((left, right) => (priority[left.status] ?? 9) - (priority[right.status] ?? 9) || right.updatedMs - left.updatedMs);
      const activeTasks = currentTasks.filter((task) => {
        if (task.status === "completed") return now - task.updatedMs <= this.recentMs;
        return task.can_stop || now - task.updatedMs <= this.recentMs;
      });
      const completed = activeTasks.filter((task) => task.status === "completed").slice(0, 5);
      const tasks = [...activeTasks.filter((task) => task.status !== "completed"), ...completed];
      this.targets = new Map(tasks.filter((task) => task.threadId && task.turnId).map((task) => [task.task_id, {
        threadId: task.threadId,
        turnId: task.turnId,
      }]));
      const publicTasks = tasks.map(({
        updatedMs: _updatedMs,
        threadId: _threadId,
        turnId: _turnId,
        sourceKind: _sourceKind,
        requestStartedMs: _requestStartedMs,
        ...task
      }) => task);
      const payload = {
        contract_version: CONTRACT_VERSION,
        active_count: publicTasks.filter((task) => ["waiting_permission", "preparing", "queued", "generating", "reviewing"].includes(task.status)).length,
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

  async #scanPreflightRoot({ deck, root, conversations, active, codexInteraction, now }) {
    const preflightRoot = path.join(root, ".fast8_preflight");
    let entries;
    try {
      entries = await readdir(preflightRoot, { withFileTypes: true });
    } catch {
      return [];
    }
    const tasks = [];
    for (const entry of entries) {
      if (!entry.isFile() || entry.isSymbolicLink() || path.extname(entry.name) !== ".json") continue;
      const manifestPath = path.join(preflightRoot, entry.name);
      const preflight = await readJson(manifestPath);
      if (
        preflight?.fast8_preflight_manifest_version !== 1
        || preflight?.run_mode !== "fast_8x1_diverse"
        || typeof preflight?.task_name !== "string"
        || !Array.isArray(preflight?.page_ids)
        || !preflight.page_ids.length
        || !preflightBelongsToDeck(preflight, deck)
      ) continue;
      const formalStatePath = path.join(root, preflight.task_name, "state", "style_run_state.json");
      if ((await stat(formalStatePath).catch(() => null))?.isFile()) continue;
      const info = await stat(manifestPath).catch(() => null);
      if (!info?.isFile()) continue;
      const requestMs = asTime(preflight.request_started_at) || info.mtimeMs;
      const pageIds = preflight.page_ids.filter((value) => typeof value === "string");
      const slides = pageIds
        .map((pageId) => deck.slides.find((slide) => slide.page_id === pageId))
        .filter(Boolean);
      const pageLabels = slides.map((slide) => slide.page_label).filter(Boolean);
      const pageLabel = pageLabels[0] || pageIds[0] || null;

      const activeMatches = active.map((candidate) => {
        const latest = codexInteraction?.latestTurn?.(candidate.thread_id);
        const turnId = codexInteraction?.activeTurn?.(candidate.thread_id);
        if (!turnId) return null;
        const startedAtMs = latest?.turnId === turnId ? latest.startedAtMs : null;
        const activityMs = asTime(candidate.last_used_at);
        const related = startedAtMs
          ? Math.abs(requestMs - startedAtMs) <= this.associationGraceMs
          : !activityMs || requestMs >= activityMs - this.associationGraceMs;
        return related ? { conversation: candidate, turnId } : null;
      }).filter(Boolean);
      const activeMatch = activeMatches.length === 1 ? activeMatches[0] : null;
      let conversation = activeMatch?.conversation || null;
      let turnId = activeMatch?.turnId || null;
      let terminalTurnStatus = null;
      if (!conversation) {
        const terminalMatches = conversations.map((candidate) => {
          const latest = codexInteraction?.latestTurn?.(candidate.thread_id);
          if (!latest || !["interrupted", "failed"].includes(latest.status)) return null;
          if (!latest.startedAtMs || Math.abs(requestMs - latest.startedAtMs) > this.associationGraceMs) return null;
          return { conversation: candidate, latest };
        }).filter(Boolean);
        if (terminalMatches.length === 1) {
          conversation = terminalMatches[0].conversation;
          terminalTurnStatus = terminalMatches[0].latest.status;
        }
      }
      const pendingApprovals = pendingPreflightApprovalCount(
        codexInteraction,
        conversation?.thread_id,
        turnId,
        manifestPath,
      );
      let status = "preparing";
      let statusLabel = "正在准备正式任务";
      if (turnId && pendingApprovals > 0) {
        status = "waiting_permission";
        statusLabel = "等待允许操作";
      } else if (!turnId && terminalTurnStatus) {
        status = "attention";
        statusLabel = terminalTurnStatus === "interrupted" ? "任务已停止" : "任务需要查看";
      } else if (!turnId) {
        status = "attention";
        statusLabel = "初始化未完成";
      }
      tasks.push({
        task_id: idFor(deck.deck_id, manifestPath, "preflight"),
        deck_id: deck.deck_id,
        deck_label: deck.label,
        conversation_id: conversation?.conversation_id || null,
        slide_uid: slides[0]?.slide_uid || null,
        page_label: pageLabel,
        title: modeTitle("fast_8x1_diverse", pageLabel, 8, pageLabels),
        mode: "fast_8x1_diverse",
        status,
        status_label: statusLabel,
        completed_units: 0,
        total_units: 8,
        progress_percent: null,
        pending_approval_count: pendingApprovals,
        elapsed_seconds: Math.max(0, Math.round((now - requestMs) / 1000)),
        updated_at: new Date(info.mtimeMs).toISOString(),
        can_stop: Boolean(turnId),
        can_open_conversation: Boolean(conversation),
        updatedMs: info.mtimeMs,
        threadId: conversation?.thread_id || null,
        turnId,
        sourceKind: "preflight",
        requestStartedMs: requestMs,
      });
    }
    return tasks;
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
        const preflight = kind === "style" ? await readJson(path.join(stateDir, "preflight_manifest.json")) : null;
        const identity = kind === "single" ? state.identity || {} : snapshot?.slide_identity || {};
        if (identity.deck_uid && identity.deck_uid !== deck.deck_uid) continue;
        const pageIds = kind === "single"
          ? [identity.page_id].filter(Boolean)
          : Array.isArray(snapshot?.page_ids) && snapshot.page_ids.length
            ? snapshot.page_ids
            : Array.isArray(preflight?.page_ids) ? preflight.page_ids : [];
        const slideUids = kind === "single"
          ? [identity.slide_uid].filter(Boolean)
          : pageIds.map((pageId) => identity.slide_uids?.[pageId]
            || deck.slides.find((slide) => slide.page_id === pageId)?.slide_uid).filter(Boolean);
        const slides = slideUids.map((uid) => deck.slides.find((slide) => slide.slide_uid === uid)).filter(Boolean);
        const pageLabels = slides.map((slide) => slide.page_label).filter(Boolean);
        const pageLabel = pageLabels[0] || firstString(identity.page_id, pageIds[0]);
        const units = pageEntries(state, kind);
        const total = units.length || (
          kind === "single"
            ? 1
            : ["fast_8x1_diverse", "quick_8x1"].includes(state.run_mode)
              ? 8
              : pageIds.length
        );
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
        const exactApprovalMatches = active.map((candidate) => {
          const activeTurnId = codexInteraction?.activeTurn(candidate.thread_id);
          return approvalReferencesState(codexInteraction, candidate.thread_id, activeTurnId, statePath, path.dirname(stateDir))
            ? { conversation: candidate, turnId: activeTurnId }
            : null;
        }).filter(Boolean);
        const exactApproval = exactApprovalMatches.length === 1 ? exactApprovalMatches[0] : null;
        if (exactApproval) conversation = exactApproval.conversation;
        if (!conversation && active.length === 1 && !FINISHED.has(String(state.status || "").toLowerCase())) {
          const candidate = active[0];
          const activityMs = asTime(candidate.last_used_at);
          if (!activityMs || updatedMs >= activityMs - this.associationGraceMs) conversation = candidate;
        }
        let terminalTurnStatus = null;
        if (!conversation && !FINISHED.has(String(state.status || "").toLowerCase())) {
          const terminalMatches = conversations.map((candidate) => {
            const latest = codexInteraction?.latestTurn?.(candidate.thread_id);
            if (!latest || !["interrupted", "failed"].includes(latest.status)) return null;
            if (!latest.startedAtMs || Math.abs(updatedMs - latest.startedAtMs) > this.associationGraceMs) return null;
            return { conversation: candidate, latest };
          }).filter(Boolean);
          if (terminalMatches.length === 1) {
            conversation = terminalMatches[0].conversation;
            terminalTurnStatus = terminalMatches[0].latest.status;
          }
        }
        const activeTurnId = conversation ? codexInteraction?.activeTurn(conversation.thread_id) : null;
        if (conversation && !activeTurnId && !FINISHED.has(String(state.status || "").toLowerCase())) {
          const latest = codexInteraction?.latestTurn?.(conversation.thread_id);
          if (
            latest
            && ["interrupted", "failed"].includes(latest.status)
            && latest.startedAtMs
            && Math.abs(updatedMs - latest.startedAtMs) <= this.associationGraceMs
          ) terminalTurnStatus = latest.status;
        }
        const activityMs = asTime(conversation?.last_used_at);
        const exactTurn = exactApproval
          && exactApproval.conversation.thread_id === conversation?.thread_id
          && exactApproval.turnId === activeTurnId;
        const turnId = activeTurnId && (exactTurn || !activityMs || updatedMs >= activityMs - this.associationGraceMs)
          ? activeTurnId
          : null;
        const pendingApprovals = pendingApprovalCount(
          codexInteraction,
          conversation?.thread_id,
          turnId,
          statePath,
          path.dirname(stateDir),
        );
        const started = units.some((unit) => Boolean(
          unit?.tool_started_at
          || ["running", "leased", "inprogress"].includes(String(unit?.status || "").toLowerCase()),
        ));
        const stage = stageOf({
          state,
          kind,
          completed,
          total,
          started,
          updatedAt: updatedMs,
          now,
          staleMs: this.staleMs,
          hasLiveTurn: Boolean(turnId),
          pendingApprovals,
          terminalTurnStatus,
        });
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
          pending_approval_count: pendingApprovals,
          elapsed_seconds: Math.max(0, Math.round((endMs - startMs) / 1000)),
          updated_at: new Date(updatedMs).toISOString(),
          can_stop: Boolean(turnId),
          can_open_conversation: Boolean(conversation),
          updatedMs,
          threadId: conversation?.thread_id || null,
          turnId: turnId || null,
          sourceKind: "state",
          requestStartedMs: asTime(preflight?.request_started_at),
        });
      }
    }
    return tasks;
  }
}
