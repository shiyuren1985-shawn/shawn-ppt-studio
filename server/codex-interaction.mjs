function threadIdOf(params) {
  return params?.threadId || params?.thread?.id || null;
}

function turnIdOf(params) {
  return params?.turnId || params?.turn?.id || null;
}

function epochMilliseconds(value, fallback = null) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return fallback;
  return numeric < 1_000_000_000_000 ? numeric * 1000 : numeric;
}

function browserSafeParams(method, params) {
  if (!["item/started", "item/completed"].includes(method)) return params;
  if (params?.item?.type !== "imageGeneration") return params;
  const item = params.item;
  return {
    ...params,
    item: {
      id: item.id || null,
      type: "imageGeneration",
      status: item.status || null,
      savedPath: item.savedPath || null,
      revisedPrompt: item.revisedPrompt || null,
    },
  };
}

function approvalChoices(request) {
  const params = request?.params || {};
  if (request?.method === "item/permissions/requestApproval") {
    return [
      { decision: "grantForTurn", label: "本轮允许" },
      { decision: "grantForSession", label: "本次对话允许" },
      { decision: "decline", label: "拒绝" },
    ];
  }
  const available = Array.isArray(params.availableDecisions) && params.availableDecisions.length
    ? params.availableDecisions
    : ["accept", "acceptForSession", "decline", "cancel"];
  const labels = {
    accept: "允许",
    acceptForSession: "本次对话允许",
    decline: "拒绝",
    cancel: "取消",
  };
  return available.map((decision) => ({
    decision,
    label: typeof decision === "string" ? labels[decision] || decision : "按建议允许",
  }));
}

export function publicApprovalRequest(request) {
  const method = request?.method || "";
  if (![
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
  ].includes(method)) return null;
  const params = request.params || {};
  return {
    contract_version: 1,
    method,
    request_id: String(request.requestId ?? request.id),
    thread_id: params.threadId || null,
    turn_id: params.turnId || null,
    item_id: params.itemId || null,
    params,
    choices: approvalChoices(request),
  };
}

function sameDecision(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function approvalIdentity(record) {
  return JSON.stringify([
    record?.thread_id || null,
    record?.turn_id || null,
    record?.request_id || null,
    record?.item_id || null,
    record?.method || null,
  ]);
}

export function approvalResult(request, decision) {
  const method = request?.method || "";
  if (method === "item/permissions/requestApproval") {
    if (!["grantForTurn", "grantForSession", "decline", "allow"].includes(decision)) {
      throw Object.assign(new Error("decision is not available for this permission request"), {
        code: "invalid_approval_decision",
      });
    }
    const permissions = decision === "decline" ? {} : request.params?.permissions || {};
    return {
      permissions,
      scope: decision === "grantForSession" ? "session" : "turn",
    };
  }

  const normalized = decision === "allow" ? "accept" : decision;
  const choices = approvalChoices(request).map((choice) => choice.decision);
  if (!choices.some((choice) => sameDecision(choice, normalized))) {
    throw Object.assign(new Error("decision is not available for this approval request"), {
      code: "invalid_approval_decision",
    });
  }
  return { decision: normalized };
}

/**
 * A transport relay, not a second task state machine. It forwards App Server
 * notifications verbatim, keeps a short reconnect buffer, and remembers only
 * the currently active turn id for routing turn/steer and turn/interrupt.
 */
export class CodexInteractionRelay {
  constructor({ client, maxEventsPerTurn = 5000, turnObserver = null }) {
    this.client = client;
    this.maxEventsPerTurn = maxEventsPerTurn;
    this.nextSequence = 1;
    this.activeByThread = new Map();
    this.latestByThread = new Map();
    this.startingThreads = new Set();
    this.eventsByTurn = new Map();
    this.listeners = new Set();
    this.turnObserver = turnObserver;
    this.unsubscribe = client.subscribe((notification) => this.#notification(notification));
    this.unsubscribeRequests = client.subscribeServerRequests((request) => this.#serverRequest(request));
    this.onRequestResolved = ({ request, reason }) => this.resolveApproval(request, null, reason);
    this.onClientError = (error) => this.#disconnect(error);
    client.on?.("serverRequestResolved", this.onRequestResolved);
    client.on?.("appServerError", this.onClientError);
  }

  close() {
    this.unsubscribe?.();
    this.unsubscribeRequests?.();
    this.client.off?.("serverRequestResolved", this.onRequestResolved);
    this.client.off?.("appServerError", this.onClientError);
    this.listeners.clear();
  }

  activeTurn(threadId) {
    return this.activeByThread.get(threadId) || null;
  }

  activeEntries() {
    return [...this.activeByThread.entries()].map(([threadId, turnId]) => ({ threadId, turnId }));
  }

  latestTurn(threadId) {
    return this.latestByThread.get(threadId) || null;
  }

  observeThreadSnapshot(thread) {
    const threadId = thread?.id || thread?.threadId || null;
    const turns = Array.isArray(thread?.turns) ? thread.turns : [];
    const latest = turns.at(-1);
    const turnId = latest?.id || latest?.turnId || null;
    if (!threadId || !turnId) return null;
    // A read/resume response may arrive after newer streamed notifications.
    // Never revive a turn whose terminal event we already observed, or replace
    // a different live turn with an older snapshot.
    const activeTurnId = this.activeByThread.get(threadId);
    if (this.isStreamFinished(threadId, turnId) || (activeTurnId && activeTurnId !== turnId)) {
      return this.latestByThread.get(threadId) || null;
    }
    const status = latest.status || "completed";
    const snapshot = {
      turnId,
      status,
      startedAtMs: epochMilliseconds(latest.startedAt || latest.startedAtMs),
      completedAtMs: epochMilliseconds(latest.completedAt || latest.completedAtMs),
    };
    this.latestByThread.set(threadId, snapshot);
    if (status === "inProgress") this.activeByThread.set(threadId, turnId);
    else if (this.activeByThread.get(threadId) === turnId) this.activeByThread.delete(threadId);
    return snapshot;
  }

  markStarting(threadId) {
    if (this.startingThreads.has(threadId) || this.activeByThread.has(threadId)) return false;
    this.startingThreads.add(threadId);
    return true;
  }

  clearStarting(threadId) {
    this.startingThreads.delete(threadId);
  }

  isBusy(threadId) {
    return this.startingThreads.has(threadId) || this.activeByThread.has(threadId);
  }

  records(threadId, turnId, after = 0) {
    const key = `${threadId}\u0000${turnId}`;
    const records = this.eventsByTurn.get(key);
    if (!records) return null;
    const resolvedApprovalIdentities = new Set(
      records
        .filter((record) => record.event === "approval_resolution" && record.resolved === true)
        .map(approvalIdentity),
    );
    return records.filter((record) => (
      record.sequence > after &&
      !(record.event === "approval" && resolvedApprovalIdentities.has(approvalIdentity(record)))
    ));
  }

  isStreamFinished(threadId, turnId) {
    return (this.eventsByTurn.get(`${threadId}\u0000${turnId}`) || []).some(
      (record) => record.method === "turn/completed" || record.terminal === true,
    );
  }

  resolveApproval(request, decision, reason = null) {
    const approval = publicApprovalRequest(request);
    if (!approval?.thread_id || !approval.turn_id) return null;
    const record = {
      event: "approval_resolution",
      contract_version: 1,
      sequence: this.nextSequence++,
      thread_id: approval.thread_id,
      turn_id: approval.turn_id,
      item_id: approval.item_id,
      request_id: approval.request_id,
      method: approval.method,
      resolved: true,
      decision,
      ...(reason ? { reason } : {}),
    };
    this.#publish(record);
    return record;
  }

  #disconnect(error) {
    const active = this.activeEntries();
    this.activeByThread.clear();
    // Preparing HTTP requests still own their starting guard. They release it
    // when their pending work detects the failed/replaced transport.
    for (const { threadId, turnId } of active) {
      this.latestByThread.set(threadId, {
        ...this.latestByThread.get(threadId), status: "unknown",
      });
      this.#publish({
        event: "error",
        contract_version: 1,
        sequence: this.nextSequence++,
        thread_id: threadId,
        turn_id: turnId,
        terminal: true,
        code: error?.code || "app_server_unavailable",
        message: "Codex 连接已断开，本轮结果尚未确认。可以重新打开对话检查后继续。",
      });
    }
  }

  subscribe({ threadId, turnId = null, listener }) {
    const entry = { threadId, turnId, listener };
    this.listeners.add(entry);
    return () => this.listeners.delete(entry);
  }

  #publish(record) {
    const key = `${record.thread_id}\u0000${record.turn_id}`;
    const events = this.eventsByTurn.get(key) || [];
    events.push(record);
    if (events.length > this.maxEventsPerTurn) events.splice(0, events.length - this.maxEventsPerTurn);
    this.eventsByTurn.set(key, events);
    for (const subscriber of this.listeners) {
      if (subscriber.threadId !== record.thread_id) continue;
      if (subscriber.turnId && subscriber.turnId !== record.turn_id) continue;
      subscriber.listener(record);
    }
  }

  #notification(notification) {
    this.turnObserver?.observeNotification?.(notification);
    const rawParams = notification?.params || {};
    const params = browserSafeParams(notification.method, rawParams);
    const threadId = threadIdOf(params);
    const turnId = turnIdOf(params);
    if (!threadId || !turnId) return;
    if (notification.method === "turn/started") {
      this.startingThreads.delete(threadId);
      this.activeByThread.set(threadId, turnId);
      this.latestByThread.set(threadId, {
        turnId,
        status: params?.turn?.status || "inProgress",
        startedAtMs: epochMilliseconds(params?.turn?.startedAt || params?.startedAtMs, Date.now()),
        completedAtMs: null,
      });
    }
    const record = {
      event: "codex",
      contract_version: 1,
      sequence: this.nextSequence++,
      thread_id: threadId,
      turn_id: turnId,
      method: notification.method,
      params,
    };
    this.#publish(record);
    if (notification.method === "turn/completed") {
      this.startingThreads.delete(threadId);
      if (this.activeByThread.get(threadId) === turnId) this.activeByThread.delete(threadId);
      const prior = this.latestByThread.get(threadId);
      this.latestByThread.set(threadId, {
        turnId,
        status: params?.turn?.status || params?.status || "completed",
        startedAtMs: prior?.turnId === turnId ? prior.startedAtMs : null,
        completedAtMs: epochMilliseconds(params?.turn?.completedAt || params?.completedAtMs, Date.now()),
      });
    }
  }

  #serverRequest(request) {
    this.turnObserver?.observeApproval?.(request);
    const approval = publicApprovalRequest(request);
    if (!approval) {
      this.client.rejectServerRequest?.(request.requestId ?? request.id, {
        code: -32601,
        message: "Shawn PPT Studio does not support this interactive request. Ask the user in a normal text reply and wait for their response instead.",
      });
      const threadId = threadIdOf(request.params);
      const turnId = turnIdOf(request.params);
      if (threadId && turnId) this.#publish({
        event: "error", contract_version: 1, sequence: this.nextSequence++,
        thread_id: threadId, turn_id: turnId,
        code: "unsupported_interactive_request",
        message: "这项交互暂不支持，AI 可改用普通消息向你提问。",
      });
      return;
    }
    if (!approval.thread_id || !approval.turn_id) return;
    this.#publish({
      event: "approval",
      sequence: this.nextSequence++,
      ...approval,
    });
  }
}
