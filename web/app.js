import * as api from "./api.js";
import {
  chooseScope,
  agentMessageSegments,
  codexHistoryTurns,
  codexItemPresentation,
  codexItemText,
  codexPlanSteps,
  formatConversationTime,
  normalizeConversations,
  normalizeDecks,
  normalizeSelection,
  outlineReadingModel,
  safeAttachmentPaths,
  scopeFromSlide,
  retouchDisplayLabel,
} from "./model.js";
import { createTaskCatalogRefreshTracker } from "./task-catalog-refresh.js";

const STORAGE_KEY = "shawn-ppt-studio.ui.v5";
const state = {
  workspace: "outline",
  decks: [],
  defaultDeckId: "",
  deckId: "",
  slideUid: "",
  scope: null,
  draftMarkdown: "",
  selection: normalizeSelection({ status: "unavailable" }),
  selectorController: null,
  selectorMounting: null,
  columns: { left: true, content: true, conversation: true },
  conversations: [],
  activeConversationId: "",
  messages: [],
  activeHistoryFallback: null,
  attachments: [],
  activeTurnId: "",
  activeTurnStatus: "",
  eventSequence: 0,
  eventController: null,
  itemViews: new Map(),
  turnProcessViews: new Map(),
  userMessageViews: new Map(),
  pendingApprovals: new Map(),
  resolvedApprovalIds: new Set(),
  resolvingApprovalIds: new Set(),
  submitting: false,
  interrupting: false,
  creatingConversation: false,
  removeTargetDeckId: "",
  tasks: [],
  taskCounts: { active: 0, attention: 0 },
  taskPollTimer: null,
  taskLoading: false,
  showCompletedTasks: false,
  studioRulesLoading: false,
  outlineLanguageView: "bilingual",
};

const ids = [
  "main-content", "deck-switcher", "outline-slide-count", "outline-slide-list", "retouch-slide-count",
  "retouch-slide-list", "current-page-label", "current-page-title", "composer-page", "composer-scope-copy", "selection-count",
  "current-page-context-copy", "retouch-page-label", "retouch-page-title",
  "selected-preview", "outline-version", "outline-language-switch", "outline-reading-view", "active-conversation-title",
  "active-conversation-time", "message-list", "conversation-form", "message-input", "attachment-list",
  "attachment-input", "attach-button", "send-button", "conversation-menu-button", "conversation-drawer",
  "stop-button", "turn-status", "turn-status-copy",
  "close-conversation-drawer", "drawer-backdrop", "drawer-new-conversation",
  "conversation-list", "refresh-button", "selector-workspace", "retouch-gallery",
  "conversation-panel", "outline-conversation-host", "retouch-conversation-host", "conversation-column-toggle",
  "outline-left-toggle", "retouch-left-toggle", "outline-content-toggle", "retouch-content-toggle", "retouch-stage",
  "image-dialog", "image-dialog-close", "image-dialog-toggle", "image-dialog-content", "page-comparison", "toast",
  "project-dialog", "project-dialog-close", "blank-project-button", "existing-outline-button", "project-dialog-status",
  "project-picker-button", "project-picker-label", "project-picker-meta", "project-popover", "project-search", "project-popover-new",
  "remove-project-dialog", "remove-project-name", "remove-project-cancel", "remove-project-confirm", "remove-project-status",
  "task-center-button", "task-count", "task-center-popover", "task-center-close", "task-center-summary", "task-center-tip", "task-list",
  "studio-rules-button", "studio-rules-dialog", "studio-rules-close", "studio-rules-input", "studio-rules-hint",
  "studio-rules-cancel", "studio-rules-save", "studio-rules-status",
];
const el = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));

const observeTaskCatalogRefresh = createTaskCatalogRefreshTracker({
  refreshCatalog: async (deckId) => {
    if (deckId === state.deckId && state.selectorController) {
      await state.selectorController.refresh();
      return;
    }
    const { selectorApi } = await import("./selector/api.js");
    await selectorApi.refreshCatalog(deckId);
  },
});

function savedState() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); }
  catch { return {}; }
}

function persist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    workspace: state.workspace,
    deckId: state.deckId,
    slideUid: state.slideUid,
    sidebarWidth: getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width").trim(),
    conversationWidth: getComputedStyle(document.documentElement).getPropertyValue("--conversation-width").trim(),
    outlineImageHeight: getComputedStyle(document.documentElement).getPropertyValue("--outline-image-height").trim(),
    columns: state.columns,
    outlineLanguageView: state.outlineLanguageView,
  }));
}

function toast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.toast.hidden = true; }, 3200);
}

function currentDeck() {
  return state.decks.find((deck) => deck.deck_id === state.deckId) || null;
}

function currentSlide() {
  return currentDeck()?.slides.find((slide) => slide.slide_uid === state.slideUid) || null;
}

function updateComposerContext() {
  const page = state.scope?.page_label || currentSlide()?.page_label || (currentDeck() ? "整套 PPT" : "当前页");
  el["composer-page"].textContent = page;
  if (!state.slideUid && currentDeck()) {
    el["message-input"].placeholder = "例如：这份 PPT 讲海外项目交付，请先帮我整理整体故事线。";
    el["composer-scope-copy"].textContent = "，处理范围：整套 PPT";
  } else if (state.workspace === "retouch") {
    el["message-input"].placeholder = "例如：把这一页 Logo 去掉；或者改 P04-A / P08 的图片细节。";
    el["composer-scope-copy"].textContent = "，可直接说“这一页”或图片名称";
  } else {
    el["message-input"].placeholder = "例如：第 5 页的表达还不够直接，请结合整套大纲调整；再为第 5、8 页各做几种图片方案。";
    el["composer-scope-copy"].textContent = "，处理范围：整套 PPT";
  }
}

function attachConversationPanel(workspace) {
  const host = workspace === "retouch" ? el["retouch-conversation-host"] : el["outline-conversation-host"];
  if (host && el["conversation-panel"].parentElement !== host) host.append(el["conversation-panel"]);
  updateComposerContext();
}

function applyColumnState({ save = true } = {}) {
  const root = document.documentElement;
  root.dataset.leftColumn = state.columns.left ? "open" : "collapsed";
  root.dataset.contentColumn = state.columns.content ? "open" : "collapsed";
  root.dataset.conversationColumn = state.columns.conversation ? "open" : "collapsed";
  const names = { left: "页面", content: "内容", conversation: "对话" };
  for (const button of document.querySelectorAll("[data-column-toggle]")) {
    const column = button.dataset.columnToggle;
    const open = Boolean(state.columns[column]);
    const name = names[column] || "这一栏";
    button.setAttribute("aria-expanded", String(open));
    button.setAttribute("aria-label", open ? `收起${name}` : `打开${name}`);
    button.textContent = open ? "收起" : `打开${name}`;
  }
  for (const resizer of document.querySelectorAll("[data-column-resizer='left']")) {
    resizer.setAttribute("aria-disabled", String(!state.columns.left));
  }
  for (const resizer of document.querySelectorAll("[data-column-resizer='conversation']")) {
    resizer.setAttribute("aria-disabled", String(!state.columns.content || !state.columns.conversation));
  }
  if (save) persist();
}

function toggleColumn(column) {
  if (!Object.hasOwn(state.columns, column)) return;
  const next = !state.columns[column];
  if (column === "content" && !next && !state.columns.conversation) state.columns.conversation = true;
  if (column === "conversation" && !next && !state.columns.content) state.columns.content = true;
  state.columns[column] = next;
  applyColumnState();
}

function setWorkspace(workspace) {
  if (!new Set(["outline", "selector", "retouch"]).has(workspace)) return;
  state.workspace = workspace;
  for (const button of document.querySelectorAll("[data-workspace]")) {
    if (button.dataset.workspace === workspace) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  for (const panel of document.querySelectorAll("[data-workspace-panel]")) {
    panel.hidden = panel.dataset.workspacePanel !== workspace;
  }
  if (workspace === "outline" || workspace === "retouch") attachConversationPanel(workspace);
  if (workspace === "selector") void syncSelectorWorkspace();
  if ((workspace === "outline" || workspace === "retouch") && state.deckId) loadCurrentPage();
  persist();
}

function renderDeckSwitcher() {
  el["deck-switcher"].replaceChildren();
  const active = currentDeck();
  el["project-picker-label"].textContent = active?.label || "选择一份 PPT";
  el["project-picker-button"].title = active?.label || "选择一份 PPT";
  el["project-picker-meta"].textContent = active
    ? (active.slides.length ? `${active.slides.length} 页` : "大纲草稿")
    : (state.decks.length ? `${state.decks.length} 个项目` : "还没有项目");
  for (const deck of state.decks) {
    const row = document.createElement("div");
    row.className = "project-option-row";
    row.dataset.searchValue = `${deck.label || ""} ${deck.deck_id}`.toLocaleLowerCase("zh-CN");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "deck-button";
    button.title = deck.label || deck.deck_id;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(deck.deck_id === state.deckId));
    const check = document.createElement("span");
    check.className = "deck-option-check";
    check.textContent = deck.deck_id === state.deckId ? "✓" : "";
    const copy = document.createElement("span");
    copy.className = "deck-option-copy";
    const label = document.createElement("strong");
    label.textContent = deck.label || deck.deck_id;
    const meta = document.createElement("small");
    meta.textContent = deck.slides.length ? `${deck.slides.length} 页` : "大纲草稿";
    copy.append(label, meta);
    button.append(check, copy);
    button.addEventListener("click", async () => {
      closeProjectPicker();
      await selectDeck(deck.deck_id);
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "project-remove-button";
    remove.setAttribute("aria-label", `从列表移除 ${deck.label || deck.deck_id}`);
    remove.title = "从列表移除";
    remove.textContent = "⋯";
    remove.addEventListener("click", () => openRemoveProjectDialog(deck.deck_id));
    row.append(button, remove);
    el["deck-switcher"].append(row);
  }
  filterProjectOptions();
}

function openProjectPicker() {
  el["project-popover"].hidden = false;
  el["project-picker-button"].setAttribute("aria-expanded", "true");
  el["project-search"].value = "";
  filterProjectOptions();
  requestAnimationFrame(() => el["project-search"].focus());
}

function closeProjectPicker({ focusButton = false } = {}) {
  el["project-popover"].hidden = true;
  el["project-picker-button"].setAttribute("aria-expanded", "false");
  if (focusButton) el["project-picker-button"].focus();
}

function toggleProjectPicker() {
  if (el["project-popover"].hidden) openProjectPicker();
  else closeProjectPicker();
}

function filterProjectOptions() {
  const query = (el["project-search"]?.value || "").trim().toLocaleLowerCase("zh-CN");
  let visible = 0;
  for (const row of el["deck-switcher"].querySelectorAll(".project-option-row")) {
    row.hidden = Boolean(query) && !row.dataset.searchValue.includes(query);
    if (!row.hidden) visible += 1;
  }
  el["deck-switcher"].querySelector(".project-empty-result")?.remove();
  if (!visible) {
    const empty = document.createElement("p");
    empty.className = "project-empty-result";
    empty.textContent = "没有找到这份 PPT";
    el["deck-switcher"].append(empty);
  }
}

function openRemoveProjectDialog(deckId) {
  const deck = state.decks.find((item) => item.deck_id === deckId);
  if (!deck) return;
  state.removeTargetDeckId = deckId;
  closeProjectPicker();
  el["remove-project-name"].textContent = deck.label || deck.deck_id;
  el["remove-project-status"].hidden = true;
  el["remove-project-confirm"].disabled = false;
  el["remove-project-cancel"].disabled = false;
  el["remove-project-dialog"].showModal();
}

function closeRemoveProjectDialog() {
  if (el["remove-project-dialog"].open) el["remove-project-dialog"].close();
  state.removeTargetDeckId = "";
}

async function confirmRemoveProject() {
  const deckId = state.removeTargetDeckId;
  if (!deckId) return;
  el["remove-project-confirm"].disabled = true;
  el["remove-project-cancel"].disabled = true;
  el["remove-project-status"].hidden = false;
  el["remove-project-status"].textContent = "正在从列表移除…";
  try {
    await api.hideProject(deckId);
    if (deckId === state.deckId) {
      state.deckId = "";
      state.slideUid = "";
      state.activeConversationId = "";
      state.conversations = [];
      state.messages = [];
      stopEventStream();
      setActiveTurn(null);
    }
    closeRemoveProjectDialog();
    await refreshAll();
    await loadConversations();
    persist();
    toast("已从列表移除。大纲、图片和输出文件都还在原文件夹里。");
  } catch (error) {
    el["remove-project-status"].textContent = `暂时无法移除：${error.message}`;
    el["remove-project-confirm"].disabled = false;
    el["remove-project-cancel"].disabled = false;
  }
}

function openProjectDialog() {
  setProjectDialogBusy(false, "");
  el["project-dialog"].showModal();
}

function closeProjectDialog() {
  el["project-dialog"].close();
}

function setProjectDialogBusy(busy, message = "") {
  el["blank-project-button"].disabled = busy;
  el["existing-outline-button"].disabled = busy;
  el["project-dialog-status"].hidden = !message;
  el["project-dialog-status"].textContent = message;
}

function setStudioRulesStatus(message = "") {
  el["studio-rules-status"].hidden = !message;
  el["studio-rules-status"].textContent = message;
}

function closeStudioRulesDialog() {
  if (el["studio-rules-dialog"].open) el["studio-rules-dialog"].close();
  setStudioRulesStatus();
  el["studio-rules-button"].disabled = false;
}

async function openStudioRulesDialog() {
  if (state.studioRulesLoading) return;
  state.studioRulesLoading = true;
  el["studio-rules-button"].disabled = true;
  try {
    const payload = await api.getStudioRules();
    setStudioRulesStatus(`${payload?.rules?.length || 0} 条规则`);
    el["studio-rules-dialog"].showModal();
    requestAnimationFrame(() => {
      const input = el["studio-rules-input"];
      input.value = (payload?.rules || []).join("\n");
      input.scrollTop = 0;
      input.setSelectionRange(0, 0);
      input.focus();
    });
  } catch (error) {
    el["studio-rules-button"].disabled = false;
    toast(`无法读取长期规则：${error.message}`);
  } finally {
    state.studioRulesLoading = false;
  }
}

async function saveStudioRules() {
  if (state.studioRulesLoading) return;
  const rules = [...new Set(
    el["studio-rules-input"].value
      .split(/\r?\n/)
      .map((rule) => rule.replace(/\s+/g, " ").trim())
      .filter(Boolean),
  )];
  state.studioRulesLoading = true;
  el["studio-rules-save"].disabled = true;
  el["studio-rules-cancel"].disabled = true;
  setStudioRulesStatus("正在保存…");
  try {
    const payload = await api.saveStudioRules(rules);
    closeStudioRulesDialog();
    toast(`长期规则已保存，共 ${payload?.rules?.length || 0} 条`);
  } catch (error) {
    setStudioRulesStatus(`保存失败：${error.message}`);
  } finally {
    state.studioRulesLoading = false;
    el["studio-rules-save"].disabled = false;
    el["studio-rules-cancel"].disabled = false;
  }
}

async function startProject(mode) {
  setProjectDialogBusy(true, mode === "blank" ? "正在选择文件夹…" : "正在选择大纲…");
  try {
    const picked = mode === "blank" ? await api.pickProjectFolder() : await api.pickOutlineFile();
    if (picked?.cancelled || !picked?.selection?.path) {
      setProjectDialogBusy(false, "");
      return;
    }
    setProjectDialogBusy(true, "正在打开…");
    const created = await api.createProject(mode === "blank"
      ? { mode: "blank", folder_path: picked.selection.path }
      : { mode: "existing", outline_path: picked.selection.path });
    const project = created?.project;
    if (!project?.deck_id) throw new Error("没有创建成功");
    state.deckId = project.deck_id;
    state.slideUid = project.default_slide_uid || project.slides?.[0]?.slide_uid || "";
    state.activeConversationId = "";
    state.conversations = [];
    state.messages = [];
    state.draftMarkdown = "";
    stopEventStream();
    setActiveTurn(null);
    closeProjectDialog();
    setWorkspace("outline");
    await refreshAll();
    await loadConversations();
    persist();
    el["message-input"].focus();
  } catch (error) {
    const message = error.code === "project_already_registered"
      ? "这份大纲已经在左侧列表中。"
      : error.code === "project_file_exists"
        ? "这个文件夹里已经有一份同名大纲，请选择另一个文件夹。"
        : `暂时无法打开：${error.message}`;
    setProjectDialogBusy(false, message);
  }
}

function slideButton(slide, target) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "slide-button";
  button.dataset.testid = "slide-item";
  button.setAttribute("aria-current", slide.slide_uid === state.slideUid ? "page" : "false");
  const number = document.createElement("span");
  number.className = "slide-number";
  number.textContent = slide.page_label || `P${String(slide.order).padStart(2, "0")}`;
  const title = document.createElement("span");
  title.className = "slide-title";
  title.textContent = slide.title || "未命名页面";
  button.append(number, title);
  button.addEventListener("click", () => selectSlide(slide.slide_uid));
  target.append(button);
}

function renderSlideLists() {
  const slides = currentDeck()?.slides || [];
  el["outline-slide-list"].replaceChildren();
  el["retouch-slide-list"].replaceChildren();
  for (const slide of slides) {
    slideButton(slide, el["outline-slide-list"]);
    slideButton(slide, el["retouch-slide-list"]);
  }
  el["outline-slide-count"].textContent = String(slides.length);
  el["retouch-slide-count"].textContent = String(slides.length);
}

async function selectDeck(deckId) {
  const deck = state.decks.find((item) => item.deck_id === deckId);
  if (!deck || deck.deck_id === state.deckId) return;
  state.deckId = deck.deck_id;
  state.slideUid = deck.default_slide_uid || deck.slides[0]?.slide_uid || "";
  state.activeConversationId = "";
  state.conversations = [];
  state.messages = [];
  state.draftMarkdown = "";
  stopEventStream();
  setActiveTurn(null);
  renderDeckSwitcher();
  renderSlideLists();
  await Promise.all([loadCurrentPage(), loadConversations()]);
  renderTaskCenter();
  if (state.workspace === "selector") void syncSelectorWorkspace();
  persist();
}

async function selectSlide(slideUid) {
  if (!slideUid || slideUid === state.slideUid) return;
  state.slideUid = slideUid;
  renderSlideLists();
  await loadCurrentPage();
  if (state.workspace === "selector") void syncSelectorWorkspace();
  persist();
}

function renderOutline() {
  const slide = currentSlide();
  el["current-page-label"].textContent = state.scope?.page_label || slide?.page_label || "—";
  el["current-page-title"].textContent = state.scope?.title || slide?.title || "请选择一页";
  el["composer-page"].textContent = state.scope?.page_label || "未选择页面";
  el["retouch-page-label"].textContent = state.scope?.page_label || slide?.page_label || "—";
  el["retouch-page-title"].textContent = state.scope?.title || slide?.title || "修图";
  updateComposerContext();
  el["current-page-context-copy"].textContent = state.scope?.page_label
    ? `你正在查看 ${state.scope.page_label}。AI 会把它作为参考，但仍会结合整套 PPT 理解你的要求。`
    : "当前页会作为参考；下方对话仍面向整套 PPT。";
  el["outline-version"].textContent = currentDeck()?.version_label || "";
  const multilingual = state.scope?.multilingual || slide?.multilingual || null;
  el["outline-language-switch"].hidden = !multilingual;
  for (const button of el["outline-language-switch"].querySelectorAll("[data-outline-language]")) {
    button.setAttribute("aria-pressed", String(button.dataset.outlineLanguage === state.outlineLanguageView));
  }
  const model = outlineReadingModel(
    state.scope?.outline_markdown,
    state.scope?.title || slide?.title,
    state.scope?.subtitle || slide?.subtitle,
    multilingual,
    state.outlineLanguageView,
  );
  el["outline-reading-view"].replaceChildren();
  const list = document.createElement("dl");
  const appendField = (label, value, className = "") => {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const content = document.createElement("dd");
    content.textContent = value;
    if (className) content.className = className;
    row.append(term, content);
    list.append(row);
  };
  appendField("标题", model.title, "outline-title-value");
  if (model.subtitle) appendField("副标题", model.subtitle, "outline-subtitle-value");
  if (!model.sections.length) {
    el["outline-reading-view"].append(list);
    const empty = document.createElement("p");
    empty.className = "loading-copy";
    empty.textContent = "这页暂时没有可预览的大纲内容。";
    el["outline-reading-view"].append(empty);
    return;
  }
  for (const section of model.sections) {
    appendField(section.label, section.value);
  }
  el["outline-reading-view"].append(list);
}

function projectEmptyNode(title, copy) {
  const empty = document.createElement("div");
  empty.className = "project-empty";
  const strong = document.createElement("strong");
  strong.textContent = title;
  const paragraph = document.createElement("p");
  paragraph.textContent = copy;
  empty.append(strong, paragraph);
  return empty;
}

function renderProjectWithoutSlides() {
  const deck = currentDeck();
  el["outline-language-switch"].hidden = true;
  el["current-page-label"].textContent = "";
  el["current-page-title"].textContent = deck?.label || "新的 PPT";
  el["current-page-context-copy"].textContent = deck?.outline_kind === "draft" ? "大纲草稿" : "";
  el["composer-page"].textContent = "整套 PPT";
  el["composer-scope-copy"].textContent = "，处理范围：整套 PPT";
  el["outline-version"].textContent = deck?.status_label || "";
  el["selected-preview"].replaceChildren(projectEmptyNode("还没有页面", "先在右侧告诉 AI 这份 PPT 要讲什么。"));
  el["selection-count"].textContent = "";
  el["outline-reading-view"].replaceChildren();
  if (state.draftMarkdown.trim()) {
    const note = document.createElement("p");
    note.className = "draft-note";
    note.textContent = "这是现有的大纲草稿。可以直接在右侧和 AI 讨论；需要时，告诉 AI 整理成逐页大纲。";
    const draft = document.createElement("div");
    draft.className = "draft-reading-view";
    draft.textContent = state.draftMarkdown;
    el["outline-reading-view"].append(note, draft);
  } else {
    el["outline-reading-view"].append(projectEmptyNode("还没有页面", "先在右侧告诉 AI 这份 PPT 要讲什么。"));
  }
  el["retouch-page-label"].textContent = "";
  el["retouch-page-title"].textContent = deck?.label || "修图";
  el["retouch-gallery"].replaceChildren(projectEmptyNode("暂无图片", "先完成至少一页大纲，再开始生成和修改图片。"));
  updateSendState();
}

function selectorEmpty(message) {
  const empty = document.createElement("div");
  empty.className = "empty-state";
  const title = document.createElement("strong");
  title.textContent = "这一页还没有选定图片";
  const copy = document.createElement("p");
  const normalizedMessage = String(message || "").replace(/[。！!？?\s]/g, "");
  copy.textContent = normalizedMessage === "这一页还没有选定图片"
    ? "先去选稿，确定准备使用的图片。"
    : message || "先去选稿，确定准备使用的图片。";
  const action = document.createElement("button");
  action.type = "button";
  action.className = "secondary-button";
  action.dataset.openSelector = "";
  action.dataset.testid = "go-selector";
  action.textContent = "去选稿";
  empty.append(title, copy, action);
  return empty;
}

function renderSelection() {
  el["selected-preview"].replaceChildren();
  const candidates = state.selection.candidates;
  el["selection-count"].textContent = candidates.length > 1 ? `已选 ${candidates.length} 张` : candidates.length === 1 ? "已选 1 张" : "";
  if (!candidates.length) {
    el["selected-preview"].append(selectorEmpty(state.selection.message));
    return;
  }
  for (const candidate of candidates) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "preview-button";
    button.title = "点击放大";
    const image = document.createElement("img");
    image.src = candidate.preview_url;
    image.alt = `${state.scope?.page_label || "当前页"} 已选图片`;
    image.loading = "lazy";
    button.append(image);
    button.addEventListener("click", () => openImage(candidate.preview_url));
    el["selected-preview"].append(button);
  }
}

async function loadCurrentPage() {
  const deckId = state.deckId;
  const slideUid = state.slideUid;
  if (!deckId) return;
  if (!slideUid) {
    const deck = currentDeck();
    try {
      const outline = await api.getProjectOutline(deckId);
      if (deckId !== state.deckId) return;
      state.draftMarkdown = typeof outline?.draft_markdown === "string" ? outline.draft_markdown : "";
      state.scope = {
        deck_id: deckId,
        deck_uid: deck?.deck_uid || "",
        slide_uid: null,
        page_label: null,
        title: deck?.label || "",
      };
      state.selection = normalizeSelection({ status: "empty", message: "" });
      renderProjectWithoutSlides();
    } catch (error) {
      toast(`无法读取这份大纲：${error.message}`);
    }
    return;
  }
  const slideRequest = api.getSlide(deckId, slideUid);
  const selectionRequest = api.getSelection(deckId, slideUid).catch((error) => ({
    status: "unavailable",
    message: error.status === 404 ? "选稿信息尚未接入。" : "暂时无法读取选中的图片。",
  }));
  try {
    const [detail, selectionPayload] = await Promise.all([slideRequest, selectionRequest]);
    if (deckId !== state.deckId || slideUid !== state.slideUid) return;
    state.scope = scopeFromSlide(detail);
    state.selection = normalizeSelection(selectionPayload);
    renderOutline();
    renderSelection();
    renderRetouch();
    updateSendState();
  } catch (error) {
    toast(`无法读取这一页：${error.message}`);
  }
}

function openImage(url) {
  if (!url) return;
  el["image-dialog-content"].src = url;
  el["image-dialog"].showModal();
}

function renderAgentMessageBody(body, text) {
  body.replaceChildren();
  for (const segment of agentMessageSegments(text)) {
    if (segment.type === "text") {
      body.append(document.createTextNode(segment.text));
      continue;
    }
    const link = document.createElement("a");
    link.className = "conversation-file-link";
    link.textContent = segment.label;
    link.title = segment.type === "local_image"
      ? "点击查看图片"
      : segment.type === "local_file" ? "用默认应用打开" : "在新窗口打开";
    if (segment.type === "local_image") {
      const url = api.conversationImageUrl(state.deckId, segment.target);
      if (!url) {
        body.append(document.createTextNode(segment.label));
        continue;
      }
      link.href = url;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        openImage(url);
      });
    } else if (segment.type === "local_file") {
      link.href = "#";
      link.addEventListener("click", async (event) => {
        event.preventDefault();
        try {
          await api.openConversationFile(state.deckId, segment.target);
        } catch (error) {
          toast(`无法打开这个文件：${error.message}`);
        }
      });
    } else {
      link.href = segment.target;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }
    body.append(link);
  }
}

function closeImage() {
  el["image-dialog"].close();
  el["image-dialog-content"].removeAttribute("src");
}

async function synchronizeFromSelector({ deckId, slideUid } = {}) {
  const deck = state.decks.find((item) => item.deck_id === deckId);
  if (!deck) return;
  const slide = deck.slides.find((item) => item.slide_uid === slideUid) || deck.slides[0];
  if (!slide) return;
  const deckChanged = deck.deck_id !== state.deckId;
  state.deckId = deck.deck_id;
  state.slideUid = slide.slide_uid;
  if (deckChanged) {
    state.activeConversationId = "";
    state.conversations = [];
    state.messages = [];
    stopEventStream();
    setActiveTurn(null);
  }
  renderDeckSwitcher();
  renderSlideLists();
  await loadCurrentPage();
  if (deckChanged) await loadConversations();
  persist();
}

async function mountSelectorWorkspaceIfNeeded() {
  if (state.selectorController) return state.selectorController;
  if (state.selectorMounting) return state.selectorMounting;
  state.selectorMounting = (async () => {
    try {
      const [{ mountSelectorWorkspace }, { selectorApi }] = await Promise.all([
        import("./selector/workspace.js"),
        import("./selector/api.js"),
      ]);
      state.selectorController = await mountSelectorWorkspace({
        root: el["selector-workspace"],
        api: selectorApi,
        state: { deckId: state.deckId, slideUid: state.slideUid, decks: state.decks },
        onSlideChange: (context) => { void synchronizeFromSelector(context); },
        onSelectionChange: (context) => {
          if (context?.deckId === state.deckId && context?.slideUid === state.slideUid) void loadCurrentPage();
        },
        onError: (error) => toast(error?.message || "选稿台暂时无法读取，请稍后重试"),
      });
      return state.selectorController;
    } catch (error) {
      el["selector-workspace"].replaceChildren();
      const empty = document.createElement("div");
      empty.className = "empty-state";
      const title = document.createElement("strong");
      title.textContent = "选稿台暂时无法读取";
      const copy = document.createElement("p");
      copy.textContent = "请稍后再试，你的大纲和正式选图不会受到影响。";
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "secondary-button";
      retry.textContent = "重新读取";
      retry.addEventListener("click", () => {
        state.selectorMounting = null;
        void syncSelectorWorkspace();
      });
      empty.append(title, copy, retry);
      el["selector-workspace"].append(empty);
      throw error;
    } finally {
      state.selectorMounting = null;
    }
  })();
  return state.selectorMounting;
}

async function syncSelectorWorkspace() {
  if (!state.slideUid) {
    el["selector-workspace"].replaceChildren(projectEmptyNode("暂无选稿", "先完成至少一页大纲，再开始生成和选择图片。"));
    state.selectorController = null;
    state.selectorMounting = null;
    return;
  }
  try {
    const alreadyMounted = Boolean(state.selectorController);
    const controller = await mountSelectorWorkspaceIfNeeded();
    if (alreadyMounted) await controller?.setContext?.({ deckId: state.deckId, slideUid: state.slideUid, decks: state.decks });
  } catch { /* The selector workspace already shows a plain-language retry state. */ }
}

function renderRetouch() {
  if (!el["retouch-gallery"]) return;
  el["retouch-gallery"].replaceChildren();
  if (!state.slideUid) {
    el["retouch-gallery"].append(projectEmptyNode("暂无图片", "先完成至少一页大纲，再开始生成和修改图片。"));
    return;
  }
  const candidates = state.selection.candidates;
  if (!candidates.length) {
    el["retouch-gallery"].append(selectorEmpty(state.selection.message));
    return;
  }
  const pageLabel = state.scope?.page_label || currentSlide()?.page_label || "当前页";
  candidates.forEach((candidate, index) => {
    const displayLabel = retouchDisplayLabel(pageLabel, index, candidates.length, candidate.display_label);
    const card = document.createElement("article");
    card.className = "retouch-card";
    card.dataset.testid = "retouch-image-card";
    const imageButton = document.createElement("button");
    imageButton.type = "button";
    imageButton.className = "image-button";
    imageButton.dataset.testid = "retouch-image-preview";
    imageButton.title = `查看 ${displayLabel} 大图`;
    const image = document.createElement("img");
    image.src = candidate.preview_url;
    image.alt = `${displayLabel} 正式图片`;
    imageButton.append(image);
    imageButton.addEventListener("click", () => openImage(candidate.preview_url));
    const caption = document.createElement("div");
    caption.className = "retouch-card-caption";
    const label = document.createElement("strong");
    label.dataset.testid = "retouch-display-label";
    label.textContent = displayLabel;
    const copy = document.createElement("span");
    copy.textContent = "正式图片";
    caption.append(label, copy);
    card.append(imageButton, caption);
    el["retouch-gallery"].append(card);
  });
}

function openConversationDrawer() {
  el["conversation-drawer"].hidden = false;
  el["drawer-backdrop"].hidden = false;
  el["conversation-menu-button"].setAttribute("aria-expanded", "true");
  el["close-conversation-drawer"].focus();
}

function closeConversationDrawer() {
  el["conversation-drawer"].hidden = true;
  el["drawer-backdrop"].hidden = true;
  el["conversation-menu-button"].setAttribute("aria-expanded", "false");
  el["conversation-menu-button"].focus();
}

function renderConversationList() {
  el["conversation-list"].replaceChildren();
  if (!state.conversations.length) {
    const empty = document.createElement("p");
    empty.className = "loading-copy";
    empty.textContent = "还没有历史对话。";
    el["conversation-list"].append(empty);
  }
  for (const conversation of state.conversations) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "conversation-item";
    button.setAttribute("aria-current", String(conversation.conversation_id === state.activeConversationId));
    const title = document.createElement("strong");
    title.textContent = conversation.title;
    const time = document.createElement("span");
    time.textContent = formatConversationTime(conversation.last_used_at || conversation.created_at);
    button.append(title, time);
    button.addEventListener("click", () => activateConversation(conversation.conversation_id));
    el["conversation-list"].append(button);
  }
  const active = state.conversations.find((item) => item.conversation_id === state.activeConversationId);
  el["active-conversation-title"].textContent = active?.title || "和 AI 讨论这份 PPT";
  el["active-conversation-time"].textContent = active ? `${formatConversationTime(active.last_used_at)} · 自动保存` : "自动保存";
}

function renderMessages() {
  el["message-list"].replaceChildren();
  state.itemViews.clear();
  state.turnProcessViews.clear();
  state.userMessageViews.clear();
  state.pendingApprovals.clear();
  state.resolvedApprovalIds.clear();
  state.resolvingApprovalIds.clear();
  if (!state.messages.length) {
    const welcome = document.createElement("div");
    welcome.className = "welcome-message";
    welcome.innerHTML = "<strong>可以直接告诉 AI 你想做什么</strong><p>你可以讨论或修改大纲，也可以要求为一页、几页或整套 PPT 作图。当前页面会作为参考，但不会限制 AI 只能处理这一页。</p>";
    el["message-list"].append(welcome);
    return;
  }
  for (const turn of state.messages) {
    for (const item of turn.items || []) {
      renderCodexItem(
        { ...item, __turnId: turn.turn_id, __source: "history" },
        { scroll: false, authoritative: true },
      );
    }
    if (turn.status === "inProgress") ensureTurnProcess(turn.turn_id);
    else finishTurnProcess(turn.turn_id, turn.status);
  }
  el["message-list"].scrollTop = el["message-list"].scrollHeight;
}

function appendMessage(role, text, { streaming = false, scroll = true } = {}) {
  const article = document.createElement("article");
  article.className = `message ${role}${streaming ? " streaming" : ""}`;
  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = role === "user" ? "你" : role === "assistant" ? "AI" : "提示";
  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text;
  article.append(meta, body);
  el["message-list"].append(article);
  if (scroll) el["message-list"].scrollTop = el["message-list"].scrollHeight;
  return { article, body };
}

function scrollTimeline() {
  el["message-list"].scrollTop = el["message-list"].scrollHeight;
}

function statusLabel(status) {
  return ({
    inProgress: "进行中",
    completed: "已完成",
    failed: "失败",
    declined: "已拒绝",
    interrupted: "已停止",
    pending: "等待中",
  })[status] || status || "";
}

function ensureTurnProcess(turnId) {
  const id = String(turnId || state.activeTurnId || "current-turn");
  const active = Boolean(state.activeTurnId) && String(state.activeTurnId) === id;
  let view = state.turnProcessViews.get(id);
  if (view) {
    if (active) {
      view.details.open = true;
      view.status.textContent = "进行中";
    }
    return view;
  }
  const article = document.createElement("article");
  article.className = "codex-item codex-process";
  article.dataset.turnId = id;
  const details = document.createElement("details");
  details.open = active;
  const summary = document.createElement("summary");
  const title = document.createElement("span");
  title.textContent = "处理过程";
  const status = document.createElement("span");
  status.className = "codex-process-status";
  status.textContent = active ? "进行中" : "已完成";
  summary.append(title, status);
  const body = document.createElement("div");
  body.className = "codex-process-body";
  details.append(summary, body);
  article.append(details);
  el["message-list"].append(article);
  view = { article, details, status, body, commentaries: [], events: new Map() };
  state.turnProcessViews.set(id, view);
  return view;
}

function finishTurnProcess(turnId, status = "completed") {
  const view = state.turnProcessViews.get(String(turnId || ""));
  if (!view) return;
  view.details.open = false;
  view.status.textContent = status === "interrupted"
    ? "已停止"
    : status === "failed" ? "失败" : "已完成";
}

function appendProcessCommentary(process, article) {
  process.body.append(article);
  process.commentaries.push(article);
  while (process.commentaries.length > 3) process.commentaries.shift()?.remove();
}

function processEventView(process, itemId, presentation) {
  const key = presentation.title || "处理步骤";
  let aggregate = process.events.get(key);
  if (!aggregate) {
    const article = document.createElement("div");
    article.className = "codex-process-event";
    const title = document.createElement("span");
    title.className = "codex-process-event-title";
    const status = document.createElement("span");
    status.className = "codex-process-event-status";
    const detail = document.createElement("pre");
    detail.hidden = true;
    article.append(title, status, detail);
    process.body.append(article);
    aggregate = { article, title, status, detail, label: key, count: 0, itemIds: new Set() };
    process.events.set(key, aggregate);
  }
  if (!aggregate.itemIds.has(itemId)) {
    aggregate.itemIds.add(itemId);
    aggregate.count += 1;
  }
  aggregate.title.textContent = aggregate.count > 1 ? `${aggregate.label} ×${aggregate.count}` : aggregate.label;
  aggregate.status.textContent = statusLabel(presentation.status);
  return { ...aggregate, type: "step", aggregate };
}

function renderPlan(value, { scroll = true } = {}) {
  const steps = codexPlanSteps(value);
  if (!steps.length) return null;
  const itemId = String(value?.itemId || value?.item_id || "active-plan");
  let view = state.itemViews.get(itemId);
  if (!view) {
    const article = document.createElement("article");
    article.className = "codex-item codex-plan";
    article.dataset.itemId = itemId;
    const title = document.createElement("strong");
    title.textContent = "计划";
    const list = document.createElement("ol");
    article.append(title, list);
    ensureTurnProcess(value?.__turnId).body.append(article);
    view = { article, list, type: "plan" };
    state.itemViews.set(itemId, view);
  }
  view.list.replaceChildren();
  for (const step of steps) {
    const row = document.createElement("li");
    row.textContent = step.text;
    row.className = step.status === "inProgress" ? "in-progress" : step.status;
    view.list.append(row);
  }
  if (scroll) scrollTimeline();
  return view;
}

function renderCodexItem(item, { scroll = true, authoritative = false, streaming = false } = {}) {
  if (!item || typeof item !== "object") return null;
  const itemId = String(item.id || item.itemId || item.item_id || "");
  if (!itemId) return null;
  if (item.type === "plan") return renderPlan({ ...item, itemId }, { scroll });
  const presentation = item.type === "userMessage" || item.type === "agentMessage"
    ? null
    : codexItemPresentation(item);
  const lowSignal = ["reasoning", "collabAgentToolCall", "collabToolCall", "subAgentActivity", "contextCompaction"].includes(item.type);
  if (lowSignal && !presentation?.detail && (!streaming || item.type !== "reasoning")) return null;
  let view = state.itemViews.get(itemId);
  if (view) {
    if (view.type === "agentMessage") {
      const commentary = item.phase === "commentary";
      view.article.classList.toggle("commentary", commentary);
      view.article.classList.toggle("final-answer", !commentary);
      if (view.meta) view.meta.textContent = commentary ? "Codex · 进展" : "Codex";
      if (authoritative) renderAgentMessageBody(view.body, codexItemText(item));
    }
    if (view.type === "step") {
      const nextPresentation = codexItemPresentation(item);
      if (authoritative && lowSignal && !nextPresentation.detail && !view.aggregate) {
        view.article.remove();
        state.itemViews.delete(itemId);
        return null;
      }
      if (view.aggregate) {
        view.aggregate.label = nextPresentation.title || view.aggregate.label;
        view.title.textContent = view.aggregate.count > 1
          ? `${view.aggregate.label} ×${view.aggregate.count}`
          : view.aggregate.label;
      } else {
        view.title.textContent = nextPresentation.title;
      }
      view.status.textContent = statusLabel(nextPresentation.status);
      if (nextPresentation.detail) view.detail.textContent = nextPresentation.detail;
    }
    view.article.classList.toggle("streaming", streaming && !authoritative);
    if (authoritative) view.article.classList.remove("streaming");
    if (scroll) scrollTimeline();
    return view;
  }

  if (item.type === "userMessage") {
    const text = codexItemText(item);
    const semanticKey = item.__turnId && text ? `${item.__turnId}\u0000${text}` : "";
    const prior = semanticKey
      ? (state.userMessageViews.get(semanticKey) || []).find((entry) => (
          entry.source && item.__source && entry.source !== item.__source
        ))
      : null;
    if (prior) {
      state.itemViews.set(itemId, prior.view);
      return prior.view;
    }
    const message = appendMessage("user", text, { scroll: false });
    message.article.dataset.itemId = itemId;
    view = { ...message, type: "userMessage" };
    if (semanticKey) {
      const entries = state.userMessageViews.get(semanticKey) || [];
      entries.push({ source: item.__source || "", view });
      state.userMessageViews.set(semanticKey, entries);
    }
  } else if (item.type === "agentMessage") {
    if (item.phase === "commentary") {
      const process = ensureTurnProcess(item.__turnId);
      const article = document.createElement("p");
      article.className = `codex-process-commentary${streaming ? " streaming" : ""}`;
      article.dataset.itemId = itemId;
      const body = document.createElement("span");
      body.className = "message-body";
      renderAgentMessageBody(body, codexItemText(item));
      article.append(body);
      appendProcessCommentary(process, article);
      view = { article, body, meta: null, type: "agentMessage" };
    } else {
    const article = document.createElement("article");
    article.className = `codex-item agent-message final-answer${streaming ? " streaming" : ""}`;
    article.dataset.itemId = itemId;
    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = "Codex";
    const body = document.createElement("div");
    body.className = "message-body";
    renderAgentMessageBody(body, codexItemText(item));
    article.append(meta, body);
    el["message-list"].append(article);
    view = { article, meta, body, type: "agentMessage" };
    }
  } else {
    const process = ensureTurnProcess(item.__turnId);
    view = processEventView(process, itemId, presentation);
    view.detail.textContent = presentation.detail || "";
  }
  state.itemViews.set(itemId, view);
  if (scroll) scrollTimeline();
  return view;
}

async function loadConversations() {
  const deck = currentDeck();
  if (!deck) return;
  try {
    let directory = normalizeConversations(await api.getConversations(deck.deck_id));
    state.conversations = directory.conversations;
    state.activeConversationId = directory.active_conversation_id || state.conversations[0]?.conversation_id || "";
    if (!state.activeConversationId) {
      await createConversation({ silent: true });
      return;
    }
    renderConversationList();
    await loadConversationHistory(state.activeConversationId);
  } catch (error) {
    state.conversations = [];
    state.activeConversationId = "";
    state.messages = [];
    renderConversationList();
    renderMessages();
    if (error.status !== 404) toast("历史对话暂时无法读取，你仍可以查看大纲和选稿。");
  }
  updateSendState();
}

async function createConversation({ silent = false } = {}) {
  if (state.creatingConversation) return;
  const deck = currentDeck();
  if (!deck) return;
  state.creatingConversation = true;
  el["drawer-new-conversation"].disabled = true;
  try {
    const payload = await api.createConversation(deck.deck_id);
    const created = payload?.conversation || payload;
    if (!created?.conversation_id) throw new Error("没有创建成功");
    const directory = normalizeConversations(await api.getConversations(deck.deck_id));
    state.conversations = directory.conversations;
    state.activeConversationId = created.conversation_id;
    state.messages = [];
    stopEventStream();
    setActiveTurn(null);
    renderConversationList();
    renderMessages();
    closeConversationDrawerIfOpen();
    if (!silent) toast("已新建对话，原来的对话仍保留在历史对话中");
  } catch (error) {
    if (!silent) toast(`无法新建对话：${error.message}`);
  } finally {
    state.creatingConversation = false;
    el["drawer-new-conversation"].disabled = false;
    updateSendState();
  }
}

function closeConversationDrawerIfOpen() {
  if (!el["conversation-drawer"].hidden) closeConversationDrawer();
}

async function activateConversation(conversationId) {
  if (!conversationId || conversationId === state.activeConversationId) return;
  const deck = currentDeck();
  if (!deck) return;
  try {
    stopEventStream();
    setActiveTurn(null);
    await api.activateConversation(deck.deck_id, conversationId);
    state.activeConversationId = conversationId;
    renderConversationList();
    await loadConversationHistory(conversationId);
    closeConversationDrawerIfOpen();
  } catch (error) {
    toast(`无法打开这个对话：${error.message}`);
  }
}

async function loadConversationHistory(conversationId) {
  const deck = currentDeck();
  if (!deck || !conversationId) return;
  try {
    const payload = await api.getConversationHistory(deck.deck_id, conversationId);
    const turns = codexHistoryTurns(payload);
    const activeTurnId = String(payload?.active_turn?.turn_id || "");
    state.activeHistoryFallback = activeTurnId
      ? turns.find((turn) => turn.turn_id === activeTurnId) || null
      : null;
    // An active turn has two representations: thread/read history and the
    // relay replay. Render only the relay while it is available, otherwise the
    // same user/commentary items appear twice with different App Server IDs.
    state.messages = activeTurnId
      ? turns.filter((turn) => turn.turn_id !== activeTurnId)
      : turns;
    setActiveTurn(payload?.active_turn || null);
    renderMessages();
    if (state.activeTurnId) attachToActiveTurn();
  } catch (error) {
    state.messages = [];
    setActiveTurn(null);
    renderMessages();
    toast(`对话内容暂时无法读取：${error.message}`);
  }
}

function setActiveTurn(active) {
  const turnId = String(active?.turn_id || active?.id || "");
  const status = String(active?.status || "");
  state.activeTurnId = turnId;
  state.activeTurnStatus = turnId ? status || "inProgress" : "";
  if (!turnId) state.activeHistoryFallback = null;
  el["turn-status"].hidden = !turnId;
  updateTurnStatus();
  el["stop-button"].hidden = !turnId;
  el["stop-button"].disabled = !turnId || state.interrupting;
  updateSendState();
}

function formatTaskElapsed(seconds) {
  if (!Number.isFinite(seconds) || seconds < 60) return "刚刚开始";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return minutes ? `${hours} 小时 ${minutes} 分钟` : `${hours} 小时`;
}

function currentConversationTask() {
  return state.tasks.find((task) => task.deck_id === state.deckId
    && task.conversation_id === state.activeConversationId
    && ["preparing", "queued", "generating", "reviewing", "waiting_permission"].includes(task.status)) || null;
}

function updateTurnStatus() {
  if (!state.activeTurnId) return;
  const task = currentConversationTask();
  el["turn-status-copy"].textContent = state.interrupting
    ? "正在停止…"
    : task ? `${task.title} · ${task.status_label}` : "Codex 正在处理";
}

function taskGroupLabel(status) {
  if (["preparing", "queued", "generating", "reviewing", "waiting_permission"].includes(status)) return "进行中";
  if (["attention", "stalled", "failed"].includes(status)) return "需要查看";
  return "最近完成";
}

function taskStatusCopy(task) {
  if (task.status === "waiting_permission" && Number(task.pending_approval_count) > 0) {
    return `等待允许操作 · ${Number(task.pending_approval_count)}项`;
  }
  return `${task.status_label} · ${formatTaskElapsed(task.elapsed_seconds)}`;
}

function renderTaskCenter() {
  const activeCount = state.taskCounts.active;
  el["task-count"].hidden = activeCount === 0;
  el["task-count"].textContent = String(activeCount);
  el["task-center-button"].title = state.taskCounts.attention > 0
    ? `${state.taskCounts.attention} 个历史任务需要查看`
    : "查看作图任务";
  el["task-center-button"].classList.toggle("has-active", state.taskCounts.active > 0);
  el["task-center-button"].classList.toggle("has-attention", state.taskCounts.active === 0 && state.taskCounts.attention > 0);
  el["task-center-summary"].textContent = state.taskCounts.active
    ? `${state.taskCounts.active} 个正在进行`
    : state.taskCounts.attention ? `${state.taskCounts.attention} 个需要查看` : "没有正在进行的作图任务";
  el["task-center-tip"].hidden = state.taskCounts.active === 0;
  el["task-list"].replaceChildren();
  if (!state.tasks.length) {
    const empty = document.createElement("div");
    empty.className = "task-empty";
    empty.innerHTML = "<strong>暂时没有作图任务</strong><span>从对话里发布作图或修图后，会自动出现在这里。</span>";
    el["task-list"].append(empty);
    updateTurnStatus();
    return;
  }
  const completedTasks = state.tasks.filter((task) => task.status === "completed");
  const visibleTasks = state.showCompletedTasks
    ? state.tasks
    : state.tasks.filter((task) => task.status !== "completed");
  let previousGroup = "";
  for (const task of visibleTasks) {
    const group = taskGroupLabel(task.status);
    if (group !== previousGroup) {
      const heading = document.createElement("h3");
      heading.className = "task-group-label";
      heading.textContent = group;
      el["task-list"].append(heading);
      previousGroup = group;
    }
    const card = document.createElement("article");
    card.className = `task-card status-${task.status}`;
    card.dataset.taskId = task.task_id;
    const main = document.createElement("button");
    main.type = "button";
    main.className = "task-card-main";
    main.disabled = !task.deck_id;
    main.addEventListener("click", () => openTask(task));
    const eyebrow = document.createElement("span");
    eyebrow.className = "task-project";
    eyebrow.textContent = task.deck_label;
    const title = document.createElement("strong");
    title.textContent = task.title;
    const status = document.createElement("span");
    status.className = "task-card-status";
    status.textContent = taskStatusCopy(task);
    main.append(eyebrow, title, status);
    if (Number.isFinite(task.progress_percent)) {
      const progress = document.createElement("div");
      progress.className = "task-progress";
      progress.setAttribute("role", "progressbar");
      progress.setAttribute("aria-valuemin", "0");
      progress.setAttribute("aria-valuemax", "100");
      progress.setAttribute("aria-valuenow", String(task.progress_percent));
      const bar = document.createElement("span");
      bar.style.width = `${Math.max(0, Math.min(100, task.progress_percent))}%`;
      progress.append(bar);
      main.append(progress);
    } else if (["preparing", "reviewing"].includes(task.status)) {
      const progress = document.createElement("div");
      progress.className = "task-progress indeterminate";
      progress.setAttribute("role", "progressbar");
      progress.removeAttribute("aria-valuenow");
      progress.append(document.createElement("span"));
      main.append(progress);
    }
    card.append(main);
    if (task.can_stop) {
      const stop = document.createElement("button");
      stop.type = "button";
      stop.className = "task-stop";
      stop.textContent = "停止";
      stop.addEventListener("click", async () => {
        stop.disabled = true;
        try {
          await api.interruptTask(task.task_id);
          toast("已请求停止这个任务");
          await loadTasks({ force: true });
        } catch (error) {
          toast(`无法停止：${error.message}`);
          stop.disabled = false;
        }
      });
      card.append(stop);
    }
    el["task-list"].append(card);
  }
  if (completedTasks.length) {
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "task-history-toggle";
    toggle.textContent = state.showCompletedTasks
      ? "收起最近完成"
      : `查看最近完成（${completedTasks.length}）`;
    toggle.addEventListener("click", () => {
      state.showCompletedTasks = !state.showCompletedTasks;
      renderTaskCenter();
    });
    el["task-list"].append(toggle);
  }
  updateTurnStatus();
}

async function openTask(task) {
  closeTaskCenter();
  if (task.deck_id !== state.deckId) await selectDeck(task.deck_id);
  if (task.slide_uid && task.slide_uid !== state.slideUid) await selectSlide(task.slide_uid);
  setWorkspace("outline");
  if (task.conversation_id && task.conversation_id !== state.activeConversationId) {
    await activateConversation(task.conversation_id);
  } else if (!task.conversation_id) {
    toast("这个任务没有可恢复的来源对话，已打开对应页面");
  }
}

function openTaskCenter() {
  el["task-center-popover"].hidden = false;
  el["task-center-button"].setAttribute("aria-expanded", "true");
  void loadTasks({ force: true });
}

function closeTaskCenter({ focusButton = false } = {}) {
  el["task-center-popover"].hidden = true;
  el["task-center-button"].setAttribute("aria-expanded", "false");
  if (focusButton) el["task-center-button"].focus();
}

function toggleTaskCenter() {
  if (el["task-center-popover"].hidden) openTaskCenter();
  else closeTaskCenter();
}

async function loadTasks({ force = false } = {}) {
  if (state.taskLoading) return;
  state.taskLoading = true;
  try {
    const payload = await api.getTasks();
    state.tasks = Array.isArray(payload?.tasks) ? payload.tasks : [];
    state.taskCounts = {
      active: Number(payload?.active_count || 0),
      attention: Number(payload?.attention_count || 0),
    };
    renderTaskCenter();
    try {
      await observeTaskCatalogRefresh(state.tasks);
    } catch (error) {
      console.warn("Unable to refresh selector catalog after task completion", error);
    }
  } catch (error) {
    if (force) toast(`任务状态暂时无法读取：${error.message}`);
  } finally {
    state.taskLoading = false;
    clearTimeout(state.taskPollTimer);
    const delay = state.taskCounts.active > 0 ? 4000 : 15000;
    state.taskPollTimer = setTimeout(() => loadTasks(), delay);
  }
}

function stopEventStream() {
  state.eventController?.abort();
  state.eventController = null;
  state.eventSequence = 0;
}

function attachToActiveTurn() {
  if (!state.activeTurnId || !state.activeConversationId || state.eventController) return;
  const deckId = state.deckId;
  const conversationId = state.activeConversationId;
  const turnId = state.activeTurnId;
  const controller = new AbortController();
  state.eventController = controller;
  void api.streamConversationEvents(deckId, conversationId, turnId, state.eventSequence, onConversationEvent, controller.signal)
    .catch((error) => {
      if (error.name === "AbortError" || state.activeTurnId !== turnId) return;
      if (error.status === 404 && state.activeHistoryFallback?.turn_id === turnId) {
        for (const item of state.activeHistoryFallback.items || []) {
          renderCodexItem(item, { authoritative: true });
        }
        state.activeHistoryFallback = null;
        return;
      }
      toast(`无法继续显示 AI 进度：${error.message}`);
    })
    .finally(() => {
      if (state.eventController === controller) state.eventController = null;
    });
}

function renderAttachments() {
  el["attachment-list"].replaceChildren();
  el["attachment-list"].hidden = !state.attachments.length;
  for (const [index, attachment] of state.attachments.entries()) {
    const chip = document.createElement("div");
    chip.className = "attachment-chip";
    const name = document.createElement("span");
    name.textContent = attachment.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "text-button";
    remove.textContent = "移除";
    remove.addEventListener("click", () => {
      state.attachments.splice(index, 1);
      renderAttachments();
    });
    chip.append(name, remove);
    el["attachment-list"].append(chip);
  }
}

async function uploadReferenceFiles(files) {
  const allowed = new Set(["image/png", "image/jpeg", "image/webp"]);
  const usable = [...files].filter((file) => allowed.has(file.type));
  if (!usable.length) {
    toast("请添加 PNG、JPEG 或 WebP 图片；本地路径也可以直接写进对话。 ");
    return;
  }
  el["attach-button"].disabled = true;
  const attachments = await Promise.all(usable.map(async (file) => {
    try {
      const payload = await api.uploadAttachment(file);
      if (payload?.attachment?.path) return { name: file.name || "粘贴的截图", path: payload.attachment.path };
      throw new Error("服务没有返回附件");
    } catch (error) {
      toast(`无法添加 ${file.name || "截图"}：${error.message}`);
      return null;
    }
  }));
  state.attachments.push(...attachments.filter(Boolean));
  renderAttachments();
  el["attach-button"].disabled = false;
}

function resizeMessageInput() {
  const input = el["message-input"];
  input.style.height = "auto";
  const maximum = Math.min(240, Math.max(120, window.innerHeight * 0.32));
  const next = Math.max(52, Math.min(input.scrollHeight, maximum));
  input.style.height = `${Math.ceil(next)}px`;
  input.style.overflowY = input.scrollHeight > maximum ? "auto" : "hidden";
}

function updateSendState() {
  el["send-button"].disabled = state.submitting || !state.activeConversationId || !state.scope || !el["message-input"].value.trim();
  el["send-button"].textContent = "发送";
}

function stableApprovalValue(value) {
  if (Array.isArray(value)) return value.map(stableApprovalValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stableApprovalValue(value[key])]));
}

function approvalValueKey(value) {
  return JSON.stringify(stableApprovalValue(value));
}

function firstApprovalValue(source, names) {
  for (const name of names) {
    if (source?.[name] !== undefined && source[name] !== null && source[name] !== "") return source[name];
  }
  return null;
}

function canonicalFast8Claim(request) {
  const params = request?.params || request || {};
  const actionCommands = Array.isArray(params.commandActions)
    ? params.commandActions.map((action) => typeof action?.command === "string" ? action.command : null).filter(Boolean)
    : [];
  if (actionCommands.length > 1 || (!actionCommands.length && typeof params.command !== "string")) return null;
  const command = (actionCommands[0] || params.command).trim();
  const invocation = command.match(/(?:^|\s)(?:python3?|\/[^\s"']*\/python3?)(?:\s+)(["']?)(\/[^\s"']*\/fast8_control_plane_v1\.py)\1\s+(\S+)/);
  if (!invocation || invocation[3] !== "claim") return null;
  const state = command.match(/--state(?:=|\s+)(["']?)(\/[^\s"']+\/state\/style_run_state\.json)\1/);
  const ticket = command.match(/--ticket(?:=|\s+)(["']?)(\/[^\s"']+\/style_jobs\/dispatch_tickets\/ticket_[^/\s"']+\.json)\1/);
  if (!state?.[2] || !ticket?.[2]) return null;
  const runRoot = state[2].replace(/\/state\/style_run_state\.json$/, "");
  if (!ticket[2].startsWith(`${runRoot}/style_jobs/dispatch_tickets/ticket_`)) return null;
  return { script: invocation[2], operation: "claim", state_path: state[2], run_root: runRoot };
}

function approvalBatchKey(request) {
  const params = request?.params || request || {};
  const threadId = request?.["thread" + "_id"] || params.threadId || "";
  const turnId = request?.turn_id || params.turnId || "";
  const amendment = firstApprovalValue(params, [
    "proposedExecpolicyAmendment", "proposed_execpolicy_amendment", "execpolicyAmendment", "execpolicy_amendment",
  ]);
  const claim = canonicalFast8Claim(request);
  if (!threadId || !turnId || amendment === null || !claim) return null;
  return approvalValueKey([
    threadId,
    turnId,
    request.method || "",
    amendment,
    claim,
    request.choices || [],
  ]);
}

function approvalLocation(request) {
  const params = request?.params || request || {};
  return firstApprovalValue(params, ["grantRoot", "grant_root", "cwd", "runRoot", "run_root"]);
}

function approvalKind(request) {
  if (request?.method === "item/fileChange/requestApproval") return "修改项目文件";
  if (request?.method === "item/permissions/requestApproval") return "使用指定权限";
  return "运行任务步骤";
}

function approvalIdentity(request) {
  const params = request?.params || request || {};
  const requestId = String(request?.request_id || "");
  if (!requestId) return "";
  return approvalValueKey([
    requestId,
    request?.item_id || params.itemId || "",
    request?.method || "",
    request?.["thread" + "_id"] || params.threadId || "",
    request?.turn_id || params.turnId || "",
  ]);
}

function markApprovalResolved(request) {
  const identity = approvalIdentity(request);
  if (!identity) return;
  state.resolvedApprovalIds.add(identity);
  state.pendingApprovals.delete(identity);
  state.resolvingApprovalIds.delete(identity);
}

function appendApprovalResolutionNote(request, decision) {
  const selected = (request.choices || []).find((choice) => approvalValueKey(choice.decision) === approvalValueKey(decision));
  const note = document.createElement("article");
  note.className = "action-confirmation completed";
  note.dataset.testid = "codex-permission-request";
  const copy = document.createElement("div");
  copy.className = "action-confirmation-copy";
  const title = document.createElement("strong");
  title.textContent = "权限请求已处理";
  const status = document.createElement("span");
  status.textContent = `已选择：${selected?.label || "已回复"}`;
  copy.append(title, status);
  note.append(copy);
  el["message-list"].append(note);
}

function renderApprovalCards() {
  const timeline = el["message-list"];
  const keepAtBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 48;
  for (const card of el["message-list"].querySelectorAll("[data-approval-card]")) card.remove();
  const groups = new Map();
  for (const request of state.pendingApprovals.values()) {
    const batchKey = approvalBatchKey(request);
    const key = batchKey ? `batch:${batchKey}` : `single:${request.request_id}`;
    const group = groups.get(key) || [];
    group.push(request);
    groups.set(key, group);
  }

  for (const requests of groups.values()) {
    const batch = requests.length > 1;
    const card = document.createElement("article");
    card.className = "action-confirmation";
    card.dataset.approvalCard = batch ? "batch" : "single";
    card.dataset.testid = batch ? "codex-permission-batch" : "codex-permission-request";
    card.dataset.requestIds = requests.map((request) => request.request_id).join(" ");

    const header = document.createElement("div");
    header.className = "action-confirmation-header";
    const copy = document.createElement("div");
    copy.className = "action-confirmation-copy";
    const strong = document.createElement("strong");
    strong.textContent = batch ? `Codex 需要允许 ${requests.length} 个连续步骤` : "Codex 需要你的允许";
    const summaryText = document.createElement("span");
    const reasons = [...new Set(requests.map((request) => request.params?.reason).filter(Boolean))];
    summaryText.textContent = batch
      ? (reasons.length === 1 ? reasons[0] : "这些步骤属于当前同一项任务，可以一次决定。")
      : (reasons[0] || `${approvalKind(requests[0])}需要你的允许。`);
    copy.append(strong, summaryText);
    header.append(copy);

    const detail = document.createElement("details");
    const detailSummary = document.createElement("summary");
    detailSummary.textContent = batch ? `查看本批次范围（${requests.length}）` : "查看访问范围";
    const list = document.createElement("ul");
    list.className = "action-details";
    const detailRows = batch ? [`范围：当前任务中的 ${requests.length} 个步骤`] : [`类型：${approvalKind(requests[0])}`];
    const locations = [...new Set(requests.map(approvalLocation).filter(Boolean))];
    if (locations.length === 1) detailRows.push(`位置：${locations[0]}`);
    else if (locations.length > 1) detailRows.push(`位置：${locations.length} 个任务目录`);
    for (const item of detailRows) {
      const row = document.createElement("li");
      row.textContent = item;
      list.append(row);
    }
    detail.append(detailSummary, list);

    const status = document.createElement("p");
    status.className = "action-status";
    status.textContent = batch ? "选择会逐个回复本批次中的请求。" : "请选择 Codex 提供的一个选项。";
    const actions = document.createElement("div");
    actions.className = "permission-actions";
    const request = requests[0];
    const resolving = requests.some((request) => state.resolvingApprovalIds.has(approvalIdentity(request)));
    const resolve = async (decision) => {
      const active = requests.filter((request) => state.pendingApprovals.has(approvalIdentity(request)));
      for (const request of active) state.resolvingApprovalIds.add(approvalIdentity(request));
      renderApprovalCards();
      const failures = [];
      for (const request of active) {
        try {
          await api.resolveCodexApproval(request.request_id, decision);
          markApprovalResolved(request);
          renderApprovalCards();
          if (active.length === 1) appendApprovalResolutionNote(request, decision);
        } catch (error) {
          if (error.status === 404 && error.code === "approval_request_not_found") {
            markApprovalResolved(request);
            renderApprovalCards();
            continue;
          }
          state.resolvingApprovalIds.delete(approvalIdentity(request));
          failures.push(error);
        }
      }
      renderApprovalCards();
      if (failures.length) toast(`有 ${failures.length} 个请求没有提交成功：${failures[0].message}`);
    };
    for (const [index, choice] of (request.choices || []).entries()) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = index === 0 ? "action-confirm-button" : "secondary-button";
      button.textContent = batch && index === 0 ? `允许本批次（${requests.length}）` : choice.label;
      button.disabled = resolving;
      button.addEventListener("click", () => resolve(choice.decision));
      actions.append(button);
    }
    if (!actions.childElementCount) status.textContent = "Codex 没有返回可用的选项。";
    if (resolving) status.textContent = "正在逐个提交…";
    card.append(header, detail, status, actions);
    el["message-list"].append(card);
  }
  if (keepAtBottom) timeline.scrollTop = timeline.scrollHeight;
}

function appendPermissionRequest(request) {
  const requestId = String(request?.request_id || "");
  const normalized = { ...request, request_id: requestId };
  const identity = approvalIdentity(normalized);
  if (!identity || state.resolvedApprovalIds.has(identity) || request.resolved === true || request.status === "resolved") return null;
  state.pendingApprovals.set(identity, normalized);
  renderApprovalCards();
  return el["message-list"].querySelector(`[data-request-ids~="${CSS.escape(requestId)}"]`);
}

function appendTurnOutcome(status) {
  if (!status || status === "completed") return;
  const note = document.createElement("p");
  note.className = "codex-item codex-context-note";
  note.textContent = status === "interrupted" ? "已停止" : status === "failed" ? "这轮工作失败" : statusLabel(status);
  el["message-list"].append(note);
  scrollTimeline();
}

function onConversationEvent(event) {
  const data = event.data;
  if (Number.isFinite(data?.sequence)) state.eventSequence = Math.max(state.eventSequence, data.sequence);
  if (event.event === "approval_resolution") {
    if (data?.resolved !== false) markApprovalResolved(data);
    renderApprovalCards();
    return;
  }
  if (event.event === "approval") {
    appendPermissionRequest(data);
    return;
  }
  if (event.event === "studio_rule_saved") {
    toast(data?.added ? "已加入 Studio 长期规则" : "这条内容已经在长期规则里");
    return;
  }
  if (event.event === "error") {
    toast(data?.message || "Codex 返回了一个错误");
    return;
  }
  if (event.event !== "codex" || !data?.method) return;
  const params = data.params || {};
  const method = data.method;
  const turnId = String(data.turn_id || params.turnId || params.turn?.id || state.activeTurnId || "");
  if (method === "turn/started") {
    state.submitting = false;
    setActiveTurn({ turn_id: turnId, status: params.turn?.status || "inProgress" });
    void loadTasks();
    return;
  }
  if (method === "item/started") {
    renderCodexItem({
      ...(params.item || {}),
      id: params.item?.id || params.itemId,
      __turnId: turnId,
      __source: "event",
    }, { streaming: true });
    return;
  }
  if (method === "item/agentMessage/delta") {
    const itemId = String(params.itemId || "");
    if (!itemId || typeof params.delta !== "string") return;
    const view = renderCodexItem({ id: itemId, type: "agentMessage", phase: params.phase || "commentary", __turnId: turnId }, { streaming: true });
    view.body.textContent += params.delta;
    scrollTimeline();
    return;
  }
  if (method === "item/commandExecution/outputDelta") {
    const itemId = String(params.itemId || "");
    if (!itemId || typeof params.delta !== "string") return;
    const view = renderCodexItem({ id: itemId, type: "commandExecution", status: "inProgress", __turnId: turnId }, { streaming: true });
    view.detail.textContent = view.detail.textContent === "暂无更多细节" ? params.delta : view.detail.textContent + params.delta;
    return;
  }
  if (method.includes("reasoning") && method.endsWith("Delta") && typeof params.delta === "string") {
    const itemId = String(params.itemId || `reasoning-${turnId}`);
    const view = renderCodexItem({ id: itemId, type: "reasoning", status: "inProgress", __turnId: turnId }, { streaming: true });
    view.detail.textContent = view.detail.textContent === "暂无更多细节" ? params.delta : view.detail.textContent + params.delta;
    return;
  }
  if (method === "item/completed") {
    renderCodexItem({
      ...(params.item || {}),
      id: params.item?.id || params.itemId,
      __turnId: turnId,
      __source: "event",
    }, { authoritative: true });
    return;
  }
  if (method === "turn/plan/updated") {
    renderPlan({ ...params, itemId: `plan-${turnId}`, __turnId: turnId });
    return;
  }
  if (method === "turn/completed") {
    const status = String(params.turn?.status || params.status || "completed");
    finishTurnProcess(turnId, status);
    appendTurnOutcome(status);
    if (!state.activeTurnId || state.activeTurnId === turnId) {
      state.interrupting = false;
      setActiveTurn(null);
    }
    for (const view of state.itemViews.values()) view.article?.classList.remove("streaming");
    for (const [requestId, request] of state.pendingApprovals) {
      const requestTurnId = String(request.turn_id || request.params?.turnId || "");
      if (requestTurnId === turnId) state.pendingApprovals.delete(requestId);
    }
    renderApprovalCards();
    void refreshAll();
    void loadTasks({ force: true });
  }
}

async function submitConversation(event) {
  event.preventDefault();
  if (state.submitting || !state.activeConversationId || !state.scope) return;
  const message = el["message-input"].value.trim();
  if (!message) return;
  const attachments = safeAttachmentPaths(state.attachments);
  const retouchContext = state.workspace === "retouch";
  const expectedTurnId = state.activeTurnId;
  state.submitting = true;
  el["message-input"].value = "";
  resizeMessageInput();
  state.attachments = [];
  renderAttachments();
  updateSendState();
  const requestBody = {
    message,
    current_slide_uid: state.scope.slide_uid,
    reference_images: attachments.map((item) => ({ path: item.path })),
  };
  if (retouchContext) requestBody.retouch_context = true;
  try {
    if (expectedTurnId) {
      try {
        const result = await api.steerConversationTurn(state.deckId, state.activeConversationId, {
          message,
          expected_turn_id: expectedTurnId,
          reference_images: requestBody.reference_images,
        });
        if (result?.studio_rule) {
          toast(result.studio_rule.added ? "已加入 Studio 长期规则" : "这条内容已经在长期规则里");
        }
      } catch (error) {
        if (error.status !== 409 || error.code !== "turn_not_active") throw error;
        setActiveTurn(null);
        await api.streamConversationTurn(state.deckId, state.activeConversationId, requestBody, onConversationEvent);
      }
    } else {
      try {
        await api.streamConversationTurn(state.deckId, state.activeConversationId, requestBody, onConversationEvent);
      } catch (error) {
        if (error.status !== 409 || error.code !== "turn_already_active") throw error;
        const current = await api.getConversationHistory(state.deckId, state.activeConversationId);
        const recoveredTurnId = String(current?.active_turn?.turn_id || "");
        if (!recoveredTurnId) throw error;
        setActiveTurn(current.active_turn);
        attachToActiveTurn();
        await api.steerConversationTurn(state.deckId, state.activeConversationId, {
          message,
          expected_turn_id: recoveredTurnId,
          reference_images: requestBody.reference_images,
        });
      }
    }
    const deck = currentDeck();
    if (deck) {
      const directory = normalizeConversations(await api.getConversations(deck.deck_id));
      state.conversations = directory.conversations;
      renderConversationList();
    }
  } catch (error) {
    toast(`这次没有发送成功：${error.message}`);
  } finally {
    state.submitting = false;
    updateSendState();
    el["message-input"].focus();
  }
}

async function interruptActiveTurn() {
  if (!state.activeTurnId || state.interrupting) return;
  state.interrupting = true;
  setActiveTurn({ turn_id: state.activeTurnId, status: state.activeTurnStatus });
  try {
    await api.interruptConversationTurn(state.deckId, state.activeConversationId, state.activeTurnId);
  } catch (error) {
    state.interrupting = false;
    setActiveTurn({ turn_id: state.activeTurnId, status: state.activeTurnStatus });
    toast(`无法停止：${error.message}`);
  }
}

function initializeResizers() {
  const saved = savedState();
  if (/^\d+px$/.test(saved.sidebarWidth || "")) document.documentElement.style.setProperty("--sidebar-width", saved.sidebarWidth);
  if (/^\d+px$/.test(saved.conversationWidth || "")) document.documentElement.style.setProperty("--conversation-width", saved.conversationWidth);
  if (/^\d+px$/.test(saved.outlineImageHeight || "")) document.documentElement.style.setProperty("--outline-image-height", saved.outlineImageHeight);

  const clampSidebar = (value) => Math.max(150, Math.min(340, value));
  const conversationMaximum = () => {
    const workspace = document.querySelector(".workspace:not([hidden]):not(.selector-workspace)");
    const available = workspace?.getBoundingClientRect().width || window.innerWidth;
    const sidebar = state.columns.left ? Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width")) || 218 : 58;
    return Math.max(300, Math.min(620, available - sidebar - 360));
  };
  const clampConversation = (value) => Math.max(300, Math.min(conversationMaximum(), value));

  for (const resizer of document.querySelectorAll("[data-column-resizer='left']")) {
    let startX = 0;
    let startWidth = 0;
    const move = (event) => {
      const next = clampSidebar(startWidth + event.clientX - startX);
      document.documentElement.style.setProperty("--sidebar-width", `${Math.round(next)}px`);
    };
    const stop = () => {
      resizer.classList.remove("dragging");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      persist();
    };
    resizer.addEventListener("pointerdown", (event) => {
      if (!state.columns.left) return;
      startX = event.clientX;
      startWidth = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width")) || 218;
      resizer.classList.add("dragging");
      resizer.setPointerCapture?.(event.pointerId);
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop, { once: true });
    });
    resizer.addEventListener("keydown", (event) => {
      if (!state.columns.left || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const current = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width")) || 218;
      const next = event.key === "Home" ? 150 : event.key === "End" ? 340 : clampSidebar(current + (event.key === "ArrowRight" ? 12 : -12));
      document.documentElement.style.setProperty("--sidebar-width", `${Math.round(next)}px`);
      persist();
    });
  }

  for (const resizer of document.querySelectorAll("[data-column-resizer='conversation']")) {
    let startX = 0;
    let startWidth = 0;
    const move = (event) => {
      const next = clampConversation(startWidth - (event.clientX - startX));
      document.documentElement.style.setProperty("--conversation-width", `${Math.round(next)}px`);
      resizeMessageInput();
    };
    const stop = () => {
      resizer.classList.remove("dragging");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      persist();
    };
    resizer.addEventListener("pointerdown", (event) => {
      if (!state.columns.content || !state.columns.conversation) return;
      startX = event.clientX;
      startWidth = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--conversation-width")) || 400;
      resizer.classList.add("dragging");
      resizer.setPointerCapture?.(event.pointerId);
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop, { once: true });
    });
    resizer.addEventListener("keydown", (event) => {
      if (!state.columns.content || !state.columns.conversation || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const current = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--conversation-width")) || 400;
      const next = event.key === "Home" ? 300 : event.key === "End" ? conversationMaximum() : clampConversation(current + (event.key === "ArrowLeft" ? 12 : -12));
      document.documentElement.style.setProperty("--conversation-width", `${Math.round(next)}px`);
      resizeMessageInput();
      persist();
    });
  }

  const rowResizer = document.querySelector("[data-row-resizer='outline-preview']");
  const rowBounds = () => {
    const comparison = el["page-comparison"];
    const available = comparison?.clientHeight ? comparison.clientHeight - 30 : 0;
    return { minimum: 140, maximum: Math.max(140, available - 180) };
  };
  const setImageHeight = (value) => {
    const bounds = rowBounds();
    const next = Math.max(bounds.minimum, Math.min(bounds.maximum, value));
    document.documentElement.style.setProperty("--outline-image-height", `${Math.round(next)}px`);
    rowResizer?.setAttribute("aria-valuemax", String(Math.round(bounds.maximum)));
    rowResizer?.setAttribute("aria-valuenow", String(Math.round(next)));
    return next;
  };
  if (rowResizer) {
    let startY = 0;
    let startHeight = 0;
    const move = (event) => setImageHeight(startHeight + event.clientY - startY);
    const stop = () => {
      rowResizer.classList.remove("dragging");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      persist();
    };
    rowResizer.addEventListener("pointerdown", (event) => {
      startY = event.clientY;
      startHeight = document.querySelector(".preview-card")?.getBoundingClientRect().height || 240;
      rowResizer.classList.add("dragging");
      rowResizer.setPointerCapture?.(event.pointerId);
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop, { once: true });
    });
    rowResizer.addEventListener("keydown", (event) => {
      if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const bounds = rowBounds();
      const current = document.querySelector(".preview-card")?.getBoundingClientRect().height || bounds.minimum;
      const next = event.key === "Home" ? bounds.minimum : event.key === "End" ? bounds.maximum : current + (event.key === "ArrowDown" ? 16 : -16);
      setImageHeight(next);
      persist();
    });
  }

  const keepWidthsInBounds = () => {
    const current = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--conversation-width")) || 400;
    document.documentElement.style.setProperty("--conversation-width", `${Math.round(clampConversation(current))}px`);
    const imageHeight = document.querySelector(".preview-card")?.getBoundingClientRect().height;
    if (imageHeight && el["page-comparison"]?.clientHeight) setImageHeight(imageHeight);
    resizeMessageInput();
  };
  window.addEventListener("resize", keepWidthsInBounds);
  requestAnimationFrame(keepWidthsInBounds);
}

async function refreshAll() {
  el["refresh-button"].disabled = true;
  try {
    const payload = await api.getProjects();
    state.defaultDeckId = payload?.default_deck || "";
    state.decks = normalizeDecks(payload);
    const chosen = chooseScope(state.decks, { deckId: state.deckId, slideUid: state.slideUid }, state.defaultDeckId);
    state.deckId = chosen.deckId;
    state.slideUid = chosen.slideUid;
    const deck = currentDeck();
    renderDeckSwitcher();
    renderSlideLists();
    await loadCurrentPage();
    if (state.workspace === "selector") await syncSelectorWorkspace();
    void loadTasks();
  } catch (error) {
    toast(`无法打开 PPT：${error.message}`);
  } finally {
    el["refresh-button"].disabled = false;
  }
}

function bindEvents() {
  for (const button of document.querySelectorAll("[data-workspace]")) button.addEventListener("click", () => setWorkspace(button.dataset.workspace));
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-open-selector]")) setWorkspace("selector");
    if (!event.target.closest(".project-picker")) closeProjectPicker();
    if (!event.target.closest(".task-center")) closeTaskCenter();
  });
  el["conversation-menu-button"].addEventListener("click", openConversationDrawer);
  el["task-center-button"].addEventListener("click", toggleTaskCenter);
  el["task-center-close"].addEventListener("click", () => closeTaskCenter({ focusButton: true }));
  el["studio-rules-button"].addEventListener("click", openStudioRulesDialog);
  el["studio-rules-close"].addEventListener("click", closeStudioRulesDialog);
  el["studio-rules-cancel"].addEventListener("click", closeStudioRulesDialog);
  el["studio-rules-save"].addEventListener("click", saveStudioRules);
  el["studio-rules-dialog"].addEventListener("click", (event) => {
    if (event.target === el["studio-rules-dialog"]) closeStudioRulesDialog();
  });
  el["studio-rules-dialog"].addEventListener("close", () => {
    setStudioRulesStatus();
    el["studio-rules-button"].disabled = false;
  });
  el["project-picker-button"].addEventListener("click", toggleProjectPicker);
  el["project-picker-button"].addEventListener("keydown", (event) => {
    if (!new Set(["ArrowDown", "Enter", " "]).has(event.key)) return;
    event.preventDefault();
    openProjectPicker();
  });
  el["project-search"].addEventListener("input", filterProjectOptions);
  el["project-search"].addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeProjectPicker({ focusButton: true });
      return;
    }
    if (event.key !== "ArrowDown") return;
    const first = [...el["deck-switcher"].querySelectorAll(".deck-button")]
      .find((button) => !button.closest(".project-option-row")?.hidden);
    if (first) {
      event.preventDefault();
      first.focus();
    }
  });
  el["deck-switcher"].addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeProjectPicker({ focusButton: true });
      return;
    }
    if (!new Set(["ArrowDown", "ArrowUp"]).has(event.key)) return;
    const buttons = [...el["deck-switcher"].querySelectorAll(".deck-button")]
      .filter((button) => !button.closest(".project-option-row")?.hidden);
    const index = buttons.indexOf(document.activeElement);
    const next = event.key === "ArrowDown" ? Math.min(index + 1, buttons.length - 1) : Math.max(index - 1, 0);
    if (buttons[next]) {
      event.preventDefault();
      buttons[next].focus();
    }
  });
  el["project-popover-new"].addEventListener("click", () => {
    closeProjectPicker();
    openProjectDialog();
  });
  el["project-dialog-close"].addEventListener("click", closeProjectDialog);
  el["project-dialog"].addEventListener("click", (event) => { if (event.target === el["project-dialog"]) closeProjectDialog(); });
  el["blank-project-button"].addEventListener("click", () => startProject("blank"));
  el["existing-outline-button"].addEventListener("click", () => startProject("existing"));
  el["remove-project-cancel"].addEventListener("click", closeRemoveProjectDialog);
  el["remove-project-confirm"].addEventListener("click", confirmRemoveProject);
  el["remove-project-dialog"].addEventListener("click", (event) => { if (event.target === el["remove-project-dialog"]) closeRemoveProjectDialog(); });
  el["close-conversation-drawer"].addEventListener("click", closeConversationDrawer);
  el["drawer-backdrop"].addEventListener("click", closeConversationDrawer);
  el["drawer-new-conversation"].addEventListener("click", () => createConversation());
  el["outline-language-switch"].addEventListener("click", (event) => {
    const button = event.target.closest("[data-outline-language]");
    if (!button) return;
    state.outlineLanguageView = button.dataset.outlineLanguage;
    renderOutline();
    persist();
  });
  for (const button of document.querySelectorAll("[data-column-toggle]")) {
    button.addEventListener("click", () => toggleColumn(button.dataset.columnToggle));
  }
  el["conversation-form"].addEventListener("submit", submitConversation);
  el["stop-button"].addEventListener("click", interruptActiveTurn);
  el["message-input"].addEventListener("input", () => {
    resizeMessageInput();
    updateSendState();
  });
  el["message-input"].addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing || event.keyCode === 229) return;
    if (event.shiftKey) {
      event.preventDefault();
      const input = el["message-input"];
      input.setRangeText("\n", input.selectionStart, input.selectionEnd, "end");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    event.preventDefault();
    if (!el["send-button"].disabled) el["conversation-form"].requestSubmit();
  });
  el["message-input"].addEventListener("paste", (event) => {
    if (event.clipboardData?.getData("text/plain")) return;
    const images = [...(event.clipboardData?.files || [])].filter((file) => file.type.startsWith("image/"));
    if (!images.length) return;
    event.preventDefault();
    uploadReferenceFiles(images);
  });
  el["attach-button"].addEventListener("click", () => el["attachment-input"].click());
  el["attachment-input"].addEventListener("change", () => {
    const files = [...el["attachment-input"].files];
    el["attachment-input"].value = "";
    if (!files.length) return;
    uploadReferenceFiles(files);
  });
  el["refresh-button"].addEventListener("click", refreshAll);
  el["image-dialog-close"].addEventListener("click", closeImage);
  el["image-dialog"].addEventListener("click", (event) => { if (event.target === el["image-dialog"]) closeImage(); });
  el["image-dialog-toggle"].addEventListener("click", closeImage);
  el["image-dialog"].addEventListener("close", () => el["image-dialog-content"].removeAttribute("src"));
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!el["conversation-drawer"].hidden) closeConversationDrawer();
    if (!el["task-center-popover"].hidden) closeTaskCenter({ focusButton: true });
    if (!el["project-popover"].hidden) closeProjectPicker({ focusButton: true });
  });
}

async function initialize() {
  const saved = savedState();
  state.workspace = ["outline", "selector", "retouch"].includes(saved.workspace) ? saved.workspace : "outline";
  state.deckId = typeof saved.deckId === "string" ? saved.deckId : "";
  state.slideUid = typeof saved.slideUid === "string" ? saved.slideUid : "";
  state.outlineLanguageView = ["bilingual", "zh", "en"].includes(saved.outlineLanguageView)
    ? saved.outlineLanguageView
    : "bilingual";
  if (saved.columns && typeof saved.columns === "object") {
    state.columns = {
      left: saved.columns.left !== false,
      content: saved.columns.content !== false,
      conversation: saved.columns.conversation !== false,
    };
  }
  if (!state.columns.content && !state.columns.conversation) state.columns.conversation = true;
  bindEvents();
  resizeMessageInput();
  initializeResizers();
  applyColumnState({ save: false });
  setWorkspace(state.workspace);
  await refreshAll();
  await loadConversations();
  await loadTasks();
}

initialize();
