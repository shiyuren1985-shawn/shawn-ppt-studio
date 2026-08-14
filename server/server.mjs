#!/usr/bin/env node

import path from "node:path";
import { fileURLToPath } from "node:url";

import { AppServerClient, resolveCodexExecutable } from "./app-server-client.mjs";
import { CandidateEditService } from "./candidate-edits.mjs";
import { ConversationIndex } from "./conversations.mjs";
import { DeckDiscovery, DEFAULT_DECKS_FILE } from "./discovery.mjs";
import { ProjectDiscovery } from "./project-discovery.mjs";
import { StudioProjectRegistry } from "./projects.mjs";
import { MacProjectPicker } from "./project-picker.mjs";
import { createLabHttpServer } from "./http-server.mjs";
import { LabLedger } from "./ledger.mjs";
import { OutlineStore } from "./outline-store.mjs";
import { createPathPolicy } from "./path-policy.mjs";
import { ProductionIntentService } from "./production-intents.mjs";
import { SelectionProjection } from "./selection-projection.mjs";
import { SelectorWorkspace } from "./selector-workspace.mjs";
import { ExportService } from "./export-service.mjs";
import { SingleEditTurnFinalizer } from "./single-edit-turn-finalizer.mjs";
import {
  DEFAULT_MONITORING_ROOT,
  DEFAULT_OVERVIEW_PYTHON,
} from "../integrations/shawn-single-page.mjs";

function parsePort(argv, env) {
  const index = argv.indexOf("--port");
  const raw = index >= 0 ? argv[index + 1] : env.PPT_AI_LAB_PORT || env.PORT || "8770";
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error(`Invalid port: ${raw}`);
  }
  return port;
}

const serverDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(serverDir, "..");
const dataRoot =
  process.env.PPT_AI_LAB_TEST_MODE === "1" && process.env.PPT_AI_LAB_ROOT
    ? path.resolve(process.env.PPT_AI_LAB_ROOT)
    : path.resolve(process.env.SHAWN_PPT_STUDIO_DATA_ROOT || projectRoot);
const labRoot = dataRoot;
const pathPolicy = createPathPolicy(dataRoot);
await pathPolicy.ensureRuntime();
const ledger = new LabLedger({ labRoot: dataRoot });
try {
  await ledger.initialize();
} catch (error) {
  process.stderr.write(`PPT AI Lab: ledger unavailable: ${error.message}\n`);
}
const decksFile =
  process.env.PPT_AI_LAB_TEST_MODE === "1"
    ? path.resolve(process.env.PPT_AI_LAB_DECKS_FILE || path.join(labRoot, "fixtures", "decks.json"))
    : DEFAULT_DECKS_FILE;
const projects = new StudioProjectRegistry({ dataRoot });
try {
  await projects.initialize();
} catch (error) {
  projects.lastError = error;
  process.stderr.write(`Shawn PPT Studio: project registry unavailable: ${error.message}\n`);
}
const legacyDiscovery = new DeckDiscovery({ decksFile });
const discovery = new ProjectDiscovery({ legacyDiscovery, projects });
const projectPicker = new MacProjectPicker();
await discovery.probe();
const outlineStore = new OutlineStore({ labRoot, discovery });
const selectionProjection = new SelectionProjection({ discovery });
const singleEditTurnFinalizer = new SingleEditTurnFinalizer();
const selectorWorkspace = new SelectorWorkspace({
  discovery,
  selectorOrigin: process.env.SHAWN_PPT_SELECTOR_ORIGIN || "http://127.0.0.1:8765/",
});
const exports = new ExportService({
  discovery,
  selectionProjection,
  integrationPath: path.join(projectRoot, "integrations", "export-image-deck.mjs"),
  publicLabelTemplate: process.env.SHAWN_PPT_PUBLIC_LABEL_TEMPLATE || null,
  // A metadata copy is not a real Office label verification. Keep PPTX
  // unavailable until a PowerPoint/MIP verifier is supplied by the desktop host.
  officeLabelVerifier: null,
});
try {
  await exports.initialize();
} catch (error) {
  exports.runtimeHealth = { ready: false, missing: [], message: error.message };
  process.stderr.write(`Shawn PPT Studio: export service unavailable: ${error.message}\n`);
}
const conversations = new ConversationIndex({ dataRoot });
try {
  await conversations.initialize();
} catch (error) {
  conversations.lastError = error;
  process.stderr.write(`Shawn PPT Studio: conversation history unavailable: ${error.message}\n`);
}

const client = new AppServerClient({
  executable: resolveCodexExecutable(),
  cwd: labRoot,
});

try {
  await client.start();
} catch (error) {
  client.lastError = error;
  process.stderr.write(`PPT AI Lab: Codex App Server unavailable: ${error.message}\n`);
}

const productionRunRoot =
  process.env.PPT_AI_LAB_TEST_MODE === "1"
    ? path.resolve(process.env.PPT_AI_LAB_RUN_ROOT || path.join(labRoot, "runtime", "shawn-runs"))
    : path.join(labRoot, "runtime", "shawn-runs");
const monitoringRoot =
  process.env.PPT_AI_LAB_TEST_MODE === "1"
    ? path.resolve(
        process.env.PPT_AI_LAB_MONITORING_ROOT || path.join(labRoot, "fixtures", "monitoring"),
      )
    : DEFAULT_MONITORING_ROOT;
const overviewPython =
  process.env.PPT_AI_LAB_TEST_MODE === "1" && process.env.PPT_AI_LAB_OVERVIEW_PYTHON
    ? path.resolve(process.env.PPT_AI_LAB_OVERVIEW_PYTHON)
    : DEFAULT_OVERVIEW_PYTHON;
const production = new ProductionIntentService({
  labRoot,
  discovery,
  client,
  runRoot: productionRunRoot,
  monitoringRoot,
  overviewPython,
});
try {
  await production.initialize();
} catch (error) {
  production.lastError = error;
  process.stderr.write(`PPT AI Lab: production intent service unavailable: ${error.message}\n`);
}
const candidateEdits = new CandidateEditService({
  labRoot,
  discovery,
  production,
  selectionProjection,
  client,
  monitoringRoot,
});
try {
  await candidateEdits.initialize();
} catch (error) {
  candidateEdits.lastError = error;
  process.stderr.write(`PPT AI Lab: candidate edit service unavailable: ${error.message}\n`);
}

const server = createLabHttpServer({
  client,
  appId: "shawn-ppt-studio",
  codeRoot: projectRoot,
  dataRoot,
  labRoot,
  imageRoot: pathPolicy.imageRoot,
  pathPolicy,
  ledger,
  conversations,
  discovery,
  outlineStore,
  production,
  candidateEdits,
  selectionProjection,
  selectorWorkspace,
  monitoringRoot,
  projects,
  projectPicker,
  exports,
  singleEditTurnFinalizer,
});
const port = parsePort(process.argv.slice(2), process.env);

await new Promise((resolve, reject) => {
  server.once("error", reject);
  server.listen(port, "127.0.0.1", resolve);
});

const address = server.address();
process.stdout.write(`PPT AI Lab listening on http://127.0.0.1:${address.port}\n`);

let closing = false;
async function close() {
  if (closing) return;
  closing = true;
  await new Promise((resolve) => server.close(resolve));
  production.stop();
  candidateEdits.stop();
  await client.stop();
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    await close();
    process.exit(0);
  });
}

process.on("uncaughtException", async (error) => {
  process.stderr.write(`PPT AI Lab uncaught exception: ${error.stack || error.message}\n`);
  await close();
  process.exit(1);
});

process.on("unhandledRejection", async (error) => {
  process.stderr.write(`PPT AI Lab unhandled rejection: ${error?.stack || error}\n`);
  await close();
  process.exit(1);
});
