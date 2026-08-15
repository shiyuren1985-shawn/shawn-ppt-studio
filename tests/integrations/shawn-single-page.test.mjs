import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  DEFAULT_LAB_ROOT,
  DEFAULT_RUN_ROOT,
  FAST8_ORCHESTRATION_CONTRACT,
  STUDIO_APP_SERVER_TRANSPORT,
  buildAppServerTurn,
  compileSinglePageRequest,
  parseNativeRefs,
  sha256Text,
  verifyNativeRefs,
} from "../../integrations/shawn-single-page.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
let scratch;

const VALID_OUTLINE = `---
deck_uid: TEST_DECK
slide_identity_required: true
slide_uids:
  P1: TEST_COVER
  P7: TEST_SCOPE
---
# Test outline

| Page | Title | Content |
| --- | --- | --- |
| P1 | Cover | A |
| P7 | Scope | B |
`;

function input(overrides = {}) {
  return {
    deck_uid: "TEST_DECK",
    slide_uid: "TEST_SCOPE",
    outline_path: path.join(scratch, "outline.md"),
    expected_revision: `sha256:${sha256Text(VALID_OUTLINE)}`,
    user_request: "生成八个清楚分离的正式候选，不改变页面事实。",
    ...overrides,
  };
}

function context(overrides = {}) {
  const approvedRunRoot = path.join(scratch, "runtime", "shawn-runs");
  return {
    outline_markdown: VALID_OUTLINE,
    outline_sha256: sha256Text(VALID_OUTLINE),
    request_started_at: "2026-08-12T08:00:00.000Z",
    lab_root: scratch,
    approved_run_root: approvedRunRoot,
    approved_run_roots: [approvedRunRoot],
    monitoring_root: path.join(scratch, "central-monitoring"),
    overview_python: "/usr/bin/python3",
    ...overrides,
  };
}

before(async () => {
  scratch = await mkdtemp(path.join(here, ".tmp-shawn-adapter-"));
  await writeFile(path.join(scratch, "outline.md"), VALID_OUTLINE, "utf8");
});

after(async () => {
  await rm(scratch, { recursive: true, force: true });
});

test("compiles authoritative UID and revision into a bounded Fast8 request", () => {
  const compiled = compileSinglePageRequest(input(), context());
  assert.deepEqual(compiled.identity, {
    deck_uid: "TEST_DECK",
    slide_uid: "TEST_SCOPE",
    page_id: "P07",
  });
  assert.equal(compiled.run_mode, "fast_8x1_diverse");
  assert.equal(compiled.transport, STUDIO_APP_SERVER_TRANSPORT);
  assert.match(compiled.runtime.task_name, /^P07_8x1_20260812_workbench_[0-9a-f]{10}$/);
  assert.ok(compiled.runtime.preflight_path.startsWith(compiled.runtime.run_root));

  const turn = buildAppServerTurn(compiled, { thread_id: "thread-test" });
  assert.equal(turn.threadId, "thread-test");
  assert.equal(turn.cwd, compiled.runtime.run_root);
  assert.notEqual(turn.cwd, compiled.runtime.lab_root);
  assert.deepEqual(turn.sandboxPolicy.writableRoots, [
    compiled.runtime.run_root,
    compiled.runtime.monitoring_root,
  ]);
  assert.deepEqual(turn.additionalContext, {
    shawn_ppt_studio_transport: {
      kind: "application",
      value: "transport=studio_app_server_v1",
    },
  });
  assert.equal(turn.input[1].type, "skill");
  assert.equal(turn.input[1].name, "shawn-ppt-image");
  assert.match(turn.input[0].text, /fast8_control_plane_v1\.py/);
  assert.match(turn.input[0].text, /same outline as slide-identity-file only to build_fast8_preflight_manifest\.py/);
  assert.match(turn.input[0].text, /Never pass --slide-identity-file to init_task_dir\.py for Fast8/);
  assert.match(turn.input[0].text, /Do not create a second UID file, monitor, semaphore, Judge/);
  assert.doesNotMatch(turn.input[0].text, /outputSchema/);
  assert.match(turn.input[0].text, /final JSON contract/);
  assert.match(turn.input[0].text, /transport=studio_app_server_v1/);
  assert.match(turn.input[0].text, /Subagent creation is not dispatch/);
  assert.match(turn.input[0].text, /canonical file evidence is authoritative/);
  assert.match(turn.input[0].text, /prepare-directors immediately in this same turn without asking for a user steer/);
  assert.match(turn.input[0].text, /do not spawn an image-execution subagent/);
  assert.match(turn.input[0].text, /root turn is the one and only mechanical executor/);
  assert.match(turn.input[0].text, /prepare --state <state_path> --render-action/);
  assert.match(turn.input[0].text, /explicitly execute await eval\(action\)/);
  assert.match(turn.input[0].text, /must not spawn or bind eight A-H per-seat LLM worker sessions/);
  assert.match(turn.input[0].text, /claim -> ImageGen -> savedPath\/receipt -> release/);
  assert.match(turn.input[0].text, /existing central cap5 registry/);
  assert.match(turn.input[0].text, /Never call generatedImage\(\.\.\.\), image\(\.\.\.\)/);
  assert.equal(Object.hasOwn(turn, "outputSchema"), false);
});

test("Studio fake8 dispatches spawned control sessions while root claims before fake ImageGen", async () => {
  const events = [];
  const sessions = [];
  let nextSession = 0;
  let leases = 0;
  let peakLeases = 0;
  const claimWaiters = [];

  function spawn(role) {
    const session = { id: `fake-session-${++nextSession}`, role, dispatched: false };
    sessions.push(session);
    events.push({ kind: "spawn", session: session.id, role });
    return session;
  }

  async function dispatch(session, taskName, task) {
    assert.equal(session.dispatched, false);
    assert.ok(taskName.trim());
    session.dispatched = true;
    events.push({ kind: "dispatch", session: session.id, role: session.role, taskName });
    return task();
  }

  async function claim(slot) {
    while (leases >= FAST8_ORCHESTRATION_CONTRACT.image_execution.slots.capacity) {
      await new Promise((resolve) => claimWaiters.push(resolve));
    }
    leases += 1;
    peakLeases = Math.max(peakLeases, leases);
    events.push({ kind: "claim", slot });
  }

  function release(slot) {
    events.push({ kind: "release", slot });
    leases -= 1;
    claimWaiters.shift()?.();
  }

  for (const role of FAST8_ORCHESTRATION_CONTRACT.directors.roles) {
    const session = spawn(role);
    await dispatch(session, `run ${role} bounded prompt`, async () => {
      events.push({ kind: "director_output", role });
    });
  }

  const judge = spawn("standby_judge");
  await dispatch(judge, "await-fast8-judge-job", async () => {
    events.push({ kind: "judge_waiting" });
  });

  events.push({ kind: "root_wrapper_dispatch", transport: STUDIO_APP_SERVER_TRANSPORT });
  events.push({ kind: "prepare_render_action" });
  events.push({ kind: "await_eval_action" });
  await Promise.all(
    "ABCDEFGH".split("").map(async (slot) => {
      await claim(slot);
      try {
        await new Promise((resolve) => setImmediate(resolve));
        events.push({ kind: "imagegen", slot });
        events.push({ kind: "receipt", slot });
      } finally {
        release(slot);
      }
    }),
  );

  assert.equal(
    sessions.filter((session) => session.role === "fast8_burst_executor").length,
    FAST8_ORCHESTRATION_CONTRACT.image_execution.subagent_executor_count,
  );
  assert.equal(FAST8_ORCHESTRATION_CONTRACT.image_execution.executor_location, "root_turn");
  assert.equal(FAST8_ORCHESTRATION_CONTRACT.image_execution.executor_count, 1);
  assert.equal(sessions.some((session) => /^fast8_worker_[A-H]$/i.test(session.role)), false);
  assert.equal(sessions.every((session) => session.dispatched), true);
  assert.equal(peakLeases, 5);
  assert.equal(leases, 0);

  for (const session of sessions) {
    const spawnedAt = events.findIndex(
      (event) => event.kind === "spawn" && event.session === session.id,
    );
    const dispatchedAt = events.findIndex(
      (event) => event.kind === "dispatch" && event.session === session.id,
    );
    assert.ok(spawnedAt >= 0 && dispatchedAt > spawnedAt, `${session.role} must be dispatched`);
  }
  for (const slot of "ABCDEFGH") {
    const sequence = events.filter((event) => event.slot === slot).map((event) => event.kind);
    assert.deepEqual(sequence, FAST8_ORCHESTRATION_CONTRACT.image_execution.branch_sequence);
  }
});

test("defaults resolve beside the current Studio module and explicit roots override them", (t) => {
  const studioRoot = path.resolve(here, "..", "..");
  assert.equal(DEFAULT_LAB_ROOT, studioRoot);
  assert.equal(DEFAULT_RUN_ROOT, path.join(studioRoot, "runtime", "shawn-runs"));
  assert.doesNotMatch(DEFAULT_LAB_ROOT, /\/ppt-ai-lab(?:\/|$)/);

  const previousLabRoot = process.env.PPT_AI_LAB_ROOT;
  const previousRunRoot = process.env.PPT_AI_LAB_RUN_ROOT;
  t.after(() => {
    if (previousLabRoot === undefined) delete process.env.PPT_AI_LAB_ROOT;
    else process.env.PPT_AI_LAB_ROOT = previousLabRoot;
    if (previousRunRoot === undefined) delete process.env.PPT_AI_LAB_RUN_ROOT;
    else process.env.PPT_AI_LAB_RUN_ROOT = previousRunRoot;
  });

  const environmentLabRoot = path.join(scratch, "environment-studio");
  const environmentRunRoot = path.join(environmentLabRoot, "runtime", "configured-runs");
  process.env.PPT_AI_LAB_ROOT = environmentLabRoot;
  process.env.PPT_AI_LAB_RUN_ROOT = environmentRunRoot;
  const fromEnvironment = compileSinglePageRequest(
    input(),
    context({
      lab_root: undefined,
      approved_run_root: undefined,
      approved_run_roots: [environmentRunRoot],
    }),
  );
  assert.equal(fromEnvironment.runtime.lab_root, environmentLabRoot);
  assert.equal(fromEnvironment.runtime.run_root, environmentRunRoot);

  const parameterLabRoot = path.join(scratch, "parameter-studio");
  const parameterRunRoot = path.join(parameterLabRoot, "runtime", "configured-runs");
  const fromParameters = compileSinglePageRequest(
    input(),
    context({
      lab_root: parameterLabRoot,
      approved_run_root: parameterRunRoot,
      approved_run_roots: [parameterRunRoot],
    }),
  );
  assert.equal(fromParameters.runtime.lab_root, parameterLabRoot);
  assert.equal(fromParameters.runtime.run_root, parameterRunRoot);
});

test("fails closed on source revision conflict", () => {
  assert.throws(
    () =>
      compileSinglePageRequest(
        input({ expected_revision: `sha256:${"0".repeat(64)}` }),
        context(),
      ),
    (error) => error.code === "outline_revision_conflict",
  );
});

test("fails closed on deck or slide identity mismatch", () => {
  assert.throws(
    () => compileSinglePageRequest(input({ deck_uid: "OTHER" }), context()),
    (error) => error.code === "deck_uid_mismatch",
  );
  assert.throws(
    () => compileSinglePageRequest(input({ slide_uid: "MISSING" }), context()),
    (error) => error.code === "slide_uid_missing",
  );
});

test("rejects duplicate UID and run roots outside the explicit whitelist", () => {
  const duplicate = VALID_OUTLINE.replace("TEST_COVER", "TEST_SCOPE");
  assert.throws(
    () =>
      compileSinglePageRequest(input({ expected_revision: `sha256:${sha256Text(duplicate)}` }), {
        ...context(),
        outline_markdown: duplicate,
        outline_sha256: sha256Text(duplicate),
      }),
    (error) => error.code === "duplicate_slide_uid",
  );
  assert.throws(
    () =>
      compileSinglePageRequest(
        input(),
        context({
          approved_run_root: path.join(scratch, "unapproved-candidates"),
          approved_run_roots: [path.join(scratch, "configured-candidates")],
        }),
      ),
    (error) => error.code === "run_root_not_approved",
  );
});

test("accepts a deck-config candidate root outside the lab when explicitly approved", () => {
  const candidateRoot = path.join(scratch, "saturated-ppt-deck", "candidate-root");
  const compiled = compileSinglePageRequest(
    input(),
    context({
      approved_run_root: candidateRoot,
      approved_run_roots: [candidateRoot],
    }),
  );
  assert.equal(compiled.runtime.run_root, candidateRoot);
  assert.deepEqual(compiled.runtime.approved_run_roots, [candidateRoot]);
  const turn = buildAppServerTurn(compiled, { thread_id: "candidate-root-thread" });
  assert.equal(turn.cwd, candidateRoot);
  assert.deepEqual(turn.sandboxPolicy.writableRoots, [
    candidateRoot,
    compiled.runtime.monitoring_root,
  ]);
});

test("keeps isolated smoke compatibility with either lab or run-root whitelist", () => {
  const runRoot = path.join(scratch, "runtime", "shawn-runs");
  const approvedByLab = compileSinglePageRequest(
    input(),
    context({ approved_run_root: runRoot, approved_run_roots: [scratch] }),
  );
  const approvedByRunRoot = compileSinglePageRequest(
    input(),
    context({ approved_run_root: runRoot, approved_run_roots: [runRoot] }),
  );
  assert.equal(approvedByLab.runtime.run_root, runRoot);
  assert.equal(approvedByRunRoot.runtime.run_root, runRoot);
});

test("requires an explicit non-empty run-root whitelist", () => {
  assert.throws(
    () => compileSinglePageRequest(input(), context({ approved_run_roots: undefined })),
    (error) => error.code === "approved_run_roots_missing",
  );
  assert.throws(
    () => compileSinglePageRequest(input(), context({ approved_run_roots: [] })),
    (error) => error.code === "approved_run_roots_missing",
  );
});

test("parses exactly four absolute native refs", () => {
  const projectDir = path.join(scratch, "runtime", "shawn-runs", "run-1");
  const parsed = parseNativeRefs({
    contract_version: 1,
    native_refs: {
      project_dir: projectDir,
      state_path: path.join(projectDir, "state", "style_run_state.json"),
      handoff_path: path.join(projectDir, "state", "handoff.json"),
      run_id: "fast8-test",
    },
  });
  assert.equal(parsed.run_id, "fast8-test");
  const fenced = parseNativeRefs(
    `\`\`\`json\n${JSON.stringify({ contract_version: 1, native_refs: parsed })}\n\`\`\``,
  );
  assert.deepEqual(fenced, parsed);
  assert.throws(
    () => parseNativeRefs({ contract_version: 1, native_refs: { ...parsed, extra: true } }),
    (error) => error.code === "invalid_native_refs",
  );
  assert.throws(
    () =>
      parseNativeRefs(
        `progress first\n${JSON.stringify({ contract_version: 1, native_refs: parsed })}`,
      ),
    (error) => error.code === "invalid_native_refs",
  );
});

test("verifies a fake canonical state/snapshot/handoff without image review", async () => {
  const runRoot = path.join(scratch, "runtime", "shawn-runs");
  const projectDir = path.join(runRoot, "P07_8x1_20260812_fake");
  const stateDir = path.join(projectDir, "state");
  await mkdir(stateDir, { recursive: true });
  const statePath = path.join(stateDir, "style_run_state.json");
  const snapshotPath = path.join(stateDir, "source_snapshot.json");
  const handoffPath = path.join(stateDir, "handoff.json");
  const runId = "fast8-fake-contract";
  const revision = sha256Text(VALID_OUTLINE);
  const identity = {
    slide_identity_contract_version: 1,
    required: true,
    deck_uid: "TEST_DECK",
    slide_uids: { P07: "TEST_SCOPE" },
    source_path: path.join(scratch, "outline.md"),
    source_sha256: revision,
    identity_rule: "immutable_content_identity_not_page_or_title",
  };
  const snapshot = {
    source_snapshot_contract_version: 1,
    run_id: runId,
    project_dir: projectDir,
    run_mode: "fast_8x1_diverse",
    page_ids: ["P07"],
    slide_identity: identity,
  };
  await writeFile(snapshotPath, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");
  const snapshotHash = createHash("sha256").update(await readFile(snapshotPath)).digest("hex");
  const state = {
    run_id: runId,
    run_mode: "fast_8x1_diverse",
    status: "completed",
    anchor_page_id: "P07",
    source_snapshot_path: snapshotPath,
    source_snapshot_sha256: snapshotHash,
  };
  await writeFile(statePath, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  const stateHash = createHash("sha256").update(await readFile(statePath)).digest("hex");
  const candidates = "ABCDEFGH".split("").map((style) => ({
    style_slot: style,
    page_id: "P07",
    deck_uid: "TEST_DECK",
    slide_uid: "TEST_SCOPE",
  }));
  const handoff = {
    handoff_contract_version: 1,
    project_dir: projectDir,
    run_id: runId,
    run_mode: "fast_8x1_diverse",
    status: "candidate_ready",
    pipeline_status: "completed",
    state_ref: { path: statePath, sha256: stateHash },
    source_snapshot_ref: { path: snapshotPath, sha256: snapshotHash },
    slide_identity: identity,
    candidates,
  };
  await writeFile(handoffPath, `${JSON.stringify(handoff, null, 2)}\n`, "utf8");

  const result = await verifyNativeRefs(
    {
      project_dir: projectDir,
      state_path: statePath,
      handoff_path: handoffPath,
      run_id: runId,
    },
    {
      approved_run_root: runRoot,
      outline_path: path.join(scratch, "outline.md"),
      expected_revision: `sha256:${revision}`,
      deck_uid: "TEST_DECK",
      slide_uid: "TEST_SCOPE",
      page_id: "P07",
    },
  );
  assert.equal(result.status, "verified");
  assert.equal(result.native_refs.run_id, runId);
});

test("rejects fake refs when the snapshot revision no longer matches", async () => {
  const runRoot = path.join(scratch, "runtime", "shawn-runs");
  const projectDir = path.join(runRoot, "P07_8x1_20260812_fake");
  await assert.rejects(
    verifyNativeRefs(
      {
        project_dir: projectDir,
        state_path: path.join(projectDir, "state", "style_run_state.json"),
        handoff_path: path.join(projectDir, "state", "handoff.json"),
        run_id: "fast8-fake-contract",
      },
      {
        approved_run_root: runRoot,
        outline_path: path.join(scratch, "outline.md"),
        expected_revision: `sha256:${"0".repeat(64)}`,
        deck_uid: "TEST_DECK",
        slide_uid: "TEST_SCOPE",
        page_id: "P07",
      },
    ),
    (error) => error.code === "source_identity_mismatch",
  );
});
