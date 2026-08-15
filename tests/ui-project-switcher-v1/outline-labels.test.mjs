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
