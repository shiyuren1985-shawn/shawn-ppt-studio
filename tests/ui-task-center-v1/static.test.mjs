import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const html = await readFile(new URL("../../web/index.html", import.meta.url), "utf8");
const css = await readFile(new URL("../../web/styles.css", import.meta.url), "utf8");
const app = await readFile(new URL("../../web/app.js", import.meta.url), "utf8");

test("top bar is grouped into project, workspace, and task action zones", () => {
  assert.match(html, /class="topbar-project-context"/);
  assert.match(html, /class="toolbar-divider"/);
  assert.match(html, /class="workspace-tabs"/);
  assert.match(html, /id="task-center-button"/);
  assert.doesNotMatch(html, /id="new-project-button"/);
  assert.match(html, /id="project-popover-new"/);
});

test("task center shows canonical progress and does not expose internal task identifiers", () => {
  assert.match(app, /task\.status_label/);
  assert.match(app, /task\.progress_percent/);
  assert.match(app, /api\.interruptTask\(task\.task_id\)/);
  assert.match(app, /查看最近完成（\$\{completedTasks\.length\}）/);
  assert.doesNotMatch(html, /run_id|thread_id|state_path|sha256/);
  assert.match(css, /\.task-progress\.indeterminate/);
  assert.match(app, /这个任务没有可恢复的来源对话，已打开对应页面/);
});

test("top task badge counts only active work while attention stays inside the panel", () => {
  assert.match(app, /const activeCount = state\.taskCounts\.active/);
  assert.match(app, /task-count"\]\.textContent = String\(activeCount\)/);
  assert.doesNotMatch(app, /const count = state\.taskCounts\.active \+ state\.taskCounts\.attention/);
  assert.match(app, /历史任务需要查看/);
});
