import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { ConversationIndex } from "../../server/conversations.mjs";

test("HTTP startup does not wait for historical conversation maintenance", { timeout: 15000 }, async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-startup-maintenance-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const conversations = new ConversationIndex({ dataRoot: root });
  await conversations.initialize();
  await conversations.create({ deckId: "test", deckUid: "TEST", threadId: "historical", title: "Test" });
  const marker = path.join(root, "maintenance-started");
  const executable = path.join(root, "fake-codex.mjs");
  await writeFile(executable, `#!/usr/bin/env node
import readline from "node:readline";
import { writeFileSync } from "node:fs";
readline.createInterface({ input: process.stdin }).on("line", line => {
  const message = JSON.parse(line);
  if (!Object.hasOwn(message, "id")) return;
  if (message.method === "thread/read") {
    writeFileSync(process.env.STUDIO_TEST_MAINTENANCE_MARKER, "waiting");
    return; // Deliberately remain pending until the fixture process is stopped.
  }
  const result = message.method === "account/read" ? { account: { type: "chatgpt" } } : {};
  process.stdout.write(JSON.stringify({ id: message.id, result }) + "\\n");
});
`);
  await chmod(executable, 0o700);
  const repo = fileURLToPath(new URL("../../", import.meta.url));
  const child = spawn(process.execPath, [path.join(repo, "server/server.mjs"), "--port", "0"], {
    cwd: repo,
    env: { ...process.env,
      PATH: `${path.dirname(process.execPath)}:${process.env.PATH}`,
      CODEX_BIN: executable,
      SHAWN_PPT_STUDIO_CODEX_HOME: path.join(root, "isolated"),
      SHAWN_PPT_STUDIO_LEGACY_CODEX_HOME: path.join(root, "empty-legacy"),
      SHAWN_PPT_STUDIO_EXPORT_ROOT: path.join(root, "exports"),
      PPT_AI_LAB_TEST_MODE: "1", PPT_AI_LAB_ROOT: root,
      PPT_AI_LAB_DECKS_FILE: path.join(root, "absent-decks.json"),
      PPT_AI_LAB_OVERVIEW_PYTHON: path.join(root, "absent-python"),
      STUDIO_TEST_MAINTENANCE_MARKER: marker,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", chunk => { stdout += chunk; });
  child.stderr.on("data", chunk => { stderr += chunk; });
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) {
      const exited = once(child, "exit");
      child.kill("SIGTERM");
      await exited;
    }
  });
  const deadline = Date.now() + 10000;
  while (!(await readFile(marker, "utf8").catch(() => ""))) {
    assert.equal(child.exitCode, null, stderr);
    assert.ok(Date.now() < deadline, `maintenance never started: ${stderr}`);
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  const base = stdout.match(/listening on (http:\/\/127\.0\.0\.1:\d+)/)?.[1];
  assert.ok(base, "the HTTP bridge must listen before a slow history read begins");
  const response = await fetch(`${base}/api/health`, { signal: AbortSignal.timeout(1000) });
  assert.equal(response.status, 200);
  assert.equal((await response.json()).app_server.ready, true);
});
