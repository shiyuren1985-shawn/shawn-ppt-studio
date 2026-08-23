import assert from "node:assert/strict";
import test from "node:test";

import { classifyImageTaskRequest } from "../../server/image-task-intent.mjs";

test("classifies explicit image work without treating outline edits as image tasks", () => {
  assert.deepEqual(classifyImageTaskRequest({ message: "请为 P06 做一个 8×1 管线" }), {
    kind: "image",
    mode_hint: "fast_8x1",
    title: "P06 · 8×1",
  });
  assert.deepEqual(classifyImageTaskRequest({ message: "重新生成 P06、P07 和 P08 的页面图片" }), {
    kind: "image",
    mode_hint: "image_generation",
    title: "P06 等 3 页 · 作图",
  });
  assert.equal(classifyImageTaskRequest({ message: "帮我做 10 张图片" })?.kind, "image");
  assert.equal(classifyImageTaskRequest({ message: "把 P06 的大纲标题改短一点" }), null);
  assert.equal(classifyImageTaskRequest({ message: "分析一下这套图片为什么不好看" }), null);
});

test("retouch context and anchored references enter the image task catalog", () => {
  assert.deepEqual(classifyImageTaskRequest({
    message: "把标题往上移动一点",
    retouchContext: true,
  }), {
    kind: "image",
    mode_hint: "retouch",
    title: "当前页 · 修图",
  });
  assert.deepEqual(classifyImageTaskRequest({
    message: "参考这张图重新做 P11",
    referenceImages: [{ path: "/tmp/reference.png" }],
  }), {
    kind: "image",
    mode_hint: "image_generation",
    title: "P11 · 作图",
  });
});
