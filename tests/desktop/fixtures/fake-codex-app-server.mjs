#!/usr/bin/env node

// Minimal deterministic Codex App Server fixture for desktop startup tests.
// The smoke test only needs initialization and account discovery; keeping the
// fixture here makes the published test independent of ignored local files.

import readline from "node:readline";

function reply(id, result) {
  process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id, result })}\n`);
}

function fail(id, method) {
  process.stdout.write(`${JSON.stringify({
    jsonrpc: "2.0",
    id,
    error: { code: -32601, message: `method not found: ${method}` },
  })}\n`);
}

const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
lines.on("line", (line) => {
  if (!line.trim()) return;
  const message = JSON.parse(line);
  if (message.id === undefined || message.id === null) return;

  if (message.method === "initialize") {
    reply(message.id, {
      protocolVersion: 1,
      userAgent: "shawn-ppt-studio-desktop-fixture/1.0",
    });
    return;
  }
  if (message.method === "account/read") {
    reply(message.id, {
      account: { type: "chatgpt", email: "desktop-test@example.invalid", planType: "test" },
      requiresOpenaiAuth: false,
    });
    return;
  }
  fail(message.id, message.method);
});
