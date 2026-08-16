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

export function resolveShawnSkillRoot({
  override = process.env.SHAWN_PPT_IMAGE_SKILL_ROOT,
  codexHome = CODEX_HOME,
  bundledRoot = BUNDLED_SHAWN_SKILL_ROOT,
} = {}) {
  if (override) return path.resolve(override);

  const candidates = [
    path.join(codexHome, "skills", "Shawn-PPT-image"),
    path.join(codexHome, "skills", "shawn-ppt-image"),
    bundledRoot,
  ];
  return candidates.find(hasSkill) || bundledRoot;
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
