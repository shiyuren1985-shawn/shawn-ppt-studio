import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmod, mkdir, mkdtemp, readFile, readdir, realpath, rm, stat, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { verifyPreservedPublicLabel } from "../../server/export-office-label.mjs";
import { DEFAULT_EXPORT_RUNTIME, probeExportRuntime, runProcess } from "../../server/export-runtime.mjs";
import { ExportNotReadyError, ExportService, publicReadiness } from "../../server/export-service.mjs";

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAABAAAAAJCAIAAAC0SDtlAAAAGElEQVR4nGP8z0AaYCJRPcOoBmIAyaEEAMeRAREzvAXuAAAAAElFTkSuQmCC",
  "base64",
);

const PNG_HASH = createHash("sha256").update(PNG).digest("hex");

async function fixture({ missingSecond = false, emptyAll = false, enablePptx = false, openFolder = null, runtime = DEFAULT_EXPORT_RUNTIME } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-export-v1-"));
  const first = path.join(root, "first.png");
  const second = path.join(root, "second.png");
  await Promise.all([writeFile(first, PNG), writeFile(second, PNG)]);
  const slides = [
    { order: 1, page_label: "P01", page_id: "P1", slide_uid: "slide-1", title: "第一页" },
    { order: 2, page_label: "P02", page_id: "P2", slide_uid: "slide-2", title: "第二页" },
  ];
  const deck = {
    deck_id: "demo",
    label: "测试 PPT",
    source_kind: "studio",
    project_root: root,
    config_path: null,
    outline: { deck_uid: "deck-demo", revision_id: "sha256:test", slides },
  };
  const selections = new Map([
    ["slide-1", emptyAll ? {
      status: "empty",
      confirmed: false,
      selected_candidates: [],
    } : {
      status: "selected",
      confirmed: true,
      selected_candidates: [
        { candidate_id: "one", path: first, file_sha256: PNG_HASH, width: 16, height: 9 },
        { candidate_id: "two", path: second, file_sha256: PNG_HASH, width: 16, height: 9 },
      ],
    }],
    ["slide-2", (missingSecond || emptyAll) ? {
      status: "empty",
      confirmed: false,
      selected_candidates: [],
    } : {
      status: "selected",
      confirmed: true,
      selected_candidates: [
        { candidate_id: "three", path: first, file_sha256: PNG_HASH, width: 16, height: 9 },
      ],
    }],
  ]);
  const service = new ExportService({
    runtime,
    discovery: { readDeck: async () => deck },
    selectionProjection: { get: async (_deckId, slideUid) => selections.get(slideUid) },
    integrationPath: path.resolve("integrations/export-image-deck.mjs"),
    idFactory: () => "export-test",
    clock: () => new Date("2026-08-13T12:00:00Z"),
    exportRoot: path.join(root, "Shawn PPT Studio Exports"),
    publicLabelTemplate: enablePptx ? path.resolve("assets/Public_Label_Template.pptx") : null,
    officeLabelVerifier: enablePptx ? verifyPreservedPublicLabel : null,
    openFolder,
  });
  await service.initialize();
  return { root, service, selections, deck, first };
}

test("readiness exports selected pages and treats unselected pages as non-blocking omissions", async (t) => {
  const { root, service } = await fixture({ missingSecond: true });
  t.after(() => rm(root, { recursive: true, force: true }));
  const result = publicReadiness(await service.readiness("demo"));
  assert.equal(result.ready, true);
  assert.equal(result.selected_page_count, 1);
  assert.equal(result.skipped_page_count, 1);
  assert.equal(result.output_slide_count, 2);
  assert.equal(result.multi_variant_page_count, 1);
  assert.deepEqual(result.missing_pages, []);
  assert.deepEqual(result.skipped_pages.map((item) => item.slide_uid), ["slide-2"]);
  assert.match(result.message, /已选择 1 页，共 2 张图片.*其余 1 页本次不会导出/);
  assert.equal(result.capabilities.pptx.available, false);
  assert.deepEqual(result.formats, ["pdf", "images_zip"]);

  const exported = await service.create("demo", { name: "部分页面", formats: ["pdf"] });
  assert.equal(exported.slide_count, 2);
  const manifest = JSON.parse(await readFile((await service.resolveFile("demo", "export-test", "manifest")).path, "utf8"));
  assert.deepEqual(manifest.pages.map((item) => item.candidate_id), ["one", "two"]);
  assert.deepEqual(manifest.pages.map((item) => item.page_label), ["P01", "P01"]);
});

test("a deck with no selected image remains blocked", async (t) => {
  const { root, service } = await fixture({ emptyAll: true });
  t.after(() => rm(root, { recursive: true, force: true }));
  const result = publicReadiness(await service.readiness("demo"));
  assert.equal(result.ready, false);
  assert.equal(result.selected_page_count, 0);
  assert.equal(result.output_slide_count, 0);
  assert.equal(result.missing_pages.length, 1);
  assert.match(result.message, /还没有选中任何图片/);
  await assert.rejects(service.create("demo"), ExportNotReadyError);
});

test("export preserves outline and per-page selection order and delivers verified PDF plus page ZIP", async (t) => {
  const { root, service } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const result = await service.create("demo", { name: "客户评审版" });
  assert.equal(result.status, "completed_with_warnings");
  assert.equal(result.slide_count, 3);
  assert.equal(result.artifacts.pptx, null);
  assert.ok(result.artifacts.pdf.size > 0);
  assert.ok(result.artifacts.images_zip.size > 0);
  assert.match(result.warnings[0].message, /Public 标签模板/);

  const manifestFile = await service.resolveFile("demo", "export-test", "manifest");
  const manifest = JSON.parse(await readFile(manifestFile.path, "utf8"));
  assert.deepEqual(manifest.pages.map((item) => item.candidate_id), ["one", "two", "three"]);
  assert.equal(JSON.stringify(manifest).includes("source_path"), false);
  assert.equal(manifest.pages[0].filename, "001_P01-A.png");
  assert.equal(manifest.pages[1].filename, "002_P01-B.png");
  assert.equal(manifest.pages[2].filename, "003_P02.png");

  const qaFile = await service.resolveFile("demo", "export-test", "qa");
  const qa = JSON.parse(await readFile(qaFile.path, "utf8"));
  assert.equal(qa.pdf.page_count, 3);
  assert.equal(qa.pdf.rendered_page_count, 3);
  assert.equal(qa.selection_source, "canonical");
  await assert.rejects(service.resolveFile("demo", "export-test", "pptx"), /找不到/);
  assert.ok((await stat(path.join(root, "Shawn PPT Studio Exports", "测试 PPT", "export-test", "客户评审版.pdf"))).isFile());
});

test("image-only PPTX is Public-labelled and all three formats share the fixed export folder", async (t) => {
  const opened = [];
  const { root, service } = await fixture({ enablePptx: true, openFolder: async (folder) => opened.push(folder) });
  t.after(() => rm(root, { recursive: true, force: true }));

  const readiness = publicReadiness(await service.readiness("demo"));
  assert.deepEqual(readiness.formats, ["pptx", "pdf", "images_zip"]);
  assert.equal(readiness.capabilities.pptx.available, true);

  await service.showRootInFinder();
  assert.equal(opened[0], path.join(root, "Shawn PPT Studio Exports"));

  const result = await service.create("demo", { name: "客户评审版" });
  assert.equal(result.status, "completed");
  assert.equal(result.output_folder_name, "Shawn PPT Studio Exports");
  assert.equal(result.artifacts.pptx.sensitivity_label.verified, true);
  assert.equal(result.artifacts.pptx.sensitivity_label.name, "Public");
  assert.ok(result.artifacts.pptx.size > 0);
  assert.ok(result.artifacts.pdf.size > 0);
  assert.ok(result.artifacts.images_zip.size > 0);

  const pptx = await service.resolveFile("demo", "export-test", "pptx");
  assert.equal(pptx.root, await realpath(path.join(root, "Shawn PPT Studio Exports", "测试 PPT", "export-test")));
  await assert.rejects(stat(path.join(pptx.root, "pages")), (error) => error.code === "ENOENT");
  await service.showInFinder("demo", "export-test");
  assert.equal(opened[1], pptx.root);

  const qa = JSON.parse(await readFile((await service.resolveFile("demo", "export-test", "qa")).path, "utf8"));
  assert.deepEqual(qa.pptx, { page_count: 3, rendered_page_count: 3 });
});

test("an explicit format selection creates only the requested deliverable", async (t) => {
  const { root, service } = await fixture({ enablePptx: true });
  t.after(() => rm(root, { recursive: true, force: true }));

  const result = await service.create("demo", { name: "仅 PDF", formats: ["pdf"] });
  assert.equal(result.status, "completed");
  assert.deepEqual(result.formats, ["pdf"]);
  assert.equal(result.artifacts.pptx, null);
  assert.ok(result.artifacts.pdf.size > 0);
  assert.equal(result.artifacts.images_zip, null);
  assert.deepEqual(result.warnings, []);

  const exportRoot = path.join(root, "Shawn PPT Studio Exports", "测试 PPT", "export-test");
  assert.ok((await stat(path.join(exportRoot, "仅 PDF.pdf"))).isFile());
  await assert.rejects(stat(path.join(exportRoot, "仅 PDF.pptx")), (error) => error.code === "ENOENT");
  await assert.rejects(stat(path.join(exportRoot, "仅 PDF-页面图片.zip")), (error) => error.code === "ENOENT");
  const qa = JSON.parse(await readFile(path.join(exportRoot, "qa.json"), "utf8"));
  assert.deepEqual(qa.formats, ["pdf"]);
  assert.equal(qa.pptx, null);
  assert.equal(qa.images_zip, null);
});

test("an image-set-only export creates its ZIP without PDF, PPTX, or loose page copies", async (t) => {
  const { root, service } = await fixture({ enablePptx: true });
  t.after(() => rm(root, { recursive: true, force: true }));

  const result = await service.create("demo", { name: "仅图片集", formats: ["images_zip"] });
  assert.equal(result.status, "completed");
  assert.deepEqual(result.formats, ["images_zip"]);
  assert.equal(result.artifacts.pptx, null);
  assert.equal(result.artifacts.pdf, null);
  assert.ok(result.artifacts.images_zip.size > 0);

  const exportRoot = path.join(root, "Shawn PPT Studio Exports", "测试 PPT", "export-test");
  assert.ok((await stat(path.join(exportRoot, "仅图片集-页面图片.zip"))).isFile());
  await assert.rejects(stat(path.join(exportRoot, "仅图片集.pdf")), (error) => error.code === "ENOENT");
  await assert.rejects(stat(path.join(exportRoot, "仅图片集.pptx")), (error) => error.code === "ENOENT");
  await assert.rejects(stat(path.join(exportRoot, "pages")), (error) => error.code === "ENOENT");
  const qa = JSON.parse(await readFile(path.join(exportRoot, "qa.json"), "utf8"));
  assert.deepEqual(qa.images_zip, { file_count: 3 });
});

test("empty, unknown, and unavailable explicit format selections are rejected", async (t) => {
  const { root, service } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  await assert.rejects(
    service.create("demo", { formats: [] }),
    (error) => error.code === "invalid_export_formats",
  );
  await assert.rejects(
    service.create("demo", { formats: ["docx"] }),
    (error) => error.code === "invalid_export_formats",
  );
  await assert.rejects(
    service.create("demo", { formats: ["pptx"] }),
    (error) => error.code === "export_format_unavailable",
  );
});

test("invalid names are rejected before creating an export directory", async (t) => {
  const { root, service } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  await assert.rejects(service.create("demo", { name: "   " }), (error) => error.code === "invalid_export_name");
});


test("ZIP and PDF remain available without PowerPoint and Finder dependencies", async (t) => {
  const runtime = { ...DEFAULT_EXPORT_RUNTIME, node: "/missing/node", artifactToolEntry: "/missing/artifact", soffice: "/missing/soffice", open: "/missing/open" };
  const { root, service } = await fixture({ enablePptx: true, runtime });
  t.after(() => rm(root, { recursive: true, force: true }));
  const readiness = await service.readiness("demo");
  assert.equal(readiness.ready, true);
  assert.deepEqual(readiness.formats, ["pdf", "images_zip"]);
  const exported = await service.create("demo", { formats: ["images_zip"] });
  assert.ok(exported.artifacts.images_zip.size > 0);
  const zipOnly = await probeExportRuntime({ ...runtime, pdfinfo: "/missing/pdfinfo", pdftoppm: "/missing/pdftoppm" });
  assert.equal(zipOnly.formats.images_zip.available, true);
  assert.equal(zipOnly.formats.pdf.available, false);
});

test("a changed selection fails before publishing and can retry after correction", async (t) => {
  const { root, service, first } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  await writeFile(first, "changed source");
  await assert.rejects(service.create("demo", { formats: ["images_zip"] }), (error) => error.code === "export_image_changed");
  assert.deepEqual(await readdir(path.join(service.exportRoot, "测试 PPT")), []);
  await writeFile(first, PNG);
  assert.equal((await service.create("demo", { formats: ["images_zip"] })).status, "completed");
});

test("even a matching selected hash cannot export an undecodable PNG in a ZIP", async (t) => {
  const { root, service, first, selections } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const broken = PNG.subarray(0, 40);
  await writeFile(first, broken);
  for (const selection of selections.values()) for (const item of selection.selected_candidates) {
    if (item.path === first) item.file_sha256 = createHash("sha256").update(broken).digest("hex");
  }
  await assert.rejects(service.create("demo", { formats: ["images_zip"] }), (error) => error.code === "export_image_invalid" && error.statusCode === 409);
  assert.deepEqual(await readdir(path.join(service.exportRoot, "测试 PPT")), []);
});

test("same-deck duplicate exports are rejected while a render is active", async (t) => {
  const { root, service } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const first = service.create("demo", { formats: ["images_zip"] });
  await assert.rejects(service.create("demo", { formats: ["images_zip"] }), (error) => error.code === "export_in_progress");
  assert.equal((await first).status, "completed");
});

test("failed explicit PPTX leaves no half export and a later ZIP retry succeeds", async (t) => {
  const { root, service } = await fixture({ enablePptx: true });
  t.after(() => rm(root, { recursive: true, force: true }));
  service.integrationPath = path.join(root, "missing-integration.mjs");
  await assert.rejects(service.create("demo", { formats: ["pdf", "pptx"] }), (error) => error.code === "pptx_export_failed");
  assert.deepEqual(await readdir(path.join(service.exportRoot, "测试 PPT")), []);
  assert.equal((await service.create("demo", { formats: ["images_zip"] })).status, "completed");
});

test("implicit PPTX failure reports only formats actually delivered", async (t) => {
  const { root, service } = await fixture({ enablePptx: true });
  t.after(() => rm(root, { recursive: true, force: true }));
  service.integrationPath = path.join(root, "missing-integration.mjs");
  const result = await service.create("demo");
  assert.deepEqual(result.formats, ["pdf", "images_zip"]);
  assert.equal(result.warnings[0].code, "pptx_export_failed");
  const manifest = JSON.parse(await readFile((await service.resolveFile("demo", "export-test", "manifest")).path, "utf8"));
  assert.deepEqual(manifest.formats, result.formats);
});

test("download resolution rejects dot IDs, symlinks, sidecar escapes and a different deck", async (t) => {
  const { root, service, deck } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  await service.create("demo", { formats: ["images_zip"] });
  const output = path.join(service.exportRoot, "测试 PPT", "export-test");
  for (const id of [".", "..", ".export-test.working"]) {
    await assert.rejects(service.resolveFile("demo", id, "manifest"), (error) => error.code === "export_not_found");
  }
  const resultPath = path.join(output, ".result.json");
  const result = JSON.parse(await readFile(resultPath, "utf8"));
  result.artifacts.images_zip.filename = "../../secret.txt";
  await writeFile(resultPath, JSON.stringify(result));
  await assert.rejects(service.resolveFile("demo", "export-test", "images_zip"), (error) => error.code === "file_not_found");
  await writeFile(path.join(root, "secret.txt"), "private");
  await symlink(path.join(root, "secret.txt"), path.join(output, "linked.zip"));
  result.artifacts.images_zip.filename = "linked.zip";
  await writeFile(resultPath, JSON.stringify(result));
  await assert.rejects(service.resolveFile("demo", "export-test", "images_zip"), (error) => error.code === "file_not_found");
  const external = path.join(root, "external");
  await mkdir(external);
  await symlink(external, path.join(service.exportRoot, "测试 PPT", "linked-export"));
  await assert.rejects(service.resolveFile("demo", "linked-export", "manifest"), (error) => error.code === "export_not_found");
  deck.deck_id = "different-deck";
  await assert.rejects(service.resolveFile("different-deck", "export-test", "manifest"), (error) => error.code === "export_not_found");
});

test("stuck export tools time out and release the operation", async () => {
  await assert.rejects(runProcess(DEFAULT_EXPORT_RUNTIME.node, ["-e", "setInterval(()=>{}, 1000)"], { timeoutMs: 50 }), (error) => error.code === "export_tool_timeout");
});


test("all formats keep the selected snapshot when the original changes during PDF generation", async (t) => {
  const { root, service, first } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  const wrapper = path.join(root, "mutating-python");
  const program = `#!${DEFAULT_EXPORT_RUNTIME.python}\nimport os,sys\nfrom pathlib import Path\nif any('pdf=canvas.Canvas' in arg for arg in sys.argv):\n    Path(${JSON.stringify(first)}).write_bytes(b'changed during PDF export')\nos.execv(${JSON.stringify(DEFAULT_EXPORT_RUNTIME.python)}, [${JSON.stringify(DEFAULT_EXPORT_RUNTIME.python)}] + sys.argv[1:])\n`;
  await writeFile(wrapper, program);
  await chmod(wrapper, 0o755);
  service.runtime = { ...DEFAULT_EXPORT_RUNTIME, python: wrapper };
  const result = await service.create("demo", { formats: ["pdf", "images_zip"] });
  assert.equal(await readFile(first, "utf8"), "changed during PDF export");
  const zip = await service.resolveFile("demo", result.export_id, "images_zip");
  const inspection = await runProcess(DEFAULT_EXPORT_RUNTIME.python, ["-c", "import hashlib,json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); print(json.dumps([hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith('/')]))", zip.path]);
  assert.deepEqual(JSON.parse(inspection.stdout), [PNG_HASH, PNG_HASH, PNG_HASH]);
  assert.equal(result.artifacts.pdf.size > 0, true);
});


test("project and page labels cannot become export paths", async (t) => {
  const { root, service, deck } = await fixture();
  t.after(() => rm(root, { recursive: true, force: true }));
  deck.label = "../../outside";
  deck.outline.slides[0].page_label = "../../../outside";
  const result = await service.create("demo", { formats: ["images_zip"] });
  assert.equal(result.artifacts.images_zip.filename.includes("/"), false);
  const resolved = await service.resolveFile("demo", result.export_id, "images_zip");
  assert.equal(resolved.root.startsWith(await realpath(service.exportRoot) + path.sep), true);
  const inspection = await runProcess(DEFAULT_EXPORT_RUNTIME.python, ["-c", "import json,sys,zipfile; print(json.dumps(zipfile.ZipFile(sys.argv[1]).namelist()))", resolved.path]);
  assert.equal(JSON.parse(inspection.stdout).some((name) => name.includes("../")), false);
});
