#!/bin/sh
set -eu

STUDIO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
APP="$STUDIO_ROOT/desktop/src-tauri/target/release/bundle/macos/Shawn PPT Studio.app"
FAKE_CODEX="$STUDIO_ROOT/tests/desktop/fixtures/fake-codex-app-server.mjs"
NODE_BIN=${SHAWN_PPT_STUDIO_NODE:-}
OLD_PORT=8772
SELECTOR_PORT=8765

if [ -z "$NODE_BIN" ]; then
  NODE_BIN=$(command -v node 2>/dev/null || true)
fi
if [ -z "$NODE_BIN" ] || [ ! -x "$NODE_BIN" ]; then
  echo "Node.js was not found; set SHAWN_PPT_STUDIO_NODE to a Node.js executable" >&2
  exit 77
fi
if [ ! -x "$FAKE_CODEX" ]; then
  echo "tracked desktop Codex fixture is missing or not executable: $FAKE_CODEX" >&2
  exit 1
fi

OLD_PID=$(lsof -nP -t -iTCP:$OLD_PORT -sTCP:LISTEN 2>/dev/null | head -1)
if [ -z "$OLD_PID" ]; then
  echo "port fallback smoke requires an existing user service on 127.0.0.1:$OLD_PORT" >&2
  exit 77
fi

OLD_HEALTH=$(curl -fsS "http://127.0.0.1:$OLD_PORT/api/health")
SELECTOR_PID=$(lsof -nP -t -iTCP:$SELECTOR_PORT -sTCP:LISTEN 2>/dev/null | head -1)
if [ -z "$SELECTOR_PID" ]; then
  echo "port fallback smoke requires the existing selector on 127.0.0.1:$SELECTOR_PORT" >&2
  exit 77
fi
SELECTOR_HEALTH=$(curl -fsS "http://127.0.0.1:$SELECTOR_PORT/api/health")
if ! printf '%s' "$SELECTOR_HEALTH" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
  echo "existing selector is not healthy" >&2
  exit 77
fi

NEW_PORT=
for port in $(jot - 8773 8782); do
  if ! nc -z 127.0.0.1 "$port" 2>/dev/null; then
    NEW_PORT=$port
    break
  fi
done
if [ -z "$NEW_PORT" ]; then
  echo "port fallback smoke found no free port from 8773 through 8782" >&2
  exit 77
fi

SMOKE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/shawn-ppt-studio-port-fallback.XXXXXX")
DESKTOP_PID=
cleanup() {
  if [ -n "$DESKTOP_PID" ] && kill -0 "$DESKTOP_PID" 2>/dev/null; then
    kill -TERM "$DESKTOP_PID" 2>/dev/null || true
    wait "$DESKTOP_PID" 2>/dev/null || true
  fi
  rm -rf -- "$SMOKE_DIR"
}
trap cleanup EXIT HUP INT TERM

cp -R "$APP" "$SMOKE_DIR/Shawn PPT Studio.app"
BINARY="$SMOKE_DIR/Shawn PPT Studio.app/Contents/MacOS/shawn-ppt-studio"
mkdir -p "$SMOKE_DIR/lab" "$SMOKE_DIR/run" "$SMOKE_DIR/monitoring"

wait_new_studio() {
  attempt=0
  until curl -fsS "http://127.0.0.1:$NEW_PORT/api/health" >"$SMOKE_DIR/new-health.json" 2>/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 200 ]; then
      return 1
    fi
    sleep 0.1
  done
  grep -q '"app_id":"shawn-ppt-studio"' "$SMOKE_DIR/new-health.json"
}

# Do not set SHAWN_PPT_STUDIO_PORT: the desktop must skip the occupied user
# service and navigate its window to the first free port in 8773..8782.
env -u SHAWN_PPT_STUDIO_PORT -u PPT_AI_LAB_DESKTOP_PORT \
  SHAWN_PPT_STUDIO_NODE="$NODE_BIN" \
  SHAWN_PPT_STUDIO_DATA_ROOT="$SMOKE_DIR/data" \
  SHAWN_PPT_STUDIO_DESKTOP_SMOKE_MS=3500 \
  PPT_AI_LAB_TEST_MODE=1 \
  PPT_AI_LAB_ROOT="$SMOKE_DIR/lab" \
  PPT_AI_LAB_CODEX_BIN="$FAKE_CODEX" \
  PPT_AI_LAB_FAKE_STATE="$SMOKE_DIR/fake-codex.json" \
  PPT_AI_LAB_DECKS_FILE="$SMOKE_DIR/missing-decks.json" \
  PPT_AI_LAB_RUN_ROOT="$SMOKE_DIR/run" \
  PPT_AI_LAB_MONITORING_ROOT="$SMOKE_DIR/monitoring" \
  PATH="$(dirname -- "$NODE_BIN"):$PATH" \
  "$BINARY" -ApplePersistenceIgnoreState YES \
    >"$SMOKE_DIR/fallback.stdout" 2>"$SMOKE_DIR/fallback.stderr" &
DESKTOP_PID=$!

wait_new_studio
curl -fsS "http://127.0.0.1:$NEW_PORT/" >"$SMOKE_DIR/new-index.html"
grep -q 'data-app="shawn-ppt-studio"' "$SMOKE_DIR/new-index.html"
grep -q 'id="project-popover-new"' "$SMOKE_DIR/new-index.html"
grep -q 'id="task-center-button"' "$SMOKE_DIR/new-index.html"
curl -fsS "http://127.0.0.1:$NEW_PORT/api/tasks" >"$SMOKE_DIR/new-tasks.json"
grep -q '"contract_version":1' "$SMOKE_DIR/new-tasks.json"
grep -q '"tasks":\[\]' "$SMOKE_DIR/new-tasks.json"
kill -0 "$OLD_PID"
test "$(lsof -nP -t -iTCP:$OLD_PORT -sTCP:LISTEN 2>/dev/null | head -1)" = "$OLD_PID"
curl -fsS "http://127.0.0.1:$OLD_PORT/api/health" >"$SMOKE_DIR/legacy-after-fallback.json"
kill -0 "$SELECTOR_PID"
test "$(lsof -nP -t -iTCP:$SELECTOR_PORT -sTCP:LISTEN 2>/dev/null | head -1)" = "$SELECTOR_PID"
curl -fsS "http://127.0.0.1:$SELECTOR_PORT/api/health" >"$SMOKE_DIR/selector-after-fallback.json"

wait "$DESKTOP_PID"
DESKTOP_PID=
if nc -z 127.0.0.1 "$NEW_PORT" 2>/dev/null; then
  echo "fallback bridge did not release 127.0.0.1:$NEW_PORT" >&2
  exit 1
fi
kill -0 "$OLD_PID"
kill -0 "$SELECTOR_PID"
test "$(lsof -nP -t -iTCP:$SELECTOR_PORT -sTCP:LISTEN 2>/dev/null | head -1)" = "$SELECTOR_PID"

# An explicitly selected occupied port must fail rather than silently moving.
if env \
  SHAWN_PPT_STUDIO_PORT="$OLD_PORT" \
  SHAWN_PPT_STUDIO_NODE="$NODE_BIN" \
  SHAWN_PPT_STUDIO_DATA_ROOT="$SMOKE_DIR/explicit-data" \
  PPT_AI_LAB_TEST_MODE=1 \
  PPT_AI_LAB_ROOT="$SMOKE_DIR/explicit-lab" \
  PPT_AI_LAB_CODEX_BIN="$FAKE_CODEX" \
  PPT_AI_LAB_FAKE_STATE="$SMOKE_DIR/explicit-fake-codex.json" \
  "$BINARY" -ApplePersistenceIgnoreState YES \
    >"$SMOKE_DIR/explicit.stdout" 2>"$SMOKE_DIR/explicit.stderr"; then
  echo "desktop accepted an explicitly configured occupied port" >&2
  exit 1
fi
grep -q 'explicit desktop loopback address 127.0.0.1:8772 is already in use' \
  "$SMOKE_DIR/explicit.stderr"
kill -0 "$OLD_PID"
kill -0 "$SELECTOR_PID"

echo "desktop coexist: default 8772 -> $NEW_PORT PASS, explicit occupied reject PASS, user 8772 PID $OLD_PID and selector 8765 PID $SELECTOR_PID preserved PASS"
