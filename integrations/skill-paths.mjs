import { existsSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const CODEX_HOME = path.resolve(
  process.env.CODEX_HOME || path.join(homedir(), ".codex"),
);
export const STUDIO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
export const BUNDLED_SHAWN_SKILL_ROOT = path.join(
  STUDIO_ROOT,
  ".agents",
  "skills",
  "shawn-ppt-image",
);

function hasSkill(root) {
  return existsSync(path.join(root, "SKILL.md"));
}

export function resolveShawnSkillRoot() {
  const override = process.env.SHAWN_PPT_IMAGE_SKILL_ROOT;
  if (override) return path.resolve(override);

  const candidates = [
    BUNDLED_SHAWN_SKILL_ROOT,
    path.join(CODEX_HOME, "skills", "Shawn-PPT-image"),
    path.join(CODEX_HOME, "skills", "shawn-ppt-image"),
  ];
  return candidates.find(hasSkill) || BUNDLED_SHAWN_SKILL_ROOT;
}

export const SHAWN_SKILL_ROOT = resolveShawnSkillRoot();
export const SHAWN_SKILL_PATH = path.join(SHAWN_SKILL_ROOT, "SKILL.md");
export const IMAGEGEN_SKILL_PATH = path.join(
  CODEX_HOME,
  "skills",
  ".system",
  "imagegen",
  "SKILL.md",
);
