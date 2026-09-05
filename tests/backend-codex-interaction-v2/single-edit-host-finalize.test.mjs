import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, realpath, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { SINGLE_IMAGE_EDIT_CONTROL_PLANE } from "../../integrations/single-image-edit.mjs";
import {
  canonicalSingleEditStatePath,
  SingleEditTurnFinalizer,
  STUDIO_APP_SERVER_TRANSPORT,
} from "../../server/single-edit-turn-finalizer.mjs";
import { buildWorkspaceTurn } from "../../server/turns.mjs";

function pendingState() {
  return {
    single_image_edit_state_contract_version: 1,
    run_mode: "single_image_edit",
    status: "prepared",
    imagegen: { status: "leased", global_lease_id: "lease-1" },
    candidate: null,
  };
}

function planBuilder(compiled, { saved_path: savedPath }) {
  assert.equal(compiled.run_mode, "single_image_edit");
  return {
    attempt_complete: { command: "canonical", args: ["complete", compiled.runtime.state_path, savedPath] },
    recover_only_if_error_code: "imagegen_slot_not_claimed",
    recovery_commands: [
      { command: "canonical", args: ["claim", compiled.runtime.state_path] },
      { command: "canonical", args: ["complete", compiled.runtime.state_path, savedPath] },
    ],
  };
}

async function harness(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-root-turn-finalize-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const statePath = path.join(root, "run with spaces", "state", "single_image_edit_state.json");
  const savedPath = path.join(root, "actual-saved-path.png");
  const state = pendingState();
  const commands = [];
  const finalizer = new SingleEditTurnFinalizer({
    readState: async () => structuredClone(state),
    planBuilder,
    commandRunner: async (spec) => {
      commands.push(spec);
      if (spec.args[0] === "complete") {
        state.status = "completed";
        state.imagegen.status = "completed";
        state.candidate = { path: "candidate.png" };
      }
      if (spec.args[1] === "release") {
        state.imagegen = { status: "pending", global_lease_id: null };
      }
      return { stdout: "{}" };
    },
  });
  return { root, statePath, savedPath, state, commands, finalizer };
}

function start(finalizer, threadId = "thread-1", turnId = "turn-1") {
  finalizer.registerStarting(threadId, { transport: STUDIO_APP_SERVER_TRANSPORT });
  finalizer.observeNotification({
    method: "turn/started",
    params: { threadId, turn: { id: turnId, status: "inProgress" } },
  });
}

function stateCommand(statePath, action = "claim", savedPath = null) {
  return `python3 '${SINGLE_IMAGE_EDIT_CONTROL_PLANE}' ${action} --state '${statePath}'${savedPath ? ` --saved-path '${savedPath}'` : ""}`;
}

function completed(finalizer, item, status = "interrupted") {
  finalizer.observeNotification({
    method: "item/completed",
    params: { threadId: "thread-1", turnId: "turn-1", item },
  });
  finalizer.observeNotification({
    method: "turn/completed",
    params: { threadId: "thread-1", turn: { id: "turn-1", status, items: [] } },
  });
}

test("completed savedPath wins over a wrong output_hint used in the declined complete approval", async (t) => {
  const { statePath, savedPath, commands, finalizer } = await harness(t);
  start(finalizer);
  finalizer.observeApproval({
    method: "item/commandExecution/requestApproval",
    params: {
      threadId: "thread-1",
      turnId: "turn-1",
      command: stateCommand(statePath, "complete", "/wrong/output_hint.png"),
    },
  });
  completed(finalizer, {
    id: "image-1",
    type: "imageGeneration",
    status: "completed",
    savedPath,
    output_hint: "/wrong/output_hint.png",
  });
  const outcome = await finalizer.waitForOutcome("thread-1", "turn-1");
  assert.equal(outcome.status, "completed");
  assert.deepEqual(commands, [{ command: "canonical", args: ["complete", statePath, savedPath] }]);
});

test("zero completed images releases a still-leased exact run without guessing", async (t) => {
  const { statePath, commands, finalizer } = await harness(t);
  start(finalizer);
  finalizer.observeNotification({
    method: "item/started",
    params: {
      threadId: "thread-1",
      turnId: "turn-1",
      item: { type: "commandExecution", command: stateCommand(statePath) },
    },
  });
  completed(finalizer, { type: "imageGeneration", status: "failed", savedPath: null });
  const outcome = await finalizer.waitForOutcome("thread-1", "turn-1");
  assert.equal(outcome.status, "released");
  assert.equal(commands.length, 1);
  assert.deepEqual(commands[0].args, [SINGLE_IMAGE_EDIT_CONTROL_PLANE, "release", "--state", statePath]);
});

test("two completed images never complete or release either result", async (t) => {
  const { statePath, savedPath, commands, finalizer } = await harness(t);
  start(finalizer);
  finalizer.observeApproval({ params: { threadId: "thread-1", turnId: "turn-1", command: stateCommand(statePath) } });
  for (const [id, suffix] of [["one", ""], ["two", ".two"]]) {
    finalizer.observeNotification({
      method: "item/completed",
      params: {
        threadId: "thread-1",
        turnId: "turn-1",
        item: { id, type: "imageGeneration", status: "completed", savedPath: `${savedPath}${suffix}` },
      },
    });
  }
  finalizer.observeNotification({
    method: "turn/completed",
    params: { threadId: "thread-1", turn: { id: "turn-1", status: "completed", items: [] } },
  });
  const outcome = await finalizer.waitForOutcome("thread-1", "turn-1");
  assert.equal(outcome.reason, "multiple_completed_images");
  assert.deepEqual(commands, []);
});

test("a canonical complete failure with a completed image never releases the lease", async (t) => {
  const { statePath, savedPath, commands, finalizer } = await harness(t);
  finalizer.commandRunner = async (spec) => {
    commands.push(spec);
    throw Object.assign(new Error("candidate import failed"), { code: "candidate_copy_failed" });
  };
  start(finalizer);
  finalizer.observeApproval({ params: { threadId: "thread-1", turnId: "turn-1", command: stateCommand(statePath) } });
  completed(finalizer, { id: "image-1", type: "imageGeneration", status: "completed", savedPath });
  const outcome = await finalizer.waitForOutcome("thread-1", "turn-1");
  assert.equal(outcome.status, "failed");
  assert.equal(commands.length, 1);
  assert.equal(commands[0].args[0], "complete");
});

test("state path parser accepts quoted spaces only for the canonical single-edit control plane", () => {
  const statePath = "/tmp/project with spaces/state/single_image_edit_state.json";
  assert.equal(canonicalSingleEditStatePath(stateCommand(statePath)), statePath);
  assert.equal(canonicalSingleEditStatePath(`python3 /tmp/fake.py claim --state '${statePath}'`), null);
  assert.equal(canonicalSingleEditStatePath(`${SINGLE_IMAGE_EDIT_CONTROL_PLANE} claim --state /tmp/other.json`), null);
});

test("workspace turn explicitly carries the Studio transport marker for the root-turn exception", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-turn-marker-"));
  await writeFile(path.join(root, "outline.md"), "# test\n");
  const result = await buildWorkspaceTurn({ message: "修改 P04 图片" }, {
    dataRoot: root,
    deck: {
      candidate_roots: [{ path: root }],
      outline: {
        path: path.join(root, "outline.md"),
        text: "# test",
        deck_uid: "deck",
        revision_id: "sha256:test",
        slides: [{ slide_uid: "slide-4" }],
      },
    },
    conversationId: "conversation",
    threadId: "thread",
    overviewPython: path.join(root, "runtime", "python3"),
    pathPolicy: { requireReferenceImage: async (value) => value },
  });
  assert.equal(
    result.params.additionalContext.shawn_ppt_studio_transport.value,
    "transport=studio_app_server_v1",
  );
  const prompt = result.params.input.find((item) => item.type === "text")?.text || "";
  assert.match(prompt, /project_generation_sources: \[\]/);
  assert.doesNotMatch(prompt, /project_generation_sources: \[\{.*global_chrome_contract/s);
  await rm(root, { recursive: true, force: true });
});


test("host finalize binds path validation and canonical subprocess to the same isolated Codex home", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-finalize-home-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const home = path.join(root, "Studio Codex Home");
  const alias = path.join(root, "home-alias");
  const artifactRoot = path.join(home, "generated_images");
  await mkdir(artifactRoot, { recursive: true });
  await symlink(home, alias);
  const savedPath = path.join(artifactRoot, "fixture.png");
  await writeFile(savedPath, "fixture bytes");
  const statePath = path.join(root, "state", "single_image_edit_state.json");
  await mkdir(path.dirname(statePath));
  await writeFile(statePath, "{}");
  const resultPath = path.join(root, "subprocess-env.json");
  let observedRoot;
  let observedSavedPath;
  const finalizer = new SingleEditTurnFinalizer({
    env: { ...process.env, CODEX_HOME: alias },
    readState: async () => pendingState(),
    planBuilder(_compiled, input, options) {
      observedRoot = options.generatedImagesRoot;
      observedSavedPath = input.saved_path;
      return { attempt_complete: { command: process.execPath, args: ["-e",
        "require('node:fs').writeFileSync(process.argv[1], JSON.stringify({home:process.env.CODEX_HOME}))", resultPath] } };
    },
  });
  finalizer.registerStarting("thread-1", { transport: STUDIO_APP_SERVER_TRANSPORT, candidateRoots: [root] });
  finalizer.observeNotification({ method: "turn/started", params: { threadId: "thread-1", turn: { id: "turn-1" } } });
  finalizer.observeNotification({ method: "item/started", params: {
    threadId: "thread-1", turnId: "turn-1", item: { command: stateCommand(await realpath(statePath)) },
  } });
  completed(finalizer, { id: "image", type: "imageGeneration", status: "completed", savedPath });
  assert.equal((await finalizer.waitForOutcome("thread-1", "turn-1", 3000)).status, "completed");
  assert.equal(observedRoot, await realpath(artifactRoot));
  assert.equal(observedSavedPath, await realpath(savedPath));
  assert.equal(JSON.parse(await readFile(resultPath, "utf8")).home, alias);
});
