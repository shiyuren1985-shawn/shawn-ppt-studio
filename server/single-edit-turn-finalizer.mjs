import { execFile } from "node:child_process";
import { readFile, realpath } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { promisify } from "node:util";

import {
  buildSingleImageEditHostFinalizePlan,
  SINGLE_IMAGE_EDIT_CONTRACT_VERSION,
  SINGLE_IMAGE_EDIT_CONTROL_PLANE,
  SINGLE_IMAGE_EDIT_RUN_MODE,
} from "../integrations/single-image-edit.mjs";
import { STUDIO_APP_SERVER_TRANSPORT } from "../integrations/shawn-single-page.mjs";

const execFileAsync = promisify(execFile);
export { STUDIO_APP_SERVER_TRANSPORT };

function threadIdOf(params) {
  return params?.threadId || params?.thread?.id || null;
}

function turnIdOf(params) {
  return params?.turnId || params?.turn?.id || null;
}

function commandValue(value) {
  if (typeof value === "string") return value;
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return value.join(" ");
  }
  return "";
}

function unquote(value) {
  if (value.startsWith("'") && value.endsWith("'")) return value.slice(1, -1);
  if (value.startsWith('"') && value.endsWith('"')) return value.slice(1, -1).replace(/\\(["\\$`])/g, "$1");
  return value.replace(/\\([\\\s])/g, "$1");
}

export function canonicalSingleEditStatePath(value) {
  const command = commandValue(value);
  if (!command.includes(SINGLE_IMAGE_EDIT_CONTROL_PLANE)) return null;
  const match = command.match(/(?:^|\s)--state(?:=|\s+)("(?:[^"\\]|\\.)*"|'[^']*'|(?:\\.|[^\s])+)/);
  if (!match) return null;
  const statePath = unquote(match[1]);
  if (!path.isAbsolute(statePath) || path.basename(statePath) !== "single_image_edit_state.json") {
    return null;
  }
  return path.normalize(statePath);
}

function imageSavedPath(item) {
  if (
    item?.type !== "imageGeneration" ||
    item.status !== "completed" ||
    typeof item.savedPath !== "string" ||
    !path.isAbsolute(item.savedPath)
  ) return null;
  return path.normalize(item.savedPath);
}

function commandErrorCode(error) {
  for (const value of [error?.stderr, error?.stdout]) {
    if (typeof value !== "string") continue;
    for (const line of value.trim().split("\n").reverse()) {
      try {
        const parsed = JSON.parse(line);
        if (typeof parsed?.error?.code === "string") return parsed.error.code;
      } catch {
        // Canonical scripts may write ordinary diagnostics around their JSON.
      }
    }
  }
  return error?.code || "single_edit_host_finalize_failed";
}

async function defaultCommandRunner(spec, env) {
  return execFileAsync(spec.command, spec.args, {
    encoding: "utf8",
    env,
    maxBuffer: 1024 * 1024,
    timeout: 11 * 60 * 1000,
  });
}

async function defaultReadState(statePath) {
  return JSON.parse(await readFile(statePath, "utf8"));
}

function stateNeedsComplete(state) {
  return (
    state?.single_image_edit_state_contract_version === SINGLE_IMAGE_EDIT_CONTRACT_VERSION &&
    state?.run_mode === SINGLE_IMAGE_EDIT_RUN_MODE &&
    state?.status === "prepared" &&
    state?.imagegen?.status === "leased" &&
    typeof state?.imagegen?.global_lease_id === "string" &&
    state.imagegen.global_lease_id &&
    !state?.candidate
  );
}

function stateNeedsRelease(state) {
  return (
    state?.single_image_edit_state_contract_version === SINGLE_IMAGE_EDIT_CONTRACT_VERSION &&
    state?.run_mode === SINGLE_IMAGE_EDIT_RUN_MODE &&
    state?.status === "prepared" &&
    state?.imagegen?.status === "leased" &&
    typeof state?.imagegen?.global_lease_id === "string" &&
    state.imagegen.global_lease_id &&
    !state?.candidate
  );
}

function minimalCompiled(statePath) {
  return {
    contract_version: SINGLE_IMAGE_EDIT_CONTRACT_VERSION,
    run_mode: SINGLE_IMAGE_EDIT_RUN_MODE,
    runtime: {
      control_plane_path: SINGLE_IMAGE_EDIT_CONTROL_PLANE,
      state_path: statePath,
    },
  };
}

function releaseSpec(statePath) {
  return {
    command: "python3",
    args: [SINGLE_IMAGE_EDIT_CONTROL_PLANE, "release", "--state", statePath],
  };
}

/**
 * Per-turn evidence join for the Studio root conversation. This owns no run
 * state: it observes one official turn, reads the canonical native state and
 * invokes only the existing deterministic complete/release entrypoints.
 */
export class SingleEditTurnFinalizer {
  constructor({
    commandRunner = null,
    env = process.env,
    readState = defaultReadState,
    planBuilder = buildSingleImageEditHostFinalizePlan,
  } = {}) {
    this.env = { ...env };
    this.generatedImagesRoot = path.join(path.resolve(env.CODEX_HOME || path.join(os.homedir(), ".codex")), "generated_images");
    this.commandRunner = commandRunner || ((spec) => defaultCommandRunner(spec, this.env));
    this.readState = readState;
    this.planBuilder = planBuilder;
    this.starting = new Map();
    this.turns = new Map();
    this.outcomes = new Map();
    this.waiters = new Map();
  }

  registerStarting(threadId, { transport, deckUid = null, candidateRoots = [] } = {}) {
    if (transport !== STUDIO_APP_SERVER_TRANSPORT) return;
    this.starting.set(threadId, {
      transport,
      deckUid: typeof deckUid === "string" ? deckUid : null,
      candidateRoots: Array.isArray(candidateRoots)
        ? candidateRoots.filter((item) => typeof item === "string").map((item) => path.resolve(item))
        : [],
    });
  }

  clearStarting(threadId) {
    this.starting.delete(threadId);
  }

  outcome(threadId, turnId) {
    return this.outcomes.get(`${threadId}\u0000${turnId}`) || null;
  }

  async waitForOutcome(threadId, turnId, timeoutMs = 1000) {
    const key = `${threadId}\u0000${turnId}`;
    if (this.outcomes.has(key)) return this.outcomes.get(key);
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.waiters.delete(key);
        resolve(null);
      }, timeoutMs);
      this.waiters.set(key, (value) => {
        clearTimeout(timer);
        resolve(value);
      });
    });
  }

  observeApproval(request) {
    const params = request?.params || {};
    const threadId = threadIdOf(params);
    const turnId = turnIdOf(params);
    if (!threadId || !turnId) return;
    this.#observeStatePath(threadId, turnId, params.command);
  }

  observeNotification(notification) {
    const params = notification?.params || {};
    const threadId = threadIdOf(params);
    const turnId = turnIdOf(params);
    if (!threadId || !turnId) return;
    if (notification.method === "turn/started") {
      const starting = this.starting.get(threadId);
      if (!starting) return;
      this.starting.delete(threadId);
      this.turns.set(`${threadId}\u0000${turnId}`, {
        threadId,
        turnId,
        transport: starting.transport,
        deckUid: starting.deckUid,
        candidateRoots: starting.candidateRoots,
        statePaths: new Set(),
        completedImages: new Map(),
        finishing: false,
      });
      return;
    }
    const entry = this.turns.get(`${threadId}\u0000${turnId}`);
    if (!entry) return;
    if (["item/started", "item/completed"].includes(notification.method)) {
      this.#observeStatePath(threadId, turnId, params.item?.command);
    }
    if (notification.method === "item/completed") {
      const savedPath = imageSavedPath(params.item);
      if (savedPath) entry.completedImages.set(params.item.id || savedPath, savedPath);
    }
    if (notification.method === "turn/completed") {
      for (const item of params.turn?.items || []) {
        this.#observeStatePath(threadId, turnId, item?.command);
        const savedPath = imageSavedPath(item);
        if (savedPath) entry.completedImages.set(item.id || savedPath, savedPath);
      }
      void this.#finish(entry);
    }
  }

  #observeStatePath(threadId, turnId, command) {
    const entry = this.turns.get(`${threadId}\u0000${turnId}`);
    if (!entry) return;
    const statePath = canonicalSingleEditStatePath(command);
    if (statePath) entry.statePaths.add(statePath);
  }

  async #finish(entry) {
    if (entry.finishing) return;
    entry.finishing = true;
    const key = `${entry.threadId}\u0000${entry.turnId}`;
    let outcome = { status: "ignored", reason: "insufficient_exact_evidence" };
    try {
      if (entry.statePaths.size !== 1) return;
      const observedStatePath = [...entry.statePaths][0];
      const statePath = await realpath(observedStatePath).catch(() => observedStatePath);
      const candidateRoots = await Promise.all(entry.candidateRoots.map((root) => realpath(root).catch(() => root)));
      let state;
      try {
        state = await this.readState(statePath);
      } catch {
        outcome = { status: "ignored", reason: "native_state_unavailable", state_path: statePath };
        return;
      }
      if (
        (entry.deckUid && state?.identity?.deck_uid !== entry.deckUid) ||
        (candidateRoots.length && !candidateRoots.some((root) => {
          const relative = path.relative(root, statePath);
          return relative && relative !== ".." && !relative.startsWith(`..${path.sep}`);
        }))
      ) {
        outcome = { status: "ignored", reason: "native_state_scope_mismatch", state_path: statePath };
        return;
      }
      if (entry.completedImages.size === 1) {
        if (!stateNeedsComplete(state)) {
          outcome = { status: "ignored", reason: "native_state_not_pending", state_path: statePath };
          return;
        }
        const observedPath = [...entry.completedImages.values()][0];
        const savedPath = await realpath(observedPath).catch(() => observedPath);
        const generatedImagesRoot = await realpath(this.generatedImagesRoot).catch(() => this.generatedImagesRoot);
        const plan = this.planBuilder(minimalCompiled(statePath), { saved_path: savedPath }, {
          generatedImagesRoot,
        });
        try {
          await this.commandRunner(plan.attempt_complete);
        } catch (error) {
          if (commandErrorCode(error) !== plan.recover_only_if_error_code) throw error;
          for (const command of plan.recovery_commands) await this.commandRunner(command);
        }
        outcome = { status: "completed", state_path: statePath, saved_path: savedPath };
        return;
      }
      if (entry.completedImages.size === 0 && stateNeedsRelease(state)) {
        try {
          await this.commandRunner(releaseSpec(statePath));
          outcome = { status: "released", reason: "no_completed_image", state_path: statePath };
        } catch {
          outcome = { status: "release_failed", reason: "no_completed_image", state_path: statePath };
        }
        return;
      }
      outcome = {
        status: "ignored",
        reason: entry.completedImages.size > 1 ? "multiple_completed_images" : "native_state_not_pending",
        state_path: statePath,
      };
    } catch (error) {
      // A completed image is evidence that must never be discarded. In
      // particular, do not release the lease after a canonical complete error.
      outcome = {
        status: "failed",
        reason: error?.code || "single_edit_host_finalize_failed",
        message: error?.message || "single-image edit host finalize failed",
      };
    } finally {
      this.turns.delete(key);
      this.outcomes.set(key, outcome);
      const waiter = this.waiters.get(key);
      this.waiters.delete(key);
      waiter?.(outcome);
    }
  }
}
