import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const workspace = fs.readFileSync(path.join(root, "web/selector/workspace.js"), "utf8");
const css = fs.readFileSync(path.join(root, "web/selector/styles.css"), "utf8");

test("selector actionbar has one concise export entry and a lightweight dialog", () => {
  assert.equal((workspace.match(/data-export-open>/g) || []).length, 1);
  assert.match(workspace, /data-export-open>导出成品</);
  assert.match(workspace, /data-export-generate hidden>生成成品</);
  assert.match(workspace, /data-export-open-folder>打开导出文件夹</);
  assert.match(workspace, /data-export-result-open-folder>打开本次成品文件夹</);
  assert.match(css, /\.selector-export-dialog \{[^}]*width: min\(92vw, 560px\)/s);
});

test("export UI offers three selectable deliverables and hides engineering artifacts", () => {
  const markup = workspace.match(/shell\.innerHTML = `([\s\S]*?)`;\n  root\.classList/)?.[1] || "";
  for (const format of ["pptx", "pdf", "images_zip"]) {
    assert.match(markup, new RegExp(`value="${format}" data-export-format`));
  }
  assert.match(markup, /PPTX/);
  assert.match(markup, /PDF/);
  assert.match(markup, /图片集 ZIP/);
  assert.match(workspace, /view\.exportFormats = \[\.\.\.view\.exportReadiness\.formats\]/);
  assert.doesNotMatch(markup, /manifest|qa_download|sha256|sensitivity_label|output_slide_count|export_id/);
});

test("only a ready export can call the single generation action", () => {
  assert.match(workspace, /view\.exportFormats\.length === 0/);
  assert.equal((workspace.match(/api\.createExport\(view\.deckId,/g) || []).length, 1);
  assert.match(workspace, /formats: view\.exportFormats/);
  assert.match(workspace, /error\?\.status === 409/);
});

test("the export dialog explains that it reads selected images instead of requiring every page", () => {
  assert.match(workspace, /正在读取已选中的图片/);
  assert.match(workspace, /还没有已选图片/);
  assert.doesNotMatch(workspace, /正在确认每一页是否已经选好图片/);
});

test("completed local exports open Finder and never offer browser downloads", () => {
  assert.match(workspace, /已保存在本机的/);
  assert.match(workspace, /artifact\.filename/);
  assert.match(workspace, /api\.openExportFolder\(view\.deckId, view\.exportResult\.export_id\)/);
  assert.doesNotMatch(workspace, /下载副本|artifact\.download_url|element\("a", "selector-export-file"\)/);
});
