import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const html = await readFile(new URL("../../web/index.html", import.meta.url), "utf8");
const css = await readFile(new URL("../../web/styles.css", import.meta.url), "utf8");
const app = await readFile(new URL("../../web/app.js", import.meta.url), "utf8");
const api = await readFile(new URL("../../web/api.js", import.meta.url), "utf8");

test("the project selector is global, compact, searchable, and single-select", () => {
  const topbar = html.match(/<header class="topbar">([\s\S]*?)<\/header>/)?.[1] || "";
  const outlineSidebar = html.match(/<aside class="slide-sidebar" id="outline-sidebar"[\s\S]*?<\/aside>/)?.[0] || "";
  assert.match(topbar, /id="project-picker-button"/);
  assert.match(topbar, /id="project-popover-new"/);
  assert.match(topbar, /id="project-search"/);
  assert.doesNotMatch(outlineSidebar, /deck-switcher|project-popover-new/);
  assert.match(css, /\.deck-switcher \{ max-height:/);
  assert.match(app, /role", "option"/);
  assert.match(app, /project-picker-button"\]\.title = active\?\.label/);
  assert.match(app, /button\.title = deck\.label \|\| deck\.deck_id/);
});

test("switching a task keeps the current workspace and reloads its conversations", () => {
  const selectDeck = app.match(/async function selectDeck\(deckId\) \{([\s\S]*?)\n\}/)?.[1] || "";
  assert.match(selectDeck, /loadConversations\(\)/);
  assert.doesNotMatch(selectDeck, /setWorkspace\("outline"\)/);
  assert.match(selectDeck, /state\.activeConversationId = ""/);
});

test("remove means hide from the list, never delete project files", () => {
  assert.match(html, /从列表移除这份 PPT/);
  assert.match(html, /大纲、图片、对话和导出文件都不会删除/);
  assert.match(app, /class="project-remove-icon"/);
  assert.match(app, /从列表移除（不会删除文件）/);
  assert.doesNotMatch(app, /remove\.textContent = "⋯"/);
  assert.match(api, /\/api\/projects\/\$\{encodeURIComponent\(deckId\)\}\/hide/);
  const hideProject = api.match(/export async function hideProject\(deckId\) \{([\s\S]*?)\n\}/)?.[1] || "";
  assert.doesNotMatch(hideProject, /method:\s*"DELETE"/);
  assert.match(app, /project-option-unavailable/);
  assert.match(app, /meta\.textContent = deck\.status_label/);
  assert.match(app, /已移除失效记录。其他项目未受影响。/);
});

test("the composer follows Codex keyboard behavior", () => {
  assert.match(app, /event\.key !== "Enter" \|\| event\.isComposing/);
  assert.match(app, /if \(event\.shiftKey\)[\s\S]*setRangeText\("\\n"/);
  assert.match(app, /event\.isComposing \|\| event\.keyCode === 229/);
  assert.match(app, /event\.preventDefault\(\)/);
  assert.match(app, /conversation-form"\]\.requestSubmit\(\)/);
});

test("sent input is optimistic, deduplicated, and visually separate from final output", () => {
  assert.match(app, /appendOptimisticUserMessage\(message\)/);
  assert.match(app, /reconcileOptimisticUserMessage/);
  assert.match(app, /conversationDisplayTurns\(turns, activeTurnId\)/);
  assert.match(app, /Codex · 最终结果/);
  assert.match(app, /createAgentMessageView/);
  assert.match(css, /\.codex-process/);
  assert.match(css, /\.final-answer/);
});

test("history conversations can be renamed, soft-deleted, and restored", () => {
  assert.match(html, /id="conversation-context-rename"/);
  assert.match(html, /id="conversation-context-delete"/);
  assert.match(html, /id="conversation-archive-list"/);
  assert.match(html, /项目文件未受影响|作图任务记录不会删除/);
  assert.match(api, /export async function renameConversation/);
  assert.match(api, /export async function deleteConversation/);
  assert.match(api, /export async function restoreConversation/);
});

test("the selector keeps the requested page visible and the composer grows to a bounded height", async () => {
  const selector = await readFile(new URL("../../web/selector/workspace.js", import.meta.url), "utf8");
  const selectorModel = await readFile(new URL("../../web/selector/model.js", import.meta.url), "utf8");
  assert.match(selector, /querySelector\('\[aria-current="page"\]'\)/);
  assert.match(selector, /scrollIntoView\(\{ block: "nearest" \}\)/);
  assert.match(app, /function resizeMessageInput\(\)/);
  assert.match(app, /Math\.min\(240, Math\.max\(120, window\.innerHeight \* 0\.32\)\)/);
  assert.match(css, /max-height: min\(240px, 32vh\)/);
  assert.match(css, /resize: none; overflow-y: hidden/);
  assert.match(selector, /exportFormatsCopy\(readiness\.formats\)/);
  assert.match(selectorModel, /export function exportFormatsCopy\(formats\)/);
  assert.doesNotMatch(selector, /PPTX、PDF 和页面图片正在生成/);
});

test("selected and deduplicated candidate cards have one recoverable delete flow", async () => {
  const selector = await readFile(new URL("../../web/selector/workspace.js", import.meta.url), "utf8");
  const selectorModel = await readFile(new URL("../../web/selector/model.js", import.meta.url), "utf8");
  assert.match(selector, /"取消选择并删除"/);
  assert.match(selector, /相同图片/);
  assert.match(selector, /trash\.disabled = view\.busy/);
  assert.doesNotMatch(selector, /trash\.disabled = view\.busy \|\| selected/);
  assert.match(selector, /view\.candidateRenderKey === renderKey/);
  assert.match(selector, /mutationPayload\?\.catalog \|\| mutationPayload/);
  assert.match(selectorModel, /source_count:/);
});

test("long-term Studio rules are visible, editable, and can also be saved from remember messages", async () => {
  const server = await readFile(new URL("../../server/http-server.mjs", import.meta.url), "utf8");
  assert.match(html, /id="studio-rules-button"[^>]*>长期规则</);
  assert.match(html, /id="studio-rules-dialog"/);
  assert.match(html, /id="studio-rules-input"/);
  assert.match(html, /以“记住，……”开头/);
  assert.match(html, /“记住这个要求”/);
  assert.match(css, /\.studio-rules-dialog textarea/);
  assert.match(api, /fetch\("\/api\/studio-rules"/);
  assert.match(api, /method: "PUT"/);
  assert.match(app, /async function openStudioRulesDialog\(\)/);
  assert.match(app, /async function saveStudioRules\(\)/);
  const openDialog = app.match(/async function openStudioRulesDialog\(\) \{([\s\S]*?)\n\}/)?.[1] || "";
  assert.ok(openDialog.indexOf('showModal()') < openDialog.indexOf('input.value ='));
  assert.match(openDialog, /input\.scrollTop = 0/);
  assert.match(css, /-webkit-text-fill-color: var\(--ink\)/);
  assert.match(app, /event\.event === "studio_rule_saved"/);
  assert.match(server, /rememberFromMessage\(body\?\.message\)/);
  assert.match(server, /requestUrl\.pathname === "\/api\/studio-rules"/);
});

test("the visible Studio version comes from the running desktop health response", () => {
  assert.match(html, /id="app-version"/);
  assert.match(app, /async function loadAppVersion\(\)/);
  assert.match(app, /health\?\.app_version/);
  assert.match(app, /document\.title = `Shawn PPT Studio · v\$\{version\}`/);
});
