import assert from "node:assert/strict";
import test from "node:test";
import { parseOutlineText } from "../../server/discovery.mjs";

for (const newline of ["\n", "\r\n"]) {
  for (const headers of [
    ["页码", "标题", "内容", "页面说明", "视觉约束"],
    ["页码", "客户钩子／页面标题", "核心命题", "信息密度／上屏层级", "页面必讲内容", "页面说明／资产引用", "视觉表达目标／用户硬约束"],
  ]) {
    test(`${headers.length}-column outline retains source labels and empty cells with ${JSON.stringify(newline)} line endings`, () => {
      const cells = headers.map((header, index) => index === 0 ? "P1" : index === 1 ? "标题" : index === 2 || index === headers.length - 1 ? "" : `值${index}`);
      const text = ["---", "deck_uid: DECK", "slide_uids:", "  P1: SLIDE", "---", `| ${headers.join(" | ")} |`, `| ${headers.map(() => "---").join(" | ")} |`, `| ${cells.join(" | ")} |`, ""].join(newline);
      const outline = parseOutlineText({ text, bytes: Buffer.from(text), outlinePath: "/tmp/outline.md", info: { mtimeMs: 0, size: Buffer.byteLength(text) } });
      assert.deepEqual(outline.slides[0].table_headers, headers);
      assert.deepEqual(outline.slides[0].table_cells, cells);
      assert.equal(outline.slides[0].table_cells[2], "");
      assert.equal(outline.slides[0].table_cells.at(-1), "");
      assert.equal(outline.text, text);
    });
  }
}
