import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(here, "../../web");
const evidenceRoot = path.resolve(here, "../ux-evidence/project-switcher-v1");
const require = createRequire("/Users/shawn/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/package.json");
const { chromium } = require("playwright");

const projects = Array.from({ length: 7 }, (_, index) => {
  const number = index + 1;
  const slide = {
    slide_uid: `SLIDE_${number}`,
    page_id: "P1",
    page_label: "P01",
    order: 1,
    title: `项目 ${number} 的第一页`,
    markdown: `| P01 | **项目 ${number} 的第一页** | 核心表达 | 内容 | 视觉 |`,
  };
  return {
    deck_id: `project-${number}`,
    deck_uid: `PROJECT_${number}`,
    label: `项目 ${number} · 海外交付方案`,
    default_slide_uid: slide.slide_uid,
    slides: [slide],
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
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
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
      return json(response, {
        deck_id: project.deck_id,
        deck_uid: project.deck_uid,
        revision_id: "test",
        sha256: "a".repeat(64),
        slide: project.slides[0],
      });
    }
    if (request.method === "GET" && /^\/api\/decks\/project-\d+\/slides\/SLIDE_\d+\/selection$/.test(url.pathname)) {
      return json(response, { status: "empty", confirmed: false, selected_candidates: [] });
    }
    const directory = url.pathname.match(/^\/api\/decks\/(project-\d+)\/conversations$/);
    if (request.method === "GET" && directory) {
      const number = directory[1].split("-")[1];
      return json(response, {
        active_conversation_id: `chat-${number}`,
        conversations: [{
          conversation_id: `chat-${number}`,
          title: `项目 ${number} 最近对话`,
          created_at: "2026-08-14T01:00:00Z",
          last_used_at: "2026-08-14T02:00:00Z",
        }],
      });
    }
    if (request.method === "GET" && /^\/api\/decks\/project-\d+\/conversations\/chat-\d+$/.test(url.pathname)) {
      return json(response, { active_turn: null, turns: [] });
    }
    if (request.method === "POST" && /^\/api\/decks\/project-\d+\/conversations\/chat-\d+\/messages$/.test(url.pathname)) {
      const body = await readBody(request);
      sentMessages.push(body.message);
      const turnId = `keyboard-turn-${sentMessages.length}`;
      response.writeHead(200, { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-store" });
      const events = [
        { method: "turn/started", params: { turn: { id: turnId, status: "inProgress" } } },
        { method: "item/started", params: { turnId, item: { id: `${turnId}-user`, type: "userMessage", content: [{ type: "text", text: body.message }] } } },
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
        pages: [{
          slide_uid: project.slides[0].slide_uid,
          page_label: "P01",
          title: project.slides[0].title,
          included: true,
          confirmed: false,
          resolution: "missing",
          candidates: [],
        }],
        summary: { page_count: 1, included_count: 1, confirmed_count: 0, pending_count: 1 },
      });
    }
    const selectorPage = url.pathname.match(/^\/api\/selector-workspace\/decks\/(project-\d+)\/slides\/(SLIDE_\d+)$/);
    if (request.method === "GET" && selectorPage) {
      const project = projects.find((item) => item.deck_id === selectorPage[1]);
      return json(response, {
        page: {
          slide_uid: project.slides[0].slide_uid,
          page_label: "P01",
          title: project.slides[0].title,
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
  return { server, sentMessages, url: `http://127.0.0.1:${server.address().port}/` };
}

test("seven projects stay compact and switch the whole task context", async () => {
  const { server, sentMessages, url } = await startServer();
  let browser;
  try {
    fs.mkdirSync(evidenceRoot, { recursive: true });
    browser = await chromium.launch({ headless: true, executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
    for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 760 }]) {
      const page = await browser.newPage({ viewport });
      await page.goto(url, { waitUntil: "networkidle" });
      await page.locator("#project-picker-label").filter({ hasText: "项目 1" }).waitFor();

      const picker = await page.locator("#project-picker-button").boundingBox();
      const create = await page.locator("#new-project-button").boundingBox();
      const topbar = await page.locator(".topbar").boundingBox();
      assert.ok(picker && create && topbar);
      assert.ok(picker.height >= 44 && create.height >= 44);
      assert.ok(picker.y >= topbar.y && create.y + create.height <= topbar.y + topbar.height + 1);
      assert.equal(await page.locator("body").evaluate((node) => node.scrollHeight <= node.clientHeight), true);

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
      await sent;
      assert.equal(sentMessages.at(-1), "按回车发送");

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
        await page.locator("#new-project-button").click();
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
