import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { AppServerClient, resolveCodexExecutable } from "../../server/app-server-client.mjs";

test("public CODEX_BIN override takes precedence over the legacy variable", () => {
  assert.equal(
    resolveCodexExecutable({ CODEX_BIN: "/opt/codex", PPT_AI_LAB_CODEX_BIN: "/legacy/codex" }),
    "/opt/codex",
  );
});

test("Codex executable discovery handles current and older app bundles", () => {
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "studio-codex-discovery-"));
  const current = path.join(scratch, "codex-cli/bin/codex");
  const older = path.join(scratch, "codex");
  try {
    fs.mkdirSync(path.dirname(current), { recursive: true });
    fs.writeFileSync(older, "", { mode: 0o755 });
    assert.equal(resolveCodexExecutable({}, scratch), older);
    fs.writeFileSync(current, "", { mode: 0o755 });
    assert.equal(resolveCodexExecutable({}, scratch), current);
    fs.chmodSync(current, 0o644);
    assert.equal(resolveCodexExecutable({}, scratch), older);
    assert.equal(resolveCodexExecutable({ CODEX_BIN: "/custom/codex" }, scratch), "/custom/codex");
  } finally {
    fs.rmSync(scratch, { recursive: true, force: true });
  }
});

test("missing Codex executable reports an actionable launch error", async () => {
  const client = new AppServerClient({
    executable: "/nonexistent/shawn-ppt-studio-codex",
    cwd: os.tmpdir(),
  });
  await assert.rejects(client.start(), (error) => {
    assert.equal(error.code, "codex_executable_missing");
    assert.match(error.message, /找不到 Codex 命令/);
    return true;
  });
});

test("App Server connection opts into experimental fields used by turn/start", async () => {
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "studio-app-server-capability-"));
  const fake = path.join(scratch, "fake-app-server.mjs");
  const requestLog = path.join(scratch, "initialize.json");
  fs.writeFileSync(
    fake,
    `#!/usr/bin/env node
import fs from "node:fs";
import readline from "node:readline";
const lines = readline.createInterface({ input: process.stdin });
for await (const line of lines) {
  const message = JSON.parse(line);
  if (message.method === "initialize") {
    fs.writeFileSync(process.env.STUDIO_INIT_LOG, JSON.stringify(message.params));
    process.stdout.write(JSON.stringify({ id: message.id, result: { protocolVersion: 1 } }) + "\\n");
  } else if (message.method === "account/read") {
    process.stdout.write(JSON.stringify({ id: message.id, result: { account: { type: "chatgpt" } } }) + "\\n");
  }
}
`,
    { mode: 0o755 },
  );

  const client = new AppServerClient({
    executable: fake,
    cwd: scratch,
    env: {
      ...process.env,
      PATH: `${path.dirname(process.execPath)}:${process.env.PATH || ""}`,
      STUDIO_INIT_LOG: requestLog,
    },
  });

  try {
    await client.start();
    const initialize = JSON.parse(fs.readFileSync(requestLog, "utf8"));
    assert.equal(initialize.clientInfo.name, "shawn_ppt_studio");
    assert.equal(initialize.capabilities.experimentalApi, true);
  } finally {
    await client.stop();
    fs.rmSync(scratch, { recursive: true, force: true });
  }
});
