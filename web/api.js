async function readJson(response) {
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { message: text };
    }
  }
  if (!response.ok) {
    const detail = payload?.error;
    const message = detail?.message || detail || payload?.message || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.code = detail?.code || payload?.code || null;
    error.payload = payload;
    throw error;
  }
  return payload;
}

export async function getHealth() {
  return readJson(await fetch("/api/health", { cache: "no-store" }));
}

export async function getDecks() {
  return readJson(await fetch("/api/decks", { cache: "no-store" }));
}

export async function getProjects() {
  try {
    return await readJson(await fetch("/api/projects", { cache: "no-store" }));
  } catch (error) {
    // Older isolated UI fixtures and an older running Studio backend expose the
    // same merged list at /api/decks. Keep that read-only fallback while users
    // transition to the project-aware build.
    if (error.status !== 404) throw error;
    return getDecks();
  }
}

export async function pickProjectFolder() {
  return readJson(await fetch("/api/projects/pick-folder", {
    method: "POST", headers: MUTATION_HEADERS, body: JSON.stringify({}),
  }));
}

export async function pickOutlineFile() {
  return readJson(await fetch("/api/projects/pick-outline", {
    method: "POST", headers: MUTATION_HEADERS, body: JSON.stringify({}),
  }));
}

export async function createProject(body) {
  return readJson(await fetch("/api/projects", {
    method: "POST", headers: MUTATION_HEADERS, body: JSON.stringify(body),
  }));
}

export async function getProjectOutline(deckId) {
  return readJson(await fetch(`/api/decks/${encodeURIComponent(deckId)}/outline`, { cache: "no-store" }));
}

export async function getSelector(deckId) {
  const query = deckId ? `?deck=${encodeURIComponent(deckId)}` : "";
  return readJson(await fetch(`${"/api/"}${"selector"}${query}`, { cache: "no-store" }));
}

export async function getSlide(deckId, slideUid) {
  const route = `/api/decks/${encodeURIComponent(deckId)}/slides/${encodeURIComponent(slideUid)}`;
  return readJson(await fetch(route, { cache: "no-store" }));
}

export async function getSelection(deckId, slideUid) {
  const route = `/api/decks/${encodeURIComponent(deckId)}/slides/${encodeURIComponent(slideUid)}/selection`;
  return readJson(await fetch(route, { cache: "no-store" }));
}

export async function uploadAttachment(file) {
  return readJson(await fetch("/api/attachments", {
    method: "POST",
    headers: {
      "Content-Type": file.type || "application/octet-stream",
      "X-Shawn-PPT-Studio": "1",
    },
    body: file,
  }));
}

const MUTATION_HEADERS = Object.freeze({
  "Content-Type": "application/json",
  "X-Shawn-PPT-Studio": "1",
});

export async function getConversations(deckId) {
  return readJson(await fetch(`/api/decks/${encodeURIComponent(deckId)}/conversations`, { cache: "no-store" }));
}

export async function createConversation(deckId, body = {}) {
  return readJson(await fetch(`/api/decks/${encodeURIComponent(deckId)}/conversations`, {
    method: "POST",
    headers: MUTATION_HEADERS,
    body: JSON.stringify(body),
  }));
}

export async function activateConversation(deckId, conversationId) {
  return readJson(await fetch(`/api/decks/${encodeURIComponent(deckId)}/conversations/${encodeURIComponent(conversationId)}/open`, {
    method: "POST",
    headers: MUTATION_HEADERS,
    body: JSON.stringify({}),
  }));
}

export async function getConversationHistory(deckId, conversationId) {
  return readJson(await fetch(`/api/decks/${encodeURIComponent(deckId)}/conversations/${encodeURIComponent(conversationId)}`, { cache: "no-store" }));
}

export async function streamConversationTurn(deckId, conversationId, payload, onEvent, signal) {
  const response = await fetch(`/api/decks/${encodeURIComponent(deckId)}/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: "POST",
    headers: { ...MUTATION_HEADERS, Accept: "text/event-stream" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) return readJson(response);
  if (!response.body) throw new Error("无法接收 AI 回复，请稍后再试");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    for (const block of blocks) if (block.trim()) onEvent(parseSseBlock(block));
    if (done) break;
  }
  if (buffer.trim()) onEvent(parseSseBlock(buffer));
}

export async function steerConversationTurn(deckId, conversationId, payload) {
  return readJson(await fetch(`/api/decks/${encodeURIComponent(deckId)}/conversations/${encodeURIComponent(conversationId)}/steer`, {
    method: "POST",
    headers: MUTATION_HEADERS,
    body: JSON.stringify(payload),
  }));
}

export async function interruptConversationTurn(deckId, conversationId, turnId) {
  return readJson(await fetch(`/api/decks/${encodeURIComponent(deckId)}/conversations/${encodeURIComponent(conversationId)}/interrupt`, {
    method: "POST",
    headers: MUTATION_HEADERS,
    body: JSON.stringify({ turn_id: turnId }),
  }));
}

export async function streamConversationEvents(deckId, conversationId, turnId, after, onEvent, signal) {
  const query = new URLSearchParams({ turn_id: turnId });
  if (Number.isFinite(after) && after > 0) query.set("after", String(after));
  const response = await fetch(`/api/decks/${encodeURIComponent(deckId)}/conversations/${encodeURIComponent(conversationId)}/events?${query}`, {
    headers: { Accept: "text/event-stream" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) return readJson(response);
  if (!response.body) throw new Error("无法恢复正在进行的对话");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    for (const block of blocks) if (block.trim()) onEvent(parseSseBlock(block));
    if (done) break;
  }
  if (buffer.trim()) onEvent(parseSseBlock(buffer));
}

export async function resolveCodexApproval(requestId, decision) {
  return readJson(await fetch(`/api/codex/approvals/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: MUTATION_HEADERS,
    body: JSON.stringify({ decision }),
  }));
}

export async function applyOutlineRow(deckId, slideUid, body) {
  const route = `/api/decks/${encodeURIComponent(deckId)}/slides/${encodeURIComponent(slideUid)}/outline`;
  return readJson(await fetch(route, {
    method: "PATCH",
    headers: MUTATION_HEADERS,
    body: JSON.stringify(body),
  }));
}

export async function applyOutlineChanges(deckId, body) {
  return readJson(await fetch(`/api/decks/${encodeURIComponent(deckId)}/outline`, {
    method: "PATCH",
    headers: MUTATION_HEADERS,
    body: JSON.stringify(body),
  }));
}

export async function startThread(threadId) {
  return readJson(await fetch("/api/threads", {
    method: "POST",
    headers: MUTATION_HEADERS,
    body: JSON.stringify(threadId ? { thread_id: threadId } : {}),
  }));
}

export async function createProductionIntent(body) {
  return readJson(await fetch("/api/production/intents", {
    method: "POST",
    headers: MUTATION_HEADERS,
    body: JSON.stringify(body),
  }));
}

export async function getProductionIntent(intentId) {
  return readJson(await fetch(`/api/production/intents/${encodeURIComponent(intentId)}`, { cache: "no-store" }));
}

export async function executeProductionIntent(intentId) {
  return readJson(await fetch(`/api/production/intents/${encodeURIComponent(intentId)}/execute`, {
    method: "POST",
    headers: MUTATION_HEADERS,
    body: JSON.stringify({ confirmed: true }),
  }));
}

export async function getProductionCandidates(intentId) {
  return readJson(await fetch(`/api/production/intents/${encodeURIComponent(intentId)}/candidates`, { cache: "no-store" }));
}

export async function createCandidateEdit(body) {
  return readJson(await fetch("/api/production/candidate-edits", {
    method: "POST",
    headers: MUTATION_HEADERS,
    body: JSON.stringify(body),
  }));
}

export async function getCandidateEdit(editId) {
  return readJson(await fetch(`/api/production/candidate-edits/${encodeURIComponent(editId)}`, { cache: "no-store" }));
}

export async function executeCandidateEdit(editId) {
  return readJson(await fetch(`/api/production/candidate-edits/${encodeURIComponent(editId)}/execute`, {
    method: "POST",
    headers: MUTATION_HEADERS,
    body: JSON.stringify({ confirmed: true }),
  }));
}

export async function getCandidateEditCandidates(editId) {
  return readJson(await fetch(`/api/production/candidate-edits/${encodeURIComponent(editId)}/candidates`, { cache: "no-store" }));
}

export async function getThread(threadId) {
  return readJson(await fetch(`/api/threads/${encodeURIComponent(threadId)}`, { cache: "no-store" }));
}

export function parseSseBlock(block) {
  let event = "message";
  const data = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  const raw = data.join("\n");
  if (!raw) return { event, data: null };
  try {
    return { event, data: JSON.parse(raw) };
  } catch {
    return { event, data: raw };
  }
}

export async function streamTurn(payload, onEvent, signal) {
  const response = await fetch("/api/turns", {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      "X-Shawn-PPT-Studio": "1",
    },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) return readJson(response);
  if (!response.body) throw new Error("浏览器未提供流式响应体");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      if (block.trim()) onEvent(parseSseBlock(block));
    }
    if (done) break;
  }
  if (buffer.trim()) onEvent(parseSseBlock(buffer));
}

export function runtimeFileUrl(path) {
  if (typeof path !== "string" || !path.trim()) return null;
  if (!path.trim().startsWith("/") || /^(data|blob):/i.test(path.trim())) return null;
  return `/api/runtime-file?path=${encodeURIComponent(path.trim())}`;
}
