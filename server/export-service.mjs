import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, realpath, rename, rm, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { HttpError } from "./errors.mjs";
import { preserveOfficeLabelMetadata, PUBLIC_LABEL_ID } from "./export-office-label.mjs";
import {
  artifactDescriptor,
  buildPageCopies,
  buildPdf,
  buildPptx,
  DEFAULT_EXPORT_RUNTIME,
  describePageCopies,
  openFolderDetached,
  probeExportRuntime,
  validateSlideImages,
  verifyPdf,
  verifyPptxRender,
  writeJson,
  zipPages,
} from "./export-runtime.mjs";

const CONTRACT_VERSION = 1;
const EXPORT_FORMATS = Object.freeze(["pptx", "pdf", "images_zip"]);
export const DEFAULT_STUDIO_EXPORT_ROOT = path.join(os.homedir(), "Documents", "Shawn PPT Studio Exports");
const PPTX_WARNING = Object.freeze({
  code: "pptx_label_template_unavailable",
  message: "Public 标签模板暂时不可用，因此这次没有生成 PPTX。",
});

function safeName(value, fallback) {
  for (const item of [value, fallback]) {
    if (typeof item !== "string") continue;
    const clean = item.normalize("NFKC").replace(/[\\/:*?"<>|\u0000-\u001f]/g, " ").replace(/\s+/g, " ").trim();
    if (clean && !/^\.+$/.test(clean)) return clean.slice(0, 80);
  }
  return "未命名导出";
}

function exportId(now = new Date(), suffix = randomUUID().slice(0, 8)) {
  const timestamp = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  return `${timestamp}-${suffix}`;
}

function normalizeRequestedFormats(value, availableFormats, capabilities = {}) {
  if (value === null || value === undefined) return [...availableFormats];
  if (!Array.isArray(value) || value.length === 0) {
    throw new HttpError(400, "请至少选择一种导出格式。", "invalid_export_formats");
  }
  const formats = [...new Set(value)];
  if (formats.some((format) => typeof format !== "string" || !EXPORT_FORMATS.includes(format))) {
    throw new HttpError(400, "导出格式无效。", "invalid_export_formats");
  }
  const unavailable = formats.filter((format) => !availableFormats.includes(format));
  if (unavailable.length) {
    throw new HttpError(
      409,
      capabilities[unavailable[0]]?.message || "所选导出格式暂时不可用。",
      "export_format_unavailable",
    );
  }
  return EXPORT_FORMATS.filter((format) => formats.includes(format));
}

function missingPage(slide, reason, detail = null) {
  const message = reason === "no_selection"
    ? `${slide.page_label} 还没有确认选图。`
    : reason === "selection_unavailable"
      ? `${slide.page_label} 的选稿记录暂时无法读取。`
      : `${slide.page_label} 的选稿尚未确认。`;
  return {
    slide_uid: slide.slide_uid,
    page_label: slide.page_label,
    title: slide.title,
    reason,
    message: detail || message,
  };
}

function publicPage(slide, projection) {
  const selected = projection?.status === "selected"
    && projection?.confirmed === true
    && Array.isArray(projection.selected_candidates)
    && projection.selected_candidates.length > 0;
  return {
    order: slide.order,
    page_label: slide.page_label,
    slide_uid: slide.slide_uid,
    confirmed: selected,
    selected_count: selected ? projection.selected_candidates.length : 0,
  };
}

function exportCandidates(projection) {
  return projection?.status === "selected"
    && projection?.confirmed === true
    && Array.isArray(projection.selected_candidates)
    ? projection.selected_candidates
    : [];
}

async function readableFile(filePath) {
  if (!filePath) return null;
  try {
    return await realpath(filePath);
  } catch {
    return null;
  }
}

export class ExportNotReadyError extends HttpError {
  constructor(readiness) {
    super(409, readiness.message, "export_not_ready");
    this.missingPages = readiness.missing_pages;
  }
}

export class ExportService {
  constructor({
    discovery,
    selectionProjection,
    integrationPath,
    runtime = DEFAULT_EXPORT_RUNTIME,
    publicLabelTemplate = null,
    officeLabelVerifier = null,
    clock = () => new Date(),
    idFactory = null,
    openFolder = null,
    exportRoot = process.env.SHAWN_PPT_STUDIO_EXPORT_ROOT || DEFAULT_STUDIO_EXPORT_ROOT,
  }) {
    this.discovery = discovery;
    this.selectionProjection = selectionProjection;
    this.integrationPath = integrationPath;
    this.runtime = runtime;
    this.publicLabelTemplate = publicLabelTemplate;
    this.officeLabelVerifier = officeLabelVerifier;
    this.clock = clock;
    this.idFactory = idFactory;
    this.openFolder = openFolder;
    this.exportRoot = path.resolve(exportRoot);
    this.activeExports = new Set();
    this.runtimeHealth = { ready: false, missing: [], message: "尚未检查导出运行环境。" };
  }

  async initialize() {
    this.runtimeHealth = await probeExportRuntime(this.runtime);
    if (this.runtimeHealth.ready) await mkdir(this.exportRoot, { recursive: true });
    return this.runtimeHealth;
  }

  health() {
    return { ...this.runtimeHealth };
  }

  async #labelTemplate(deck) {
    if (!this.officeLabelVerifier) return null;
    return readableFile(this.publicLabelTemplate);
  }

  #deckExportRoot(deck) {
    return path.join(this.exportRoot, safeName(deck.label, "未命名项目"));
  }

  async #project(deckId) {
    const deck = await this.discovery.readDeck(deckId);
    const projections = [];
    for (const slide of deck.outline.slides) {
      projections.push(await this.selectionProjection.get(deckId, slide.slide_uid));
    }
    return { deck, projections };
  }

  async readiness(deckId) {
    const { deck, projections } = await this.#project(deckId);
    const missing = [];
    const skipped = [];
    const pages = [];
    for (const [index, slide] of deck.outline.slides.entries()) {
      const projection = projections[index];
      pages.push(publicPage(slide, projection));
      if (exportCandidates(projection).length) {
        continue;
      }
      if (projection?.status === "empty") skipped.push(missingPage(slide, "no_selection"));
      else if (projection?.status === "unavailable") {
        skipped.push(missingPage(slide, "selection_unavailable", projection.message || null));
      } else skipped.push(missingPage(slide, "not_confirmed"));
    }
    if (deck.outline.slides.length === 0) {
      missing.push({
        slide_uid: null,
        page_label: null,
        title: null,
        reason: "outline_empty",
        message: "这份 PPT 还没有页面，暂时不能导出。",
      });
    }
    const labelTemplate = await this.#labelTemplate(deck);
    const capability = (format) => this.runtimeHealth.formats?.[format]
      || { available: Boolean(this.runtimeHealth.ready), message: this.runtimeHealth.message };
    const pptxAvailable = Boolean(capability("pptx").available && labelTemplate);
    const pdfAvailable = capability("pdf").available;
    const zipAvailable = capability("images_zip").available;
    const baseAvailable = pptxAvailable || pdfAvailable || zipAvailable;
    const pptxWarning = labelTemplate
      ? { code: "pptx_runtime_unavailable", message: capability("pptx").message || "PPTX 导出组件暂时不可用。" }
      : PPTX_WARNING;
    const warnings = pptxAvailable ? [] : [pptxWarning];
    const outputSlideCount = projections.reduce(
      (count, projection) => count + exportCandidates(projection).length,
      0,
    );
    const selectedPageCount = projections.filter((projection) => exportCandidates(projection).length > 0).length;
    if (deck.outline.slides.length > 0 && outputSlideCount === 0) {
      missing.push({
        slide_uid: null,
        page_label: null,
        title: null,
        reason: "no_selection",
        message: "请先在选稿台至少选择一张图片。",
      });
    }
    const ready = baseAvailable && outputSlideCount > 0;
    const message = !baseAvailable
      ? this.runtimeHealth.message || pptxWarning.message
      : outputSlideCount === 0
        ? "还没有选中任何图片，请先在选稿台选择要导出的页面。"
        : skipped.length
          ? `已选择 ${selectedPageCount} 页，共 ${outputSlideCount} 张图片；其余 ${skipped.length} 页本次不会导出。`
          : `已选择 ${selectedPageCount} 页，共 ${outputSlideCount} 张图片，可以导出。`;
    return {
      contract_version: CONTRACT_VERSION,
      deck_id: deck.deck_id,
      deck_uid: deck.outline.deck_uid,
      ready,
      logical_page_count: deck.outline.slides.length,
      selected_page_count: selectedPageCount,
      skipped_page_count: skipped.length,
      output_slide_count: outputSlideCount,
      multi_variant_page_count: projections.filter((item) => exportCandidates(item).length > 1).length,
      missing_pages: missing,
      skipped_pages: skipped,
      pages,
      capabilities: {
        pptx: { available: pptxAvailable, message: pptxAvailable ? null : pptxWarning.message },
        pdf: capability("pdf"),
        images_zip: capability("images_zip"),
      },
      formats: [pptxAvailable ? "pptx" : null, pdfAvailable ? "pdf" : null, zipAvailable ? "images_zip" : null].filter(Boolean),
      warnings,
      message,
      _deck: deck,
      _projections: projections,
      _label_template: labelTemplate,
    };
  }

  async create(deckId, options = {}) {
    if (this.activeExports.has(deckId)) {
      throw new HttpError(409, "这个项目正在导出，请等待完成后再试。", "export_in_progress");
    }
    this.activeExports.add(deckId);
    try { return await this.#create(deckId, options); }
    finally { this.activeExports.delete(deckId); }
  }

  async #create(deckId, { name = null, formats = null } = {}) {
    if (name !== null && (typeof name !== "string" || !name.trim())) {
      throw new HttpError(400, "导出名称不能为空。", "invalid_export_name");
    }
    const readiness = await this.readiness(deckId);
    if (!readiness.ready) throw new ExportNotReadyError(readiness);
    const explicitFormats = formats !== null && formats !== undefined;
    const requestedFormats = normalizeRequestedFormats(formats, readiness.formats, readiness.capabilities);
    const wantsPptx = requestedFormats.includes("pptx");
    const wantsPdf = requestedFormats.includes("pdf");
    const wantsImagesZip = requestedFormats.includes("images_zip");
    const deck = readiness._deck;
    const projections = readiness._projections;
    const id = this.idFactory ? this.idFactory() : exportId(this.clock());
    if (!/^[0-9A-Za-z][0-9A-Za-z._-]*$/.test(id || "")) throw new Error("Invalid export id");
    const exportsRoot = this.#deckExportRoot(deck);
    const workingRoot = path.join(exportsRoot, `.${id}.working`);
    const finalRoot = path.join(exportsRoot, id);
    await mkdir(exportsRoot, { recursive: true });
    await mkdir(workingRoot, { recursive: false });
    try {
      const slides = [];
      for (const [pageIndex, slide] of deck.outline.slides.entries()) {
        const candidates = exportCandidates(projections[pageIndex]);
        for (const [variantIndex, candidate] of candidates.entries()) {
          slides.push({
            order: slides.length + 1,
            logical_order: slide.order,
            page_label: slide.page_label,
            slide_uid: slide.slide_uid,
            title: slide.title,
            variant_index: variantIndex + 1,
            variant_label: candidates.length > 1 ? String.fromCharCode(65 + variantIndex) : null,
            candidate_id: candidate.candidate_id,
            file_sha256: candidate.file_sha256,
            width: candidate.width,
            height: candidate.height,
            source_path: candidate.path,
          });
        }
      }
      // Freeze the selected bytes once. Every format uses this snapshot even
      // if another window replaces an image while a render is running.
      const snapshotRoot = path.join(workingRoot, ".sources");
      await mkdir(snapshotRoot);
      for (const slide of slides) {
        const bytes = await readFile(slide.source_path).catch((cause) => {
          throw new HttpError(409, "选中的图片已无法读取，请回到选稿台重新选择。", "export_image_unavailable", { cause });
        });
        const digest = createHash("sha256").update(bytes).digest("hex");
        if (digest !== slide.file_sha256) {
          throw new HttpError(409, "选中的图片已变化，请回到选稿台重新选择。", "export_image_changed");
        }
        const extension = path.extname(slide.source_path).toLowerCase();
        if (![".png", ".jpg", ".jpeg", ".webp"].includes(extension)) {
          throw new HttpError(409, "选中的图片格式不受支持，请重新选择。", "export_image_invalid");
        }
        slide.source_path = path.join(snapshotRoot, `${slide.order}${extension}`);
        await writeFile(slide.source_path, bytes, { flag: "wx" });
      }
      const assemblyManifest = { contract_version: 1, slide_size: { width: 1280, height: 720 }, slides };
      await validateSlideImages({ manifest: assemblyManifest, runtime: this.runtime });
      const assemblyPath = path.join(workingRoot, ".assembly.json");
      await writeJson(assemblyPath, assemblyManifest);
      let copied = describePageCopies({ manifest: assemblyManifest });
      const baseName = safeName(name, deck.label || "PPT导出");
      let pdfPath = null;
      let zipPath = null;
      const qaRoot = path.join(workingRoot, ".qa-render");
      let pdfQa = null;
      let imagesZipQa = null;
      if (wantsPdf) {
        pdfPath = path.join(workingRoot, `${baseName}.pdf`);
        await buildPdf({ manifest: assemblyManifest, outputPath: pdfPath, runtime: this.runtime });
        pdfQa = await verifyPdf({ pdfPath, expectedPages: slides.length, qaRoot, runtime: this.runtime });
      }
      if (wantsImagesZip) {
        const pagesRoot = path.join(workingRoot, "pages");
        copied = await buildPageCopies({ manifest: assemblyManifest, pagesRoot });
        zipPath = path.join(workingRoot, `${baseName}-页面图片.zip`);
        await zipPages({ exportRoot: workingRoot, zipPath, runtime: this.runtime });
        imagesZipQa = { file_count: copied.length };
        await rm(pagesRoot, { recursive: true, force: true });
      }

      let pptxPath = null;
      let label = null;
      let pptxQa = null;
      const warnings = explicitFormats ? [] : [...readiness.warnings];
      if (wantsPptx) {
        try {
          pptxPath = path.join(workingRoot, `${baseName}.pptx`);
          await buildPptx({ manifestPath: assemblyPath, outputPath: pptxPath, integrationPath: this.integrationPath, runtime: this.runtime });
          const metadata = await preserveOfficeLabelMetadata({
            pptxPath,
            sourcePptx: readiness._label_template,
            pythonPath: this.runtime.python,
            expectedLabelId: PUBLIC_LABEL_ID,
          });
          pptxQa = await verifyPptxRender({ pptxPath, expectedPages: slides.length, qaRoot, runtime: this.runtime });
          label = await this.officeLabelVerifier({ pptxPath, templatePath: readiness._label_template, metadata, deck });
          if (!label?.verified) throw new Error("PowerPoint sensitivity label was not verified");
        } catch (error) {
          if (pptxPath) await rm(pptxPath, { force: true });
          pptxPath = null;
          label = null;
          pptxQa = null;
          if (explicitFormats) {
            throw new HttpError(500, "PPTX 没有生成成功，请重试。", "pptx_export_failed", { cause: error });
          }
          warnings.push({ code: "pptx_export_failed", message: "PPTX 生成或校验失败，其他格式已导出。" });
        }
      }

      const deliveredFormats = requestedFormats.filter((format) => ({ pptx: pptxPath, pdf: pdfPath, images_zip: zipPath })[format]);
      if (!deliveredFormats.length) throw new HttpError(500, "成品没有生成成功，请重试。", "export_failed");
      const publicSlides = copied.map(({ source_path: _sourcePath, ...item }) => item);
      const manifest = {
        contract_version: 1,
        export_id: id,
        created_at: this.clock().toISOString(),
        deck_id: deck.deck_id,
        deck_uid: deck.outline.deck_uid,
        outline_revision_id: deck.outline.revision_id,
        formats: deliveredFormats,
        logical_page_count: deck.outline.slides.length,
        slide_count: slides.length,
        pages: publicSlides,
      };
      const qa = {
        contract_version: 1,
        pdf: pdfQa,
        pptx: pptxQa,
        images_zip: imagesZipQa,
        formats: deliveredFormats,
        selection_source: "canonical",
        page_order_verified: true,
      };
      await writeJson(path.join(workingRoot, "manifest.json"), manifest);
      await writeJson(path.join(workingRoot, "qa.json"), qa);
      await rm(assemblyPath, { force: true });
      await rm(qaRoot, { recursive: true, force: true });
      await rm(snapshotRoot, { recursive: true, force: true });

      const baseUrl = `/api/decks/${encodeURIComponent(deckId)}/exports/${encodeURIComponent(id)}/files`;
      const artifacts = {
        pptx: pptxPath
          ? await artifactDescriptor(pptxPath, `${baseUrl}/pptx`, {
              sensitivity_label: label,
            })
          : null,
        pdf: pdfPath
          ? await artifactDescriptor(pdfPath, `${baseUrl}/pdf`)
          : null,
        images_zip: zipPath
          ? await artifactDescriptor(zipPath, `${baseUrl}/images_zip`)
          : null,
      };
      const resultWarnings = [...new Map(warnings.map((item) => [item.code, item])).values()];
      const result = {
        contract_version: CONTRACT_VERSION,
        status: resultWarnings.length ? "completed_with_warnings" : "completed",
        export_id: id,
        name: baseName,
        formats: deliveredFormats,
        logical_page_count: manifest.logical_page_count,
        slide_count: manifest.slide_count,
        artifacts,
        manifest_download_url: `${baseUrl}/manifest`,
        qa_download_url: `${baseUrl}/qa`,
        warnings: resultWarnings,
        output_folder_name: path.basename(this.exportRoot),
      };
      await writeJson(path.join(workingRoot, ".result.json"), result);
      // Publish only after every file and result descriptor is complete.
      await rename(workingRoot, finalRoot);
      return result;
    } catch (error) {
      await rm(workingRoot, { recursive: true, force: true }).catch(() => {});
      throw Object.assign(error, { code: error.code || "export_failed" });
    }
  }

  async resolveFile(deckId, id, kind) {
    const deck = await this.discovery.readDeck(deckId);
    if (!/^[0-9A-Za-z][0-9A-Za-z._-]*$/.test(id || "")) throw new HttpError(404, "找不到这次导出。", "export_not_found");
    const bases = [this.#deckExportRoot(deck), path.join(deck.project_root, "output", "exports")];
    let rootReal = null;
    for (const base of bases) {
      try {
        const baseReal = await realpath(base);
        const candidate = await realpath(path.join(base, id));
        if (path.dirname(candidate) !== baseReal) continue;
        rootReal = candidate;
        break;
      } catch { /* Legacy project-local exports remain readable. */ }
    }
    if (!rootReal) throw new HttpError(404, "找不到这次导出。", "export_not_found");
    const localFile = async (filename) => {
      if (typeof filename !== "string" || !filename || path.basename(filename) !== filename || filename.includes("\\")) {
        throw new HttpError(404, "找不到这个导出文件。", "file_not_found");
      }
      const filePath = await realpath(path.join(rootReal, filename)).catch(() => null);
      if (!filePath || path.dirname(filePath) !== rootReal || !(await stat(filePath)).isFile()) {
        throw new HttpError(404, "找不到这个导出文件。", "file_not_found");
      }
      return filePath;
    };
    const manifest = JSON.parse(await readFile(await localFile("manifest.json"), "utf8"));
    if (manifest.deck_id !== deck.deck_id) throw new HttpError(404, "找不到这次导出。", "export_not_found");
    let result = null;
    try { result = JSON.parse(await readFile(await localFile(".result.json"), "utf8")); }
    catch (error) { if (error.code !== "file_not_found") throw error; }
    const names = {
      manifest: "manifest.json", qa: "qa.json",
      pptx: result?.artifacts?.pptx?.filename || null,
      pdf: result?.artifacts?.pdf?.filename || null,
      images_zip: result?.artifacts?.images_zip?.filename || null,
    };
    const filename = Object.hasOwn(names, kind) ? names[kind] : null;
    return { path: await localFile(filename), filename, root: rootReal, manifest };
  }

  async showInFinder(deckId, id) {
    const resolved = await this.resolveFile(deckId, id, "manifest");
    if (this.openFolder) await this.openFolder(resolved.root);
    else await openFolderDetached(resolved.root, this.runtime);
    return { opened: true };
  }

  async showRootInFinder() {
    await mkdir(this.exportRoot, { recursive: true });
    if (this.openFolder) await this.openFolder(this.exportRoot);
    else await openFolderDetached(this.exportRoot, this.runtime);
    return { opened: true, folder_name: path.basename(this.exportRoot) };
  }
}

export function publicReadiness(readiness) {
  const {
    _deck: _deck,
    _projections: _projections,
    _label_template: _labelTemplate,
    ...value
  } = readiness;
  return value;
}
