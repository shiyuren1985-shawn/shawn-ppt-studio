import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import {
  BUNDLED_SHAWN_SKILL_ROOT,
  resolveShawnSkillRoot,
  SHAWN_SKILL_PATH,
  SHAWN_SKILL_ROOT,
  STUDIO_ROOT,
} from "../../integrations/skill-paths.mjs";

test("Studio uses the installed Shawn PPT Skill before its bundled fallback", async () => {
  assert.equal(
    BUNDLED_SHAWN_SKILL_ROOT,
    path.join(STUDIO_ROOT, ".agents", "skills", "shawn-ppt-image"),
  );
  const root = await mkdtemp(path.join(tmpdir(), "studio-skill-paths-"));
  const codexHome = path.join(root, "codex");
  const installedRoot = path.join(codexHome, "skills", "Shawn-PPT-image");
  const bundledRoot = path.join(root, "bundled");
  try {
    await mkdir(installedRoot, { recursive: true });
    await mkdir(bundledRoot, { recursive: true });
    await writeFile(path.join(installedRoot, "SKILL.md"), "installed\n");
    await writeFile(path.join(bundledRoot, "SKILL.md"), "fallback\n");
    assert.equal(
      resolveShawnSkillRoot({ codexHome, bundledRoot }),
      installedRoot,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("the active Studio Skill path resolves to an existing Skill", async () => {
  assert.equal(SHAWN_SKILL_PATH, path.join(SHAWN_SKILL_ROOT, "SKILL.md"));
  assert.equal((await stat(SHAWN_SKILL_PATH)).isFile(), true);
});

test("Studio falls back to the bundled Skill when no installed copy exists", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "studio-skill-paths-"));
  const codexHome = path.join(root, "codex");
  const bundledRoot = path.join(root, "bundled");
  try {
    await mkdir(bundledRoot, { recursive: true });
    await writeFile(path.join(bundledRoot, "SKILL.md"), "fallback\n");
    assert.equal(
      resolveShawnSkillRoot({ codexHome, bundledRoot }),
      bundledRoot,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("an explicit Skill override remains authoritative", () => {
  assert.equal(
    resolveShawnSkillRoot({ override: "/tmp/custom-shawn-skill" }),
    "/tmp/custom-shawn-skill",
  );
});
