import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import { HttpError } from "./errors.mjs";
import { studioLibraryRoot } from "./studio-library.mjs";

const CONTRACT_VERSION = 1;
const MAX_RULES = 50;
const MAX_RULE_LENGTH = 800;

export const DEFAULT_STUDIO_RULES = Object.freeze([
  "面向客户的大纲和成稿只呈现客户需要理解的内容，不出现证据管理、审核说明、保护性措辞、估算状态说明或“不得写成已实现成果”等内部工作语言；事实边界应在后台约束中执行，不直接暴露给客户。",
  "正常成功回复不提供 SHA、哈希值、绝对路径、内部 ID、状态枚举、台账或 QA 记录，只报告有用结果和下一步；仅在用户明确要求或故障诊断确实需要时提供最少技术细节。",
]);

function nowIso() {
  return new Date().toISOString();
}

function normalizeRule(value) {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

export function normalizeStudioRules(value) {
  if (!Array.isArray(value)) {
    throw new HttpError(400, "rules must be an array", "invalid_studio_rules");
  }
  if (value.length > MAX_RULES) {
    throw new HttpError(400, `rules cannot contain more than ${MAX_RULES} items`, "invalid_studio_rules");
  }
  const result = [];
  const seen = new Set();
  for (const raw of value) {
    const rule = normalizeRule(raw);
    if (!rule) throw new HttpError(400, "rules cannot contain empty items", "invalid_studio_rules");
    if (rule.length > MAX_RULE_LENGTH) {
      throw new HttpError(400, `each rule must be ${MAX_RULE_LENGTH} characters or fewer`, "invalid_studio_rules");
    }
    if (seen.has(rule)) continue;
    seen.add(rule);
    result.push(rule);
  }
  return result;
}

export function rememberedStudioRule(value) {
  if (typeof value !== "string") return null;
  const prefix = value.match(/^\s*记住(?:[，,:：]\s*|\s+)([\s\S]+?)\s*$/);
  const suffix = value.match(/^\s*([\s\S]+?)[。.!！]\s*(?:请)?记住(?:这个要求)?[。.!！]?\s*$/);
  const rule = normalizeRule(prefix?.[1] || suffix?.[1]);
  if (!rule || rule.length > MAX_RULE_LENGTH) return null;
  return rule;
}

async function atomicJson(filePath, value) {
  const temporary = `${filePath}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, {
      encoding: "utf8",
      mode: 0o600,
      flag: "wx",
    });
    await rename(temporary, filePath);
  } catch (error) {
    await rm(temporary, { force: true }).catch(() => {});
    throw error;
  }
}

export class StudioRulesStore {
  constructor({ dataRoot, clock = nowIso }) {
    this.runtimeRoot = studioLibraryRoot(dataRoot);
    this.path = path.join(this.runtimeRoot, "studio-rules.json");
    this.clock = clock;
    this.state = {
      contract_version: CONTRACT_VERSION,
      rules: [...DEFAULT_STUDIO_RULES],
      created_at: null,
      updated_at: null,
    };
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
        throw Object.assign(new Error("Studio rules are not valid JSON"), {
          code: "studio_rules_corrupt",
        });
      }
    }
    if (parsed) {
      this.#validateDocument(parsed);
      this.state = {
        ...parsed,
        rules: normalizeStudioRules(parsed.rules),
      };
    } else {
      const timestamp = this.clock();
      this.state.created_at = timestamp;
      this.state.updated_at = timestamp;
      await atomicJson(this.path, this.state);
    }
    this.ready = true;
    this.lastError = null;
    return this.list();
  }

  health() {
    return {
      ready: this.ready,
      rule_count: this.state.rules.length,
      error: this.lastError?.message || null,
    };
  }

  list() {
    this.#requireReady();
    return {
      contract_version: CONTRACT_VERSION,
      rules: [...this.state.rules],
      updated_at: this.state.updated_at,
    };
  }

  async replace(rules) {
    const normalized = normalizeStudioRules(rules);
    return this.#enqueue(async () => {
      const timestamp = this.clock();
      const nextState = {
        contract_version: CONTRACT_VERSION,
        rules: normalized,
        created_at: this.state.created_at || timestamp,
        updated_at: timestamp,
      };
      await atomicJson(this.path, nextState);
      this.state = nextState;
      this.lastError = null;
      return this.list();
    });
  }

  async rememberFromMessage(message) {
    const rule = rememberedStudioRule(message);
    if (!rule) return { remembered: false, added: false, rule: null, ...this.list() };
    return this.#enqueue(async () => {
      if (this.state.rules.includes(rule)) {
        return { remembered: true, added: false, rule, ...this.list() };
      }
      const rules = [...this.state.rules, rule];
      if (rules.length > MAX_RULES) {
        throw new HttpError(409, "Studio long-term rules are full", "studio_rules_full");
      }
      const timestamp = this.clock();
      const nextState = {
        contract_version: CONTRACT_VERSION,
        rules,
        created_at: this.state.created_at || timestamp,
        updated_at: timestamp,
      };
      await atomicJson(this.path, nextState);
      this.state = nextState;
      this.lastError = null;
      return { remembered: true, added: true, rule, ...this.list() };
    });
  }

  #requireReady() {
    if (!this.ready) {
      throw new HttpError(503, "Studio rules are unavailable", "studio_rules_unavailable");
    }
  }

  #validateDocument(value) {
    if (
      !value ||
      typeof value !== "object" ||
      Array.isArray(value) ||
      value.contract_version !== CONTRACT_VERSION ||
      !Array.isArray(value.rules)
    ) {
      throw Object.assign(new Error("Studio rules document has an invalid contract"), {
        code: "studio_rules_invalid_contract",
      });
    }
  }

  #enqueue(operation) {
    this.#requireReady();
    const next = this.writeQueue.then(operation);
    this.writeQueue = next.catch((error) => {
      this.lastError = error;
    });
    return next;
  }
}
