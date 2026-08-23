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

test("the normal Studio runtime treats its intentionally absent legacy registry as empty", async (t) => {
  const root = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-empty-legacy-")));
  t.after(() => rm(root, { recursive: true, force: true }));

  const discovery = new DeckDiscovery({
    decksFile: path.join(root, "missing", "decks.json"),
    allowMissing: true,
  });
  const listed = await discovery.listDecks();

  assert.equal(listed.default_deck, null);
  assert.deepEqual(listed.decks, []);
  assert.equal(discovery.health().ready, true);
  assert.equal(discovery.health().deck_count, 0);
  assert.equal(discovery.health().error, null);
});

test("one missing outline is isolated while valid Studio projects remain available", async (t) => {
  const root = await realpath(await mkdtemp(path.join(os.tmpdir(), "studio-stale-project-")));
  t.after(() => rm(root, { recursive: true, force: true }));
  const dataRoot = path.join(root, "data");
  const validRoot = path.join(root, "valid");
  const missingRoot = path.join(root, "missing");
  await mkdir(validRoot, { recursive: true });
  await mkdir(missingRoot, { recursive: true });
  const validOutline = path.join(validRoot, "outline.md");
  const missingOutline = path.join(missingRoot, "outline.md");
  await writeFile(validOutline, "# Valid outline\n", "utf8");
  await writeFile(missingOutline, "# Missing later\n", "utf8");

  const projects = new StudioProjectRegistry({ dataRoot });
  await projects.initialize();
  const valid = await projects.openExisting({ outlinePath: validOutline, label: "Valid" });
  const missing = await projects.openExisting({ outlinePath: missingOutline, label: "Missing" });
  await rm(missingOutline);
  const discovery = new ProjectDiscovery({
    legacyDiscovery: new DeckDiscovery({ decksFile: path.join(root, "legacy.json"), allowMissing: true }),
    projects,
  });

  const listed = await discovery.listDecks();
  assert.deepEqual(listed.decks.map((deck) => deck.deck_id), [valid.deck_id]);
  assert.deepEqual(listed.unavailable_projects, [{
    deck_id: missing.deck_id,
    label: "Missing",
    outline_path: missingOutline,
    status: "outline_unavailable",
    status_label: "原大纲文件已丢失",
  }]);
  await discovery.hideDeck(missing.deck_id);
  assert.deepEqual((await discovery.listDecks()).unavailable_projects, []);
});
