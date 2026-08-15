import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";

const CONTRACT_VERSION = 1;

function validRecord(value) {
  return value
    && typeof value.deck_uid === "string"
    && value.deck_uid
    && typeof value.conversation_id === "string"
    && value.conversation_id
    && typeof value.bound_at === "string";
}

export class TaskAssociationIndex {
  constructor({ dataRoot, clock = () => new Date().toISOString() }) {
    this.runtimeRoot = path.join(path.resolve(dataRoot), "runtime");
    this.path = path.join(this.runtimeRoot, "task-associations.json");
    this.clock = clock;
    this.state = { contract_version: CONTRACT_VERSION, associations: {}, requests: {} };
    this.ready = false;
    this.lastError = null;
    this.writeQueue = Promise.resolve();
  }

  async initialize() {
    await mkdir(this.runtimeRoot, { recursive: true });
    let parsed = null;
    try {
      parsed = JSON.parse(await readFile(this.path, "utf8"));
    } catch (error) {
      if (error?.code !== "ENOENT") throw new Error("task association index is not valid JSON");
    }
    if (parsed !== null && parsed.requests === undefined) parsed.requests = {};
    if (parsed !== null) this.#validate(parsed);
    this.state = parsed || { contract_version: CONTRACT_VERSION, associations: {}, requests: {} };
    this.ready = true;
    this.lastError = null;
  }

  resolve(taskId, deckUid, conversations) {
    if (!this.ready) return null;
    const record = this.state.associations[taskId];
    if (!record || record.deck_uid !== deckUid) return null;
    return conversations.find((item) => item.conversation_id === record.conversation_id) || null;
  }

  resolveRequest(deckUid, requestStartedAt, conversations) {
    if (!this.ready || !deckUid || !requestStartedAt) return null;
    const record = this.state.requests[this.#requestKey(deckUid, requestStartedAt)];
    if (!record || record.deck_uid !== deckUid) return null;
    return conversations.find((item) => item.conversation_id === record.conversation_id) || null;
  }

  async remember(taskId, deckUid, conversationId) {
    if (!this.ready || !taskId || !deckUid || !conversationId) return;
    const current = this.state.associations[taskId];
    if (current?.deck_uid === deckUid && current?.conversation_id === conversationId) return;
    return this.#mutate((next) => {
      next.associations[taskId] = {
        deck_uid: deckUid,
        conversation_id: conversationId,
        bound_at: this.clock(),
      };
    });
  }

  async rememberRequest(deckUid, requestStartedAt, conversationId) {
    if (!this.ready || !deckUid || !requestStartedAt || !conversationId) return;
    const key = this.#requestKey(deckUid, requestStartedAt);
    const current = this.state.requests[key];
    if (current?.deck_uid === deckUid && current?.conversation_id === conversationId) return;
    return this.#mutate((next) => {
      next.requests[key] = {
        deck_uid: deckUid,
        conversation_id: conversationId,
        bound_at: this.clock(),
      };
    });
  }

  async #mutate(change) {
    const operation = async () => {
      const next = structuredClone(this.state);
      change(next);
      const temporary = `${this.path}.${process.pid}.tmp`;
      try {
        await writeFile(temporary, `${JSON.stringify(next, null, 2)}\n`, {
          encoding: "utf8",
          mode: 0o600,
        });
        await rename(temporary, this.path);
      } catch (error) {
        await rm(temporary, { force: true }).catch(() => {});
        throw error;
      }
      this.state = next;
      this.lastError = null;
    };
    const result = this.writeQueue.then(operation);
    this.writeQueue = result.catch((error) => {
      this.lastError = error;
    });
    return result;
  }

  #requestKey(deckUid, requestStartedAt) {
    return `${deckUid}\u0000${requestStartedAt}`;
  }

  #validate(state) {
    if (
      !state
      || state.contract_version !== CONTRACT_VERSION
      || !state.associations
      || typeof state.associations !== "object"
      || Array.isArray(state.associations)
      || !state.requests
      || typeof state.requests !== "object"
      || Array.isArray(state.requests)
      || Object.entries(state.associations).some(([taskId, value]) => !taskId || !validRecord(value))
      || Object.entries(state.requests).some(([requestId, value]) => !requestId || !validRecord(value))
    ) {
      throw new Error("task association index has an invalid shape");
    }
  }
}
