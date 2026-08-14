import assert from "node:assert/strict";
import test from "node:test";

import { createLabHttpServer } from "../../server/http-server.mjs";

test("task routes list projected work and interrupt only the linked active turn", async (t) => {
  const calls = [];
  const client = {
    ready: true,
    subscribe() { return () => {}; },
    subscribeServerRequests() { return () => {}; },
    async request(method, params) { calls.push({ method, params }); return {}; },
  };
  const taskProjection = {
    health() { return { ready: true, task_count: 1, error: null }; },
    async list() {
      return { contract_version: 1, active_count: 1, attention_count: 0, tasks: [{ task_id: "task-one", title: "P06 · 8×1" }] };
    },
    interruptTarget(taskId) {
      return taskId === "task-one" ? { threadId: "thread-one", turnId: "turn-one" } : null;
    },
  };
  const server = createLabHttpServer({ client, taskProjection, codexInteraction: {
    activeTurn(threadId) { return threadId === "thread-one" ? "turn-one" : null; },
  } });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const origin = `http://127.0.0.1:${server.address().port}`;

  const list = await fetch(`${origin}/api/tasks`).then((response) => response.json());
  assert.equal(list.tasks[0].title, "P06 · 8×1");

  const stopped = await fetch(`${origin}/api/tasks/task-one/interrupt`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-shawn-ppt-studio": "1" },
    body: "{}",
  });
  assert.equal(stopped.status, 202);
  assert.deepEqual(calls, [{ method: "turn/interrupt", params: { threadId: "thread-one", turnId: "turn-one" } }]);
});
