import assert from "node:assert/strict";
import test from "node:test";

import { createCandidateArtifactCleanupPlanner } from "../../integrations/candidate-artifact-cleanup.mjs";

test("candidate artifact cleanup integration invokes the canonical Skill planner", async () => {
  let invocation;
  const expected = {
    candidate_artifact_cleanup_plan_version: 1,
    project_root: "/tmp/project",
    strategy: "partial",
    delete_candidate_paths: ["/tmp/project/origin_image/A.png"],
    retained_candidate_paths: ["/tmp/project/origin_image/H.png"],
    targets: [{ path: "/tmp/project/origin_image/A.png", kind: "file" }],
  };
  const planner = createCandidateArtifactCleanupPlanner({
    pythonPath: "/usr/bin/python3",
    skillRoot: "/tmp/skill",
    run: async (...args) => {
      invocation = args;
      return { stdout: JSON.stringify(expected) };
    },
  });
  assert.deepEqual(await planner({
    projectRoot: "/tmp/project",
    candidatePaths: ["/tmp/project/origin_image/A.png"],
  }), expected);
  assert.equal(invocation[0], "/usr/bin/python3");
  assert.deepEqual(invocation[1], [
    "/tmp/skill/scripts/plan_candidate_artifact_cleanup.py",
    "--project-root",
    "/tmp/project",
    "--candidate-path",
    "/tmp/project/origin_image/A.png",
  ]);
});
