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
  assert.match(topbar, /id="new-project-button"/);
  assert.match(topbar, /id="project-search"/);
  assert.doesNotMatch(outlineSidebar, /deck-switcher|new-project-button/);
  assert.match(css, /\.deck-switcher \{ max-height:/);
  assert.match(app, /role", "option"/);
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
  assert.match(api, /\/api\/projects\/\$\{encodeURIComponent\(deckId\)\}\/hide/);
  assert.doesNotMatch(api, /method:\s*"DELETE"/);
});

test("the composer follows Codex keyboard behavior", () => {
  assert.match(app, /event\.key !== "Enter" \|\| event\.shiftKey/);
  assert.match(app, /event\.isComposing \|\| event\.keyCode === 229/);
  assert.match(app, /event\.preventDefault\(\)/);
  assert.match(app, /conversation-form"\]\.requestSubmit\(\)/);
});

test("the selector keeps the requested page visible and the composer grows to a bounded height", async () => {
  const selector = await readFile(new URL("../../web/selector/workspace.js", import.meta.url), "utf8");
  assert.match(selector, /querySelector\('\[aria-current="page"\]'\)/);
  assert.match(selector, /scrollIntoView\(\{ block: "nearest" \}\)/);
  assert.match(app, /function resizeMessageInput\(\)/);
  assert.match(app, /Math\.min\(240, Math\.max\(120, window\.innerHeight \* 0\.32\)\)/);
  assert.match(css, /max-height: min\(240px, 32vh\)/);
  assert.match(css, /resize: none; overflow-y: hidden/);
});
