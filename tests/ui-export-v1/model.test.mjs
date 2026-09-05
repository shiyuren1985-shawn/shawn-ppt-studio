import assert from "node:assert/strict";
import test from "node:test";

import { exportFormatsCopy, normalizeExportReadiness, normalizeExportResult } from "../../web/selector/model.js";

test("readiness turns missing pages into concise user-facing rows", () => {
  const value = normalizeExportReadiness({
    ready: false,
    message: "还有 2 页需要确认图片",
    logical_page_count: 12,
    output_slide_count: 10,
    missing_pages: [
      { slide_uid: "secret", page_label: "P03", title: "交付路径", reason: "unconfirmed", message: "请选择准备使用的图片" },
      { slide_uid: "secret-2", page_label: "P07", title: "案例", reason: "missing", message: "这一页还没有可用图片" },
    ],
  });
  assert.equal(value.ready, false);
  assert.deepEqual(value.missing_pages, [
    { page_label: "P03", title: "交付路径", message: "请选择准备使用的图片" },
    { page_label: "P07", title: "案例", message: "这一页还没有可用图片" },
  ]);
  assert.doesNotMatch(JSON.stringify(value), /slide_uid|reason|secret/);
});

test("partial selection is ready and reports how many pages will be skipped", () => {
  const value = normalizeExportReadiness({
    ready: true,
    logical_page_count: 12,
    selected_page_count: 7,
    skipped_page_count: 5,
    output_slide_count: 8,
    missing_pages: [],
    message: "已选择 7 页，共 8 张图片；其余 5 页本次不会导出。",
    formats: ["pptx", "pdf", "images_zip"],
  });
  assert.equal(value.ready, true);
  assert.equal(value.selected_page_count, 7);
  assert.equal(value.skipped_page_count, 5);
  assert.equal(value.output_slide_count, 8);
  assert.match(value.message, /其余 5 页本次不会导出/);
});

test("completed export exposes only the three local artifact names", () => {
  const value = normalizeExportResult({
    status: "completed",
    export_id: "result-1",
    name: "EPC 成品",
    manifest_download_url: "/hidden/manifest",
    qa_download_url: "/hidden/qa",
    artifacts: {
      pptx: { filename: "deck.pptx", download_url: "/api/decks/epc/exports/result-1/files/pptx", sha256: "hidden" },
      pdf: { filename: "deck.pdf", download_url: "/api/decks/epc/exports/result-1/files/pdf", sha256: "hidden" },
      images_zip: { filename: "pages.zip", download_url: "/api/decks/epc/exports/result-1/files/images_zip", sha256: "hidden" },
    },
  });
  assert.deepEqual(value.artifacts.map((item) => item.label), ["图片版 PPTX（Public）", "图片版 PDF", "图片集 ZIP"]);
  assert.deepEqual(value.artifacts.map((item) => item.filename), ["deck.pptx", "deck.pdf", "pages.zip"]);
  assert.doesNotMatch(JSON.stringify(value), /sha256|manifest|qa|download_url/);
});

test("result never exposes browser download links in the local desktop UI", () => {
  const value = normalizeExportResult({
    status: "completed",
    export_id: "result-1",
    artifacts: {
      pptx: { download_url: "https://example.com/deck.pptx" },
      pdf: { download_url: "/api/decks/epc/exports/result-1/files/pdf" },
      images_zip: { download_url: "/api/decks/epc/exports/result-1/files/images_zip" },
    },
  });
  assert.equal(value.artifacts.length, 3);
  assert.doesNotMatch(JSON.stringify(value), /download_url|example\.com|\/files\//);
});

test("missing PPTX label template keeps PDF and image ZIP available with one plain warning", () => {
  const readiness = normalizeExportReadiness({
    ready: true,
    formats: ["pdf", "images_zip"],
    warnings: [{
      code: "pptx_label_template_unavailable",
      message: "需要公司标签模板后才能生成 PPTX。",
    }],
  });
  assert.equal(readiness.ready, true);
  assert.deepEqual(readiness.formats, ["pdf", "images_zip"]);
  assert.equal(readiness.warning, "需要公司标签模板后才能生成 PPTX。");

  const result = normalizeExportResult({
    status: "completed_with_warnings",
    export_id: "result-2",
    warnings: [{ code: "pptx_label_template_unavailable", message: "需要公司标签模板后才能生成 PPTX。" }],
    artifacts: {
      pptx: null,
      pdf: { filename: "deck.pdf", download_url: "/api/decks/epc/exports/result-2/files/pdf" },
      images_zip: { filename: "pages.zip", download_url: "/api/decks/epc/exports/result-2/files/images_zip" },
    },
  });
  assert.deepEqual(result.artifacts.map((artifact) => artifact.kind), ["pdf", "images_zip"]);
  assert.equal(result.warning, "需要公司标签模板后才能生成 PPTX。");
});

test("export progress names only formats that are actually available", () => {
  assert.equal(exportFormatsCopy(["pdf", "images_zip"]), "PDF和图片集 ZIP");
  assert.equal(exportFormatsCopy(["pptx", "pdf", "images_zip"]), "PPTX、PDF和图片集 ZIP");
  assert.equal(exportFormatsCopy([]), "成品");
});
