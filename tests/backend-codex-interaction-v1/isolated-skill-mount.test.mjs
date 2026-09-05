import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { StudioConversationLifecycle } from "../../server/studio-codex-storage.mjs";

test("an isolated Studio home discovers its required image skill without sharing main history", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-isolated-skill-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const legacyHome = path.join(root, "main");
  const skillRoot = path.join(legacyHome, "skills", "Shawn-PPT-image");
  await mkdir(path.join(skillRoot, "scripts"), { recursive: true });
  await writeFile(path.join(skillRoot, "SKILL.md"), "---\nname: shawn-ppt-image\ndescription: Test image skill\n---\n");
  await writeFile(path.join(skillRoot, "scripts", "init_task_dir.py"), "# fixture\n");
  await mkdir(path.join(legacyHome, "sessions"));
  await writeFile(path.join(legacyHome, "sessions", "untouched.txt"), "private session marker");
  const lifecycle = new StudioConversationLifecycle({ dataRoot: path.join(root, "data"), legacyHome, executable: "unused", cwd: root });
  await lifecycle.initialize();
  const mounted = path.join(lifecycle.isolatedHome, "skills", "shawn-ppt-image");
  assert.equal(await realpath(mounted), await realpath(skillRoot));
  assert.equal(await readFile(path.join(mounted, "scripts", "init_task_dir.py"), "utf8"), "# fixture\n");
  await assert.rejects(readFile(path.join(lifecycle.isolatedHome, "sessions", "untouched.txt")), { code: "ENOENT" });
  await lifecycle.initialize();
  assert.equal(await readFile(path.join(legacyHome, "sessions", "untouched.txt"), "utf8"), "private session marker");
});

test("managed skill links recover from target moves without replacing a local skill directory", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-skill-link-recovery-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const sources = [path.join(root, "skill-one"), path.join(root, "skill-two"), path.join(root, "skill-three")];
  for (const source of sources) {
    await mkdir(source);
    await writeFile(path.join(source, "SKILL.md"), "fixture");
  }
  const baseEnv = { SHAWN_PPT_IMAGE_SKILL_ROOT: sources[0] };
  const lifecycle = new StudioConversationLifecycle({ dataRoot: path.join(root, "data"), legacyHome: path.join(root, "main"), baseEnv, executable: "unused", cwd: root });
  await lifecycle.initialize();
  const mounted = path.join(lifecycle.isolatedHome, "skills", "shawn-ppt-image");
  baseEnv.SHAWN_PPT_IMAGE_SKILL_ROOT = sources[1];
  await lifecycle.initialize();
  assert.equal(await realpath(mounted), await realpath(sources[1]), "an explicit source change updates the managed link");
  await rm(sources[1], { recursive: true });
  baseEnv.SHAWN_PPT_IMAGE_SKILL_ROOT = sources[2];
  await lifecycle.initialize();
  assert.equal(await realpath(mounted), await realpath(sources[2]), "a broken managed link is repaired");
  await rm(mounted);
  await mkdir(mounted);
  await writeFile(path.join(mounted, "SKILL.md"), "local user skill");
  await lifecycle.initialize();
  assert.equal(await readFile(path.join(mounted, "SKILL.md"), "utf8"), "local user skill");
});

test("a skill mount failure remains separate from usable conversation storage", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-skill-missing-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const baseEnv = { SHAWN_PPT_IMAGE_SKILL_ROOT: path.join(root, "missing-skill") };
  const lifecycle = new StudioConversationLifecycle({ dataRoot: root, legacyHome: path.join(root, "main"), baseEnv, executable: "unused", cwd: root });
  await lifecycle.initialize();
  assert.equal(lifecycle.ready, true);
  assert.match(lifecycle.health().image_skill_error, /skill/i);
  await mkdir(baseEnv.SHAWN_PPT_IMAGE_SKILL_ROOT);
  await writeFile(path.join(baseEnv.SHAWN_PPT_IMAGE_SKILL_ROOT, "SKILL.md"), "fixture");
  await lifecycle.initialize();
  assert.equal(lifecycle.health().image_skill_error, null);
});
