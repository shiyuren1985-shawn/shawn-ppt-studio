import test from "node:test";
import assert from "node:assert/strict";
import { STUDIO_MODEL, STUDIO_REASONING_EFFORT, threadStartParams, threadResumeParams } from "../../server/turns.mjs";

test("Studio defaults to the user-requested Sol medium", () => {
  assert.equal(STUDIO_MODEL, "gpt-5.6-sol");
  assert.equal(STUDIO_REASONING_EFFORT, "medium");
  for (const params of [threadStartParams("/tmp"), threadResumeParams("/tmp", "thread")]) {
    assert.equal(params.model, "gpt-5.6-sol");
    assert.equal(params.config.model_reasoning_effort, "medium");
  }
});
