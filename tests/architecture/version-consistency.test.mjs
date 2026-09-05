import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

test("desktop package metadata shares one visible Studio version", async () => {
  const [rootPackage, desktopPackage, tauriConfig, cargo] = await Promise.all([
    readFile(path.join(root, "package.json"), "utf8").then(JSON.parse),
    readFile(path.join(root, "desktop/package.json"), "utf8").then(JSON.parse),
    readFile(path.join(root, "desktop/src-tauri/tauri.conf.json"), "utf8").then(JSON.parse),
    readFile(path.join(root, "desktop/src-tauri/Cargo.toml"), "utf8"),
  ]);
  const cargoVersion = cargo.match(/^version\s*=\s*"([^"]+)"/m)?.[1];
  assert.equal(rootPackage.version, "0.2.12");
  assert.equal(desktopPackage.version, rootPackage.version);
  assert.equal(tauriConfig.version, rootPackage.version);
  assert.equal(cargoVersion, rootPackage.version);
});
