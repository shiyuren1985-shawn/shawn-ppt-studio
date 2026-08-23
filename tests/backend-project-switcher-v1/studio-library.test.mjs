import assert from "node:assert/strict";
import { access, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  prepareStudioLibrary,
  STUDIO_LIBRARY_DIRECTORY,
  studioLibraryRoot,
} from "../../server/studio-library.mjs";

test("legacy runtime data migrates intact into the clearly named Studio Library", async (t) => {
  const dataRoot = await mkdtemp(path.join(os.tmpdir(), "studio-library-migration-"));
  t.after(() => rm(dataRoot, { recursive: true, force: true }));
  const legacyRoot = path.join(dataRoot, "runtime");
  await mkdir(legacyRoot, { recursive: true });
  await writeFile(path.join(legacyRoot, "projects.json"), "project registry", "utf8");
  await writeFile(path.join(legacyRoot, "conversations.json"), "conversation history", "utf8");

  const migrated = await prepareStudioLibrary(dataRoot);
  assert.equal(migrated.migrated, true);
  assert.equal(path.basename(migrated.library_root), STUDIO_LIBRARY_DIRECTORY);
  assert.equal(await readFile(path.join(studioLibraryRoot(dataRoot), "projects.json"), "utf8"), "project registry");
  assert.equal(await readFile(path.join(studioLibraryRoot(dataRoot), "conversations.json"), "utf8"), "conversation history");
  await assert.rejects(() => access(legacyRoot), (error) => error?.code === "ENOENT");

  const repeated = await prepareStudioLibrary(dataRoot);
  assert.equal(repeated.migrated, false);
});
