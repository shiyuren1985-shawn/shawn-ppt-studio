import { randomUUID } from "node:crypto";
import { access, mkdir, readFile, realpath, rename, rm } from "node:fs/promises";
import path from "node:path";

import { HttpError } from "./errors.mjs";
import { preserveOfficeLabelMetadata, PUBLIC_LABEL_ID } from "./export-office-label.mjs";
import {
  artifactDescriptor,
  buildPageCopies,
  buildPdf,
  buildPptx,
  DEFAULT_EXPORT_RUNTIME,
  probeExportRuntime,
  verifyPdf,
  verifyPptxRender,
  writeJson,
  zipPages,
} from "./export-runtime.mjs";

const CONTRACT_VERSION = 1;
const PPTX_WARNING = Object.freeze({
  code: "pptx_label_template_unavailable",
  message: "需要完成公司标签模板的 PowerPoint 可见验证后才能生成 PPTX。",
});

function safeName(value, fallback) {
  const clean = typeof value === "string"
    ? value.normalize("NFKC").replace(/[\\/:*?"<>|\u0000-\u001f]/g, " ").replace(/\s+/g, " ").trim()
    : "";
  return (clean || fallback).slice(0, 80);
}

function exportId(now = new Date(), suffix = randomUUID().slice(0, 8)) {
  const timestamp = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  return `${timestamp}-${suffix}`;
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
  return {
    order: slide.order,
    page_label: slide.page_label,
    slide_uid: slide.slide_uid,
    confirmed: projection?.confirmed === true && projection?.status === "selected",
    selected_count: projection?.selected_candidates?.length || 0,
  };
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
    this.runtimeHealth = { ready: false, missing: [], message: "尚未检查导出运行环境。" };
  }

  async initialize() {
    this.runtimeHealth = await probeExportRuntime(this.runtime);
    return this.runtimeHealth;
  }

  health() {
    return { ...this.runtimeHealth };
  }

  async #labelTemplate(deck) {
    if (!this.officeLabelVerifier) return null;
    let candidate = null;
    if (deck.config_path) {
      try {
        const config = JSON.parse(await readFile(deck.config_path, "utf8"));
        candidate = config.baseline_pptx || null;
      } catch {
        candidate = null;
      }
    } else {
      candidate = this.publicLabelTemplate;
    }
    return readableFile(candidate);
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
    const pages = [];
    for (const [index, slide] of deck.outline.slides.entries()) {
      const projection = projections[index];
      pages.push(publicPage(slide, projection));
      if (projection?.status === "selected" && projection.confirmed === true && projection.selected_candidates?.length) {
        continue;
      }
      if (projection?.status === "empty") missing.push(missingPage(slide, "no_selection"));
      else if (projection?.status === "unavailable") {
        missing.push(missingPage(slide, "selection_unavailable", projection.message || null));
      } else missing.push(missingPage(slide, "not_confirmed"));
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
    const pptxAvailable = Boolean(this.runtimeHealth.ready && labelTemplate);
    const baseAvailable = Boolean(this.runtimeHealth.ready);
    const warnings = pptxAvailable ? [] : [PPTX_WARNING];
    const outputSlideCount = projections.reduce(
      (count, projection) => count + (projection?.selected_candidates?.length || 0),
      0,
    );
    const ready = baseAvailable && missing.length === 0;
    const message = !baseAvailable
      ? this.runtimeHealth.message
      : missing.length
        ? `还有 ${missing.length} 页需要确认选图：${missing.map((item) => item.page_label).filter(Boolean).join("、") || "大纲为空"}。`
        : "已准备好导出。";
    return {
      contract_version: CONTRACT_VERSION,
      deck_id: deck.deck_id,
      deck_uid: deck.outline.deck_uid,
      ready,
      logical_page_count: deck.outline.slides.length,
      output_slide_count: outputSlideCount,
      multi_variant_page_count: projections.filter((item) => (item?.selected_candidates?.length || 0) > 1).length,
      missing_pages: missing,
      pages,
      capabilities: {
        pptx: { available: pptxAvailable, message: pptxAvailable ? null : PPTX_WARNING.message },
        pdf: { available: baseAvailable },
        images_zip: { available: baseAvailable },
      },
      formats: [pptxAvailable ? "pptx" : null, baseAvailable ? "pdf" : null, baseAvailable ? "images_zip" : null].filter(Boolean),
      warnings,
      message,
      _deck: deck,
      _projections: projections,
      _label_template: labelTemplate,
    };
  }

  async create(deckId, { name = null } = {}) {
    if (name !== null && (typeof name !== "string" || !name.trim())) {
      throw new HttpError(400, "导出名称不能为空。", "invalid_export_name");
    }
    const readiness = await this.readiness(deckId);
    if (!readiness.ready) throw new ExportNotReadyError(readiness);
    const deck = readiness._deck;
    const projections = readiness._projections;
    const id = this.idFactory ? this.idFactory() : exportId(this.clock());
    const exportsRoot = path.join(deck.project_root, "output", "exports");
    const workingRoot = path.join(exportsRoot, `.${id}.working`);
    const finalRoot = path.join(exportsRoot, id);
    await mkdir(exportsRoot, { recursive: true });
    await mkdir(workingRoot, { recursive: false });
    try {
      const slides = [];
      for (const [pageIndex, slide] of deck.outline.slides.entries()) {
        const candidates = projections[pageIndex].selected_candidates;
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
      const assemblyManifest = { contract_version: 1, slide_size: { width: 1280, height: 720 }, slides };
      const assemblyPath = path.join(workingRoot, ".assembly.json");
      await writeJson(assemblyPath, assemblyManifest);
      const copied = await buildPageCopies({ manifest: assemblyManifest, pagesRoot: path.join(workingRoot, "pages") });
      const baseName = safeName(name, deck.label || "PPT导出");
      const pdfPath = path.join(workingRoot, `${baseName}.pdf`);
      const zipPath = path.join(workingRoot, `${baseName}-页面图片.zip`);
      await buildPdf({ manifest: assemblyManifest, outputPath: pdfPath, runtime: this.runtime });
      await zipPages({ exportRoot: workingRoot, zipPath, runtime: this.runtime });
      const qaRoot = path.join(workingRoot, ".qa-render");
      const pdfQa = await verifyPdf({ pdfPath, expectedPages: slides.length, qaRoot, runtime: this.runtime });

      let pptxPath = null;
      let label = null;
      let pptxQa = null;
      const warnings = [...readiness.warnings];
      if (readiness.capabilities.pptx.available) {
        try {
          pptxPath = path.join(workingRoot, `${baseName}.pptx`);
          await buildPptx({ manifestPath: assemblyPath, outputPath: pptxPath, integrationPath: this.integrationPath, runtime: this.runtime });
          const metadata = await preserveOfficeLabelMetadata({
            pptxPath,
            sourcePptx: readiness._label_template,
            pythonPath: this.runtime.python,
            expectedLabelId: deck.source_kind === "studio" ? PUBLIC_LABEL_ID : null,
          });
          pptxQa = await verifyPptxRender({ pptxPath, expectedPages: slides.length, qaRoot, runtime: this.runtime });
          label = await this.officeLabelVerifier({ pptxPath, templatePath: readiness._label_template, metadata, deck });
          if (!label?.verified) throw new Error("PowerPoint sensitivity label was not verified");
        } catch {
          if (pptxPath) await rm(pptxPath, { force: true });
          pptxPath = null;
          label = null;
          pptxQa = null;
          warnings.push(PPTX_WARNING);
        }
      }

      const publicSlides = copied.map(({ source_path: _sourcePath, ...item }) => item);
      const manifest = {
        contract_version: 1,
        export_id: id,
        created_at: this.clock().toISOString(),
        deck_id: deck.deck_id,
        deck_uid: deck.outline.deck_uid,
        outline_revision_id: deck.outline.revision_id,
        logical_page_count: deck.outline.slides.length,
        slide_count: slides.length,
        pages: publicSlides,
      };
      const qa = {
        contract_version: 1,
        pdf: pdfQa,
        pptx: pptxQa,
        selection_source: "canonical",
        page_order_verified: true,
      };
      await writeJson(path.join(workingRoot, "manifest.json"), manifest);
      await writeJson(path.join(workingRoot, "qa.json"), qa);
      await rm(assemblyPath, { force: true });
      await rm(qaRoot, { recursive: true, force: true });
      await rename(workingRoot, finalRoot);

      const baseUrl = `/api/decks/${encodeURIComponent(deckId)}/exports/${encodeURIComponent(id)}/files`;
      const artifacts = {
        pptx: pptxPath
          ? await artifactDescriptor(path.join(finalRoot, path.basename(pptxPath)), `${baseUrl}/pptx`, {
              sensitivity_label: label,
            })
          : null,
        pdf: await artifactDescriptor(path.join(finalRoot, path.basename(pdfPath)), `${baseUrl}/pdf`),
        images_zip: await artifactDescriptor(path.join(finalRoot, path.basename(zipPath)), `${baseUrl}/images_zip`),
      };
      const result = {
        contract_version: CONTRACT_VERSION,
        status: artifacts.pptx ? "completed" : "completed_with_warnings",
        export_id: id,
        name: baseName,
        logical_page_count: manifest.logical_page_count,
        slide_count: manifest.slide_count,
        artifacts,
        manifest_download_url: `${baseUrl}/manifest`,
        qa_download_url: `${baseUrl}/qa`,
        warnings: [...new Map(warnings.map((item) => [item.code, item])).values()],
      };
      await writeJson(path.join(finalRoot, ".result.json"), result);
      return result;
    } catch (error) {
      await rm(workingRoot, { recursive: true, force: true }).catch(() => {});
      throw Object.assign(error, { code: error.code || "export_failed" });
    }
  }

  async resolveFile(deckId, id, kind) {
    const deck = await this.discovery.readDeck(deckId);
    if (!/^[0-9A-Za-z._-]+$/.test(id || "")) throw new HttpError(404, "找不到这次导出。", "export_not_found");
    const root = path.join(deck.project_root, "output", "exports", id);
    let rootReal;
    try {
      rootReal = await realpath(root);
    } catch {
      throw new HttpError(404, "找不到这次导出。", "export_not_found");
    }
    const manifest = JSON.parse(await readFile(path.join(rootReal, "manifest.json"), "utf8"));
    const result = JSON.parse(await readFile(path.join(rootReal, ".result.json"), "utf8").catch(() => "null"));
    const names = {
      manifest: "manifest.json",
      qa: "qa.json",
      pptx: result?.artifacts?.pptx?.filename || null,
      pdf: result?.artifacts?.pdf?.filename || null,
      images_zip: result?.artifacts?.images_zip?.filename || null,
    };
    const filename = names[kind];
    if (!filename) throw new HttpError(404, "找不到这个导出文件。", "file_not_found");
    const filePath = path.join(rootReal, filename);
    await access(filePath).catch(() => { throw new HttpError(404, "找不到这个导出文件。", "file_not_found"); });
    return { path: filePath, filename, root: rootReal, manifest };
  }

  async showInFinder(deckId, id) {
    const resolved = await this.resolveFile(deckId, id, "manifest");
    if (this.openFolder) await this.openFolder(resolved.root);
    else {
      const { runProcess } = await import("./export-runtime.mjs");
      await runProcess(this.runtime.open, [resolved.root]);
    }
    return { opened: true };
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
