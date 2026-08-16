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

test("a unified multilingual outline exposes deterministic Chinese and English layers", () => {
  const outline = parse(`---
deck_uid: STUDIO_MULTILINGUAL_TEST
slide_uids:
  P1: slide-multilingual
identity_aliases:
  - previous-outline.md
---

| 页码 | 客户钩子／页面标题 | 核心命题 | 信息密度／上屏层级 | 页面必讲内容 | English Page Content | 双语交付策略 | 同页双语配对 | 视觉表达目标／用户硬约束 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | 海外交付 | 中文命题 | 中｜一级＋必要二级 | 中文必讲内容 | **English Title:** Overseas Delivery<br>**English Core Thesis:** Deliver with certainty.<br>**English Display Content:** One accountable system. | **bilingual_strategy:** same_page | 海外交付 ⇄ Overseas Delivery | 保持清楚的责任关系 |
`);

  assert.deepEqual(outline.slides[0].multilingual, {
    default_view: "bilingual",
    chinese: {
      core_thesis: "中文命题",
      density: "中｜一级＋必要二级",
      required_content: "中文必讲内容",
    },
    english_page_content: "English Title: Overseas Delivery<br>English Core Thesis: Deliver with certainty.<br>English Display Content: One accountable system.",
    bilingual_strategy: "bilingual_strategy: same_page",
    same_page_pairing: "海外交付 ⇄ Overseas Delivery",
    visual_constraints: "保持清楚的责任关系",
  });
  assert.deepEqual(outline.identity_aliases, ["/tmp/previous-outline.md"]);
});
