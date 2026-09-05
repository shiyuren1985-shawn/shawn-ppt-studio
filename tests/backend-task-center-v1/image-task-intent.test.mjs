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
  assert.deepEqual(classifyImageTaskRequest({
    message: "参考风格定位图，做一遍整个大纲的每一页，中英文双语版本",
    referenceImages: [{ path: "/tmp/style-reference.png" }],
  }), {
    kind: "image",
    mode_hint: "image_generation",
    title: "整套作图",
  });
  assert.equal(classifyImageTaskRequest({ message: "把 P06 的大纲标题改短一点" }), null);
  assert.equal(classifyImageTaskRequest({ message: "分析一下这套图片为什么不好看" }), null);
  assert.equal(classifyImageTaskRequest({
    message: "你检查一下是什么问题。如果是大纲的问题，我们就修改大纲或页面说明。总之，刚才作图出现了这个问题，在图片中出现了不该上屏的字。",
  }), null);
  assert.equal(classifyImageTaskRequest({
    message: "参考附件，逐页修改整个大纲的文字",
    referenceImages: [{ path: "/tmp/reference.png" }],
  }), null);
  assert.deepEqual(classifyImageTaskRequest({
    message: "把刚才修改过大纲的这4页，根据风格定位图，再做一次",
    referenceImages: [{ path: "/tmp/style-reference.png" }],
  }), {
    kind: "image",
    mode_hint: "image_generation",
    title: "4 页作图",
  });
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

test("negated image instructions and informational questions do not create image tasks", () => {
  for (const message of [
    "这是隔离测试。请只回答：Studio 连接测试通过。不要访问网络、不要改文件、不要生成图片。",
    "请不要生成图片", "暂时不需要作图，先讨论大纲", "先别做 8×1，先解释方案", "先不生成图片",
    "Do not generate an image.", "Don't create images; just discuss the outline.",
    "8×1 是什么？", "什么是 8×1？", "请解释一下 Fast8", "如何生成图片？", "How do I generate an image?",
  ]) assert.equal(classifyImageTaskRequest({ message }), null, message);
  assert.equal(classifyImageTaskRequest({ message: "先只讨论，不要修图", retouchContext: true }), null);
});

test("negated modes do not override a positive one-image request", () => {
  for (const message of [
    "请给 P01 生成一张图片，不要 Fast8", "不是 8×1，请生成 P01 的图片",
    "Generate one image for P01, no Fast8.", "不要改大纲，请为 P01 生成图片",
    "Generate one image for P01. Do not use Fast8.", "生成 P01 的图片\n不使用 Fast8",
    "不要生成 P02 的图片，改为生成 P01 的图片",
  ]) assert.deepEqual(classifyImageTaskRequest({ message }), {
    kind: "image", mode_hint: "image_generation", title: "P01 · 作图",
  }, message);
  assert.equal(classifyImageTaskRequest({ message: "能帮我生成一张图片吗？" })?.kind, "image");
});
