import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

async function runtimeFiles(directory, extension) {
  const root = path.join(projectRoot, directory);
  const entries = await readdir(root, { withFileTypes: true, recursive: true });
  return entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(extension))
    .map((entry) => path.join(entry.parentPath, entry.name))
    .sort();
}

function localSpecifiers(source) {
  const specifiers = new Set();
  const patterns = [
    /\b(?:import|export)\s+(?:[^;"']*?\s+from\s*)?["'](\.[^"']+)["']/g,
    /\bimport\s*\(\s*["'](\.[^"']+)["']\s*\)/g,
  ];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) specifiers.add(match[1]);
  }
  return [...specifiers];
}

async function graphFor(files) {
  const known = new Set(files.map((file) => path.resolve(file)));
  const graph = new Map();
  for (const file of known) {
    const source = await readFile(file, "utf8");
    const dependencies = localSpecifiers(source)
      .map((specifier) => path.resolve(path.dirname(file), specifier))
      .filter((dependency) => known.has(dependency));
    graph.set(file, dependencies);
  }
  return graph;
}

function reachableFrom(graph, entry) {
  const reachable = new Set();
  const pending = [entry];
  while (pending.length) {
    const current = pending.pop();
    if (reachable.has(current)) continue;
    reachable.add(current);
    pending.push(...(graph.get(current) || []));
  }
  return reachable;
}

function cyclesIn(graph) {
  const visited = new Set();
  const active = new Set();
  const stack = [];
  const cycles = [];

  function visit(file) {
    if (active.has(file)) {
      const start = stack.indexOf(file);
      cycles.push([...stack.slice(start), file]);
      return;
    }
    if (visited.has(file)) return;
    visited.add(file);
    active.add(file);
    stack.push(file);
    for (const dependency of graph.get(file) || []) visit(dependency);
    stack.pop();
    active.delete(file);
  }

  for (const file of graph.keys()) visit(file);
  return cycles;
}

for (const target of [
  { directory: "server", extension: ".mjs", entry: "server/server.mjs" },
  { directory: "web", extension: ".js", entry: "web/app.js" },
]) {
  test(`${target.directory} runtime graph has one entry path and no import cycles`, async () => {
    const files = await runtimeFiles(target.directory, target.extension);
    const graph = await graphFor(files);
    const entry = path.join(projectRoot, target.entry);
    const reachable = reachableFrom(graph, entry);
    const unreachable = files
      .filter((file) => !reachable.has(file))
      .map((file) => path.relative(projectRoot, file));
    const cycles = cyclesIn(graph).map((cycle) =>
      cycle.map((file) => path.relative(projectRoot, file)).join(" -> "));

    assert.deepEqual(unreachable, [], `runtime modules are disconnected: ${unreachable.join(", ")}`);
    assert.deepEqual(cycles, [], `runtime import cycles detected: ${cycles.join("; ")}`);
  });
}
