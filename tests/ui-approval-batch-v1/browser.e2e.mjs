import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const webRoot = path.join(root, "web");
const evidence = path.join(here, "evidence");
function loadPlaywright() {
  const moduleRoots = [
    process.env.SHAWN_PPT_STUDIO_NODE_MODULES,
    process.env.CODEX_NODE_MODULES,
    ...(process.env.NODE_PATH?.split(path.delimiter) || []),
    path.join(root, "node_modules"),
    path.resolve(path.dirname(process.execPath), "../node_modules"),
  ].filter(Boolean);
  for (const moduleRoot of new Set(moduleRoots.map((entry) => path.resolve(entry)))) {
    try {
      return createRequire(path.join(moduleRoot, "__studio_test_loader__.cjs"))("playwright");
    } catch (error) {
      if (error?.code !== "MODULE_NOT_FOUND") throw error;
    }
  }
  throw new Error("Playwright is unavailable; set SHAWN_PPT_STUDIO_NODE_MODULES or CODEX_NODE_MODULES.");
}
const { chromium } = loadPlaywright();

const slide = {
  slide_uid: "S24", page_id: "P24", page_label: "P24", order: 24,
  title: "客户价值路径", markdown: "| P24 | **客户价值路径** | 从需求到交付 |",
};
const choices = [
  { decision: "accept", label: "允许" },
  { decision: "acceptForSession", label: "本次对话允许" },
  { decision: "decline", label: "拒绝" },
];
const amendment = { commandPrefix: ["python3", "fast8_control_plane_v1.py", "claim"] };

function approval(id, command, reason = "继续当前作图任务需要运行下一步。") {
  return {
    event: "approval", contract_version: 1, request_id: id,
    thread_id: "thread-1", turn_id: "turn-1", item_id: `item-${id}`,
    method: "item/commandExecution/requestApproval",
    params: {
      threadId: "thread-1", turnId: "turn-1", itemId: `item-${id}`,
      reason, command: `/bin/zsh -lc ${JSON.stringify(command)}`, commandActions: [{ command }], cwd: "/tmp/ppt-studio-fixture",
      proposedExecpolicyAmendment: amendment,
      availableDecisions: ["accept", "acceptForSession", "decline"],
    },
    choices,
  };
}

const claimApprovals = Array.from({ length: 8 }, (_, index) => approval(
  `claim-${index + 1}`,
  `python3 '/tmp/shawn-skill/scripts/fast8_control_plane_v1.py' claim --state '/tmp/runs/p24/state/style_run_state.json' --ticket '/tmp/runs/p24/style_jobs/dispatch_tickets/ticket_${String.fromCharCode(65 + index)}_page_P24.json'`,
));
const mixedApprovals = [
  approval("help-1", "python3 /tmp/shawn-skill/scripts/fast8_control_plane_v1.py --help", "查看工具帮助需要运行一次命令。"),
  approval("release-1", "python3 /tmp/shawn-skill/scripts/fast8_control_plane_v1.py release --state '/tmp/runs/p24/state/style_run_state.json' --ticket '/tmp/runs/p24/style_jobs/dispatch_tickets/ticket_release.json'"),
  approval("settle-1", "python3 /tmp/shawn-skill/scripts/fast8_control_plane_v1.py settle --state '/tmp/runs/p24/state/style_run_state.json' --ticket '/tmp/runs/p24/style_jobs/dispatch_tickets/ticket_settle.json'"),
  approval("receipt-1", "python3 /tmp/shawn-skill/scripts/fast8_control_plane_v1.py receipt --state '/tmp/runs/p24/state/style_run_state.json' --ticket '/tmp/runs/p24/style_jobs/dispatch_tickets/ticket_receipt.json'"),
  approval("other-script-1", "python3 /tmp/other/other_fast8_control_plane_v1.py claim --state '/tmp/runs/p24/state/style_run_state.json' --ticket '/tmp/runs/p24/style_jobs/dispatch_tickets/ticket_other.json'"),
];
const lateApproval = approval("late-resolution", "python other_tool.py --version", "检查工具版本。");
const replayResolved = approval("replay-resolved", "python old_tool.py --version", "旧请求。");
const allApprovals = [...claimApprovals, mixedApprovals[0], lateApproval, replayResolved];

function json(response, value, status = 200) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  response.end(JSON.stringify(value));
}

async function body(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

async function startFixture() {
  const activity = { decisions: [], resolved: new Set(["replay-resolved"]), streamLoads: 0, activeConversation: "chat" };
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    if (request.method === "GET" && url.pathname === "/api/projects") return json(response, {
      default_deck: "demo",
      decks: [{ deck_id: "demo", deck_uid: "DEMO", label: "SI Playbook · 24页客户沟通版", default_slide_uid: "S24", slides: [slide] }],
    });
    if (request.method === "GET" && url.pathname === "/api/tasks") return json(response, {
      active_count: 1, attention_count: 2,
      tasks: [
        { task_id: "wait-1", deck_id: "demo", conversation_id: "chat", deck_label: "SI Playbook", title: "P24 · 8×1", status: "waiting_permission", status_label: "等待允许操作", pending_approval_count: 8, elapsed_seconds: 90, can_stop: true },
        { task_id: "attention-1", deck_id: "demo", conversation_id: "chat", deck_label: "SI Playbook", title: "P12 · 4×3", status: "attention", status_label: "需要查看", elapsed_seconds: 120, can_stop: false },
        { task_id: "stalled-1", deck_id: "demo", conversation_id: "chat", deck_label: "SI Playbook", title: "P18 · 8×1", status: "stalled", status_label: "已停滞", elapsed_seconds: 300, can_stop: false },
        { task_id: "done-1", deck_id: "demo", conversation_id: "chat", deck_label: "SI Playbook", title: "P03 · 8×1", status: "completed", status_label: "已完成", elapsed_seconds: 600, can_stop: false },
      ],
    });
    if (request.method === "GET" && url.pathname === "/api/decks/demo/slides/S24") return json(response, {
      deck_id: "demo", deck_uid: "DEMO", revision_id: "sha256:fixture", sha256: "a".repeat(64), slide,
    });
    if (request.method === "GET" && url.pathname === "/api/decks/demo/slides/S24/selection") return json(response, {
      status: "empty", confirmed: false, selected_candidates: [], empty_message: "这一页还没有选定图片",
    });
    if (request.method === "GET" && url.pathname === "/api/decks/demo/conversations") return json(response, {
      active_conversation_id: activity.activeConversation,
      conversations: [
        { conversation_id: "chat", title: "P24 作图讨论", created_at: "2026-08-15T00:00:00Z", last_used_at: "2026-08-15T00:00:00Z" },
        { conversation_id: "chat-mixed", title: "混合操作边界", created_at: "2026-08-15T00:30:00Z", last_used_at: "2026-08-15T00:30:00Z" },
        { conversation_id: "chat-2", title: "另一项任务", created_at: "2026-08-15T01:00:00Z", last_used_at: "2026-08-15T01:00:00Z" },
      ],
    });
    const conversationOpen = url.pathname.match(/^\/api\/decks\/demo\/conversations\/(chat(?:-2|-mixed)?)\/open$/);
    if (request.method === "POST" && conversationOpen) {
      activity.activeConversation = conversationOpen[1];
      return json(response, { active_conversation_id: activity.activeConversation });
    }
    const conversationHistory = url.pathname.match(/^\/api\/decks\/demo\/conversations\/(chat(?:-2|-mixed)?)$/);
    if (request.method === "GET" && conversationHistory) return json(response, {
      active_turn: { turn_id: conversationHistory[1] === "chat" ? "turn-1" : conversationHistory[1] === "chat-mixed" ? "turn-mixed" : "turn-2", status: "inProgress" }, turns: [],
    });
    const conversationEvents = url.pathname.match(/^\/api\/decks\/demo\/conversations\/(chat(?:-2|-mixed)?)\/events$/);
    if (request.method === "GET" && conversationEvents) {
      activity.streamLoads += 1;
      response.writeHead(200, { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-store" });
      let sequence = 0;
      const send = (event, data) => response.write(`id: ${++sequence}\nevent: ${event}\ndata: ${JSON.stringify({ ...data, sequence })}\n\n`);
      if (conversationEvents[1] === "chat-2") {
        const reused = approval("claim-1", "python second_tool.py --version", "新对话里的新请求。");
        reused.thread_id = "thread-2";
        reused.turn_id = "turn-2";
        reused.params.threadId = "thread-2";
        reused.params.turnId = "turn-2";
        send("approval", reused);
        return response.end();
      }
      if (conversationEvents[1] === "chat-mixed") {
        for (const item of mixedApprovals) send("approval", {
          ...item,
          thread_id: "thread-mixed",
          turn_id: "turn-mixed",
          params: { ...item.params, threadId: "thread-mixed", turnId: "turn-mixed" },
        });
        return response.end();
      }
      for (const id of activity.resolved) {
        const source = allApprovals.find((item) => item.request_id === id);
        send("approval_resolution", {
          event: "approval_resolution", request_id: id, item_id: source?.item_id, method: source?.method,
          thread_id: "thread-1", turn_id: "turn-1", resolved: true, decision: "accept",
        });
      }
      for (const item of allApprovals) send("approval", item);
      activity.resolved.add("late-resolution");
      send("approval_resolution", {
        event: "approval_resolution", request_id: "late-resolution", item_id: lateApproval.item_id, method: lateApproval.method,
        thread_id: "thread-1", turn_id: "turn-1", resolved: true, decision: "accept",
      });
      return response.end();
    }
    const decisionRoute = url.pathname.match(/^\/api\/codex\/approvals\/([^/]+)$/);
    if (request.method === "POST" && decisionRoute) {
      const requestId = decodeURIComponent(decisionRoute[1]);
      const payload = await body(request);
      activity.decisions.push({ request_id: requestId, decision: payload.decision });
      activity.resolved.add(requestId);
      return json(response, { resolved: true, decision: payload.decision });
    }
    if (request.method === "POST" && url.pathname === "/api/tasks/wait-1/interrupt") return json(response, { interrupt_requested: true }, 202);
    const asset = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
    const target = path.resolve(webRoot, asset);
    if (target.startsWith(webRoot) && fs.existsSync(target) && fs.statSync(target).isFile()) {
      const type = target.endsWith(".js") ? "text/javascript" : target.endsWith(".css") ? "text/css" : "text/html";
      response.writeHead(200, { "content-type": `${type}; charset=utf-8`, "cache-control": "no-store" });
      return fs.createReadStream(target).pipe(response);
    }
    return json(response, { error: { message: "not found" } }, 404);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return { activity, server, url: `http://127.0.0.1:${server.address().port}/` };
}

async function runViewport(browser, viewport) {
  const fixture = await startFixture();
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  page.setDefaultTimeout(10_000);
  try {
    await page.goto(fixture.url, { waitUntil: "networkidle" });
    const batch = page.locator('[data-testid="codex-permission-batch"]');
    const single = page.locator('[data-testid="codex-permission-request"]:not(.completed)');
    await batch.waitFor();
    assert.equal(await batch.count(), 1);
    assert.match(await batch.locator("strong").textContent(), /8 个连续步骤/);
    assert.equal(await batch.locator("details").getAttribute("open"), null, "batch details default collapsed");
    assert.equal(await batch.getByRole("button", { name: "允许本批次（8）", exact: true }).count(), 1);
    assert.deepEqual(await batch.locator("button").allTextContents(), ["允许本批次（8）", "本次对话允许", "拒绝"]);
    assert.equal(await single.count(), 1, "help stays outside the canonical claim batch");
    assert.equal(await page.getByText("命令：", { exact: false }).count(), 0, "no internal command wall");

    const timeline = page.locator("#message-list");
    await timeline.evaluate((node) => { node.scrollTop = 0; });
    const before = await timeline.evaluate((node) => node.scrollTop);
    await page.evaluate(() => window.dispatchEvent(new Event("resize")));
    assert.equal(await timeline.evaluate((node) => node.scrollTop), before, "approval rendering does not pull history to bottom");

    fs.mkdirSync(evidence, { recursive: true });
    const approvalShot = path.join(evidence, `approval-${viewport.width}x${viewport.height}.png`);
    await page.screenshot({ path: approvalShot, fullPage: false });
    assert.ok(fs.statSync(approvalShot).size > 10_000);

    await page.locator("#task-center-button").click();
    await page.getByText("等待允许操作 · 8项", { exact: true }).waitFor();
    const grouping = await page.locator("#task-list").evaluate((node) => {
      let group = "";
      const rows = [];
      for (const child of node.children) {
        if (child.classList.contains("task-group-label")) group = child.textContent.trim();
        if (child.classList.contains("task-card")) rows.push({ group, id: child.dataset.taskId });
      }
      return rows;
    });
    assert.deepEqual(grouping, [
      { group: "进行中", id: "wait-1" },
      { group: "需要查看", id: "attention-1" },
      { group: "需要查看", id: "stalled-1" },
    ]);
    const taskShot = path.join(evidence, `task-center-${viewport.width}x${viewport.height}.png`);
    await page.screenshot({ path: taskShot, fullPage: false });
    assert.ok(fs.statSync(taskShot).size > 10_000);
    await page.locator("#task-center-close").click();

    await batch.getByRole("button", { name: "允许本批次（8）", exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('[data-testid="codex-permission-batch"]'));
    assert.equal(fixture.activity.decisions.length, 8);
    assert.deepEqual(fixture.activity.decisions.map((item) => item.request_id), claimApprovals.map((item) => item.request_id));
    assert.ok(fixture.activity.decisions.every((item) => item.decision === "accept"));
    assert.equal(await single.count(), 1, "the unrelated help approval remains pending");

    await page.reload({ waitUntil: "networkidle" });
    assert.equal(await page.locator('[data-testid="codex-permission-batch"]').count(), 0, "resolved batch replay does not revive");
    assert.equal(await page.locator('[data-testid="codex-permission-request"]:not(.completed)').count(), 1, "only unresolved help remains");
    assert.ok(fixture.activity.streamLoads >= 2);

    await page.locator("#conversation-menu-button").click();
    await page.locator("#conversation-list").getByRole("button", { name: /混合操作边界/ }).click();
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="codex-permission-request"]:not(.completed)').length === 5);
    assert.equal(await page.locator('[data-testid="codex-permission-batch"]').count(), 0,
      "help, release, settle, receipt and another script never batch");

    await page.locator("#conversation-menu-button").click();
    await page.locator("#conversation-list").getByRole("button", { name: /另一项任务/ }).click();
    await page.locator('[data-testid="codex-permission-request"]:not(.completed)').filter({ hasText: "新对话里的新请求" }).waitFor();
    assert.equal(await page.locator('[data-testid="codex-permission-request"]:not(.completed)').count(), 1,
      "a reused request id in another conversation remains actionable");

    return [approvalShot, taskShot].map((file) => ({ path: file, sha256: sha256(file), size: fs.statSync(file).size }));
  } finally {
    await context.close();
    fixture.server.closeAllConnections?.();
    await new Promise((resolve) => fixture.server.close(resolve));
  }
}

test("scoped approval batches and waiting-permission tasks work at both release viewports", async () => {
  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      executablePath: fs.existsSync("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" : undefined,
    });
    const screenshots = [];
    for (const viewport of [{ width: 1280, height: 760 }, { width: 1440, height: 900 }]) {
      screenshots.push(...await runViewport(browser, viewport));
    }
    fs.mkdirSync(evidence, { recursive: true });
    fs.writeFileSync(path.join(here, "browser-result.json"), `${JSON.stringify({ passed: true, screenshots }, null, 2)}\n`);
  } finally {
    await browser?.close();
  }
});
