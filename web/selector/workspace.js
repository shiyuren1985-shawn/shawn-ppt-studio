import { selectorApi } from "./api.js";
import {
  formatCandidateDate,
  normalizeExportReadiness,
  normalizeExportResult,
  normalizeSelectorCatalog,
  normalizeSelectorPage,
  selectionCopy,
  selectInitialSlide,
} from "./model.js";

const STYLE_ID = "shawn-ppt-selector-v2-styles";

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const link = document.createElement("link");
  link.id = STYLE_ID;
  link.rel = "stylesheet";
  link.href = "/selector/styles.css";
  document.head.append(link);
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function isRoot(value) {
  return value && typeof value.replaceChildren === "function";
}

function candidateSha256(candidate) {
  try {
    const value = new URL(candidate?.preview_url || "", globalThis.location?.origin || "http://127.0.0.1")
      .searchParams.get("sha256");
    return /^[a-f0-9]{64}$/.test(value || "") ? value : "";
  } catch {
    return "";
  }
}

export function mountSelectorWorkspace({
  root,
  api = selectorApi,
  state: initialState = {},
  onSlideChange = () => {},
  onSelectionChange = () => {},
  onError = () => {},
} = {}) {
  if (!isRoot(root)) throw new TypeError("selector workspace root is required");
  ensureStyles();

  const view = {
    deckId: initialState.deckId || "",
    slideUid: initialState.slideUid || "",
    decks: Array.isArray(initialState.decks) ? initialState.decks : [],
    catalog: null,
    page: null,
    busy: false,
    loading: true,
    error: "",
    deleteConfirmId: "",
    exportReadiness: null,
    exportResult: null,
    exportBusy: false,
    exportError: "",
    destroyed: false,
  };

  const shell = element("div", "selector-shell");
  shell.dataset.testid = "selector-native-workspace";
  shell.innerHTML = `
    <aside class="selector-sidebar" aria-label="PPT 页面">
      <div class="selector-sidebar-heading"><strong>页面</strong><span data-selector-page-count>0</span></div>
      <nav class="selector-page-list" data-testid="selector-page-list" data-selector-page-list aria-label="选稿页面"></nav>
    </aside>
    <div class="selector-resizer" data-testid="selector-sidebar-resizer" role="separator" aria-label="调整页面列表宽度" aria-orientation="vertical" tabindex="0"></div>
    <section class="selector-stage" aria-label="当前页选稿">
      <header class="selector-header">
        <div class="selector-heading-copy"><span data-selector-page-label>—</span><h2 data-selector-title>选稿</h2></div>
        <div class="selector-progress"><strong data-selector-progress>0 / 0 页已确认</strong><span data-selector-progress-copy>正在读取…</span></div>
        <div class="selector-header-actions">
          <button class="selector-secondary" type="button" data-confirm-defaults hidden>其余页都使用原 PPT 图片</button>
          <button class="selector-icon-button" type="button" data-refresh aria-label="刷新可选图片" title="刷新">↻</button>
        </div>
      </header>
      <div class="selector-status" data-selector-status data-tone="waiting" role="status" aria-live="polite">
        <div><strong data-selector-status-title>正在读取选稿内容…</strong><span data-selector-status-detail></span></div>
        <button class="selector-secondary" type="button" data-include-page hidden>重新纳入这一页</button>
      </div>
      <div class="selector-candidate-scroll" data-selector-scroll>
        <div class="selector-loading" data-selector-empty><strong>正在读取可选图片…</strong></div>
        <div class="selector-candidate-grid" data-testid="selector-candidate-grid" data-selector-candidate-grid></div>
      </div>
      <footer class="selector-actionbar">
        <div><strong data-selector-selection-count>尚未选择图片</strong><span>点击“选择这张”后会立即保存</span></div>
        <div class="selector-action-buttons">
          <button class="selector-secondary" type="button" data-use-baseline title="不使用新候选，继续使用原 PPT 中这一页已有的图片">使用原 PPT 图片</button>
          <button class="selector-primary" type="button" data-export-open>导出成品</button>
        </div>
      </footer>
    </section>
    <dialog class="selector-image-dialog" data-selector-dialog aria-label="图片大图">
      <button class="selector-dialog-close" type="button" data-selector-dialog-close aria-label="关闭大图">×</button>
      <button class="selector-dialog-image-button" type="button" data-selector-dialog-image-button aria-label="关闭大图">
        <img data-selector-dialog-image alt="可选图片大图" />
      </button>
      <p>再点一下图片即可关闭</p>
    </dialog>
    <dialog class="selector-export-dialog" data-export-dialog aria-labelledby="selector-export-title">
      <div class="selector-export-heading">
        <div><span>导出成品</span><h2 id="selector-export-title" data-export-title>正在检查…</h2></div>
        <button class="selector-dialog-close selector-export-close" type="button" data-export-close aria-label="关闭导出">×</button>
      </div>
      <p class="selector-export-message" data-export-message role="status" aria-live="polite"></p>
      <ul class="selector-export-missing" data-export-missing></ul>
      <div class="selector-export-result" data-export-result hidden>
        <div class="selector-export-files" data-export-files></div>
        <button class="selector-secondary" type="button" data-export-open-folder>在 Finder 中显示</button>
      </div>
      <div class="selector-export-actions">
        <button class="selector-secondary" type="button" data-export-close>关闭</button>
        <button class="selector-primary" type="button" data-export-generate hidden>生成成品</button>
      </div>
    </dialog>`;
  root.classList.add("selector-native");
  root.replaceChildren(shell);

  const find = (selector) => shell.querySelector(selector);
  const nodes = {
    pageCount: find("[data-selector-page-count]"),
    pageList: find("[data-selector-page-list]"),
    pageLabel: find("[data-selector-page-label]"),
    title: find("[data-selector-title]"),
    progress: find("[data-selector-progress]"),
    progressCopy: find("[data-selector-progress-copy]"),
    confirmDefaults: find("[data-confirm-defaults]"),
    refresh: find("[data-refresh]"),
    status: find("[data-selector-status]"),
    statusTitle: find("[data-selector-status-title]"),
    statusDetail: find("[data-selector-status-detail]"),
    includePage: find("[data-include-page]"),
    empty: find("[data-selector-empty]"),
    grid: find("[data-selector-candidate-grid]"),
    scroll: find("[data-selector-scroll]"),
    selectionCount: find("[data-selector-selection-count]"),
    useBaseline: find("[data-use-baseline]"),
    resizer: find("[data-testid=selector-sidebar-resizer]"),
    dialog: find("[data-selector-dialog]"),
    dialogImage: find("[data-selector-dialog-image]"),
    dialogImageButton: find("[data-selector-dialog-image-button]"),
    dialogClose: find("[data-selector-dialog-close]"),
    exportOpen: find("[data-export-open]"),
    exportDialog: find("[data-export-dialog]"),
    exportTitle: find("[data-export-title]"),
    exportMessage: find("[data-export-message]"),
    exportMissing: find("[data-export-missing]"),
    exportResult: find("[data-export-result]"),
    exportFiles: find("[data-export-files]"),
    exportGenerate: find("[data-export-generate]"),
    exportOpenFolder: find("[data-export-open-folder]"),
  };

  function reportError(error, fallback) {
    const message = error?.message || fallback;
    view.error = message;
    onError(error instanceof Error ? error : new Error(message));
    render();
  }

  function setPage(page) {
    view.page = page;
    view.slideUid = page?.slide_uid || view.slideUid;
    view.error = "";
    view.deleteConfirmId = "";
  }

  function renderPages() {
    nodes.pageList.replaceChildren();
    const pages = view.catalog?.pages || [];
    nodes.pageCount.textContent = String(pages.length);
    for (const page of pages) {
      const button = element("button", "selector-page-button");
      button.type = "button";
      button.dataset.slideUid = page.slide_uid;
      button.setAttribute("aria-current", page.slide_uid === view.slideUid ? "page" : "false");
      const number = element("span", "selector-page-number", page.page_label);
      const copy = element("span", "selector-page-copy");
      copy.append(element("strong", "", page.title));
      const status = !page.included
        ? "本次不使用"
        : page.confirmed
          ? (page.resolution === "baseline" ? "已使用原 PPT 图片" : "已确认")
          : (page.candidates.length ? "请选择图片" : "暂无图片");
      copy.append(element("span", "", status));
      const dot = element("span", `selector-page-dot ${page.confirmed ? "confirmed" : ""}`);
      dot.setAttribute("aria-hidden", "true");
      button.append(number, copy, dot);
      nodes.pageList.append(button);
    }
    const activePage = nodes.pageList.querySelector('[aria-current="page"]');
    activePage?.scrollIntoView({ block: "nearest" });
  }

  function openImage(candidate) {
    nodes.dialogImage.src = candidate.preview_url;
    nodes.dialogImage.alt = `${view.page?.page_label || "当前页"} 可选图片大图`;
    nodes.dialog.showModal();
  }

  function closeImage() {
    if (nodes.dialog.open) nodes.dialog.close();
    nodes.dialogImage.removeAttribute("src");
  }

  function renderExport() {
    const readiness = view.exportReadiness;
    const result = view.exportResult;
    nodes.exportMissing.replaceChildren();
    nodes.exportFiles.replaceChildren();
    nodes.exportResult.hidden = !result;
    nodes.exportGenerate.hidden = Boolean(result) || !readiness?.ready;
    nodes.exportGenerate.disabled = view.exportBusy;
    nodes.exportOpenFolder.disabled = view.exportBusy;
    if (view.exportBusy) {
      nodes.exportTitle.textContent = result ? "正在打开 Finder…" : (readiness ? "正在生成成品…" : "正在检查…");
      nodes.exportMessage.textContent = result ? "请稍候。" : (readiness ? "PPTX、PDF 和页面图片正在生成，请稍候。" : "正在确认每一页是否已经选好图片。");
      return;
    }
    if (view.exportError) {
      nodes.exportTitle.textContent = "暂时没有完成";
      nodes.exportMessage.textContent = view.exportError;
      return;
    }
    if (result) {
      nodes.exportTitle.textContent = "成品已生成";
      nodes.exportMessage.textContent = result.warning
        ? `PDF 和页面图片已经生成。${result.warning}`
        : "可以直接下载，也可以在 Finder 中查看。";
      for (const artifact of result.artifacts) {
        const link = element("a", "selector-export-file");
        link.href = artifact.download_url;
        link.download = artifact.filename;
        link.append(element("strong", "", artifact.label), element("span", "", "下载"));
        nodes.exportFiles.append(link);
      }
      return;
    }
    if (!readiness) {
      nodes.exportTitle.textContent = "正在检查…";
      nodes.exportMessage.textContent = "正在确认每一页是否已经选好图片。";
      return;
    }
    nodes.exportTitle.textContent = readiness.ready ? "已经可以导出" : "还差几页";
    nodes.exportMessage.textContent = readiness.warning
      ? `${readiness.message} ${readiness.warning}`
      : readiness.message;
    for (const page of readiness.missing_pages) {
      const item = element("li");
      const heading = element("strong", "", `${page.page_label} ${page.title}`);
      item.append(heading, element("span", "", page.message));
      nodes.exportMissing.append(item);
    }
  }

  async function openExport() {
    if (!view.deckId || view.exportBusy) return;
    view.exportReadiness = null;
    view.exportResult = null;
    view.exportError = "";
    view.exportBusy = true;
    renderExport();
    nodes.exportDialog.showModal();
    try {
      view.exportReadiness = normalizeExportReadiness(await api.getExportReadiness(view.deckId));
    } catch (error) {
      view.exportError = error?.message || "暂时无法检查导出状态，请重试";
    } finally {
      view.exportBusy = false;
      renderExport();
    }
  }

  function closeExport() {
    if (!view.exportBusy && nodes.exportDialog.open) nodes.exportDialog.close();
  }

  async function generateExport() {
    if (!view.exportReadiness?.ready || view.exportBusy) return;
    view.exportBusy = true;
    view.exportError = "";
    renderExport();
    try {
      view.exportResult = normalizeExportResult(await api.createExport(view.deckId));
    } catch (error) {
      view.exportError = error?.message || "成品没有生成成功，请重试";
      if (error?.status === 409 && error?.payload?.missing_pages) {
        view.exportReadiness = normalizeExportReadiness({
          ready: false,
          message: error.payload.message,
          missing_pages: error.payload.missing_pages,
        });
        view.exportError = "";
      }
    } finally {
      view.exportBusy = false;
      renderExport();
    }
  }

  async function openExportFolder() {
    if (!view.exportResult || view.exportBusy) return;
    view.exportBusy = true;
    view.exportError = "";
    renderExport();
    try {
      await api.openExportFolder(view.deckId, view.exportResult.export_id);
    } catch (error) {
      view.exportError = error?.message || "暂时无法打开 Finder";
    } finally {
      view.exportBusy = false;
      renderExport();
    }
  }

  function renderCandidates() {
    nodes.grid.replaceChildren();
    const page = view.page;
    nodes.empty.hidden = true;
    if (view.loading) {
      nodes.empty.hidden = false;
      nodes.empty.innerHTML = "<strong>正在读取可选图片…</strong>";
      return;
    }
    if (view.error) {
      nodes.empty.hidden = false;
      nodes.empty.replaceChildren(
        element("strong", "", "选稿内容没有打开"),
        element("p", "", view.error),
      );
      const retry = element("button", "selector-secondary", "重试");
      retry.type = "button";
      retry.dataset.retry = "true";
      nodes.empty.append(retry);
      return;
    }
    if (!page || page.candidates.length === 0) {
      nodes.empty.hidden = false;
      nodes.empty.replaceChildren(
        element("strong", "", "这一页还没有可选图片"),
        element("p", "", "新图片生成完成后，会自动显示在这里。"),
      );
      return;
    }
    page.candidates.forEach((candidate, index) => {
      const selected = page.selected_candidate_ids.includes(candidate.candidate_id);
      const card = element("article", `selector-candidate-card${selected ? " selected" : ""}`);
      card.dataset.candidateId = candidate.candidate_id;
      const imageButton = element("button", "selector-candidate-image");
      imageButton.type = "button";
      imageButton.dataset.previewCandidate = candidate.candidate_id;
      imageButton.setAttribute("aria-label", `放大查看第 ${index + 1} 张图片`);
      const image = element("img");
      image.loading = "lazy";
      image.src = candidate.preview_url;
      image.alt = `${page.page_label} 可选图片 ${index + 1}`;
      imageButton.append(image);
      const badges = element("div", "selector-card-badges");
      if (candidate.baseline) badges.append(element("span", "baseline", "原 PPT"));
      if (selected) badges.append(element("span", "selected", "已选择"));
      imageButton.append(badges);
      const body = element("div", "selector-candidate-body");
      const label = candidate.baseline ? "原 PPT 图片" : `图片 ${index + 1}`;
      const date = formatCandidateDate(candidate.generated_at);
      const titleRow = element("div", "selector-candidate-title");
      titleRow.append(element("strong", "", label));
      if (date) titleRow.append(element("span", "", date));
      const toggle = element(
        "button",
        selected ? "selector-choice selected" : "selector-choice",
        selected ? "取消选择" : "选择这张",
      );
      toggle.type = "button";
      toggle.dataset.toggleCandidate = candidate.candidate_id;
      toggle.setAttribute("aria-pressed", String(selected));
      toggle.disabled = view.busy || !page.included;
      const actions = element("div", "selector-card-actions");
      const trash = element(
        "button",
        view.deleteConfirmId === candidate.candidate_id
          ? "selector-delete confirming"
          : "selector-delete",
        view.deleteConfirmId === candidate.candidate_id ? "确认删除" : "删除",
      );
      trash.type = "button";
      trash.dataset.trashCandidate = candidate.candidate_id;
      trash.disabled = view.busy || selected;
      if (selected) trash.title = "请先取消选择，再删除这张图片";
      actions.append(toggle, trash);
      body.append(titleRow, actions);
      card.append(imageButton, body);
      nodes.grid.append(card);
    });
  }

  function render() {
    if (view.destroyed) return;
    renderPages();
    const catalog = view.catalog;
    const page = view.page;
    nodes.progress.textContent = catalog
      ? `${catalog.confirmed_count} / ${catalog.included_count} 页已确认`
      : "0 / 0 页已确认";
    nodes.progressCopy.textContent = catalog?.pending_count
      ? `还有 ${catalog.pending_count} 页等待确认`
      : (catalog ? "全部完成" : "正在读取…");
    const hasOriginalPpt = catalog?.source_kind !== "studio";
    nodes.confirmDefaults.hidden = !hasOriginalPpt || !catalog?.pending_count;
    nodes.pageLabel.textContent = page?.page_label || "—";
    nodes.title.textContent = page?.title || (view.loading ? "正在读取…" : "选稿");
    const copy = selectionCopy(page, { hasOriginalPpt });
    nodes.status.dataset.tone = view.error ? "error" : copy.tone;
    nodes.statusTitle.textContent = view.error ? "选稿内容没有打开" : copy.title;
    nodes.statusDetail.textContent = view.error ? "可以重试，原来的选择不会改变。" : copy.detail;
    nodes.includePage.hidden = page?.included !== false;
    const selectedCount = page?.selected_candidate_ids?.length || 0;
    nodes.selectionCount.textContent = selectedCount
      ? `已选择 ${selectedCount} 张图片`
      : "尚未选择图片";
    nodes.useBaseline.hidden = !hasOriginalPpt;
    nodes.useBaseline.disabled = view.busy || !hasOriginalPpt || !page?.included || !page?.baseline_available;
    nodes.refresh.disabled = view.busy || !view.deckId;
    nodes.confirmDefaults.disabled = view.busy;
    nodes.includePage.disabled = view.busy;
    nodes.exportOpen.disabled = view.busy || !view.deckId;
    shell.setAttribute("aria-busy", String(view.busy || view.loading));
    renderCandidates();
  }

  async function readPage(slideUid = view.slideUid) {
    if (!view.deckId || !slideUid) return;
    const payload = await api.getSlide(view.deckId, slideUid);
    const page = normalizeSelectorPage(payload);
    if (!page) throw new Error("这一页的选稿内容暂时不可用");
    setPage(page);
    const index = view.catalog?.pages.findIndex((item) => item.slide_uid === page.slide_uid) ?? -1;
    if (index >= 0) view.catalog.pages.splice(index, 1, page);
  }

  async function load({ force = false, requestedSlideUid = view.slideUid } = {}) {
    if (!view.deckId || view.busy || view.destroyed) return;
    view.loading = true;
    view.error = "";
    render();
    try {
      const payload = force
        ? await api.refreshCatalog(view.deckId)
        : await api.getCatalog(view.deckId);
      view.catalog = normalizeSelectorCatalog(payload);
      view.slideUid = selectInitialSlide(view.catalog, requestedSlideUid);
      view.page = view.catalog.pages.find((page) => page.slide_uid === view.slideUid) || null;
      if (view.slideUid) await readPage(view.slideUid);
    } catch (error) {
      view.catalog = null;
      view.page = null;
      reportError(error, "选稿内容没有打开，请重试");
    } finally {
      view.loading = false;
      render();
    }
  }

  async function selectSlide(slideUid) {
    if (!slideUid || slideUid === view.page?.slide_uid || view.busy) return;
    view.slideUid = slideUid;
    const cached = view.catalog?.pages.find((page) => page.slide_uid === slideUid) || null;
    setPage(cached);
    render();
    try {
      await readPage(slideUid);
      onSlideChange({ deckId: view.deckId, slideUid });
    } catch (error) {
      reportError(error, "这一页暂时无法打开");
    } finally {
      render();
    }
  }

  async function refreshAfterMutation(message = "") {
    const payload = await api.getCatalog(view.deckId);
    view.catalog = normalizeSelectorCatalog(payload);
    await readPage(view.slideUid);
    onSelectionChange({
      deckId: view.deckId,
      slideUid: view.slideUid,
      page: view.page,
      catalog: view.catalog,
      message,
    });
  }

  async function toggleCandidate(candidateId) {
    if (!view.page || view.busy || !candidateId || !view.page.included) return;
    const selected = view.page.selected_candidate_ids.includes(candidateId);
    view.deleteConfirmId = "";
    view.busy = true;
    render();
    try {
      await api.selectCandidate(view.deckId, view.slideUid, candidateId, !selected);
      await refreshAfterMutation(selected ? "已取消选择" : "已选择这张图片");
    } catch (error) {
      reportError(error, selected ? "没有取消成功，请重试" : "这张图片没有选上，请重试");
      try { await refreshAfterMutation(); } catch { /* keep the useful error */ }
    } finally {
      view.busy = false;
      render();
    }
  }

  async function trashCandidate(candidateId) {
    if (!view.page || view.busy || !candidateId) return;
    const candidate = view.page.candidates.find((item) => item.candidate_id === candidateId);
    if (!candidate || view.page.selected_candidate_ids.includes(candidateId)) return;
    if (view.deleteConfirmId !== candidateId) {
      view.deleteConfirmId = candidateId;
      render();
      return;
    }
    view.busy = true;
    render();
    try {
      const sha256 = candidateSha256(candidate);
      if (!sha256) throw new Error("这张图片已经变化，请刷新后再试");
      await api.trashCandidate(view.deckId, candidateId, sha256);
      view.deleteConfirmId = "";
      await refreshAfterMutation("图片已移到废纸篓");
    } catch (error) {
      view.deleteConfirmId = "";
      reportError(error, "没有移到废纸篓，请重试");
      try { await refreshAfterMutation(); } catch { /* keep the useful error */ }
    } finally {
      view.busy = false;
      render();
    }
  }

  async function useBaseline() {
    if (!view.page || view.busy || !view.page.baseline_available) return;
    view.busy = true;
    render();
    try {
      await api.useBaseline(view.deckId, view.slideUid);
      await refreshAfterMutation("已使用原 PPT 图片");
    } catch (error) {
      reportError(error, "没有切换到原 PPT 图片，请重试");
    } finally {
      view.busy = false;
      render();
    }
  }

  async function includeCurrentPage() {
    if (!view.page || view.busy) return;
    view.busy = true;
    render();
    try {
      await api.includePage(view.deckId, view.slideUid, true);
      await refreshAfterMutation("这一页已重新纳入本次 PPT");
    } catch (error) {
      reportError(error, "这一页没有重新纳入，请重试");
    } finally {
      view.busy = false;
      render();
    }
  }

  async function confirmDefaults() {
    if (view.busy || !view.catalog?.pending_count) return;
    const accepted = globalThis.confirm?.("其余未确认页面都继续使用原 PPT 中已有的图片吗？") ?? true;
    if (!accepted) return;
    view.busy = true;
    render();
    try {
      await api.confirmDefaults(view.deckId);
      await refreshAfterMutation("其余可用页面已使用原 PPT 图片");
    } catch (error) {
      reportError(error, "其余页面没有完成确认，请重试");
    } finally {
      view.busy = false;
      render();
    }
  }

  shell.addEventListener("click", (event) => {
    const pageButton = event.target.closest("[data-slide-uid]");
    if (pageButton) {
      selectSlide(pageButton.dataset.slideUid);
      return;
    }
    const preview = event.target.closest("[data-preview-candidate]");
    if (preview) {
      const candidate = view.page?.candidates.find((item) => item.candidate_id === preview.dataset.previewCandidate);
      if (candidate) openImage(candidate);
      return;
    }
    const toggle = event.target.closest("[data-toggle-candidate]");
    if (toggle && !view.busy) {
      void toggleCandidate(toggle.dataset.toggleCandidate);
      return;
    }
    const trash = event.target.closest("[data-trash-candidate]");
    if (trash && !view.busy) {
      void trashCandidate(trash.dataset.trashCandidate);
      return;
    }
    if (event.target.closest("[data-use-baseline]")) useBaseline();
    else if (event.target.closest("[data-include-page]")) includeCurrentPage();
    else if (event.target.closest("[data-confirm-defaults]")) confirmDefaults();
    else if (event.target.closest("[data-refresh], [data-retry]")) controller.refresh();
    else if (event.target.closest("[data-export-open]")) void openExport();
    else if (event.target.closest("[data-export-generate]")) void generateExport();
    else if (event.target.closest("[data-export-open-folder]")) void openExportFolder();
    else if (event.target.closest("[data-export-close]")) closeExport();
  });

  nodes.dialogImageButton.addEventListener("click", closeImage);
  nodes.dialogClose.addEventListener("click", closeImage);
  nodes.dialog.addEventListener("click", (event) => {
    if (event.target === nodes.dialog) closeImage();
  });
  nodes.exportDialog.addEventListener("click", (event) => {
    if (event.target === nodes.exportDialog) closeExport();
  });

  let startX = 0;
  let startWidth = 0;
  const resizeMove = (event) => {
    const next = Math.max(170, Math.min(360, startWidth + event.clientX - startX));
    document.documentElement.style.setProperty("--sidebar-width", `${Math.round(next)}px`);
  };
  const resizeStop = () => {
    nodes.resizer.classList.remove("dragging");
    window.removeEventListener("pointermove", resizeMove);
    window.removeEventListener("pointerup", resizeStop);
    try {
      localStorage.setItem(
        "shawn-ppt-studio.selector-sidebar-width",
        getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width").trim(),
      );
    } catch { /* local preference is optional */ }
  };
  nodes.resizer.addEventListener("pointerdown", (event) => {
    startX = event.clientX;
    startWidth = shell.querySelector(".selector-sidebar").getBoundingClientRect().width;
    nodes.resizer.classList.add("dragging");
    window.addEventListener("pointermove", resizeMove);
    window.addEventListener("pointerup", resizeStop, { once: true });
  });
  nodes.resizer.addEventListener("keydown", (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const current = shell.querySelector(".selector-sidebar").getBoundingClientRect().width;
    const next = Math.max(170, Math.min(360, current + (event.key === "ArrowRight" ? 12 : -12)));
    document.documentElement.style.setProperty("--sidebar-width", `${Math.round(next)}px`);
    try { localStorage.setItem("shawn-ppt-studio.selector-sidebar-width", `${Math.round(next)}px`); }
    catch { /* local preference is optional */ }
  });

  try {
    const savedWidth = localStorage.getItem("shawn-ppt-studio.selector-sidebar-width");
    if (/^\d+px$/.test(savedWidth || "")) {
      document.documentElement.style.setProperty("--sidebar-width", savedWidth);
    }
  } catch { /* local preference is optional */ }

  const controller = Object.freeze({
    async setContext({ deckId = view.deckId, slideUid = view.slideUid, decks = view.decks } = {}) {
      if (view.destroyed) return;
      const deckChanged = Boolean(deckId) && deckId !== view.deckId;
      view.deckId = deckId || "";
      view.decks = Array.isArray(decks) ? decks : view.decks;
      view.slideUid = slideUid || (deckChanged ? "" : view.slideUid);
      if (!view.deckId) {
        view.catalog = null;
        view.page = null;
        view.loading = false;
        view.error = "没有可用的 PPT";
        render();
        return;
      }
      if (deckChanged || !view.catalog) {
        await load({ force: true, requestedSlideUid: view.slideUid });
        if (deckChanged && view.slideUid) {
          onSlideChange({ deckId: view.deckId, slideUid: view.slideUid });
        }
      }
      else if (view.slideUid && view.page?.slide_uid !== view.slideUid) await selectSlide(view.slideUid);
      else await load({ force: true, requestedSlideUid: view.slideUid });
    },
    refresh() {
      return load({ force: true });
    },
    destroy() {
      view.destroyed = true;
      closeImage();
      if (nodes.exportDialog.open) nodes.exportDialog.close();
      root.classList.remove("selector-native");
      root.replaceChildren();
    },
  });

  render();
  if (view.deckId) {
    void load({ force: true });
  } else {
    view.loading = false;
    view.error = "没有可用的 PPT";
    render();
  }
  return controller;
}
