import assert from "node:assert/strict";
import { mkdtemp, mkdir, realpath, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { DeckDiscovery } from "../../server/discovery.mjs";
import { ProjectDiscovery } from "../../server/project-discovery.mjs";
import { StudioProjectRegistry } from "../../server/projects.mjs";

test("Studio projects stay available when the optional legacy registry is absent", async (t) => {
  const root = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-no-legacy-")));
  t.after(() => rm(root, { recursive: true, force: true }));

  const dataRoot = path.join(root, "data");
  const projectRoot = path.join(root, "project");
  const outlinePath = path.join(projectRoot, "outline.md");
  await mkdir(projectRoot, { recursive: true });
  await writeFile(outlinePath, "# Existing outline\n", "utf8");

  const projects = new StudioProjectRegistry({ dataRoot });
  await projects.initialize();
  const created = await projects.openExisting({ outlinePath });
  const discovery = new ProjectDiscovery({
    legacyDiscovery: new DeckDiscovery({ decksFile: path.join(root, "missing", "decks.json") }),
    projects,
  });

  const listed = await discovery.listDecks();
  assert.deepEqual(listed.decks.map((deck) => deck.deck_id), [created.deck_id]);
  assert.equal(listed.default_deck, created.deck_id);
  assert.equal(discovery.health().ready, true);
  assert.equal(discovery.health().legacy.ready, false);
  assert.match(discovery.health().legacy.error, /ENOENT/);

  const outline = await discovery.getOutline(created.deck_id);
  assert.equal(outline.outline_path, await realpath(outlinePath));
  assert.equal(outline.outline_kind, "draft");
});
