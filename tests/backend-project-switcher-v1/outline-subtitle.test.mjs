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

test("a unified multilingual outline accepts the explicit Chinese core thesis header", () => {
  const outline = parse(`---
deck_uid: STUDIO_MULTILINGUAL_CHINESE_HEADER_TEST
slide_uids:
  P1: slide-multilingual-chinese-header
---

| 页码 | 客户钩子／页面标题 | 中文核心命题 | 信息密度／上屏层级 | 页面必讲内容 | English Page Content | 双语交付策略 | 同页双语配对 | 视觉表达目标／用户硬约束 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | 客户标题 | 中文命题 | 高｜一级 | 中文必讲内容 | **English Title:** Customer Title<br>**English Core Thesis:** Core thesis.<br>**English Display Content:** Required content. | **bilingual_strategy:** split_zh_en | — | 保持事实一致 |
`);

  assert.equal(outline.slides[0].multilingual.chinese.core_thesis, "中文命题");
  assert.equal(outline.slides[0].multilingual.english_page_content.includes("<br>"), true);
});

test("escaped pipes inside bilingual copy remain content instead of shifting table columns", () => {
  const outline = parse(`---
deck_uid: STUDIO_MULTILINGUAL_ESCAPED_PIPE_TEST
slide_uids:
  P11: slide-multilingual-escaped-pipe
---

| 页码 | 客户钩子／页面标题 | 核心命题 | 信息密度／上屏层级 | 页面必讲内容 | English Page Content | 双语交付策略 | 同页双语配对 | 视觉表达目标／用户硬约束 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P11 | 海外项目方案 | 中文命题 | 高｜一级 | 中文必讲内容 | **English Title:** Proposal<br>**English Display Content:** **Risk Pattern \\| Clarify Early.** and **Joint Response \\| Build Together.** | **bilingual_strategy:** same_page | 风险规律 ⇄ Risk Pattern \\| Clarify Early. | 第一视觉重点是风险规律；第二视觉重点是共同回应。 |
`);

  const slide = outline.slides[0];
  assert.equal(slide.column_count, 9);
  assert.equal(slide.multilingual.bilingual_strategy, "bilingual_strategy: same_page");
  assert.equal(slide.multilingual.same_page_pairing, "风险规律 ⇄ Risk Pattern | Clarify Early.");
  assert.equal(
    slide.multilingual.visual_constraints,
    "第一视觉重点是风险规律；第二视觉重点是共同回应。",
  );
  assert.match(slide.multilingual.english_page_content, /Risk Pattern \| Clarify Early/);
});
