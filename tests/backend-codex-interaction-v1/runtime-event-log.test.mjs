import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { RuntimeEventLog } from "../../server/runtime-event-log.mjs";

test("runtime events persist operation and fatal-shutdown evidence as JSONL", async (t) => {
  const dataRoot = await mkdtemp(path.join(os.tmpdir(), "studio-runtime-events-"));
  t.after(() => rm(dataRoot, { recursive: true, force: true }));
  const events = new RuntimeEventLog({
    dataRoot,
    clock: () => "2026-08-16T08:00:00.000Z",
  });
  await events.initialize();
  await events.record("selector_trash_started", { deck_id: "demo", candidate_id: "candidate" });
  await events.record("server_uncaught_exception", { error_code: "ENOENT" });

  const records = (await readFile(events.path, "utf8"))
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
  assert.deepEqual(records.map((record) => record.type), [
    "selector_trash_started",
    "server_uncaught_exception",
  ]);
  assert.equal(records[0].occurred_at, "2026-08-16T08:00:00.000Z");
  assert.equal(records[1].error_code, "ENOENT");
});
