import assert from "node:assert/strict";
import { stat } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import {
  BUNDLED_SHAWN_SKILL_ROOT,
  SHAWN_SKILL_PATH,
  SHAWN_SKILL_ROOT,
  STUDIO_ROOT,
} from "../../integrations/skill-paths.mjs";

test("Studio prefers the bundled repo-scoped Shawn PPT Skill", async () => {
  assert.equal(
    BUNDLED_SHAWN_SKILL_ROOT,
    path.join(STUDIO_ROOT, ".agents", "skills", "shawn-ppt-image"),
  );
  assert.equal(SHAWN_SKILL_ROOT, BUNDLED_SHAWN_SKILL_ROOT);
  assert.equal(SHAWN_SKILL_PATH, path.join(SHAWN_SKILL_ROOT, "SKILL.md"));
  assert.equal((await stat(SHAWN_SKILL_PATH)).isFile(), true);
});
