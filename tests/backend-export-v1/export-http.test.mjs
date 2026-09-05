import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { ExportNotReadyError } from "../../server/export-service.mjs";
import { createLabHttpServer } from "../../server/http-server.mjs";

async function start(exports) {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-export-http-"));
  const client = new EventEmitter();
  Object.assign(client, {
    ready: false,
    pid: null,
    account: null,
    lastError: null,
    subscribe: () => () => {},
    subscribeServerRequests: () => () => {},
  });
  const server = createLabHttpServer({
    client,
    appId: "test",
    dataRoot: root,
    labRoot: root,
    webRoot: root,
    pathPolicy: { imageRoot: path.join(root, "images") },
    discovery: { listDecks: async () => ({ decks: [] }) },
    exports,
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  return {
    root,
    origin,
    close: async () => {
      await new Promise((resolve) => server.close(resolve));
      await rm(root, { recursive: true, force: true });
    },
  };
}

test("HTTP export routes use the frozen shape and stream allowlisted files", async (t) => {
  let created = 0;
  let opened = 0;
  let openedRoot = 0;
  const harness = await start({
    health: () => ({ ready: true }),
    readiness: async () => ({
      contract_version: 1,
      deck_id: "demo",
      ready: true,
      formats: ["pdf", "images_zip"],
      _deck: { private: true },
    }),
    create: async (_deckId, body) => {
      created += 1;
      assert.deepEqual(body, { name: "评审版", formats: ["pptx", "pdf"] });
      return { contract_version: 1, status: "completed_with_warnings", export_id: "result-1" };
    },
    resolveFile: async (_deckId, _id, kind) => {
      const file = path.join(harness.root, kind === "pdf" ? "deck.pdf" : "manifest.json");
      await writeFile(file, kind === "pdf" ? "%PDF-test" : "{}", "utf8");
      return { path: file, filename: path.basename(file) };
    },
    showInFinder: async () => { opened += 1; return { opened: true }; },
    showRootInFinder: async () => {
      openedRoot += 1;
      return { opened: true, folder_name: "Shawn PPT Studio Exports" };
    },
  });
  t.after(harness.close);

  let response = await fetch(`${harness.origin}/api/decks/demo/export-readiness`);
  const readiness = await response.json();
  assert.equal(readiness._deck, undefined);
  assert.equal(readiness.ready, true);

  response = await fetch(`${harness.origin}/api/decks/demo/exports`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-shawn-ppt-studio": "1" },
    body: JSON.stringify({ name: "评审版", formats: ["pptx", "pdf"] }),
  });
  assert.equal(response.status, 201);
  assert.equal((await response.json()).export_id, "result-1");
  assert.equal(created, 1);

  response = await fetch(`${harness.origin}/api/decks/demo/exports/result-1/files/pdf`);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "application/pdf");
  assert.match(response.headers.get("content-disposition"), /deck\.pdf/);

  response = await fetch(`${harness.origin}/api/decks/demo/exports/result-1/open-folder`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-shawn-ppt-studio": "1" },
    body: "{}",
  });
  assert.equal(response.status, 200);
  assert.equal(opened, 1);

  response = await fetch(`${harness.origin}/api/exports/open-folder`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-shawn-ppt-studio": "1" },
    body: "{}",
  });
  assert.equal(response.status, 200);
  assert.equal((await response.json()).folder_name, "Shawn PPT Studio Exports");
  assert.equal(openedRoot, 1);
});

test("HTTP 409 preserves the human missing-page list", async (t) => {
  const readiness = {
    ready: false,
    message: "还有 1 页需要确认选图：P02。",
    missing_pages: [{ slide_uid: "slide-2", page_label: "P02", reason: "no_selection" }],
  };
  const harness = await start({
    health: () => ({ ready: true }),
    create: async () => { throw new ExportNotReadyError(readiness); },
  });
  t.after(harness.close);
  const response = await fetch(`${harness.origin}/api/decks/demo/exports`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-shawn-ppt-studio": "1" },
    body: "{}",
  });
  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), {
    error: "export_not_ready",
    message: readiness.message,
    missing_pages: readiness.missing_pages,
  });
});
