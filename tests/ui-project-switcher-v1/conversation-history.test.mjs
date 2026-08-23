import assert from "node:assert/strict";
import test from "node:test";

import { conversationDisplayTurns } from "../../web/model.js";

test("active history keeps the official user request while relay owns progress and final output", () => {
  const turns = [{
    turn_id: "turn-complete",
    status: "completed",
    items: [{ id: "old-user", type: "userMessage", text: "旧要求" }],
  }, {
    turn_id: "turn-active",
    status: "inProgress",
    items: [
      { id: "new-user", type: "userMessage", text: "正在执行的要求" },
      { id: "progress", type: "agentMessage", phase: "commentary", text: "处理中" },
      { id: "tool", type: "commandExecution", status: "inProgress" },
    ],
  }];
  const visible = conversationDisplayTurns(turns, "turn-active");
  assert.equal(visible.length, 2);
  assert.deepEqual(visible[0], turns[0]);
  assert.deepEqual(visible[1].items, [turns[1].items[0]]);
  assert.equal(conversationDisplayTurns(turns, ""), turns);
});
