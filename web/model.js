export const MODES = Object.freeze({
  chat: {
    label: "对话",
    title: "与 Codex 讨论当前页",
    placeholder: "围绕当前内容继续讨论，AI 会接着这次对话继续理解。",
  },
  outline: {
    label: "改大纲",
    title: "让 AI 提出大纲修改",
    placeholder: "例如：把标题改成更直接的客户价值表达，保留核心事实。",
  },
  image_generate: {
    label: "作图",
    title: "为当前页生成一张实验图",
    placeholder: "描述希望的版式、视觉关系和必须保留的信息。",
  },
  image_edit: {
    label: "改图",
    title: "基于一张图片继续修改",
    placeholder: "说明要保留什么、只改变什么。",
  },
  shawn_skill_dry_run: {
    label: "Shawn 路由",
    title: "预演正式生产路线",
    placeholder: "说明正式生成目标；本动作只读路由，不会启动生产。",
  },
});

export function normalizeDecks(payload) {
  const decks = Array.isArray(payload?.decks) ? payload.decks : [];
  return decks
    .filter((deck) => deck && typeof deck.deck_id === "string" && typeof deck.deck_uid === "string")
    .map((deck) => ({
      ...deck,
      slides: (Array.isArray(deck.slides) ? deck.slides : [])
        .filter((slide) => slide && typeof slide.slide_uid === "string")
        .sort((left, right) => Number(left.order ?? 0) - Number(right.order ?? 0)),
    }));
}

export function normalizeUnavailableProjects(payload) {
  const projects = Array.isArray(payload?.unavailable_projects) ? payload.unavailable_projects : [];
  return projects
    .filter((project) => project && typeof project.deck_id === "string")
    .map((project) => ({
      deck_id: project.deck_id,
      label: typeof project.label === "string" && project.label.trim()
        ? project.label.trim()
        : "未命名 PPT",
      status: "outline_unavailable",
      status_label: "原大纲文件已丢失",
    }));
}

export function chooseScope(decks, preferred = {}, defaultDeckId = "") {
  if (!decks.length) return { deckId: "", slideUid: "" };
  const deck = decks.find((item) => item.deck_id === preferred.deckId)
    || decks.find((item) => item.deck_id === defaultDeckId)
    || decks[0];
  const slide = deck.slides.find((item) => item.slide_uid === preferred.slideUid)
    || deck.slides.find((item) => item.slide_uid === deck.default_slide_uid)
    || deck.slides[0];
  return { deckId: deck.deck_id, slideUid: slide?.slide_uid || "" };
}

const AGENT_LINK_RE = /!?\[([^\]\r\n]{1,120})\]\((<[^>\r\n]+>|[^)\r\n]+)\)/g;
const LOCAL_IMAGE_RE = /\.(?:png|jpe?g|webp)$/i;

export function agentMessageSegments(value) {
  const source = String(value || "");
  const segments = [];
  let cursor = 0;
  for (const match of source.matchAll(AGENT_LINK_RE)) {
    const rawTarget = match[2].trim();
    const target = rawTarget.startsWith("<") && rawTarget.endsWith(">")
      ? rawTarget.slice(1, -1)
      : rawTarget;
    const kind = target.startsWith("/") && LOCAL_IMAGE_RE.test(target)
      ? "local_image"
      : target.startsWith("/")
        ? "local_file"
        : /^https?:\/\//i.test(target) ? "web_link" : null;
    if (!kind) continue;
    if (match.index > cursor) segments.push({ type: "text", text: source.slice(cursor, match.index) });
    segments.push({
      type: kind,
      label: match[1].trim() || (kind === "local_image" ? "查看图片" : "打开文件"),
      target,
    });
    cursor = match.index + match[0].length;
  }
  if (cursor < source.length) segments.push({ type: "text", text: source.slice(cursor) });
  return segments.length ? segments : [{ type: "text", text: source }];
}

export function scopeFromSlide(detail) {
  if (!detail?.slide) return null;
  return {
    deck_id: detail.deck_id,
    deck_uid: detail.deck_uid,
    slide_uid: detail.slide.slide_uid,
    page_id: detail.slide.page_id,
    page_label: detail.slide.page_label,
    title: detail.slide.title,
    subtitle: detail.slide.subtitle || null,
    multilingual: detail.slide.multilingual || null,
    outline_markdown: detail.slide.markdown,
    revision_id: detail.revision_id,
    sha256: detail.sha256,
    outline_path: detail.outline_path,
  };
}

export function proposalForScope(candidate, scope) {
  if (!candidate || !scope || candidate.action !== "outline_patch") return null;
  if (candidate.deck_uid !== scope.deck_uid || candidate.slide_uid !== scope.slide_uid) return null;
  if (typeof candidate.replacement_markdown !== "string" || !candidate.replacement_markdown.trim()) return null;
  return candidate;
}

export function outlineApplyBody(proposal, scope) {
  const valid = proposalForScope(proposal, scope);
  if (!valid) throw new Error("提案与当前 Deck/Slide 不匹配");
  return {
    expected_sha256: scope.sha256,
    deck_uid: scope.deck_uid,
    slide_uid: scope.slide_uid,
    replacement_markdown: valid.replacement_markdown,
    change_note: valid.summary || "AI outline proposal confirmed in Shawn PPT Studio",
  };
}

export function normalizeImportedImages(records) {
  const byPath = new Map();
  for (const record of Array.isArray(records) ? records : []) {
    const path = record?.path;
    if (typeof path !== "string" || !path.startsWith("/") || /^(data|blob):/i.test(path)) continue;
    byPath.set(path, {
      import_id: record.import_id || null,
      thread_id: record.thread_id || null,
      turn_id: record.turn_id || null,
      item_id: record.item_id || null,
      mode: record.mode || null,
      path,
      input_image_path: record.input_image_path || null,
      file_sha256: record.file_sha256 || null,
      file_size: Number.isFinite(record.file_size) ? record.file_size : null,
      revised_prompt: record.revised_prompt || null,
      imported_at: record.imported_at || null,
      status: record.status || "completed",
    });
  }
  return [...byPath.values()].sort((left, right) => String(left.imported_at || "").localeCompare(String(right.imported_at || "")));
}

export function mergeImportedImages(current, incoming) {
  return normalizeImportedImages([...(current || []), ...(incoming || [])]);
}

export function flattenHistory(payload) {
  const source = payload?.thread || payload;
  const turns = source?.turns || payload?.turns || [];
  const messages = [];
  for (const turn of turns) {
    const items = turn?.items || turn?.output || turn?.messages || [];
    for (const item of items) {
      const role = item?.role || (item?.type === "userMessage" ? "user" : item?.type === "agentMessage" ? "assistant" : "");
      const text = item?.text || item?.content?.[0]?.text || item?.content;
      if ((role === "user" || role === "assistant") && typeof text === "string") {
        messages.push({ role, text, turn_id: turn?.id || null });
      }
    }
  }
  return messages;
}

export function productionPlan(scope) {
  if (!scope) return null;
  return {
    status: "not_connected",
    deck_uid: scope.deck_uid,
    slide_uid: scope.slide_uid,
    page_label: scope.page_label,
    outline_revision: scope.revision_id,
    route: "$shawn-ppt-image → fast_8x1_diverse → canonical control plane",
    expected_candidates: 8,
    confirmation_required: false,
  };
}

export function normalizeProductionIntent(payload) {
  const intent = payload?.intent;
  if (!intent || typeof intent.intent_id !== "string" || !intent.intent_id) return null;
  const allowedStatuses = new Set(["draft", "approved", "running", "candidate_ready", "failed"]);
  return {
    ...intent,
    status: allowedStatuses.has(intent.status) ? intent.status : "failed",
    native_refs: intent.native_refs && typeof intent.native_refs === "object" ? intent.native_refs : null,
    error: intent.error && typeof intent.error === "object" ? intent.error : null,
  };
}

export function candidateSlotSummary(payload) {
  const slots = (Array.isArray(payload?.candidates) ? payload.candidates : [])
    .map((candidate) => candidate?.style_slot)
    .filter((slot) => typeof slot === "string" && /^[A-H]$/.test(slot));
  const uniqueSlots = [...new Set(slots)].sort();
  return {
    count: uniqueSlots.length,
    slots: uniqueSlots.join(""),
    availability: payload?.availability || "unavailable",
  };
}

export function normalizeProductionCandidates(payload) {
  const candidates = [];
  for (const candidate of Array.isArray(payload?.candidates) ? payload.candidates : []) {
    if (
      !candidate ||
      typeof candidate.candidate_id !== "string" || !candidate.candidate_id ||
      typeof candidate.style_slot !== "string" || !/^[A-H]$/.test(candidate.style_slot) ||
      typeof candidate.path !== "string" || !candidate.path.startsWith("/") ||
      typeof candidate.sha256 !== "string" || !/^[a-f0-9]{64}$/i.test(candidate.sha256)
    ) continue;
    candidates.push({
      ...candidate,
      sha256: candidate.sha256.toLowerCase(),
      width: Number.isFinite(candidate.width) ? candidate.width : null,
      height: Number.isFinite(candidate.height) ? candidate.height : null,
    });
  }
  return candidates.sort((left, right) => left.style_slot.localeCompare(right.style_slot));
}

export function normalizeCandidateEdit(payload) {
  const edit = payload?.edit;
  if (!edit || typeof edit.edit_id !== "string" || !edit.edit_id) return null;
  const allowedStatuses = new Set(["draft", "approved", "running", "candidate_ready", "failed"]);
  const parent = edit.parent_candidate;
  return {
    ...edit,
    status: allowedStatuses.has(edit.status) ? edit.status : "failed",
    parent_candidate: parent &&
      typeof parent.candidate_id === "string" &&
      typeof parent.path === "string" && parent.path.startsWith("/") &&
      typeof parent.sha256 === "string" && /^[a-f0-9]{64}$/i.test(parent.sha256)
      ? { ...parent, sha256: parent.sha256.toLowerCase() }
      : null,
    native_refs: edit.native_refs && typeof edit.native_refs === "object" ? edit.native_refs : null,
    error: edit.error && typeof edit.error === "object" ? edit.error : null,
  };
}

export function normalizeEditCandidates(payload, edit) {
  const candidates = [];
  for (const candidate of Array.isArray(payload?.candidates) ? payload.candidates : []) {
    if (
      !candidate ||
      typeof candidate.candidate_id !== "string" || !candidate.candidate_id ||
      typeof candidate.path !== "string" || !candidate.path.startsWith("/") ||
      typeof candidate.sha256 !== "string" || !/^[a-f0-9]{64}$/i.test(candidate.sha256) ||
      candidate.derivation_kind !== "single_image_edit" ||
      candidate.parent_candidate_id !== edit?.candidate_id
    ) continue;
    candidates.push({ ...candidate, sha256: candidate.sha256.toLowerCase() });
  }
  return candidates;
}

export function candidateEditDraftBody(sourceIntentId, candidate, userRequest) {
  if (typeof sourceIntentId !== "string" || !sourceIntentId) throw new Error("source_intent_id is required");
  if (!candidate?.candidate_id) throw new Error("candidate_id is required");
  if (typeof userRequest !== "string" || !userRequest.trim()) throw new Error("user_request is required");
  return {
    source_intent_id: sourceIntentId,
    candidate_id: candidate.candidate_id,
    user_request: userRequest.trim(),
  };
}

export function selectorUrl(base = "http://127.0.0.1:8765/") {
  try {
    const url = new URL(base);
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "::1"].includes(url.hostname)) return null;
    return url.href;
  } catch {
    return null;
  }
}

export function shortRevision(value) {
  return String(value || "未记录").replace(/^sha256:/, "").slice(0, 12);
}

export function outlineDisplayValue(value) {
  return String(value || "")
    .replaceAll("**", "")
    .replace(/<br\s*\/?>/gi, "\n")
    .trim();
}

export function outlineInlineDisplayValue(value) {
  return outlineDisplayValue(value).replace(/\s*\n+\s*/g, " · ");
}

function englishPageModel(value) {
  const sections = [];
  let title = "";
  for (const line of outlineDisplayValue(value).split(/\n+/).map((item) => item.trim()).filter(Boolean)) {
    const match = line.match(/^English\s+(Title|Core Thesis|Display Content)\s*:\s*(.*)$/i);
    if (!match) {
      sections.push({ label: "English Content", value: line });
      continue;
    }
    const label = match[1].toLowerCase();
    if (label === "title") title = match[2].trim();
    else sections.push({
      label: label === "core thesis" ? "English Core Thesis" : "English Display Content",
      value: match[2].trim(),
    });
  }
  return { title, sections };
}

export function outlineReadingModel(
  markdown,
  fallbackTitle = "",
  explicitSubtitle = "",
  multilingual = null,
  languageView = "bilingual",
) {
  const source = String(markdown || "").trim();
  const cleanFallbackTitle = outlineDisplayValue(fallbackTitle);
  const subtitle = outlineDisplayValue(explicitSubtitle);
  if (multilingual?.english_page_content) {
    const view = ["bilingual", "zh", "en"].includes(languageView) ? languageView : "bilingual";
    const english = englishPageModel(multilingual.english_page_content);
    const chineseSections = [
      { label: "核心命题", value: outlineDisplayValue(multilingual.chinese?.core_thesis) },
      { label: "信息密度／上屏层级", value: outlineDisplayValue(multilingual.chinese?.density) },
      { label: "页面必讲内容", value: outlineDisplayValue(multilingual.chinese?.required_content) },
    ].filter((section) => section.value);
    const sharedSections = [
      { label: "双语交付策略", value: outlineDisplayValue(multilingual.bilingual_strategy) },
      { label: "同页双语配对", value: outlineDisplayValue(multilingual.same_page_pairing) },
      { label: "视觉表达目标／用户硬约束", value: outlineDisplayValue(multilingual.visual_constraints) },
    ].filter((section) => section.value);
    return {
      multilingual: true,
      languageView: view,
      title: view === "en" ? english.title || cleanFallbackTitle || "This slide" : cleanFallbackTitle || "这一页的大纲",
      subtitle: view === "en" ? "" : subtitle,
      sections: view === "zh"
        ? [...chineseSections, sharedSections.at(-1)].filter(Boolean)
        : view === "en"
          ? english.sections
          : [
              ...chineseSections,
              ...(english.title ? [{ label: "English Title", value: english.title }] : []),
              ...english.sections,
              ...sharedSections,
            ],
    };
  }
  if (!source.startsWith("|") || !source.endsWith("|")) {
    return {
      title: cleanFallbackTitle || "这一页的大纲",
      subtitle,
      sections: source ? [{ label: "内容", value: outlineDisplayValue(source) }] : [],
    };
  }
  const cells = source.slice(1, -1).split("|").map((cell) => cell.replaceAll("**", "").trim());
  const values = cells.slice(1).map(outlineDisplayValue).filter(Boolean);
  const title = values.shift() || cleanFallbackTitle || "这一页的大纲";
  if (subtitle) {
    const subtitleIndex = values.indexOf(subtitle);
    if (subtitleIndex >= 0) values.splice(subtitleIndex, 1);
  }
  const labels = ["核心表达", "内容要点", "讲述逻辑", "视觉建议", "备注"];
  return {
    title,
    subtitle,
    sections: values.map((value, index) => ({ label: labels[index] || `补充内容 ${index + 1}`, value })),
  };
}

export function normalizeSelection(payload) {
  const allowed = new Set(["selected", "empty", "unavailable"]);
  const status = allowed.has(payload?.status) ? payload.status : "unavailable";
  const candidates = [];
  for (const candidate of Array.isArray(payload?.selected_candidates) ? payload.selected_candidates : []) {
    if (!candidate || typeof candidate.candidate_id !== "string" || !candidate.candidate_id) continue;
    if (typeof candidate.preview_url !== "string" || !candidate.preview_url.startsWith("/api/")) continue;
    candidates.push({
      candidate_id: candidate.candidate_id,
      preview_url: candidate.preview_url,
      path: typeof candidate.path === "string" && candidate.path.startsWith("/") ? candidate.path : null,
      file_sha256: typeof candidate.file_sha256 === "string" ? candidate.file_sha256 : null,
      width: Number.isFinite(candidate.width) ? candidate.width : null,
      height: Number.isFinite(candidate.height) ? candidate.height : null,
      source: typeof candidate.source === "string" ? candidate.source : null,
      display_label: typeof candidate.display_label === "string" && candidate.display_label.trim()
        ? candidate.display_label.trim()
        : null,
    });
  }
  return {
    status,
    confirmed: payload?.confirmed === true,
    candidates: status === "selected" && payload?.confirmed === true ? candidates : [],
    selector_url: selectorUrl(payload?.selector_url || ""),
    message: String(payload?.empty_message || payload?.message || "暂时无法读取正式选稿。"),
  };
}

export function normalizeFocusMode(value) {
  return ["balanced", "content", "conversation"].includes(value) ? value : "balanced";
}

export function retouchDisplayLabel(pageLabel, index, total, provided = "") {
  const explicit = typeof provided === "string" ? provided.trim() : "";
  if (explicit) return explicit;
  const page = typeof pageLabel === "string" && pageLabel.trim() ? pageLabel.trim() : "当前页";
  if (!Number.isFinite(total) || total <= 1) return page;
  const offset = Math.max(0, Number.isFinite(index) ? Math.floor(index) : 0);
  const suffix = offset < 26 ? String.fromCharCode(65 + offset) : String(offset + 1);
  return `${page}-${suffix}`;
}

export function normalizeConversations(payload) {
  const items = [];
  for (const item of Array.isArray(payload?.conversations) ? payload.conversations : []) {
    if (!item || typeof item.conversation_id !== "string" || !item.conversation_id) continue;
    const createdAt = typeof item.created_at === "string" ? item.created_at : null;
    items.push({
      conversation_id: item.conversation_id,
      title: displayConversationTitle(item.title, createdAt),
      created_at: createdAt,
      updated_at: typeof item.updated_at === "string" ? item.updated_at : null,
      last_used_at: typeof item.last_used_at === "string" ? item.last_used_at : null,
      archived_at: typeof item.archived_at === "string" ? item.archived_at : null,
    });
  }
  return {
    active_conversation_id: typeof payload?.active_conversation_id === "string" ? payload.active_conversation_id : null,
    conversations: items.sort((left, right) => String(right.last_used_at || "").localeCompare(String(left.last_used_at || ""))),
  };
}

export function conversationDisplayTurns(turns, activeTurnId) {
  const items = Array.isArray(turns) ? turns : [];
  const activeId = String(activeTurnId || "");
  if (!activeId) return items;
  const activeTurn = items.find((turn) => String(turn?.turn_id || "") === activeId) || null;
  const userItems = activeTurn?.items?.filter((item) => item?.type === "userMessage") || [];
  return [
    ...items.filter((turn) => String(turn?.turn_id || "") !== activeId),
    ...(userItems.length ? [{ ...activeTurn, items: userItems }] : []),
  ];
}

export function displayConversationTitle(title, createdAt) {
  const clean = typeof title === "string" ? title.trim() : "";
  if (clean && !/^新对话\s*\d*$/u.test(clean)) return clean;
  const date = new Date(createdAt || "");
  if (Number.isNaN(date.getTime())) return "新的对话";
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${date.getMonth() + 1}月${date.getDate()}日 ${hours}:${minutes} 的对话`;
}

export function formatConversationTime(value) {
  if (!value) return "刚刚";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "已保存";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function safeAttachmentPaths(files) {
  return (Array.isArray(files) ? files : [...(files || [])])
    .map((file) => ({
      name: String(file?.name || "参考文件"),
      path: typeof file?.path === "string" && file.path.startsWith("/") ? file.path : null,
    }))
    .filter((file) => file.path);
}

export function conversationHistoryEntries(payload) {
  const entries = [];
  for (const turn of Array.isArray(payload?.turns) ? payload.turns : []) {
    for (const message of Array.isArray(turn?.messages) ? turn.messages : []) {
      if (!["user", "assistant"].includes(message?.role) || typeof message?.text !== "string") continue;
      entries.push({ role: message.role, text: message.text, response: message.response || null });
    }
  }
  return entries;
}

export function codexHistoryTurns(payload) {
  const turns = [];
  for (const [turnIndex, turn] of (Array.isArray(payload?.turns) ? payload.turns : []).entries()) {
    const turnId = String(turn?.id || turn?.turn_id || `history-turn-${turnIndex}`);
    let items = Array.isArray(turn?.items) ? turn.items.filter((item) => item && typeof item === "object") : [];
    if (!items.length && Array.isArray(turn?.messages)) {
      items = turn.messages
        .filter((message) => ["user", "assistant"].includes(message?.role) && typeof message?.text === "string")
        .map((message, messageIndex) => message.role === "user"
          ? { id: `${turnId}-legacy-${messageIndex}`, type: "userMessage", content: [{ type: "text", text: message.text }] }
          : { id: `${turnId}-legacy-${messageIndex}`, type: "agentMessage", text: message.text, phase: "final_answer" });
    }
    turns.push({ turn_id: turnId, status: String(turn?.status || "completed"), items });
  }
  return turns;
}

export function codexItemText(item) {
  if (!item || typeof item !== "object") return "";
  if (typeof item.text === "string") return item.text;
  if (item.type === "userMessage" && Array.isArray(item.content)) {
    const text = item.content
      .filter((entry) => entry?.type === "text" && typeof entry.text === "string")
      .map((entry) => entry.text)
      .join("\n");
    const startMarker = "[SHAWN_PPT_STUDIO_USER_MESSAGE]";
    const endMarker = "[/SHAWN_PPT_STUDIO_USER_MESSAGE]";
    const start = text.indexOf(startMarker);
    const end = text.indexOf(endMarker);
    return start >= 0 && end > start ? text.slice(start + startMarker.length, end).trim() : text;
  }
  if (Array.isArray(item.content)) {
    return item.content
      .filter((entry) => typeof entry?.text === "string")
      .map((entry) => entry.text)
      .join("\n");
  }
  return "";
}

export function codexPlanSteps(value) {
  const source = Array.isArray(value?.plan) ? value.plan : Array.isArray(value?.steps) ? value.steps : [];
  return source.map((step) => ({
    text: String(step?.step || step?.text || step?.description || ""),
    status: ["pending", "inProgress", "completed"].includes(step?.status) ? step.status : "pending",
  })).filter((step) => step.text);
}

export function codexItemPresentation(item) {
  const type = String(item?.type || "unknown");
  const status = String(item?.status || "");
  const labels = {
    commandExecution: "运行命令",
    fileChange: "修改文件",
    mcpToolCall: "使用工具",
    dynamicToolCall: "使用工具",
    webSearch: "搜索资料",
    imageView: "查看图片",
    imageGeneration: status === "completed" ? "图片已生成" : "正在生成图片",
    collabToolCall: "协作处理",
    contextCompaction: "整理对话上下文",
    reasoning: "思考摘要",
  };
  const title = String(item?.title || item?.name || item?.tool || labels[type] || "处理步骤");
  const detailParts = [];
  if (typeof item?.command === "string") detailParts.push(item.command);
  if (typeof item?.aggregatedOutput === "string") detailParts.push(item.aggregatedOutput);
  if (typeof item?.output === "string") detailParts.push(item.output);
  if (typeof item?.summary === "string") detailParts.push(item.summary);
  if (typeof item?.result === "string") detailParts.push(item.result);
  return { type, title, status, detail: detailParts.filter(Boolean).join("\n") };
}
