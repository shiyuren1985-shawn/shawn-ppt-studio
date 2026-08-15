import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const app = await readFile(new URL("../../web/app.js", import.meta.url), "utf8");
const css = await readFile(new URL("../../web/styles.css", import.meta.url), "utf8");

test("approval batching stays scoped and resolves each official request", () => {
  assert.match(app, /proposedExecpolicyAmendment/);
  assert.match(app, /fast8_control_plane_v1/);
  assert.match(app, /invocation\[3\] !== "claim"/);
  assert.match(app, /--state/);
  assert.match(app, /state\\\/style_run_state/);
  assert.match(app, /ticket_/);
  assert.match(app, /function approvalIdentity/);
  assert.match(app, /request\?\.\["thread" \+ "_id"\]/);
  assert.match(app, /for \(const request of active\)/);
  assert.match(app, /api\.resolveCodexApproval\(request\.request_id, decision\)/);
  assert.match(app, /approval_resolution/);
  assert.match(app, /允许本批次（\$\{requests\.length\}）/);
  assert.doesNotMatch(app, /命令：\$\{params\.command\}/);
  assert.match(css, /\.permission-actions \{ display: flex; flex-wrap: wrap/);
});

test("waiting permission is active while stalled work needs attention", () => {
  assert.match(app, /"waiting_permission"/);
  assert.match(app, /\["attention", "stalled", "failed"\]/);
  assert.match(app, /等待允许操作 · \$\{Number\(task\.pending_approval_count\)\}项/);
});
