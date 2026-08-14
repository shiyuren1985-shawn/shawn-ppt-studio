function cleanString(value, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function safePreviewUrl(value) {
  if (typeof value !== "string" || !value.startsWith("/api/selector-workspace/")) return null;
  if (/^(?:data|blob|javascript):/i.test(value)) return null;
  return value;
}

export function normalizeCandidate(value) {
  if (!value || typeof value !== "object") return null;
  const candidateId = cleanString(value.candidate_id);
  const previewUrl = safePreviewUrl(value.preview_url);
  if (!candidateId || !previewUrl) return null;
  return {
    candidate_id: candidateId,
    preview_url: previewUrl,
    selected: value.selected === true,
    baseline: value.previous_version === true || value.baseline === true,
    generated_at: cleanString(value.generated_at) || null,
    width: Number.isFinite(value.width) ? value.width : null,
    height: Number.isFinite(value.height) ? value.height : null,
  };
}

export function normalizeSelectorPage(value) {
  const page = value?.page && typeof value.page === "object" ? value.page : value;
  if (!page || typeof page !== "object") return null;
  const slideUid = cleanString(page.slide_uid);
  if (!slideUid) return null;
  const candidates = (Array.isArray(page.candidates) ? page.candidates : [])
    .map(normalizeCandidate)
    .filter(Boolean);
  const available = new Set(candidates.map((candidate) => candidate.candidate_id));
  const selectedCandidateIds = [...new Set(
    (Array.isArray(page.selected_candidate_ids) ? page.selected_candidate_ids : [])
      .filter((candidateId) => typeof candidateId === "string" && available.has(candidateId)),
  )];
  for (const candidate of candidates) {
    if (page.resolution !== "baseline" && candidate.selected && !selectedCandidateIds.includes(candidate.candidate_id)) {
      selectedCandidateIds.push(candidate.candidate_id);
    }
  }
  const resolution = ["selected", "baseline", "missing"].includes(page.resolution)
    ? page.resolution
    : null;
  return {
    slide_uid: slideUid,
    page_label: cleanString(page.page_label, "页面"),
    title: cleanString(page.title, "未命名页面"),
    included: page.included !== false,
    confirmed: page.confirmed === true,
    resolution,
    baseline_available: page.baseline_available === true || candidates.some((item) => item.baseline),
    selected_candidate_ids: selectedCandidateIds,
    candidates,
  };
}

export function normalizeSelectorCatalog(value) {
  const catalog = value?.catalog && typeof value.catalog === "object" ? value.catalog : value;
  if (!catalog || typeof catalog !== "object") throw new Error("暂时无法读取选稿内容");
  const pages = (Array.isArray(catalog.pages) ? catalog.pages : [])
    .map(normalizeSelectorPage)
    .filter(Boolean);
  const summary = catalog.summary && typeof catalog.summary === "object" ? catalog.summary : catalog;
  const includedCount = Number.isFinite(summary.included_count)
    ? summary.included_count
    : pages.filter((page) => page.included).length;
  const confirmedCount = Number.isFinite(summary.confirmed_count)
    ? summary.confirmed_count
    : pages.filter((page) => page.included && page.confirmed).length;
  return {
    deck_id: cleanString(catalog.deck_id),
    deck_label: cleanString(catalog.label || catalog.deck_label, "这份 PPT"),
    source_kind: catalog.source_kind === "studio" ? "studio" : "legacy",
    page_count: Number.isFinite(summary.page_count) ? summary.page_count : pages.length,
    included_count: includedCount,
    confirmed_count: confirmedCount,
    pending_count: Number.isFinite(summary.pending_count)
      ? summary.pending_count
      : Math.max(0, includedCount - confirmedCount),
    pages,
  };
}

export function normalizeExportReadiness(value) {
  if (!value || typeof value !== "object") throw new Error("暂时无法检查导出状态");
  const missingPages = (Array.isArray(value.missing_pages) ? value.missing_pages : [])
    .filter((page) => page && typeof page === "object")
    .map((page) => ({
      page_label: cleanString(page.page_label, "页面"),
      title: cleanString(page.title, "未命名页面"),
      message: cleanString(page.message, "还没有确认使用哪张图片"),
    }));
  return {
    ready: value.ready === true && missingPages.length === 0,
    logical_page_count: Number.isFinite(value.logical_page_count) ? value.logical_page_count : 0,
    output_slide_count: Number.isFinite(value.output_slide_count) ? value.output_slide_count : 0,
    missing_pages: missingPages,
    formats: (Array.isArray(value.formats) ? value.formats : [])
      .filter((format) => ["pptx", "pdf", "images_zip"].includes(format)),
    warning: cleanString(
      (Array.isArray(value.warnings) ? value.warnings : [])
        .find((warning) => warning?.code === "pptx_label_template_unavailable")?.message,
    ),
    message: cleanString(
      value.message,
      missingPages.length ? `还有 ${missingPages.length} 页需要确认` : "已经可以生成成品",
    ),
  };
}

function safeDownloadUrl(value) {
  return typeof value === "string" && /^\/api\/decks\/[^/]+\/exports\/[^/]+\/files\/(pptx|pdf|images_zip)$/.test(value)
    ? value
    : "";
}

export function normalizeExportResult(value) {
  if (!value || typeof value !== "object" || !["completed", "completed_with_warnings"].includes(value.status)) {
    throw new Error("成品生成结果暂时无法读取");
  }
  const source = value.artifacts && typeof value.artifacts === "object" ? value.artifacts : {};
  const definitions = [
    ["pptx", "图片版 PPTX"],
    ["pdf", "图片版 PDF"],
    ["images_zip", "页面图片 ZIP"],
  ];
  const artifacts = definitions
    .filter(([kind]) => source[kind] && typeof source[kind] === "object")
    .map(([kind, label]) => ({
      kind,
      label,
      filename: cleanString(source[kind]?.filename, label),
      download_url: safeDownloadUrl(source[kind]?.download_url),
    }));
  const requiredKinds = value.status === "completed_with_warnings" ? ["pdf", "images_zip"] : ["pptx", "pdf", "images_zip"];
  if (!cleanString(value.export_id)
    || artifacts.some((artifact) => !artifact.download_url)
    || requiredKinds.some((kind) => !artifacts.some((artifact) => artifact.kind === kind))) {
    throw new Error("成品文件还没有准备完整");
  }
  return {
    export_id: cleanString(value.export_id),
    name: cleanString(value.name, "PPT 成品"),
    artifacts,
    warning: cleanString(
      (Array.isArray(value.warnings) ? value.warnings : [])
        .find((warning) => warning?.code === "pptx_label_template_unavailable")?.message,
    ),
  };
}

export function selectionCopy(page, { hasOriginalPpt = true } = {}) {
  if (!page) return { tone: "waiting", title: "请选择一页", detail: "" };
  const selected = new Set(page.selected_candidate_ids);
  if (!page.included) {
    return { tone: "muted", title: "本次不使用这一页", detail: "需要时可以重新纳入。" };
  }
  if (page.confirmed && page.resolution === "baseline") {
    return { tone: "confirmed", title: "本页已确认", detail: "正在使用原 PPT 中这一页已有的图片。" };
  }
  if (page.confirmed && selected.size > 0) {
    return { tone: "confirmed", title: "本页已确认", detail: `已选择 ${selected.size} 张图片。` };
  }
  if (page.candidates.length === 0) {
    return { tone: "waiting", title: "还没有可选图片", detail: "新图片生成后会显示在这里。" };
  }
  return {
    tone: "waiting",
    title: "请选择图片",
    detail: hasOriginalPpt
      ? "点击“选择这张”会立即保存；也可以继续使用原 PPT 中的图片。"
      : "点击“选择这张”会立即保存。",
  };
}

export function sameSelection(left, right) {
  if (left.size !== right.size) return false;
  for (const value of left) if (!right.has(value)) return false;
  return true;
}

export function selectInitialSlide(catalog, requestedSlideUid) {
  if (!catalog?.pages?.length) return null;
  return catalog.pages.find((page) => page.slide_uid === requestedSlideUid)?.slide_uid
    || catalog.pages.find((page) => page.included && !page.confirmed)?.slide_uid
    || catalog.pages[0].slide_uid;
}

export function formatCandidateDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(date);
}
