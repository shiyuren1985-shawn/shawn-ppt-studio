import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { ProjectDiscovery } from "../../server/project-discovery.mjs";
import { StudioProjectRegistry } from "../../server/projects.mjs";

async function fixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-project-switcher-"));
  const dataRoot = path.join(root, "data");
  const projectRoot = path.join(root, "project-a");
  await mkdir(projectRoot, { recursive: true });
  const outlinePath = path.join(projectRoot, "outline.md");
  await writeFile(outlinePath, "# Project A\n\nA short outline.\n");
  const registry = new StudioProjectRegistry({ dataRoot, clock: () => "2026-08-14T00:00:00.000Z" });
  await registry.initialize();
  return { root, dataRoot, projectRoot, outlinePath, registry };
}

test("hiding a Studio project preserves files and reopening restores the same task", async () => {
  const { dataRoot, outlinePath, registry } = await fixture();
  const before = await readFile(outlinePath, "utf8");
  const created = await registry.openExisting({ outlinePath });
  await registry.hideDeck({ deckId: created.deck_id, outlinePath: created.outline_path });

  assert.equal(registry.list().projects.length, 0);
  assert.equal(registry.list({ includeHidden: true }).projects.length, 1);
  assert.equal(await readFile(outlinePath, "utf8"), before);
  assert.equal((await stat(outlinePath)).isFile(), true);

  const restored = await registry.openExisting({ outlinePath });
  assert.equal(restored.deck_id, created.deck_id);
  assert.equal(restored.project_id, created.project_id);
  assert.equal(restored.restored, true);
  assert.equal(registry.list().projects.length, 1);

  const restarted = new StudioProjectRegistry({ dataRoot });
  await restarted.initialize();
  assert.equal(restarted.list().projects[0].deck_id, created.deck_id);
  assert.equal(restarted.state.hidden_decks.length, 0);
});

test("a v1 registry without hidden_decks migrates without losing projects", async () => {
  const { dataRoot, outlinePath } = await fixture();
  const runtimeRoot = path.join(dataRoot, "runtime");
  await writeFile(path.join(runtimeRoot, "projects.json"), `${JSON.stringify({
    contract_version: 1,
    default_project_id: "p1",
    projects: [{
      project_id: "p1",
      deck_id: "studio-p1",
      deck_uid: "STUDIO_P1",
      label: "Existing",
      project_root: path.dirname(outlinePath),
      outline_path: outlinePath,
      output_root: path.join(path.dirname(outlinePath), "output"),
      created_at: "2026-08-13T00:00:00.000Z",
      updated_at: "2026-08-13T00:00:00.000Z",
    }],
  }, null, 2)}\n`);
  const registry = new StudioProjectRegistry({ dataRoot });
  await registry.initialize();
  assert.deepEqual(registry.state.hidden_decks, []);
  assert.equal(registry.list().projects[0].deck_id, "studio-p1");
});

test("hiding and reopening a legacy outline restores the same legacy task", async () => {
  const { root, registry } = await fixture();
  const legacyRoot = path.join(root, "legacy");
  await mkdir(legacyRoot, { recursive: true });
  const outlinePath = path.join(legacyRoot, "legacy.md");
  await writeFile(outlinePath, "# Legacy\n");
  const publicLegacy = {
    deck_id: "legacy-a",
    deck_uid: "LEGACY_A",
    label: "Legacy A",
    outline_path: outlinePath,
    candidate_root: legacyRoot,
    slides: [],
  };
  const legacyDiscovery = {
    decksFile: path.join(root, "decks.json"),
    health: () => ({ ready: true, deck_count: 1 }),
    listDecks: async () => ({ default_deck: "legacy-a", decks: [publicLegacy] }),
    readDeck: async () => ({
      deck_id: "legacy-a",
      label: "Legacy A",
      candidate_roots: [{ id: "output", path: legacyRoot }],
      outline: { deck_uid: "LEGACY_A", path: outlinePath, slides: [] },
    }),
  };
  const discovery = new ProjectDiscovery({ legacyDiscovery, projects: registry });

  await discovery.hideDeck("legacy-a");
  assert.equal((await discovery.listDecks()).decks.length, 0);
  const restored = await discovery.restoreExistingOutline(outlinePath);
  assert.equal(restored.deck_id, "legacy-a");
  assert.equal((await discovery.listDecks()).decks[0].deck_id, "legacy-a");
});
