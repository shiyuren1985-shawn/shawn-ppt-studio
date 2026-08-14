import { createHash, randomUUID } from "node:crypto";
import { appendFile, mkdir, readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";

import {
  buildAppServerTurn,
  compileSinglePageRequest,
  parseNativeRefs,
  verifyNativeRefs,
} from "../integrations/shawn-single-page.mjs";
import { HttpError } from "./errors.mjs";

const CONTRACT_VERSION = 1;
const LEDGER_TYPES = new Set([
  "production_intent_created",
  "production_intent_confirmed",
  "production_thread_bound",
  "production_execution_started",
  "production_native_refs_verified",
  "production_execution_failed",
]);

function boundedString(value, name, maxLength = 8_000) {
  if (typeof value !== "string" || !value.trim()) {
    throw new HttpError(400, `${name} is required`, "invalid_production_intent");
  }
  if (value.length > maxLength || value.includes("\0")) {
    throw new HttpError(400, `${name} is invalid`, "invalid_production_intent");
  }
  return value.trim();
}

function integrationHttpError(error) {
  if (error instanceof HttpError) return error;
  const code = error?.code || "production_contract_error";
  const status = code === "outline_revision_conflict" ? 409 : 400;
  return new HttpError(status, error?.message || "production contract failed", code);
}

function threadIdOf(params) {
  return params?.threadId || params?.thread?.id || null;
}

function turnIdOf(params) {
  return params?.turnId || params?.turn?.id || null;
}

function productionThreadStartParams(labRoot, intentId) {
  return {
    cwd: labRoot,
    approvalPolicy: "never",
    sandbox: "workspace-write",
    ephemeral: false,
    serviceName: "shawn_ppt_studio_production",
    developerInstructions: [
      "You are the dedicated Codex execution thread for one Shawn PPT Studio production intent.",
      `Intent id: ${intentId}.`,
      "Read the authoritative outline and the explicitly supplied Shawn-PPT-image skill as required by the turn.",
      "Only the canonical Shawn scripts and their bounded Directors may create or modify files below the approved run root or existing monitoring root.",
      "Never overwrite the authoritative outline, selection data, the installed skill, existing run directories, or existing run state.",
      "Do not create another Judge, reviewer, semaphore, state machine, UID outline, or selection record.",
      "Return one final native refs JSON object after the canonical handoff is ready.",
    ].join(" "),
  };
}

function productionThreadResumeParams(labRoot, threadId, intentId) {
  return {
    ...productionThreadStartParams(labRoot, intentId),
    threadId,
  };
}

function agentTextFromItem(item) {
  if (!item || item.type !== "agentMessage") return null;
  if (typeof item.text === "string" && item.text.trim()) return item.text;
  if (typeof item.content === "string" && item.content.trim()) return item.content;
  return null;
}

function lastNativeRefsText(texts) {
  for (let textIndex = texts.length - 1; textIndex >= 0; textIndex -= 1) {
    const text = texts[textIndex];
    try {
      parseNativeRefs(text);
      return text;
    } catch {
      // Progress and summary messages are valid production chatter, but they
      // are not the canonical native-refs result.
    }
  }
  return null;
}

function lastNativeRefsInTurn(turn) {
  const items = Array.isArray(turn?.items) ? turn.items : [];
  const text = lastNativeRefsText(items.map(agentTextFromItem).filter(Boolean));
  return text ? { text, turn_id: turn?.id || null } : null;
}

function turnStatus(turn) {
  if (typeof turn?.status === "string") return turn.status;
  if (typeof turn?.status?.type === "string") return turn.status.type;
  return null;
}

function expectedFromIntent(intent) {
  return {
    approved_run_root: intent.compiled.runtime.run_root,
    outline_path: intent.outline_path,
    expected_revision: intent.expected_revision,
    deck_uid: intent.deck_uid,
    slide_uid: intent.slide_uid,
    page_id: intent.page_id,
  };
}

function relativeWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return (
    relative === "" ||
    (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative))
  );
}

async function verifiedCandidate(candidate, intent) {
  if (
    !candidate ||
    typeof candidate !== "object" ||
    typeof candidate.candidate_id !== "string" ||
    !candidate.candidate_id ||
    typeof candidate.style_slot !== "string" ||
    !/^[A-H]$/.test(candidate.style_slot) ||
    typeof candidate.path !== "string" ||
    !path.isAbsolute(candidate.path) ||
    typeof candidate.sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(candidate.sha256)
  ) {
    throw new HttpError(409, "canonical handoff candidate metadata is invalid", "candidate_mismatch");
  }
  const [projectReal, candidateReal, info, bytes] = await Promise.all([
    realpath(intent.native_refs.project_dir),
    realpath(candidate.path),
    stat(candidate.path),
    readFile(candidate.path),
  ]).catch((error) => {
    throw new HttpError(409, `canonical candidate is unavailable: ${error.message}`, "candidate_mismatch");
  });
  if (
    candidateReal !== candidate.path ||
    !info.isFile() ||
    !relativeWithin(projectReal, candidateReal) ||
    candidateReal === projectReal ||
    createHash("sha256").update(bytes).digest("hex") !== candidate.sha256
  ) {
    throw new HttpError(409, "canonical candidate path or hash is invalid", "candidate_mismatch");
  }
  return {
    candidate_id: candidate.candidate_id,
    style_slot: candidate.style_slot,
    page_id: candidate.page_id,
    deck_uid: candidate.deck_uid,
    slide_uid: candidate.slide_uid,
    path: candidate.path,
    sha256: candidate.sha256,
    width: candidate.width || null,
    height: candidate.height || null,
    size_bytes: candidate.size_bytes || info.size,
    status: candidate.status || "candidate_ready",
  };
}

function eventPublic(record) {
  const { contract_version: _contractVersion, intent_id: _intentId, ...rest } = record;
  return rest;
}

export class ProductionIntentService {
  constructor({
    labRoot,
    discovery,
    client,
    runRoot,
    monitoringRoot,
    overviewPython,
    clock = () => new Date().toISOString(),
  }) {
    this.labRoot = path.resolve(labRoot);
    this.discovery = discovery;
    this.client = client;
    this.runRoot = path.resolve(runRoot);
    this.monitoringRoot = path.resolve(monitoringRoot);
    this.overviewPython = path.resolve(overviewPython);
    this.clock = clock;
    this.ledgerPath = path.join(this.labRoot, "runtime", "production-intents.jsonl");
    this.records = [];
    this.sequence = 0;
    this.ready = false;
    this.lastError = null;
    this.writeQueue = Promise.resolve();
    this.activeExecutions = new Map();
  }

  async initialize() {
    await mkdir(path.dirname(this.ledgerPath), { recursive: true });
    await mkdir(this.runRoot, { recursive: true });
    let text = "";
    try {
      text = await readFile(this.ledgerPath, "utf8");
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
    const records = [];
    for (const [index, line] of text.split("\n").entries()) {
      if (!line.trim()) continue;
      let record;
      try {
        record = JSON.parse(line);
      } catch {
        throw Object.assign(new Error(`production intent ledger has invalid JSON at line ${index + 1}`), {
          code: "production_ledger_corrupt",
        });
      }
      if (
        !Number.isInteger(record.sequence) ||
        record.sequence !== records.length + 1 ||
        !LEDGER_TYPES.has(record.type) ||
        typeof record.intent_id !== "string"
      ) {
        throw Object.assign(new Error(`production intent ledger has invalid record at line ${index + 1}`), {
          code: "production_ledger_corrupt",
        });
      }
      records.push(record);
    }
    this.records = records;
    this.sequence = records.length;
    this.ready = true;
    this.lastError = null;
  }

  health() {
    return {
      ready: this.ready,
      record_count: this.records.length,
      intent_count: new Set(this.records.map((record) => record.intent_id)).size,
      active_count: this.activeExecutions.size,
      error: this.lastError?.message || null,
    };
  }

  stop() {
    for (const execution of this.activeExecutions.values()) execution.unsubscribe?.();
    this.activeExecutions.clear();
  }

  async #append(intentId, type, fields = {}) {
    if (!this.ready) {
      throw new HttpError(503, "production intent service is unavailable", "production_unavailable");
    }
    const operation = async () => {
      const record = {
        contract_version: CONTRACT_VERSION,
        sequence: this.sequence + 1,
        event_id: randomUUID(),
        occurred_at: this.clock(),
        type,
        intent_id: intentId,
        ...fields,
      };
      await appendFile(this.ledgerPath, `${JSON.stringify(record)}\n`, {
        encoding: "utf8",
        mode: 0o600,
      });
      this.sequence = record.sequence;
      this.records.push(record);
      return record;
    };
    const result = this.writeQueue.then(operation);
    this.writeQueue = result.catch((error) => {
      this.ready = false;
      this.lastError = error;
    });
    return result;
  }

  #recordsFor(intentId) {
    return this.records.filter((record) => record.intent_id === intentId);
  }

  #fold(intentId) {
    const records = this.#recordsFor(intentId);
    const created = records.find((record) => record.type === "production_intent_created");
    if (!created) throw new HttpError(404, `unknown production intent: ${intentId}`, "intent_not_found");
    const confirmed = records.findLast((record) => record.type === "production_intent_confirmed");
    const thread = records.findLast((record) => record.type === "production_thread_bound");
    const started = records.findLast((record) => record.type === "production_execution_started");
    const verified = records.findLast((record) => record.type === "production_native_refs_verified");
    const failed = records.findLast((record) => record.type === "production_execution_failed");
    const terminal = [verified, failed].filter(Boolean).sort((a, b) => a.sequence - b.sequence).at(-1);
    let status = "draft";
    if (confirmed) status = "approved";
    if (thread || started) status = "running";
    if (terminal?.type === "production_native_refs_verified") status = "candidate_ready";
    if (terminal?.type === "production_execution_failed") status = "failed";
    return {
      intent_id: intentId,
      deck_id: created.deck_id,
      deck_uid: created.deck_uid,
      slide_uid: created.slide_uid,
      page_id: created.page_id,
      outline_path: created.outline_path,
      expected_revision: created.expected_revision,
      user_request: created.user_request,
      request_started_at: created.request_started_at,
      compiled: created.compiled,
      created_at: created.occurred_at,
      confirmed_at: confirmed?.occurred_at || null,
      thread_id: thread?.thread_id || null,
      turn_id: started?.turn_id || null,
      native_refs: verified?.native_refs || null,
      verified_at: verified?.occurred_at || null,
      error: terminal?.type === "production_execution_failed" ? terminal.error : null,
      status,
      records,
    };
  }

  async create(body) {
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      throw new HttpError(400, "JSON body must be an object", "invalid_production_intent");
    }
    const allowed = new Set(["deck_id", "slide_uid", "user_request"]);
    if (Object.keys(body).some((key) => !allowed.has(key))) {
      throw new HttpError(400, "production intent contains unsupported fields", "invalid_production_intent");
    }
    const deckId = boundedString(body.deck_id, "deck_id", 128);
    const slideUid = boundedString(body.slide_uid, "slide_uid", 256);
    const userRequest = boundedString(body.user_request, "user_request", 8_000);
    const deck = await this.discovery.readDeck(deckId);
    const slide = deck.outline.slides.find((candidate) => candidate.slide_uid === slideUid);
    if (!slide) {
      throw new HttpError(404, `unknown slide_uid for ${deckId}: ${slideUid}`, "slide_not_found");
    }
    const requestStartedAt = this.clock();
    const deckRunRoots = (deck.candidate_roots || []).map((root) => root.path);
    const approvedRunRoot = deckRunRoots[0] || this.runRoot;
    const approvedRunRoots = deckRunRoots.length ? deckRunRoots : [this.runRoot];
    let compiled;
    try {
      compiled = compileSinglePageRequest(
        {
          deck_uid: deck.outline.deck_uid,
          slide_uid: slideUid,
          outline_path: deck.outline.path,
          expected_revision: deck.outline.revision_id,
          user_request: userRequest,
        },
        {
          outline_markdown: deck.outline.text,
          outline_sha256: deck.outline.sha256,
          request_started_at: requestStartedAt,
          lab_root: this.labRoot,
          approved_run_root: approvedRunRoot,
          approved_run_roots: approvedRunRoots,
          monitoring_root: this.monitoringRoot,
          overview_python: this.overviewPython,
        },
      );
    } catch (error) {
      throw integrationHttpError(error);
    }
    const intentId = `intent-${randomUUID()}`;
    await this.#append(intentId, "production_intent_created", {
      deck_id: deckId,
      deck_uid: deck.outline.deck_uid,
      slide_uid: slideUid,
      page_id: compiled.identity.page_id,
      outline_path: deck.outline.path,
      expected_revision: deck.outline.revision_id,
      user_request: userRequest,
      request_started_at: requestStartedAt,
      compiled,
    });
    return this.get(intentId, { reconcile: false });
  }

  async #nativeProjection(intent) {
    if (!intent.native_refs) return { status: intent.status, native_error: null };
    try {
      await verifyNativeRefs(intent.native_refs, expectedFromIntent(intent));
      return { status: "candidate_ready", native_error: null };
    } catch (error) {
      return {
        status: "failed",
        native_error: { code: error?.code || "native_projection_failed", message: error.message },
      };
    }
  }

  async get(intentId, { reconcile = true } = {}) {
    let intent = this.#fold(intentId);
    if (
      reconcile &&
      intent.status === "running" &&
      intent.thread_id &&
      !this.activeExecutions.has(intentId)
    ) {
      await this.#reconcileThread(intent).catch(() => {});
      intent = this.#fold(intentId);
    }
    const nativeProjection = await this.#nativeProjection(intent);
    return {
      contract_version: CONTRACT_VERSION,
      intent: {
        intent_id: intent.intent_id,
        status: nativeProjection.status,
        deck_id: intent.deck_id,
        deck_uid: intent.deck_uid,
        slide_uid: intent.slide_uid,
        page_id: intent.page_id,
        outline_path: intent.outline_path,
        expected_revision: intent.expected_revision,
        approved_run_root: intent.compiled.runtime.run_root,
        user_request: intent.user_request,
        request_started_at: intent.request_started_at,
        created_at: intent.created_at,
        confirmed_at: intent.confirmed_at,
        thread_id: intent.thread_id,
        turn_id: intent.turn_id,
        native_refs: intent.native_refs,
        verified_at: intent.verified_at,
        error: intent.error || nativeProjection.native_error,
      },
    };
  }

  async #assertCurrentRevision(intent) {
    const deck = await this.discovery.readDeck(intent.deck_id);
    if (
      deck.outline.revision_id !== intent.expected_revision ||
      deck.outline.deck_uid !== intent.deck_uid ||
      !deck.outline.slides.some((slide) => slide.slide_uid === intent.slide_uid)
    ) {
      throw new HttpError(
        409,
        "authoritative outline changed after intent creation",
        "outline_revision_conflict",
      );
    }
    const configuredRunRoot = deck.candidate_roots?.[0]?.path || this.runRoot;
    if (configuredRunRoot !== intent.compiled.runtime.run_root) {
      throw new HttpError(
        409,
        "registered candidate root changed after intent creation",
        "candidate_root_changed",
      );
    }
  }

  async execute(intentId, body) {
    if (!body || body.confirmed !== true || Object.keys(body).some((key) => key !== "confirmed")) {
      throw new HttpError(
        400,
        "execute requires exactly confirmed:true",
        "execution_confirmation_required",
      );
    }
    if (!this.client.ready) {
      throw new HttpError(503, "Codex App Server is not ready", "app_server_unavailable");
    }
    let intent = this.#fold(intentId);
    if (intent.status === "candidate_ready" || intent.status === "failed") return this.get(intentId);
    if (!intent.confirmed_at) {
      await this.#append(intentId, "production_intent_confirmed", { confirmed: true });
      intent = this.#fold(intentId);
    }
    try {
      await this.#assertCurrentRevision(intent);
    } catch (error) {
      await this.#fail(intentId, error);
      throw error;
    }

    if (intent.thread_id) {
      await this.client.request(
        "thread/resume",
        productionThreadResumeParams(this.labRoot, intent.thread_id, intentId),
      );
      await this.#reconcileThread(intent).catch(() => {});
      intent = this.#fold(intentId);
      if (intent.status === "candidate_ready" || intent.status === "failed" || intent.turn_id) {
        return this.get(intentId, { reconcile: false });
      }
    } else {
      const result = await this.client.request(
        "thread/start",
        productionThreadStartParams(this.labRoot, intentId),
      );
      const threadId = result?.thread?.id;
      if (!threadId) throw new Error("Codex App Server did not return a production thread id");
      await this.#append(intentId, "production_thread_bound", { thread_id: threadId });
      intent = this.#fold(intentId);
    }

    await this.#startExecution(intent);
    return this.get(intentId, { reconcile: false });
  }

  async #verifyAndRecord(intent, value, turnId = null) {
    if (this.#fold(intent.intent_id).status === "candidate_ready") return;
    const parsed = parseNativeRefs(value);
    const verified = await verifyNativeRefs(parsed, expectedFromIntent(intent));
    await this.#append(intent.intent_id, "production_native_refs_verified", {
      thread_id: intent.thread_id,
      turn_id: turnId,
      native_refs: verified.native_refs,
    });
  }

  async #fail(intentId, error, turnId = null) {
    const current = this.#fold(intentId);
    if (current.status === "candidate_ready" || current.status === "failed") return;
    await this.#append(intentId, "production_execution_failed", {
      thread_id: current.thread_id,
      turn_id: turnId || current.turn_id,
      error: { code: error?.code || "production_execution_failed", message: error.message },
    });
  }

  async #startExecution(intent) {
    if (this.activeExecutions.has(intent.intent_id)) return;
    const params = buildAppServerTurn(intent.compiled, { thread_id: intent.thread_id });
    let activeTurnId = null;
    const agentTexts = [];
    let notificationQueue = Promise.resolve();
    let settled = false;

    const finish = async (notification) => {
      if (settled) return;
      settled = true;
      unsubscribe();
      try {
        const completedTurn = notification?.params?.turn;
        const completedTexts = Array.isArray(completedTurn?.items)
          ? completedTurn.items.map(agentTextFromItem).filter(Boolean)
          : [];
        const finalText = lastNativeRefsText([...agentTexts, ...completedTexts]);
        if (!finalText) {
          throw Object.assign(new Error("production turn returned no valid native refs"), {
            code: "invalid_native_refs",
          });
        }
        await this.#verifyAndRecord(intent, finalText, activeTurnId);
      } catch (error) {
        await this.#fail(intent.intent_id, error, activeTurnId);
      } finally {
        this.activeExecutions.delete(intent.intent_id);
      }
    };

    const route = async (notification) => {
      const values = notification.params || {};
      if (threadIdOf(values) && threadIdOf(values) !== intent.thread_id) return;
      const eventTurnId = turnIdOf(values);
      if (activeTurnId && eventTurnId && eventTurnId !== activeTurnId) return;
      if (notification.method === "turn/started") {
        activeTurnId = eventTurnId || activeTurnId;
        return;
      }
      if (notification.method === "item/completed") {
        const text = agentTextFromItem(values.item);
        if (text) agentTexts.push(text);
        return;
      }
      if (notification.method === "turn/completed") {
        await finish(notification);
        return;
      }
      if (notification.method === "error") {
        throw Object.assign(
          new Error(values.error?.message || values.message || "Codex production error"),
          { code: values.error?.code || values.code || "codex_error" },
        );
      }
    };

    const unsubscribe = this.client.subscribe((notification) => {
      notificationQueue = notificationQueue.then(() => route(notification)).catch((error) => {
        return this.#fail(intent.intent_id, error, activeTurnId).finally(() => {
          settled = true;
          unsubscribe();
          this.activeExecutions.delete(intent.intent_id);
        });
      });
    });
    this.activeExecutions.set(intent.intent_id, { unsubscribe });
    try {
      const result = await this.client.request("turn/start", params);
      activeTurnId = result?.turn?.id || activeTurnId;
      await this.#append(intent.intent_id, "production_execution_started", {
        thread_id: intent.thread_id,
        turn_id: activeTurnId,
      });
    } catch (error) {
      unsubscribe();
      this.activeExecutions.delete(intent.intent_id);
      await this.#fail(intent.intent_id, error, activeTurnId);
      throw error;
    }
  }

  async #reconcileThread(intent) {
    if (!intent.thread_id || !this.client.ready) return;
    const result = await this.client.request("thread/read", {
      threadId: intent.thread_id,
      includeTurns: true,
    });
    const turns = Array.isArray(result?.thread?.turns) ? result.thread.turns : [];
    const lastTurn = turns.at(-1);
    if (!lastTurn) return;
    const status = turnStatus(lastTurn);
    if (["interrupted", "failed", "cancelled", "canceled"].includes(status)) {
      await this.#fail(
        intent.intent_id,
        Object.assign(new Error(`production Codex turn ended with status ${status}`), {
          code: `production_turn_${status === "canceled" ? "cancelled" : status}`,
        }),
        lastTurn.id || intent.turn_id,
      );
      return;
    }
    if (status !== "completed") return;
    const final = lastNativeRefsInTurn(lastTurn);
    if (!final) {
      await this.#fail(
        intent.intent_id,
        Object.assign(new Error("completed production turn returned no native refs"), {
          code: "invalid_native_refs",
        }),
        lastTurn.id || intent.turn_id,
      );
      return;
    }
    try {
      await this.#verifyAndRecord(intent, final.text, final.turn_id);
    } catch (error) {
      await this.#fail(intent.intent_id, error, final.turn_id);
    }
  }

  events(intentId, after = 0) {
    this.#fold(intentId);
    const cursor = Number.isInteger(after) && after >= 0 ? after : 0;
    const events = this.#recordsFor(intentId)
      .filter((record) => record.sequence > cursor)
      .map(eventPublic);
    return {
      contract_version: CONTRACT_VERSION,
      intent_id: intentId,
      after: cursor,
      events,
      next_cursor: events.at(-1)?.sequence || cursor,
    };
  }

  async candidates(intentId) {
    const intent = this.#fold(intentId);
    if (!intent.native_refs) {
      return {
        contract_version: CONTRACT_VERSION,
        intent_id: intentId,
        status: intent.status,
        availability: "unavailable",
        candidates: [],
      };
    }
    await verifyNativeRefs(intent.native_refs, expectedFromIntent(intent));
    const handoff = JSON.parse(await readFile(intent.native_refs.handoff_path, "utf8"));
    const candidates = await Promise.all(
      handoff.candidates.map((candidate) => verifiedCandidate(candidate, intent)),
    );
    return {
      contract_version: CONTRACT_VERSION,
      intent_id: intentId,
      status: "candidate_ready",
      availability: "verified_handoff",
      run_id: intent.native_refs.run_id,
      candidates,
    };
  }
}
