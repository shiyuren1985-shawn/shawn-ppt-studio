import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { outlineReadingModel, scopeFromSlide } from "../../web/model.js";

const app = await readFile(new URL("../../web/app.js", import.meta.url), "utf8");

test("outline reading keeps an explicit subtitle separate from the title and body", () => {
  const model = outlineReadingModel(
    "| P1 | 第一次做北美项目 | 丰品如何把陌生要求变成讲得清的方案 | 客户需要可执行路径 |",
    "",
    "丰品如何把陌生要求变成讲得清的方案",
  );

  assert.equal(model.title, "第一次做北美项目");
  assert.equal(model.subtitle, "丰品如何把陌生要求变成讲得清的方案");
  assert.deepEqual(model.sections, [{ label: "核心表达", value: "客户需要可执行路径" }]);
});

test("slide scope and outline UI expose labels without fabricating a subtitle", () => {
  const scope = scopeFromSlide({
    deck_id: "deck-a",
    deck_uid: "DECK_A",
    revision_id: "sha256:test",
    sha256: "test",
    outline_path: "/tmp/outline.md",
    slide: {
      page_id: "P1",
      page_label: "P01",
      slide_uid: "slide-a",
      title: "只有标题",
      subtitle: null,
      markdown: "| P1 | 只有标题 | 内容 |",
    },
  });

  assert.equal(scope.subtitle, null);
  assert.match(app, /appendField\("标题", model\.title/);
  assert.match(app, /if \(model\.subtitle\) appendField\("副标题"/);
});

test("multilingual outlines default to a combined view with Chinese and English filters", () => {
  const multilingual = {
    chinese: {
      core_thesis: "中文命题",
      density: "中｜一级＋必要二级",
      required_content: "中文必讲内容",
    },
    english_page_content: "English Title: Overseas Delivery<br>English Core Thesis: Deliver with certainty.<br>English Display Content: One accountable system.",
    bilingual_strategy: "bilingual_strategy: same_page",
    same_page_pairing: "海外交付 ⇄ Overseas Delivery",
    visual_constraints: "保持清楚的责任关系",
  };

  const combined = outlineReadingModel("", "海外交付", "", multilingual, "bilingual");
  assert.equal(combined.title, "海外交付");
  assert.ok(combined.sections.some((section) => section.label === "English Title"));
  assert.ok(combined.sections.some((section) => section.label === "页面必讲内容"));

  const english = outlineReadingModel("", "海外交付", "", multilingual, "en");
  assert.equal(english.title, "Overseas Delivery");
  assert.deepEqual(english.sections.map((section) => section.label), [
    "English Core Thesis",
    "English Display Content",
  ]);

  const chinese = outlineReadingModel("", "海外交付", "", multilingual, "zh");
  assert.equal(chinese.sections.some((section) => section.label.startsWith("English")), false);
  assert.match(app, /data-outline-language/);
});
