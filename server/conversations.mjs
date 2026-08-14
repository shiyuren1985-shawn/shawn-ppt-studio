import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import { HttpError } from "./errors.mjs";

const CONTRACT_VERSION = 1;

function nowIso() {
  return new Date().toISOString();
}

function requiredString(value, name) {
  if (typeof value !== "string" || !value.trim()) {
    throw new HttpError(400, `${name} is required`, "invalid_conversation_request");
  }
  return value.trim();
}

function cleanTitle(value, fallback) {
  const title = typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  return (title || fallback).slice(0, 80);
}

function publicConversation(record) {
  return {
    conversation_id: record.conversation_id,
    title: record.title,
    created_at: record.created_at,
    updated_at: record.updated_at,
    last_used_at: record.last_used_at,
  };
}

export function titleFromMessage(message) {
  const clean = typeof message === "string" ? message.replace(/\s+/g, " ").trim() : "";
  if (!clean) return null;
  return clean.length > 28 ? `${clean.slice(0, 28)}…` : clean;
}

export class ConversationIndex {
  constructor({ dataRoot, clock = nowIso }) {
    this.runtimeRoot = path.join(path.resolve(dataRoot), "runtime");
    this.path = path.join(this.runtimeRoot, "conversations.json");
    this.clock = clock;
    this.state = { contract_version: CONTRACT_VERSION, decks: {} };
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
      if (error?.code !== "ENOENT") {
        this.lastError = error;
        throw Object.assign(new Error("conversation index is not valid JSON"), {
          code: "conversation_index_corrupt",
        });
      }
    }

    if (parsed !== null) this.#validateState(parsed);
    this.state = parsed || { contract_version: CONTRACT_VERSION, decks: {} };
    this.ready = true;
    this.lastError = null;
  }

  health() {
    return {
      ready: this.ready,
      path: this.path,
      deck_count: Object.keys(this.state.decks).length,
      conversation_count: Object.values(this.state.decks).reduce(
        (total, deck) => total + deck.conversations.length,
        0,
      ),
      error: this.lastError?.message || null,
    };
  }

  list(deckUid) {
    const uid = requiredString(deckUid, "deck_uid");
    const deck = this.state.decks[uid];
    const conversations = [...(deck?.conversations || [])]
      .sort((left, right) => right.last_used_at.localeCompare(left.last_used_at))
      .map(publicConversation);
    return {
      contract_version: CONTRACT_VERSION,
      deck_uid: uid,
      active_conversation_id: deck?.active_conversation_id || null,
      conversations,
    };
  }

  records(deckUid) {
    const uid = requiredString(deckUid, "deck_uid");
    return [...(this.state.decks[uid]?.conversations || [])]
      .sort((left, right) => right.last_used_at.localeCompare(left.last_used_at))
      .map((record) => ({ ...publicConversation(record), thread_id: record.thread_id }));
  }

  get(deckUid, conversationId) {
    const record = this.#record(deckUid, conversationId);
    return publicConversation(record);
  }

  threadIdFor(deckUid, conversationId) {
    return this.#record(deckUid, conversationId).thread_id;
  }

  active(deckUid) {
    const uid = requiredString(deckUid, "deck_uid");
    const conversationId = this.state.decks[uid]?.active_conversation_id || null;
    if (!conversationId) return null;
    return this.#record(uid, conversationId);
  }

  async create({ deckId, deckUid, threadId, title = null }) {
    const id = requiredString(deckId, "deck_id");
    const uid = requiredString(deckUid, "deck_uid");
    const codexThreadId = requiredString(threadId, "thread_id");
    const timestamp = this.clock();
    let created;
    await this.#mutate((state) => {
      const deck = state.decks[uid] || {
        deck_id: id,
        deck_uid: uid,
        active_conversation_id: null,
        conversations: [],
      };
      const number = deck.conversations.length + 1;
      created = {
        conversation_id: randomUUID(),
        thread_id: codexThreadId,
        title: cleanTitle(title, `新对话 ${number}`),
        title_is_default: !title,
        created_at: timestamp,
        updated_at: timestamp,
        last_used_at: timestamp,
      };
      deck.deck_id = id;
      deck.conversations.push(created);
      deck.active_conversation_id = created.conversation_id;
      state.decks[uid] = deck;
    });
    return publicConversation(created);
  }

  async activate(deckUid, conversationId) {
    const uid = requiredString(deckUid, "deck_uid");
    const id = requiredString(conversationId, "conversation_id");
    const timestamp = this.clock();
    let activated;
    await this.#mutate((state) => {
      const deck = state.decks[uid];
      activated = deck?.conversations.find((item) => item.conversation_id === id);
      if (!activated) {
        throw new HttpError(404, "conversation was not found", "conversation_not_found");
      }
      deck.active_conversation_id = id;
      activated.last_used_at = timestamp;
      activated.updated_at = timestamp;
    });
    return publicConversation(activated);
  }

  async touch(deckUid, conversationId, { firstMessage = null } = {}) {
    const uid = requiredString(deckUid, "deck_uid");
    const id = requiredString(conversationId, "conversation_id");
    const timestamp = this.clock();
    let updated;
    await this.#mutate((state) => {
      const deck = state.decks[uid];
      updated = deck?.conversations.find((item) => item.conversation_id === id);
      if (!updated) {
        throw new HttpError(404, "conversation was not found", "conversation_not_found");
      }
      if (updated.title_is_default && firstMessage) {
        updated.title = cleanTitle(titleFromMessage(firstMessage), updated.title);
        updated.title_is_default = false;
      }
      deck.active_conversation_id = id;
      updated.last_used_at = timestamp;
      updated.updated_at = timestamp;
    });
    return publicConversation(updated);
  }

  #record(deckUid, conversationId) {
    const uid = requiredString(deckUid, "deck_uid");
    const id = requiredString(conversationId, "conversation_id");
    const record = this.state.decks[uid]?.conversations.find(
      (item) => item.conversation_id === id,
    );
    if (!record) {
      throw new HttpError(404, "conversation was not found", "conversation_not_found");
    }
    return record;
  }

  async #mutate(change) {
    if (!this.ready) {
      throw new HttpError(503, "conversation history is unavailable", "conversation_index_unavailable");
    }
    const operation = async () => {
      const next = structuredClone(this.state);
      await change(next);
      this.#validateState(next);
      const temporary = `${this.path}.${process.pid}.${randomUUID()}.tmp`;
      try {
        await writeFile(temporary, `${JSON.stringify(next, null, 2)}\n`, {
          encoding: "utf8",
          mode: 0o600,
          flag: "wx",
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

  #validateState(state) {
    if (
      !state ||
      typeof state !== "object" ||
      state.contract_version !== CONTRACT_VERSION ||
      !state.decks ||
      typeof state.decks !== "object" ||
      Array.isArray(state.decks)
    ) {
      throw Object.assign(new Error("conversation index has an invalid root"), {
        code: "conversation_index_corrupt",
      });
    }
    for (const [deckUid, deck] of Object.entries(state.decks)) {
      if (
        !deck ||
        deck.deck_uid !== deckUid ||
        typeof deck.deck_id !== "string" ||
        !Array.isArray(deck.conversations)
      ) {
        throw Object.assign(new Error("conversation index has an invalid deck"), {
          code: "conversation_index_corrupt",
        });
      }
      const ids = new Set();
      for (const record of deck.conversations) {
        if (
          !record ||
          typeof record.conversation_id !== "string" ||
          typeof record.thread_id !== "string" ||
          typeof record.title !== "string" ||
          typeof record.created_at !== "string" ||
          typeof record.updated_at !== "string" ||
          typeof record.last_used_at !== "string" ||
          ids.has(record.conversation_id)
        ) {
          throw Object.assign(new Error("conversation index has an invalid conversation"), {
            code: "conversation_index_corrupt",
          });
        }
        ids.add(record.conversation_id);
      }
      if (deck.active_conversation_id && !ids.has(deck.active_conversation_id)) {
        throw Object.assign(new Error("conversation index has an invalid active pointer"), {
          code: "conversation_index_corrupt",
        });
      }
    }
  }
}
