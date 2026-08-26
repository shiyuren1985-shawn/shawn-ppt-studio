import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { StudioInstanceLock } from "../../server/instance-lock.mjs";

test("Studio Library permits one writer and releases cleanly", async (t) => {
  const dataRoot = await mkdtemp(path.join(os.tmpdir(), "shawn-ppt-studio-lock-"));
  t.after(() => rm(dataRoot, { recursive: true, force: true }));
  const alive = (pid) => pid === 101;
  const first = new StudioInstanceLock({ dataRoot, pid: 101, isProcessAlive: alive });
  const second = new StudioInstanceLock({ dataRoot, pid: 202, isProcessAlive: alive });

  await first.acquire();
  await assert.rejects(second.acquire(), (error) => error.code === "STUDIO_LIBRARY_IN_USE");
  await first.release();
  await second.acquire();
  await second.release();
  await assert.rejects(readFile(first.path, "utf8"), (error) => error.code === "ENOENT");
});

test("a stale owner record is recovered without weakening the live-owner check", async (t) => {
  const dataRoot = await mkdtemp(path.join(os.tmpdir(), "shawn-ppt-studio-stale-lock-"));
  t.after(() => rm(dataRoot, { recursive: true, force: true }));
  const lock = new StudioInstanceLock({ dataRoot, pid: 303, isProcessAlive: () => false });
  await mkdir(path.dirname(lock.path), { recursive: true });
  await writeFile(lock.path, JSON.stringify({ process_id: 999, token: "stale" }), "utf8");

  await lock.acquire();
  const current = JSON.parse(await readFile(lock.path, "utf8"));
  assert.equal(current.process_id, 303);
  assert.notEqual(current.token, "stale");
  await lock.release();
});
