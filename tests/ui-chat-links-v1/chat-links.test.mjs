import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { agentMessageSegments } from "../../web/model.js";

test("Codex local image markdown becomes compact clickable labels without embedding images", () => {
  const text = "[总览](</Users/test/output/overview/ABCDEFGH_2x4.png>) [A](</Users/test/output/origin_image/style_A.png>)";
  assert.deepEqual(agentMessageSegments(text), [
    { type: "local_image", label: "总览", target: "/Users/test/output/overview/ABCDEFGH_2x4.png" },
    { type: "text", text: " " },
    { type: "local_image", label: "A", target: "/Users/test/output/origin_image/style_A.png" },
  ]);
  assert.deepEqual(agentMessageSegments("![A](</Users/test/output/origin_image/style_A.png>)"), [
    { type: "local_image", label: "A", target: "/Users/test/output/origin_image/style_A.png" },
  ]);
  assert.equal(agentMessageSegments("![内嵌](data:image/png;base64,abc)")[0].type, "text");
});

test("chat renderer uses on-demand same-project image links instead of raw HTML or image tags", async () => {
  const [app, api, styles, server] = await Promise.all([
    readFile(new URL("../../web/app.js", import.meta.url), "utf8"),
    readFile(new URL("../../web/api.js", import.meta.url), "utf8"),
    readFile(new URL("../../web/styles.css", import.meta.url), "utf8"),
    readFile(new URL("../../server/http-server.mjs", import.meta.url), "utf8"),
  ]);
  assert.match(app, /renderAgentMessageBody/);
  assert.match(app, /conversation-file-link/);
  assert.match(app, /openImage\(url\)/);
  assert.doesNotMatch(app, /body\.innerHTML\s*=/);
  assert.match(api, /conversation-image\?path=/);
  assert.match(styles, /\.conversation-file-link/);
  assert.match(server, /conversation-image/);
});

test("each turn has one compact process group that collapses when work finishes", async () => {
  const [app, styles] = await Promise.all([
    readFile(new URL("../../web/app.js", import.meta.url), "utf8"),
    readFile(new URL("../../web/styles.css", import.meta.url), "utf8"),
  ]);
  assert.match(app, /turnProcessViews: new Map\(\)/);
  assert.match(app, /title\.textContent = "处理过程"/);
  assert.match(app, /while \(process\.commentaries\.length > 3\)/);
  assert.match(app, /finishTurnProcess\(turnId, status\)/);
  assert.match(app, /view\.details\.open = false/);
  assert.match(app, /turn\.status === "inProgress"/);
  assert.match(app, /String\(state\.activeTurnId\) === id/);
  assert.match(styles, /\.codex-process-body/);
  assert.match(styles, /\.codex-process-event/);
});
