import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(here, "../..");
const webRoot = path.resolve(here, "../../web");
const evidenceRoot = path.resolve(here, "../ux-evidence/project-switcher-v1");

function loadPlaywright() {
  const moduleRoots = [
    process.env.SHAWN_PPT_STUDIO_NODE_MODULES,
    process.env.CODEX_NODE_MODULES,
    ...(process.env.NODE_PATH?.split(path.delimiter) || []),
    path.join(projectRoot, "node_modules"),
    path.resolve(path.dirname(process.execPath), "../node_modules"),
  ].filter(Boolean);

  const attempted = [];
  for (const moduleRoot of new Set(moduleRoots.map((entry) => path.resolve(entry)))) {
    attempted.push(moduleRoot);
    try {
      const requireFromRoot = createRequire(path.join(moduleRoot, "__studio_test_loader__.cjs"));
      return requireFromRoot("playwright");
    } catch (error) {
      if (error?.code !== "MODULE_NOT_FOUND") throw error;
    }
  }

  throw new Error(
    `Playwright is unavailable. Install it in the project or set SHAWN_PPT_STUDIO_NODE_MODULES. Checked: ${attempted.join(", ")}`,
  );
}

function browserLaunchOptions() {
  const configured = process.env.SHAWN_PPT_STUDIO_BROWSER;
  const candidates = [
    configured,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
  ].filter(Boolean);
  const executablePath = candidates.find((candidate) => fs.existsSync(candidate));
  return executablePath ? { headless: true, executablePath } : { headless: true };
}

const { chromium } = loadPlaywright();

const projects = Array.from({ length: 7 }, (_, index) => {
  const number = index + 1;
  const slideCount = number === 1 ? 24 : 1;
  const slides = Array.from({ length: slideCount }, (_, slideIndex) => {
    const pageNumber = slideIndex + 1;
    return {
      slide_uid: number === 1 ? `SLIDE_${pageNumber}` : `SLIDE_${number}`,
      page_id: `P${pageNumber}`,
      page_label: `P${String(pageNumber).padStart(2, "0")}`,
      order: pageNumber,
      title: pageNumber === 1 ? `项目 ${number} 的第一页` : `项目 ${number} 的第 ${pageNumber} 页`,
      markdown: `| P${pageNumber} | **项目 ${number} 的第 ${pageNumber} 页** | 核心表达 | 内容 | 视觉 |`,
    };
  });
  return {
    deck_id: `project-${number}`,
    deck_uid: `PROJECT_${number}`,
    label: `项目 ${number} · 海外交付方案`,
    default_slide_uid: slides[0].slide_uid,
    slides,
  };
});

function json(response, value, status = 200) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(value));
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

async function startServer() {
  const hidden = new Set();
  const sentMessages = [];
  const stoppedTasks = [];
  const conversationStores = new Map(projects.map((project, index) => {
    const number = index + 1;
    const primary = {
      conversation_id: `chat-${number}`,
      title: `项目 ${number} 最近对话`,
      created_at: "2026-08-14T01:00:00Z",
      updated_at: "2026-08-14T02:00:00Z",
      last_used_at: "2026-08-14T02:00:00Z",
      archived_at: null,
    };
    const conversations = number === 1 ? [primary, {
      conversation_id: "chat-1-old",
      title: "项目 1 早期对话",
      created_at: "2026-08-13T01:00:00Z",
      updated_at: "2026-08-13T02:00:00Z",
      last_used_at: "2026-08-13T02:00:00Z",
      archived_at: null,
    }] : [primary];
    return [project.deck_id, { active: primary.conversation_id, conversations }];
  }));
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    if (request.method === "GET" && url.pathname === "/api/tasks") {
      return json(response, {
        active_count: 2,
        attention_count: 0,
        tasks: [
          { task_id: "task-fast8", deck_id: "project-1", deck_label: "项目 1 · 海外交付方案", conversation_id: "chat-1", slide_uid: "SLIDE_6", page_label: "P06", title: "P06 · 8×1", status: "generating", status_label: "已生成 4/8", completed_units: 4, total_units: 8, progress_percent: 50, elapsed_seconds: 420, can_stop: true, can_open_conversation: true },
          { task_id: "task-4x3", deck_id: "project-2", deck_label: "项目 2 · 海外交付方案", conversation_id: "chat-2", slide_uid: "SLIDE_2", page_label: "P01", title: "P01–P03 · 4×3", status: "preparing", status_label: "准备中", completed_units: 0, total_units: 12, progress_percent: null, elapsed_seconds: 75, can_stop: false, can_open_conversation: true },
          { task_id: "task-done", deck_id: "project-3", deck_label: "项目 3 · 海外交付方案", conversation_id: "chat-3", slide_uid: "SLIDE_3", page_label: "P01", title: "整套作图 · 1 页", status: "completed", status_label: "已完成", completed_units: 1, total_units: 1, progress_percent: 100, elapsed_seconds: 900, can_stop: false, can_open_conversation: true },
        ],
      });
    }
    const taskInterrupt = url.pathname.match(/^\/api\/tasks\/([^/]+)\/interrupt$/);
    if (request.method === "POST" && taskInterrupt) {
      stoppedTasks.push(taskInterrupt[1]);
      return json(response, { task_id: taskInterrupt[1], interrupt_requested: true }, 202);
    }
    if (request.method === "GET" && url.pathname === "/api/projects") {
      return json(response, { default_deck: projects.find((item) => !hidden.has(item.deck_id))?.deck_id || null, decks: projects.filter((item) => !hidden.has(item.deck_id)) });
    }
    if (request.method === "POST" && url.pathname === "/api/projects/pick-outline") {
      return json(response, { cancelled: false, selection: { kind: "outline", path: "/tmp/project-4.md" } });
    }
    if (request.method === "POST" && url.pathname === "/api/projects") {
      await readBody(request);
      hidden.delete("project-4");
      return json(response, { project: projects[3], reused: true, restored: true });
    }
    const hide = url.pathname.match(/^\/api\/projects\/(project-\d+)\/hide$/);
    if (request.method === "POST" && hide) {
      await readBody(request);
      hidden.add(hide[1]);
      return json(response, { hidden: true, deck_id: hide[1], remaining_count: projects.length - hidden.size });
    }
    const detail = url.pathname.match(/^\/api\/decks\/(project-\d+)\/slides\/(SLIDE_\d+)$/);
    if (request.method === "GET" && detail) {
      const project = projects.find((item) => item.deck_id === detail[1]);
      const slide = project.slides.find((item) => item.slide_uid === detail[2]);
      return json(response, {
        deck_id: project.deck_id,
        deck_uid: project.deck_uid,
        revision_id: "test",
        sha256: "a".repeat(64),
        slide,
      });
    }
    if (request.method === "GET" && /^\/api\/decks\/project-\d+\/slides\/SLIDE_\d+\/selection$/.test(url.pathname)) {
      return json(response, { status: "empty", confirmed: false, selected_candidates: [] });
    }
    const directory = url.pathname.match(/^\/api\/decks\/(project-\d+)\/conversations$/);
    if (request.method === "GET" && directory) {
      const store = conversationStores.get(directory[1]);
      return json(response, {
        active_conversation_id: store.active,
        conversations: store.conversations.filter((item) => !item.archived_at),
      });
    }
    const archivedDirectory = url.pathname.match(/^\/api\/decks\/(project-\d+)\/conversations\/archived$/);
    if (request.method === "GET" && archivedDirectory) {
      const store = conversationStores.get(archivedDirectory[1]);
      return json(response, { conversations: store.conversations.filter((item) => item.archived_at) });
    }
    const restoreConversation = url.pathname.match(/^\/api\/decks\/(project-\d+)\/conversations\/([^/]+)\/restore$/);
    if (request.method === "POST" && restoreConversation) {
      await readBody(request);
      const store = conversationStores.get(restoreConversation[1]);
      const conversation = store.conversations.find((item) => item.conversation_id === restoreConversation[2]);
      conversation.archived_at = null;
      conversation.last_used_at = "2026-08-14T03:00:00Z";
      store.active = conversation.conversation_id;
      return json(response, { conversation });
    }
    const conversationRecord = url.pathname.match(/^\/api\/decks\/(project-\d+)\/conversations\/([^/]+)$/);
    if (request.method === "PATCH" && conversationRecord) {
      const body = await readBody(request);
      const store = conversationStores.get(conversationRecord[1]);
      const conversation = store.conversations.find((item) => item.conversation_id === conversationRecord[2]);
      conversation.title = body.title;
      conversation.updated_at = "2026-08-14T03:00:00Z";
      return json(response, { conversation });
    }
    if (request.method === "DELETE" && conversationRecord) {
      const store = conversationStores.get(conversationRecord[1]);
      const conversation = store.conversations.find((item) => item.conversation_id === conversationRecord[2]);
      conversation.archived_at = "2026-08-14T03:00:00Z";
      const next = store.conversations.find((item) => !item.archived_at);
      store.active = next?.conversation_id || null;
      return json(response, { archived: true, conversation, active_conversation_id: store.active });
    }
    if (request.method === "GET" && conversationRecord) {
      return json(response, { active_turn: null, turns: [] });
    }
    if (request.method === "POST" && /^\/api\/decks\/project-\d+\/conversations\/chat-\d+\/messages$/.test(url.pathname)) {
      const body = await readBody(request);
      sentMessages.push(body.message);
      const turnId = `keyboard-turn-${sentMessages.length}`;
      await new Promise((resolve) => setTimeout(resolve, 100));
      response.writeHead(200, { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-store" });
      const events = [
        { method: "turn/started", params: { turn: { id: turnId, status: "inProgress" } } },
        { method: "item/started", params: { turnId, item: { id: `${turnId}-user`, type: "userMessage", content: [{ type: "text", text: body.message }] } } },
        { method: "item/started", params: { turnId, item: { id: `${turnId}-assistant`, type: "agentMessage", phase: "commentary", text: "" } } },
        { method: "item/agentMessage/delta", params: { turnId, itemId: `${turnId}-assistant`, phase: "commentary", delta: "正在读取项目。" } },
        { method: "item/completed", params: { turnId, item: { id: `${turnId}-assistant`, type: "agentMessage", phase: "final", text: "最终答复。" } } },
        { method: "turn/completed", params: { turn: { id: turnId, status: "completed" } } },
      ];
      for (const [index, event] of events.entries()) {
        response.write(`id: ${index + 1}\nevent: codex\ndata: ${JSON.stringify({ contract_version: 1, sequence: index + 1, turn_id: turnId, ...event })}\n\n`);
      }
      return response.end();
    }
    const selector = url.pathname.match(/^\/api\/selector-workspace\/decks\/(project-\d+)\/catalog(?:\/refresh)?$/);
    if (selector) {
      const project = projects.find((item) => item.deck_id === selector[1]);
      return json(response, {
        deck_id: project.deck_id,
        label: project.label,
        source_kind: "studio",
        pages: project.slides.map((slide) => ({
          slide_uid: slide.slide_uid,
          page_label: slide.page_label,
          title: slide.title,
          included: true,
          confirmed: false,
          resolution: "missing",
          candidates: [],
        })),
        summary: { page_count: project.slides.length, included_count: project.slides.length, confirmed_count: 0, pending_count: project.slides.length },
      });
    }
    const selectorPage = url.pathname.match(/^\/api\/selector-workspace\/decks\/(project-\d+)\/slides\/(SLIDE_\d+)$/);
    if (request.method === "GET" && selectorPage) {
      const project = projects.find((item) => item.deck_id === selectorPage[1]);
      const slide = project.slides.find((item) => item.slide_uid === selectorPage[2]);
      return json(response, {
        page: {
          slide_uid: slide.slide_uid,
          page_label: slide.page_label,
          title: slide.title,
          included: true,
          confirmed: false,
          resolution: "missing",
          candidates: [],
        },
      });
    }
    const asset = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
    const target = path.resolve(webRoot, asset);
    if (target.startsWith(webRoot) && fs.existsSync(target) && fs.statSync(target).isFile()) {
      const type = target.endsWith(".js") ? "text/javascript" : target.endsWith(".css") ? "text/css" : "text/html";
      response.writeHead(200, { "content-type": `${type}; charset=utf-8` });
      return fs.createReadStream(target).pipe(response);
    }
    return json(response, { error: "not found" }, 404);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return { server, sentMessages, stoppedTasks, url: `http://127.0.0.1:${server.address().port}/` };
}

test("seven projects stay compact and switch the whole task context", async () => {
  const { server, sentMessages, stoppedTasks, url } = await startServer();
  let browser;
  try {
    fs.mkdirSync(evidenceRoot, { recursive: true });
    browser = await chromium.launch(browserLaunchOptions());
    for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 760 }]) {
      const page = await browser.newPage({ viewport });
      await page.goto(url, { waitUntil: "networkidle" });
      await page.locator("#project-picker-label").filter({ hasText: "项目 1" }).waitFor();

      const picker = await page.locator("#project-picker-button").boundingBox();
      await page.locator("#project-picker-button").click();
      const create = await page.locator("#project-popover-new").boundingBox();
      await page.keyboard.press("Escape");
      const topbar = await page.locator(".topbar").boundingBox();
      const workspaceTabs = await page.locator(".workspace-tabs").boundingBox();
      const taskButton = await page.locator("#task-center-button").boundingBox();
      assert.ok(picker && create && topbar && workspaceTabs && taskButton);
      assert.ok(picker.height >= 44 && create.height >= 44);
      assert.ok(taskButton.height >= 44);
      assert.ok(picker.y >= topbar.y && picker.y + picker.height <= topbar.y + topbar.height + 1);
      assert.ok(create.y >= topbar.y + topbar.height && create.y + create.height <= viewport.height);
      assert.ok(picker.x + picker.width + 8 <= workspaceTabs.x, "project and workspace groups stay visually separate");
      assert.ok(workspaceTabs.x + workspaceTabs.width + 8 <= taskButton.x, "workspace and action groups stay visually separate");
      assert.equal(await page.locator("body").evaluate((node) => node.scrollHeight <= node.clientHeight), true);

      await page.locator("#task-center-button").click();
      await page.locator("#task-list .task-card").first().waitFor();
      const taskPopover = await page.locator("#task-center-popover").boundingBox();
      assert.ok(taskPopover && taskPopover.x >= 0 && taskPopover.x + taskPopover.width <= viewport.width);
      assert.ok(taskPopover.y + taskPopover.height <= viewport.height);
      assert.equal(await page.locator("#task-list .task-card").count(), 2);
      assert.equal(await page.locator(".task-history-toggle").textContent(), "查看最近完成（1）");
      assert.equal(await page.locator('[data-task-id="task-fast8"] .task-progress').getAttribute("aria-valuenow"), "50");
      assert.equal(await page.locator('[data-task-id="task-4x3"] .task-progress').getAttribute("aria-valuenow"), null);
      if (viewport.width === 1440) {
        await page.locator('[data-task-id="task-fast8"] .task-stop').click();
        assert.deepEqual(stoppedTasks, ["task-fast8"]);
      }
      await page.locator('[data-task-id="task-4x3"] .task-card-main').click();
      await page.locator("#project-picker-label").filter({ hasText: "项目 2" }).waitFor();
      await page.locator("#active-conversation-title").filter({ hasText: "项目 2 最近对话" }).waitFor();
      assert.equal(await page.locator('[data-workspace="outline"]').getAttribute("aria-current"), "page");
      await page.locator("#project-picker-button").click();
      await page.locator(".project-option-row").first().locator(".deck-button").click();
      await page.locator("#project-picker-label").filter({ hasText: "项目 1" }).waitFor();
      await page.locator("#task-center-button").click();
      await page.locator(".task-history-toggle").click();
      assert.equal(await page.locator("#task-list .task-card").count(), 3);
      await page.keyboard.press("Escape");

      if (viewport.width === 1440) {
        await page.locator("#conversation-menu-button").click();
        const activeRow = page.locator("#conversation-list .conversation-row").filter({ hasText: "项目 1 最近对话" });
        await activeRow.locator(".conversation-more").click();
        await page.locator("#conversation-context-rename").click();
        await page.locator("#conversation-rename-input").fill("项目 1 已重命名");
        await page.locator("#conversation-rename-save").click();
        await page.locator("#active-conversation-title").filter({ hasText: "项目 1 已重命名" }).waitFor();

        const renamedRow = page.locator("#conversation-list .conversation-row").filter({ hasText: "项目 1 已重命名" });
        await renamedRow.locator(".conversation-more").click();
        await page.locator("#conversation-context-delete").click();
        await page.locator("#conversation-delete-confirm").click();
        await page.locator("#active-conversation-title").filter({ hasText: "项目 1 早期对话" }).waitFor();
        await page.locator("#conversation-archive-toggle").click();
        const archivedRow = page.locator("#conversation-archive-list .archived-conversation-row").filter({ hasText: "项目 1 已重命名" });
        await archivedRow.getByRole("button", { name: "恢复" }).click();
        await page.locator("#active-conversation-title").filter({ hasText: "项目 1 已重命名" }).waitFor();

        const restoredRow = page.locator("#conversation-list .conversation-row").filter({ hasText: "项目 1 已重命名" });
        await restoredRow.locator(".conversation-more").click();
        await page.locator("#conversation-context-rename").click();
        await page.locator("#conversation-rename-input").fill("项目 1 最近对话");
        await page.locator("#conversation-rename-save").click();
        await page.locator("#close-conversation-drawer").click();
      }

      const composer = page.locator("#message-input");
      const sentBefore = sentMessages.length;
      await composer.fill("中文输入中");
      await composer.evaluate((node) => node.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true, bubbles: true })));
      assert.equal(await composer.inputValue(), "中文输入中");
      assert.equal(sentMessages.length, sentBefore);
      await composer.fill("第一行");
      await composer.press("Shift+Enter");
      assert.equal(await composer.inputValue(), "第一行\n");
      assert.equal(sentMessages.length, sentBefore);
      await composer.fill("按回车发送");
      const sent = page.waitForResponse((candidate) => candidate.request().method() === "POST" && /\/conversations\/chat-\d+\/messages$/.test(new URL(candidate.url()).pathname));
      await composer.press("Enter");
      assert.equal(await page.locator("#message-list .message.user", { hasText: "按回车发送" }).count(), 1, "user input appears before the server responds");
      await sent;
      assert.equal(sentMessages.at(-1), "按回车发送");
      await page.locator("#message-list .final-answer", { hasText: "最终答复。" }).waitFor();
      assert.equal(await page.locator("#message-list .message.user", { hasText: "按回车发送" }).count(), 1, "official history event reuses the optimistic bubble");
      assert.equal(await page.locator("#message-list > .final-answer").count(), 1);
      assert.equal(await page.locator("#message-list > .final-answer .message-meta").textContent(), "Codex · 最终结果");
      assert.equal(await page.locator("#message-list .codex-process").count(), 1);
      assert.match(await page.locator("#message-list .codex-process").textContent(), /正在读取项目/);
      assert.equal(await page.locator("#message-list .codex-process details").getAttribute("open"), null);

      await composer.fill("短要求");
      const compactHeight = await composer.evaluate((node) => node.getBoundingClientRect().height);
      await composer.fill("这是一个需要详细说明的修改要求。".repeat(48));
      const expanded = await composer.evaluate((node) => ({
        height: node.getBoundingClientRect().height,
        clientHeight: node.clientHeight,
        scrollHeight: node.scrollHeight,
        overflowY: getComputedStyle(node).overflowY,
      }));
      assert.ok(expanded.height > compactHeight + 80, "long drafts expand the composer");
      assert.ok(expanded.height <= 242, "composer growth stays bounded");
      assert.ok(expanded.scrollHeight > expanded.clientHeight, "overflowing drafts scroll inside the composer");
      assert.equal(expanded.overflowY, "auto");
      await composer.fill("");
      assert.ok(await composer.evaluate((node) => node.getBoundingClientRect().height) <= compactHeight + 1);

      await page.locator("#outline-slide-list .slide-button").nth(19).click();
      await page.locator("#current-page-label").filter({ hasText: "P20" }).waitFor();
      await page.locator('#selected-preview [data-testid="go-selector"]').click();
      await page.locator("[data-selector-page-label]").filter({ hasText: "P20" }).waitFor();
      const selectorPosition = await page.locator("[data-selector-page-list]").evaluate((list) => {
        const active = list.querySelector('[aria-current="page"]');
        const listBox = list.getBoundingClientRect();
        const activeBox = active?.getBoundingClientRect();
        return {
          scrollTop: list.scrollTop,
          visible: Boolean(activeBox && activeBox.top >= listBox.top && activeBox.bottom <= listBox.bottom),
        };
      });
      assert.ok(selectorPosition.scrollTop > 0, "the page list scrolls to the requested late page");
      assert.equal(selectorPosition.visible, true, "the requested page is visible in the selector sidebar");

      await page.locator("#project-picker-button").click();
      assert.equal(await page.locator(".project-option-row").count(), 7);
      const listMetrics = await page.locator("#deck-switcher").evaluate((node) => ({ client: node.clientHeight, scroll: node.scrollHeight }));
      assert.ok(listMetrics.scroll > listMetrics.client, "long project list scrolls inside the popover");
      await page.locator("#project-search").fill("项目 7");
      assert.equal(await page.locator(".project-option-row:not([hidden])").count(), 1);
      await page.locator("#project-search").fill("");

      await page.locator('[data-workspace="retouch"]').click();
      await page.locator("#project-picker-button").click();
      await page.locator(".project-option-row").nth(1).locator(".deck-button").click();
      await page.locator("#project-picker-label").filter({ hasText: "项目 2" }).waitFor();
      assert.equal(await page.locator('[data-workspace="retouch"]').getAttribute("aria-current"), "page");
      await page.locator("#active-conversation-title").filter({ hasText: "项目 2 最近对话" }).waitFor();
      await page.locator("#conversation-menu-button").click();
      await page.locator("#conversation-list").getByText("项目 2 最近对话", { exact: true }).waitFor();
      await page.locator("#close-conversation-drawer").click();

      await page.locator('[data-workspace="selector"]').click();
      await page.locator("#project-picker-button").click();
      await page.locator(".project-option-row").nth(2).locator(".deck-button").click();
      await page.locator("#project-picker-label").filter({ hasText: "项目 3" }).waitFor();
      assert.equal(await page.locator('[data-workspace="selector"]').getAttribute("aria-current"), "page");
      await page.locator(".selector-heading-copy h2").filter({ hasText: "项目 3" }).waitFor();

      if (viewport.width === 1280) {
        await page.locator("#project-picker-button").click();
        await page.locator(".project-option-row").nth(3).locator(".project-remove-button").click();
        await page.locator("#remove-project-dialog").waitFor();
        await page.locator("#remove-project-confirm").click();
        await page.locator("#project-picker-button").click();
        assert.equal(await page.locator(".project-option-row").count(), 6);
        await page.keyboard.press("Escape");
        await page.locator("#project-picker-button").click();
        await page.locator("#project-popover-new").click();
        await page.locator("#existing-outline-button").click();
        await page.locator("#project-picker-label").filter({ hasText: "项目 4" }).waitFor();
        await page.locator("#project-picker-button").click();
        assert.equal(await page.locator(".project-option-row").count(), 7);
        await page.keyboard.press("Escape");
      }

      await page.screenshot({ path: path.join(evidenceRoot, `02-after-${viewport.width}x${viewport.height}.png`), fullPage: false });
      await page.close();
    }
  } finally {
    await browser?.close();
    server.closeAllConnections?.();
    await new Promise((resolve) => server.close(resolve));
  }
});
