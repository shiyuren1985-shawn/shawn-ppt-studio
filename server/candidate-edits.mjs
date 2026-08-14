import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { appendFile, mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

import {
  buildSingleImageEditAppServerTurn,
  buildSingleImageEditHostFinalizePlan,
  loadAndCompileSingleImageEditRequest,
  parseSingleImageEditNativeRefs,
  verifySingleImageEditNativeRefs,
} from "../integrations/single-image-edit.mjs";
import { HttpError } from "./errors.mjs";
import { SelectedImageEditParentResolver } from "./selected-image-edit-parent.mjs";

const execFileAsync = promisify(execFile);

const CONTRACT_VERSION = 1;
const RECORD_TYPES = new Set([
  "candidate_edit_created",
  "candidate_edit_confirmed",
  "candidate_edit_thread_bound",
  "candidate_edit_execution_started",
  "candidate_edit_native_refs_verified",
  "candidate_edit_execution_failed",
]);

function boundedString(value, name, maxLength = 8_000) {
  if (typeof value !== "string" || !value.trim()) {
    throw new HttpError(400, `${name} is required`, "invalid_candidate_edit");
  }
  if (value.length > maxLength || value.includes("\0")) {
    throw new HttpError(400, `${name} is invalid`, "invalid_candidate_edit");
  }
  return value.trim();
}

function threadIdOf(params) {
  return params?.threadId || params?.thread?.id || null;
}

function turnIdOf(params) {
  return params?.turnId || params?.turn?.id || null;
}

function turnStatus(turn) {
  if (typeof turn?.status === "string") return turn.status;
  if (typeof turn?.status?.type === "string") return turn.status.type;
  return null;
}

function agentText(item) {
  if (!item || item.type !== "agentMessage") return null;
  if (typeof item.text === "string" && item.text.trim()) return item.text;
  if (typeof item.content === "string" && item.content.trim()) return item.content;
  return null;
}

function lastNativeRefsText(texts) {
  for (let index = texts.length - 1; index >= 0; index -= 1) {
    try {
      parseSingleImageEditNativeRefs(texts[index]);
      return texts[index];
    } catch {
      // A production edit may emit progress before or after its final refs.
    }
  }
  return null;
}

function completedImageItems(items) {
  const completed = new Map();
  for (const item of items || []) {
    if (
      item?.type !== "imageGeneration" ||
      item.status !== "completed" ||
      typeof item.savedPath !== "string" ||
      !path.isAbsolute(item.savedPath)
    ) {
      continue;
    }
    completed.set(item.id || item.savedPath, item.savedPath);
  }
  return completed;
}

function adapterError(error) {
  if (error instanceof HttpError) return error;
  const code = error?.code || "candidate_edit_contract_error";
  const status = [
    "outline_revision_conflict",
    "parent_candidate_mismatch",
    "parent_handoff_mismatch",
  ].includes(code)
    ? 409
    : 400;
  return new HttpError(status, error?.message || "candidate edit contract failed", code);
}

async function runCanonicalCommand(spec) {
  return execFileAsync(spec.command, spec.args, {
    encoding: "utf8",
    maxBuffer: 1024 * 1024,
    timeout: 11 * 60 * 1000,
  });
}

function commandErrorCode(error) {
  for (const value of [error?.stderr, error?.stdout]) {
    if (typeof value !== "string" || !value.trim()) continue;
    for (const line of value.trim().split("\n").reverse()) {
      try {
        const parsed = JSON.parse(line);
        if (typeof parsed?.error?.code === "string") return parsed.error.code;
      } catch {
        // Ignore process noise around the canonical JSON error line.
      }
    }
  }
  return error?.code || "candidate_edit_finalize_failed";
}

function canonicalCommandFailure(error) {
  return Object.assign(new Error(error?.message || "canonical candidate edit command failed"), {
    code: commandErrorCode(error),
    cause: error,
  });
}

function editThreadParams(compiled, editId, threadId = null) {
  const common = {
    cwd: compiled.runtime.candidate_root,
    approvalPolicy: "never",
    sandbox: "workspace-write",
    ephemeral: false,
    serviceName: "shawn_ppt_studio_candidate_edit",
    developerInstructions: [
      "You are the dedicated Codex execution thread for one Shawn PPT Studio candidate edit.",
      `Edit id: ${editId}.`,
      "Use exactly one ImageGen edit call with the supplied parent localImage.",
      "Only the supplied canonical control-plane commands may create or update the edit run, state, handoff, lineage, and candidate file.",
      "Do not overwrite the parent image, authoritative outline, selection data, installed skills, existing runs, or monitoring state.",
      "Do not create another Judge, reviewer, semaphore, workflow engine, UID outline, or selection record.",
      "Return one final native refs JSON object after canonical completion.",
    ].join(" "),
  };
  return threadId ? { ...common, threadId } : common;
}

function publicCandidate(candidate) {
  return {
    candidate_id: candidate.candidate_id,
    path: candidate.path,
    sha256: candidate.sha256,
    style_slot: candidate.style_slot || null,
    page_id: candidate.page_id || null,
    deck_uid: candidate.deck_uid,
    slide_uid: candidate.slide_uid,
    parent_candidate_id: candidate.parent_candidate_id || null,
    derivation_kind: candidate.derivation_kind || "single_image_edit",
    width: candidate.width || null,
    height: candidate.height || null,
    size_bytes: candidate.size_bytes || null,
    status: candidate.status || "candidate_ready",
  };
}

export class CandidateEditService {
  constructor({
    labRoot,
    discovery,
    production,
    selectionProjection = null,
    client,
    monitoringRoot,
    commandRunner = runCanonicalCommand,
    clock = () => new Date().toISOString(),
  }) {
    this.labRoot = path.resolve(labRoot);
    this.discovery = discovery;
    this.production = production;
    this.selectedParents = new SelectedImageEditParentResolver({
      discovery,
      selectionProjection,
    });
    this.client = client;
    this.monitoringRoot = path.resolve(monitoringRoot);
    this.commandRunner = commandRunner;
    this.clock = clock;
    this.ledgerPath = path.join(this.labRoot, "runtime", "candidate-edits.jsonl");
    this.records = [];
    this.sequence = 0;
    this.ready = false;
    this.lastError = null;
    this.writeQueue = Promise.resolve();
    this.activeExecutions = new Map();
  }

  async initialize() {
    await mkdir(path.dirname(this.ledgerPath), { recursive: true });
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
        throw Object.assign(new Error(`candidate edit ledger has invalid JSON at line ${index + 1}`), {
          code: "candidate_edit_ledger_corrupt",
        });
      }
      if (
        !Number.isInteger(record.sequence) ||
        record.sequence !== records.length + 1 ||
        !RECORD_TYPES.has(record.type) ||
        typeof record.edit_id !== "string"
      ) {
        throw Object.assign(new Error(`candidate edit ledger has invalid record at line ${index + 1}`), {
          code: "candidate_edit_ledger_corrupt",
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
      edit_count: new Set(this.records.map((record) => record.edit_id)).size,
      active_count: this.activeExecutions.size,
      error: this.lastError?.message || null,
    };
  }

  stop() {
    for (const execution of this.activeExecutions.values()) execution.unsubscribe?.();
    this.activeExecutions.clear();
  }

  async #append(editId, type, fields = {}) {
    if (!this.ready) {
      throw new HttpError(503, "candidate edit service is unavailable", "candidate_edit_unavailable");
    }
    const operation = async () => {
      const record = {
        contract_version: CONTRACT_VERSION,
        sequence: this.sequence + 1,
        event_id: randomUUID(),
        occurred_at: this.clock(),
        type,
        edit_id: editId,
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

  #recordsFor(editId) {
    return this.records.filter((record) => record.edit_id === editId);
  }

  #fold(editId) {
    const records = this.#recordsFor(editId);
    const created = records.find((record) => record.type === "candidate_edit_created");
    if (!created) throw new HttpError(404, `unknown candidate edit: ${editId}`, "candidate_edit_not_found");
    const confirmed = records.findLast((record) => record.type === "candidate_edit_confirmed");
    const thread = records.findLast((record) => record.type === "candidate_edit_thread_bound");
    const started = records.findLast((record) => record.type === "candidate_edit_execution_started");
    const verified = records.findLast((record) => record.type === "candidate_edit_native_refs_verified");
    const failed = records.findLast((record) => record.type === "candidate_edit_execution_failed");
    const terminal = [verified, failed].filter(Boolean).sort((a, b) => a.sequence - b.sequence).at(-1);
    let status = "draft";
    if (confirmed) status = "approved";
    if (thread || started) status = "running";
    if (terminal?.type === "candidate_edit_native_refs_verified") status = "candidate_ready";
    if (terminal?.type === "candidate_edit_execution_failed") status = "failed";
    return {
      edit_id: editId,
      source_intent_id: created.source_intent_id,
      source_kind: created.source_kind || "production_intent",
      deck_id: created.deck_id || null,
      deck_uid: created.deck_uid || null,
      slide_uid: created.slide_uid || null,
      selected_path: created.selected_path || null,
      selected_sha256: created.selected_sha256 || null,
      selected_width: created.selected_width || null,
      selected_height: created.selected_height || null,
      source_revision_status: created.source_revision_status || "unrecorded",
      candidate_id: created.candidate_id,
      user_request: created.user_request,
      request_started_at: created.request_started_at,
      created_at: created.occurred_at,
      confirmed_at: confirmed?.occurred_at || null,
      thread_id: thread?.thread_id || null,
      turn_id: started?.turn_id || null,
      native_refs: verified?.native_refs || null,
      verified_at: verified?.occurred_at || null,
      error: terminal?.type === "candidate_edit_execution_failed" ? terminal.error : null,
      status,
    };
  }

  async #resolve(edit, { requireCurrentSelection = true } = {}) {
    if (edit.source_kind === "selected_candidate") {
      const selected = requireCurrentSelection
        ? await this.selectedParents.resolveCurrent({
            deckId: edit.deck_id,
            slideUid: edit.slide_uid,
            candidateId: edit.candidate_id,
            expectedPath: edit.selected_path,
            expectedSha256: edit.selected_sha256,
          })
        : await this.selectedParents.resolveRecorded({
            deckId: edit.deck_id,
            slideUid: edit.slide_uid,
            candidateId: edit.candidate_id,
            path: edit.selected_path,
            fileSha256: edit.selected_sha256,
            width: edit.selected_width,
            height: edit.selected_height,
            sourceRevisionStatus: edit.source_revision_status,
          });
      let compiled;
      try {
        const parentInput = selected.parent.mode === "handoff"
          ? {
              parent: {
                handoff_path: selected.parent.handoff_path,
                candidate_id: selected.parent.source_candidate_id,
              },
            }
          : { direct_parent_refs: selected.parent.direct_parent_refs };
        compiled = await loadAndCompileSingleImageEditRequest(
          {
            deck_uid: selected.source.deck_uid,
            slide_uid: selected.source.slide_uid,
            outline_path: selected.source.outline_path,
            expected_revision: selected.source.expected_revision,
            user_request: edit.user_request,
            ...parentInput,
          },
          {
            candidate_root: selected.parent.candidate_root,
            approved_candidate_roots: selected.deck.candidate_roots.map((root) => root.path),
            request_started_at: edit.request_started_at,
            monitoring_root: this.monitoringRoot,
          },
        );
      } catch (error) {
        throw adapterError(error);
      }
      if (
        compiled.parent.path !== selected.selection.path ||
        compiled.parent.sha256 !== selected.selection.file_sha256
      ) {
        throw new HttpError(409, "compiled parent does not match selection", "parent_candidate_mismatch");
      }
      return {
        source: { intent: selected.source },
        parent: {
          candidate_id: selected.selection.candidate_id,
          source_candidate_id: selected.parent.source_candidate_id,
          path: compiled.parent.path,
          sha256: compiled.parent.sha256,
          style_slot: selected.parent.style_slot,
        },
        deck: selected.deck,
        compiled,
      };
    }
    const source = await this.production.get(edit.source_intent_id);
    if (source.intent.status !== "candidate_ready" || !source.intent.native_refs) {
      throw new HttpError(409, "source production intent is not candidate_ready", "source_intent_not_ready");
    }
    const candidateSet = await this.production.candidates(edit.source_intent_id);
    const matches = candidateSet.candidates.filter((item) => item.candidate_id === edit.candidate_id);
    if (matches.length !== 1) {
      throw new HttpError(404, "parent candidate is not in the verified source handoff", "parent_candidate_not_found");
    }
    const parent = matches[0];
    const deck = await this.discovery.readDeck(source.intent.deck_id);
    let compiled;
    try {
      compiled = await loadAndCompileSingleImageEditRequest(
        {
          deck_uid: source.intent.deck_uid,
          slide_uid: source.intent.slide_uid,
          outline_path: source.intent.outline_path,
          expected_revision: source.intent.expected_revision,
          user_request: edit.user_request,
          parent: {
            handoff_path: source.intent.native_refs.handoff_path,
            candidate_id: edit.candidate_id,
          },
        },
        {
          candidate_root: deck.candidate_roots[0]?.path,
          approved_candidate_roots: deck.candidate_roots.map((root) => root.path),
          request_started_at: edit.request_started_at,
          monitoring_root: this.monitoringRoot,
        },
      );
    } catch (error) {
      throw adapterError(error);
    }
    if (compiled.parent.path !== parent.path || compiled.parent.sha256 !== parent.sha256) {
      throw new HttpError(409, "compiled parent does not match verified candidate", "parent_candidate_mismatch");
    }
    return { source, parent, deck, compiled };
  }

  #expected(resolved) {
    return resolved.compiled;
  }

  async create(body) {
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      throw new HttpError(400, "JSON body must be an object", "invalid_candidate_edit");
    }
    const allowed = new Set([
      "source_intent_id",
      "deck_id",
      "slide_uid",
      "candidate_id",
      "user_request",
    ]);
    if (Object.keys(body).some((key) => !allowed.has(key))) {
      throw new HttpError(400, "candidate edit contains unsupported fields", "invalid_candidate_edit");
    }
    const legacy = typeof body.source_intent_id === "string" && body.source_intent_id.trim();
    const selected = typeof body.deck_id === "string" || typeof body.slide_uid === "string";
    if ((legacy && selected) || (!legacy && !selected)) {
      throw new HttpError(
        400,
        "provide either source_intent_id or deck_id and slide_uid",
        "invalid_candidate_edit",
      );
    }
    const editId = `edit-${randomUUID()}`;
    let intent = {
      edit_id: editId,
      source_kind: legacy ? "production_intent" : "selected_candidate",
      source_intent_id: legacy
        ? boundedString(body.source_intent_id, "source_intent_id", 256)
        : null,
      deck_id: legacy ? null : boundedString(body.deck_id, "deck_id", 256),
      slide_uid: legacy ? null : boundedString(body.slide_uid, "slide_uid", 512),
      candidate_id: boundedString(body.candidate_id, "candidate_id", 512),
      user_request: boundedString(body.user_request, "user_request"),
      request_started_at: this.clock(),
    };
    const resolved = await this.#resolve(intent);
    if (!legacy) {
      intent = {
        ...intent,
        deck_uid: resolved.source.intent.deck_uid,
        selected_path: resolved.parent.path,
        selected_sha256: resolved.parent.sha256,
        selected_width: resolved.compiled.parent.width,
        selected_height: resolved.compiled.parent.height,
        source_revision_status: "unrecorded",
      };
    }
    await this.#append(editId, "candidate_edit_created", {
      source_kind: intent.source_kind,
      source_intent_id: intent.source_intent_id,
      deck_id: intent.deck_id,
      deck_uid: intent.deck_uid || null,
      slide_uid: intent.slide_uid,
      candidate_id: intent.candidate_id,
      selected_path: intent.selected_path || null,
      selected_sha256: intent.selected_sha256 || null,
      selected_width: intent.selected_width || null,
      selected_height: intent.selected_height || null,
      source_revision_status: intent.source_revision_status || null,
      user_request: intent.user_request,
      request_started_at: intent.request_started_at,
    });
    return this.get(editId, { reconcile: false });
  }

  async #parentProjection(edit) {
    try {
      const resolved = await this.#resolve(edit, {
        requireCurrentSelection: ["draft", "approved"].includes(edit.status),
      });
      return {
        source: resolved.source.intent,
        parent: {
          candidate_id: resolved.parent.candidate_id,
          source_candidate_id: resolved.parent.source_candidate_id || resolved.parent.candidate_id,
          path: resolved.parent.path,
          sha256: resolved.parent.sha256,
          style_slot: resolved.parent.style_slot || null,
        },
        error: null,
      };
    } catch (error) {
      return {
        source: null,
        parent: null,
        error: { code: error?.code || "parent_candidate_unavailable", message: error.message },
      };
    }
  }

  async get(editId, { reconcile = true } = {}) {
    let edit = this.#fold(editId);
    if (reconcile && edit.status === "running" && edit.thread_id && !this.activeExecutions.has(editId)) {
      await this.#reconcile(edit).catch(() => {});
      edit = this.#fold(editId);
    }
    const parent = await this.#parentProjection(edit);
    return {
      contract_version: CONTRACT_VERSION,
      edit: {
        edit_id: edit.edit_id,
        status: edit.status,
        source_intent_id: edit.source_intent_id,
        candidate_id: edit.candidate_id,
        deck_uid: parent.source?.deck_uid || edit.deck_uid || null,
        slide_uid: parent.source?.slide_uid || edit.slide_uid || null,
        user_request: edit.user_request,
        created_at: edit.created_at,
        confirmed_at: edit.confirmed_at,
        thread_id: edit.thread_id,
        turn_id: edit.turn_id,
        native_refs: edit.native_refs,
        verified_at: edit.verified_at,
        error: edit.error || parent.error,
        parent_candidate: parent.parent,
      },
    };
  }

  async execute(editId, body) {
    if (!body || body.confirmed !== true || Object.keys(body).some((key) => key !== "confirmed")) {
      throw new HttpError(400, "execute requires exactly confirmed:true", "execution_confirmation_required");
    }
    if (!this.client.ready) {
      throw new HttpError(503, "Codex App Server is not ready", "app_server_unavailable");
    }
    let edit = this.#fold(editId);
    if (["candidate_ready", "failed"].includes(edit.status)) return this.get(editId);
    let resolved;
    try {
      resolved = await this.#resolve(edit);
    } catch (error) {
      await this.#fail(editId, error);
      throw error;
    }
    if (!edit.confirmed_at) {
      await this.#append(editId, "candidate_edit_confirmed", { confirmed: true });
      edit = this.#fold(editId);
    }
    if (edit.thread_id) {
      await this.client.request(
        "thread/resume",
        editThreadParams(resolved.compiled, editId, edit.thread_id),
      );
      await this.#reconcile(edit).catch(() => {});
      edit = this.#fold(editId);
      if (["candidate_ready", "failed"].includes(edit.status) || edit.turn_id) {
        return this.get(editId, { reconcile: false });
      }
    } else {
      const result = await this.client.request("thread/start", editThreadParams(resolved.compiled, editId));
      const threadId = result?.thread?.id;
      if (!threadId) throw new Error("Codex App Server did not return a candidate edit thread id");
      await this.#append(editId, "candidate_edit_thread_bound", { thread_id: threadId });
      edit = this.#fold(editId);
    }
    await this.#startExecution(edit, resolved);
    return this.get(editId, { reconcile: false });
  }

  async #verifyAndRecord(edit, resolved, value, turnId) {
    if (this.#fold(edit.edit_id).status === "candidate_ready") return;
    const parsed = parseSingleImageEditNativeRefs(value);
    const verified = await verifySingleImageEditNativeRefs(parsed, this.#expected(resolved));
    await this.#append(edit.edit_id, "candidate_edit_native_refs_verified", {
      thread_id: edit.thread_id,
      turn_id: turnId,
      native_refs: verified.native_refs,
    });
  }

  async #fail(editId, error, turnId = null) {
    const edit = this.#fold(editId);
    if (["candidate_ready", "failed"].includes(edit.status)) return;
    await this.#append(editId, "candidate_edit_execution_failed", {
      thread_id: edit.thread_id,
      turn_id: turnId || edit.turn_id,
      error: { code: error?.code || "candidate_edit_failed", message: error.message },
    });
  }

  async #runCommand(spec) {
    try {
      return await this.commandRunner(spec);
    } catch (error) {
      throw canonicalCommandFailure(error);
    }
  }

  async #bestEffortRelease(spec) {
    try {
      await this.commandRunner(spec);
    } catch {
      // Cleanup must not replace the original canonical finalize failure.
    }
  }

  async #hostFinalize(edit, resolved, savedPath, turnId) {
    const plan = buildSingleImageEditHostFinalizePlan(resolved.compiled, {
      saved_path: savedPath,
    });
    let output;
    try {
      try {
        output = await this.#runCommand(plan.attempt_complete);
      } catch (error) {
        if (error.code !== plan.recover_only_if_error_code) throw error;
        for (const command of plan.recovery_commands) {
          output = await this.#runCommand(command);
        }
      }
      const stdout = typeof output === "string" ? output : output?.stdout;
      if (typeof stdout !== "string" || !stdout.trim()) {
        throw Object.assign(new Error("canonical complete returned no native refs"), {
          code: "invalid_native_refs",
        });
      }
      await this.#verifyAndRecord(edit, resolved, stdout, turnId);
    } catch (error) {
      await this.#bestEffortRelease(plan.release_on_failure);
      throw error;
    }
  }

  async #releaseWithoutCompletedImage(resolved) {
    await this.#bestEffortRelease({
      command: "python3",
      args: [
        resolved.compiled.runtime.control_plane_path,
        "release",
        "--state",
        resolved.compiled.runtime.state_path,
      ],
    });
  }

  async #finish(edit, resolved, turn, observedItems, turnId) {
    const items = [...observedItems, ...(Array.isArray(turn?.items) ? turn.items : [])];
    const completed = completedImageItems(items);
    if (completed.size !== 1) {
      if (completed.size === 0) await this.#releaseWithoutCompletedImage(resolved);
      throw Object.assign(new Error("candidate edit requires exactly one completed ImageGen savedPath"), {
        code: "candidate_edit_image_count_mismatch",
      });
    }
    const text = lastNativeRefsText(items.map(agentText).filter(Boolean));
    if (text) return this.#verifyAndRecord(edit, resolved, text, turnId);
    return this.#hostFinalize(edit, resolved, [...completed.values()][0], turnId);
  }

  async #startExecution(edit, resolved) {
    if (this.activeExecutions.has(edit.edit_id)) return;
    const params = buildSingleImageEditAppServerTurn(resolved.compiled, {
      thread_id: edit.thread_id,
    });
    let activeTurnId = null;
    const items = [];
    let queue = Promise.resolve();
    let settled = false;
    const finish = async (notification) => {
      if (settled) return;
      settled = true;
      unsubscribe();
      try {
        await this.#finish(edit, resolved, notification?.params?.turn, items, activeTurnId);
      } catch (error) {
        await this.#fail(edit.edit_id, error, activeTurnId);
      } finally {
        this.activeExecutions.delete(edit.edit_id);
      }
    };
    const route = async (notification) => {
      const values = notification.params || {};
      if (threadIdOf(values) && threadIdOf(values) !== edit.thread_id) return;
      const eventTurnId = turnIdOf(values);
      if (activeTurnId && eventTurnId && eventTurnId !== activeTurnId) return;
      if (notification.method === "turn/started") {
        activeTurnId = eventTurnId || activeTurnId;
      } else if (notification.method === "item/completed") {
        items.push(values.item);
      } else if (notification.method === "turn/completed") {
        await finish(notification);
      } else if (notification.method === "error") {
        throw Object.assign(new Error(values.error?.message || values.message || "Codex edit error"), {
          code: values.error?.code || values.code || "codex_error",
        });
      }
    };
    const unsubscribe = this.client.subscribe((notification) => {
      queue = queue.then(() => route(notification)).catch((error) =>
        this.#fail(edit.edit_id, error, activeTurnId).finally(() => {
          settled = true;
          unsubscribe();
          this.activeExecutions.delete(edit.edit_id);
        }),
      );
    });
    this.activeExecutions.set(edit.edit_id, { unsubscribe });
    try {
      const result = await this.client.request("turn/start", params);
      activeTurnId = result?.turn?.id || activeTurnId;
      await this.#append(edit.edit_id, "candidate_edit_execution_started", {
        thread_id: edit.thread_id,
        turn_id: activeTurnId,
      });
    } catch (error) {
      unsubscribe();
      this.activeExecutions.delete(edit.edit_id);
      await this.#fail(edit.edit_id, error, activeTurnId);
      throw error;
    }
  }

  async #reconcile(edit) {
    if (!edit.thread_id || !this.client.ready) return;
    const result = await this.client.request("thread/read", {
      threadId: edit.thread_id,
      includeTurns: true,
    });
    const turns = Array.isArray(result?.thread?.turns) ? result.thread.turns : [];
    const turn = turns.at(-1);
    if (!turn) return;
    const status = turnStatus(turn);
    if (["interrupted", "failed", "cancelled", "canceled"].includes(status)) {
      await this.#fail(
        edit.edit_id,
        Object.assign(new Error(`candidate edit Codex turn ended with status ${status}`), {
          code: `candidate_edit_turn_${status === "canceled" ? "cancelled" : status}`,
        }),
        turn.id || edit.turn_id,
      );
      return;
    }
    if (status !== "completed") return;
    try {
      const resolved = await this.#resolve(edit, { requireCurrentSelection: false });
      await this.#finish(edit, resolved, turn, [], turn.id || edit.turn_id);
    } catch (error) {
      await this.#fail(edit.edit_id, error, turn.id || edit.turn_id);
    }
  }

  async candidates(editId) {
    const edit = this.#fold(editId);
    if (!edit.native_refs) {
      return {
        contract_version: CONTRACT_VERSION,
        edit_id: editId,
        status: edit.status,
        availability: "unavailable",
        run_id: null,
        candidates: [],
      };
    }
    const resolved = await this.#resolve(edit, { requireCurrentSelection: false });
    await verifySingleImageEditNativeRefs(edit.native_refs, this.#expected(resolved));
    const handoff = JSON.parse(await readFile(edit.native_refs.handoff_path, "utf8"));
    if (!Array.isArray(handoff.candidates) || handoff.candidates.length !== 1) {
      throw new HttpError(409, "single image edit handoff must contain one candidate", "edit_handoff_mismatch");
    }
    return {
      contract_version: CONTRACT_VERSION,
      edit_id: editId,
      status: "candidate_ready",
      availability: "verified_handoff",
      run_id: edit.native_refs.run_id,
      candidates: handoff.candidates.map(publicCandidate),
    };
  }
}
