#!/bin/sh
set -eu

STUDIO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
APP="$STUDIO_ROOT/desktop/src-tauri/target/release/bundle/macos/Shawn PPT Studio.app"
RESOURCES="$APP/Contents/Resources/studio"

test -f "$RESOURCES/server/projects.mjs"
test -f "$RESOURCES/server/project-discovery.mjs"
test -f "$RESOURCES/server/project-picker.mjs"
test -f "$RESOURCES/server/conversation-image.mjs"
test -f "$RESOURCES/.agents/skills/shawn-ppt-image/SKILL.md"
test -d "$RESOURCES/.agents/skills/shawn-ppt-image/scripts"
test ! -e "$RESOURCES/.agents/skills/shawn-ppt-image/tests"
test ! -e "$RESOURCES/.agents/skills/shawn-ppt-image/README.md"
test ! -e "$RESOURCES/.agents/skills/shawn-ppt-image/.gitignore"

test "$(shasum -a 256 "$STUDIO_ROOT/server/projects.mjs" | cut -d ' ' -f 1)" = \
  "$(shasum -a 256 "$RESOURCES/server/projects.mjs" | cut -d ' ' -f 1)"
test "$(shasum -a 256 "$STUDIO_ROOT/server/project-discovery.mjs" | cut -d ' ' -f 1)" = \
  "$(shasum -a 256 "$RESOURCES/server/project-discovery.mjs" | cut -d ' ' -f 1)"
test "$(shasum -a 256 "$STUDIO_ROOT/server/project-picker.mjs" | cut -d ' ' -f 1)" = \
  "$(shasum -a 256 "$RESOURCES/server/project-picker.mjs" | cut -d ' ' -f 1)"

grep -q 'id="project-popover-new"' "$RESOURCES/web/index.html"
grep -q 'id="task-center-button"' "$RESOURCES/web/index.html"
grep -q 'id="task-center-popover"' "$RESOURCES/web/index.html"
test -f "$RESOURCES/server/task-projection.mjs"
test -f "$RESOURCES/server/task-associations.mjs"
grep -q 'requestUrl.pathname === "/api/tasks"' "$RESOURCES/server/http-server.mjs"
grep -q 'progress_percent' "$RESOURCES/web/app.js"
grep -q 'conversation-file-link' "$RESOURCES/web/app.js"
grep -q 'codex-process' "$RESOURCES/web/app.js"
grep -q 'id="project-dialog-title">新建 PPT<' "$RESOURCES/web/index.html"
test "$(grep -E -c 'id="(blank-project-button|existing-outline-button)"' "$RESOURCES/web/index.html")" = 2
grep -q '>从空白开始<' "$RESOURCES/web/index.html"
grep -q '>打开已有大纲<' "$RESOURCES/web/index.html"
grep -q 'id="outline-slide-count">0<' "$RESOURCES/web/index.html"
grep -q '还没有页面' "$RESOURCES/web/app.js"
grep -q '先在右侧告诉 AI 这份 PPT 要讲什么' "$RESOURCES/web/app.js"
grep -q '先完成至少一页大纲' "$RESOURCES/web/app.js"

# The loopback bridge owns the macOS picker. The external loopback WebView
# remains deliberately unable to call Tauri IPC.
grep -q '"/usr/bin/osascript"' "$RESOURCES/server/project-picker.mjs"
if grep -q 'tauri-plugin-dialog' "$STUDIO_ROOT/desktop/src-tauri/Cargo.toml"; then
  echo "project picker unexpectedly depends on Tauri dialog IPC" >&2
  exit 1
fi
grep -q '"local": false' "$STUDIO_ROOT/desktop/src-tauri/capabilities/default.json"
grep -q '"permissions": \[\]' "$STUDIO_ROOT/desktop/src-tauri/capabilities/default.json"

echo "bundled project modules PASS, new PPT two-choice/zero-page UI PASS, osascript without Tauri IPC PASS"
