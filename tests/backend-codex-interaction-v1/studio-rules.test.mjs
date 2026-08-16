import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  DEFAULT_STUDIO_RULES,
  rememberedStudioRule,
  StudioRulesStore,
} from "../../server/studio-rules.mjs";

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "shawn-ppt-studio-rules-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

test("Studio rules start with the user's shared defaults and persist edits", async (t) => {
  const root = await fixture(t);
  const store = new StudioRulesStore({ dataRoot: root, clock: () => "2026-08-16T00:00:00.000Z" });
  const initial = await store.initialize();
  assert.deepEqual(initial.rules, [...DEFAULT_STUDIO_RULES]);
  assert.match(initial.rules[0], /面向客户的大纲和成稿/);
  assert.match(initial.rules[1], /不提供 SHA、哈希值/);

  const saved = await store.replace(["规则一", "规则二", "规则一"]);
  assert.deepEqual(saved.rules, ["规则一", "规则二"]);
  const mode = (await stat(store.path)).mode & 0o777;
  assert.equal(mode, 0o600);

  const restarted = new StudioRulesStore({ dataRoot: root });
  await restarted.initialize();
  assert.deepEqual(restarted.list().rules, ["规则一", "规则二"]);
  const document = JSON.parse(await readFile(restarted.path, "utf8"));
  assert.equal(document.contract_version, 1);
});

test("messages beginning with remember add one durable deduplicated rule", async (t) => {
  const root = await fixture(t);
  const store = new StudioRulesStore({ dataRoot: root });
  await store.initialize();

  const first = await store.rememberFromMessage("记住，大纲不要出现内部审核语言");
  assert.equal(first.remembered, true);
  assert.equal(first.added, true);
  assert.equal(first.rule, "大纲不要出现内部审核语言");
  const duplicate = await store.rememberFromMessage("记住：大纲不要出现内部审核语言");
  assert.equal(duplicate.remembered, true);
  assert.equal(duplicate.added, false);
  const ordinary = await store.rememberFromMessage("请修改这一页");
  assert.equal(ordinary.remembered, false);

  const restarted = new StudioRulesStore({ dataRoot: root });
  await restarted.initialize();
  assert.equal(restarted.list().rules.filter((rule) => rule === first.rule).length, 1);
});

test("parallel remember messages cannot overwrite each other", async (t) => {
  const root = await fixture(t);
  const store = new StudioRulesStore({ dataRoot: root });
  await store.initialize();
  await Promise.all([
    store.rememberFromMessage("记住，第一条并发规则"),
    store.rememberFromMessage("记住，第二条并发规则"),
  ]);
  assert.ok(store.list().rules.includes("第一条并发规则"));
  assert.ok(store.list().rules.includes("第二条并发规则"));
});

test("remember intent is explicit and invalid rule documents fail closed", async (t) => {
  assert.equal(rememberedStudioRule("记住，保持简洁"), "保持简洁");
  assert.equal(
    rememberedStudioRule("以后正常回复不要告诉我哈希值。记住这个要求"),
    "以后正常回复不要告诉我哈希值",
  );
  assert.equal(rememberedStudioRule("请记住，保持简洁"), null);
  assert.equal(rememberedStudioRule("你记住这个要求了吗？"), null);
  assert.equal(rememberedStudioRule("记住"), null);

  const root = await fixture(t);
  const store = new StudioRulesStore({ dataRoot: root });
  await store.initialize();
  await assert.rejects(store.replace("not-an-array"), (error) => error?.code === "invalid_studio_rules");
  await assert.rejects(store.replace([""]), (error) => error?.code === "invalid_studio_rules");
  const cleared = await store.replace([]);
  assert.deepEqual(cleared.rules, []);
});
