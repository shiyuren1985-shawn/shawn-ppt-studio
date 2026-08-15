import assert from "node:assert/strict";
import test from "node:test";

import { parseOutlineText } from "../../server/discovery.mjs";

function parse(text) {
  const bytes = Buffer.from(text);
  return parseOutlineText({
    text,
    bytes,
    outlinePath: "/tmp/studio-outline-subtitle.md",
    info: { mtimeMs: 0, size: bytes.length },
  });
}

test("an explicit subtitle column is preserved without inventing missing subtitles", () => {
  const outline = parse(`---
deck_uid: STUDIO_SUBTITLE_TEST
slide_uids:
  P1: slide-title-and-subtitle
  P2: slide-title-only
---

| 页码 | 标题 | 副标题 | 内容 |
| --- | --- | --- | --- |
| P1 | 第一次做北美项目 | 丰品如何把陌生要求变成讲得清的方案 | 客户需要可执行路径 |
| P2 | 只有标题的一页 |  | 不应补写副标题 |
`);

  assert.equal(outline.slides[0].title, "第一次做北美项目");
  assert.equal(outline.slides[0].subtitle, "丰品如何把陌生要求变成讲得清的方案");
  assert.equal(outline.slides[1].subtitle, null);
});

test("subtitle wording inside content is not mistaken for structured metadata", () => {
  const outline = parse(`---
deck_uid: STUDIO_SUBTITLE_CONTENT_TEST
slide_uids:
  P1: slide-content-mention
---

| 页码 | 标题 | 内容 |
| --- | --- | --- |
| P1 | 主标题 | 视觉中可以出现副标题，但这里不是结构化字段 |
`);

  assert.equal(outline.slides[0].subtitle, null);
});
