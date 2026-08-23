import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";

import { SHAWN_SKILL_ROOT } from "./skill-paths.mjs";

const execFileAsync = promisify(execFile);
const PLAN_VERSION = 1;

export function createCandidateArtifactCleanupPlanner({
  pythonPath,
  skillRoot = SHAWN_SKILL_ROOT,
  run = execFileAsync,
} = {}) {
  if (!path.isAbsolute(pythonPath || "")) {
    throw new Error("candidate cleanup python must be an absolute path");
  }
  const scriptPath = path.join(path.resolve(skillRoot), "scripts", "plan_candidate_artifact_cleanup.py");
  return async ({ projectRoot, candidatePaths }) => {
    if (
      !path.isAbsolute(projectRoot || "") ||
      !Array.isArray(candidatePaths) ||
      candidatePaths.length === 0 ||
      candidatePaths.some((item) => !path.isAbsolute(item || ""))
    ) {
      throw new Error("candidate cleanup inputs are invalid");
    }
    const args = ["--project-root", projectRoot];
    for (const candidatePath of candidatePaths) {
      args.push("--candidate-path", candidatePath);
    }
    const { stdout } = await run(pythonPath, [scriptPath, ...args], {
      timeout: 30_000,
      maxBuffer: 1024 * 1024,
      windowsHide: true,
    });
    const plan = JSON.parse(String(stdout));
    if (
      !plan ||
      plan.candidate_artifact_cleanup_plan_version !== PLAN_VERSION ||
      !Array.isArray(plan.targets) ||
      !Array.isArray(plan.delete_candidate_paths) ||
      !Array.isArray(plan.retained_candidate_paths) ||
      !["partial", "whole_run"].includes(plan.strategy)
    ) {
      throw new Error("candidate cleanup plan is invalid");
    }
    return plan;
  };
}
