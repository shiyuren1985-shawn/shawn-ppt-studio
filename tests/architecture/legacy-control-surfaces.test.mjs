import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

async function sourceTree(directory, extensions) {
  const root = path.join(projectRoot, directory);
  const entries = await readdir(root, { withFileTypes: true, recursive: true });
  const files = entries
    .filter((entry) => entry.isFile() && extensions.has(path.extname(entry.name)))
    .map((entry) => path.join(entry.parentPath, entry.name));
  return Promise.all(files.map((file) => readFile(file, "utf8")));
}

test("the shipped runtime exposes only the conversation and canonical Skill control plane", async () => {
  const [server, web, manifest] = await Promise.all([
    sourceTree("server", new Set([".mjs"])),
    sourceTree("web", new Set([".js"])),
    readFile(path.join(projectRoot, "desktop/src-tauri/tauri.conf.json"), "utf8"),
  ]);
  const runtime = [...server, ...web, manifest].join("\n");
  for (const forbidden of [
    "http://127.0.0.1:8765",
    "/api/production/",
    'requestUrl.pathname === "/api/turns"',
    'requestUrl.pathname === "/api/runtime-file"',
    "ProductionIntentService",
    "CandidateEditService",
    "LabLedger",
  ]) {
    assert.equal(runtime.includes(forbidden), false, `legacy control surface returned: ${forbidden}`);
  }
});
