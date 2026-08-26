#!/usr/bin/env node

import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import { AppServerClient, resolveCodexExecutable } from "./app-server-client.mjs";
import { ConversationIndex } from "./conversations.mjs";
import { DeckDiscovery, DEFAULT_DECKS_FILE } from "./discovery.mjs";
import { ProjectDiscovery } from "./project-discovery.mjs";
import { StudioProjectRegistry } from "./projects.mjs";
import { MacProjectPicker } from "./project-picker.mjs";
import { createLabHttpServer } from "./http-server.mjs";
import { StudioInstanceLock } from "./instance-lock.mjs";
import { createPathPolicy } from "./path-policy.mjs";
import { SelectionProjection } from "./selection-projection.mjs";
import { SelectorWorkspace } from "./selector-workspace.mjs";
import { ExportService } from "./export-service.mjs";
import { SingleEditTurnFinalizer } from "./single-edit-turn-finalizer.mjs";
import { TaskProjection } from "./task-projection.mjs";
import { TaskAssociationIndex } from "./task-associations.mjs";
import { StudioRulesStore } from "./studio-rules.mjs";
import { RuntimeEventLog } from "./runtime-event-log.mjs";
import { prepareStudioLibrary } from "./studio-library.mjs";
import {
  DEFAULT_MONITORING_ROOT,
  DEFAULT_OVERVIEW_PYTHON,
} from "../integrations/shawn-single-page.mjs";
import { createCandidateArtifactCleanupPlanner } from "../integrations/candidate-artifact-cleanup.mjs";

const execFileAsync = promisify(execFile);

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
await prepareStudioLibrary(dataRoot);
const instanceLock = new StudioInstanceLock({ dataRoot });
await instanceLock.acquire();
const pathPolicy = createPathPolicy(dataRoot);
const runtimeEvents = new RuntimeEventLog({ dataRoot });
await runtimeEvents.initialize();
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
const legacyDiscovery = new DeckDiscovery({
  decksFile,
  allowMissing: process.env.PPT_AI_LAB_TEST_MODE !== "1",
});
const discovery = new ProjectDiscovery({ legacyDiscovery, projects });
const projectPicker = new MacProjectPicker();
await discovery.probe();
const selectionProjection = new SelectionProjection({ discovery });
const singleEditTurnFinalizer = new SingleEditTurnFinalizer();
const selectorWorkspace = new SelectorWorkspace({
  discovery,
  artifactCleanupPlanner: createCandidateArtifactCleanupPlanner({
    pythonPath: (
      process.env.PPT_AI_LAB_TEST_MODE === "1" && process.env.PPT_AI_LAB_OVERVIEW_PYTHON
        ? path.resolve(process.env.PPT_AI_LAB_OVERVIEW_PYTHON)
        : DEFAULT_OVERVIEW_PYTHON
    ),
  }),
  eventLog: runtimeEvents,
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
const taskAssociations = new TaskAssociationIndex({ dataRoot });
try {
  await taskAssociations.initialize();
} catch (error) {
  taskAssociations.lastError = error;
  process.stderr.write(`Shawn PPT Studio: task conversation bindings unavailable: ${error.message}\n`);
}
const taskProjection = new TaskProjection({ discovery, conversations, associations: taskAssociations });
const studioRules = new StudioRulesStore({ dataRoot });
try {
  await studioRules.initialize();
} catch (error) {
  studioRules.lastError = error;
  process.stderr.write(`Shawn PPT Studio: long-term rules unavailable: ${error.message}\n`);
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

const monitoringRoot =
  process.env.PPT_AI_LAB_TEST_MODE === "1"
    ? path.resolve(
        process.env.PPT_AI_LAB_MONITORING_ROOT || path.join(labRoot, "fixtures", "monitoring"),
      )
    : DEFAULT_MONITORING_ROOT;
const configuredOverviewPython =
  process.env.PPT_AI_LAB_TEST_MODE === "1" && process.env.PPT_AI_LAB_OVERVIEW_PYTHON
    ? path.resolve(process.env.PPT_AI_LAB_OVERVIEW_PYTHON)
    : DEFAULT_OVERVIEW_PYTHON;
let overviewPython = null;
try {
  await execFileAsync(configuredOverviewPython, ["-c", "from PIL import Image"], {
    timeout: 10_000,
    windowsHide: true,
  });
  overviewPython = configuredOverviewPython;
} catch (error) {
  process.stderr.write(`Shawn PPT Studio: overview runtime unavailable: ${error.message}\n`);
}
const server = createLabHttpServer({
  client,
  appId: "shawn-ppt-studio",
  codeRoot: projectRoot,
  dataRoot,
  labRoot,
  pathPolicy,
  conversations,
  discovery,
  selectionProjection,
  selectorWorkspace,
  monitoringRoot,
  overviewPython,
  projects,
  projectPicker,
  exports,
  singleEditTurnFinalizer,
  taskProjection,
  studioRules,
});
const port = parsePort(process.argv.slice(2), process.env);

await new Promise((resolve, reject) => {
  server.once("error", reject);
  server.listen(port, "127.0.0.1", resolve);
});

const address = server.address();
process.stdout.write(`PPT AI Lab listening on http://127.0.0.1:${address.port}\n`);
await runtimeEvents.record("server_started", { port: address.port });

let closing = false;
async function close(reason = "unknown") {
  if (closing) return;
  closing = true;
  await runtimeEvents.record("server_shutdown_started", { reason });
  await new Promise((resolve) => {
    let settled = false;
    let forceTimer = null;
    const finish = () => {
      if (settled) return;
      settled = true;
      if (forceTimer) clearTimeout(forceTimer);
      resolve();
    };
    server.close(finish);
    forceTimer = setTimeout(() => {
      void runtimeEvents.record("server_shutdown_connections_forced", { reason });
      server.closeIdleConnections?.();
      server.closeAllConnections?.();
      finish();
    }, 1_500);
    forceTimer.unref();
  });
  try {
    await client.stop();
    await runtimeEvents.record("server_shutdown_completed", { reason });
  } finally {
    await instanceLock.release();
  }
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    await runtimeEvents.record("server_signal_received", { signal });
    await close(`signal:${signal}`);
    process.exit(0);
  });
}

process.on("uncaughtException", async (error) => {
  process.stderr.write(`PPT AI Lab uncaught exception: ${error.stack || error.message}\n`);
  await runtimeEvents.record("server_uncaught_exception", {
    error_code: error?.code || null,
    error_message: error?.message || String(error),
    error_stack: error?.stack || null,
  });
  await close("uncaught_exception");
  process.exit(1);
});

process.on("unhandledRejection", async (error) => {
  process.stderr.write(`PPT AI Lab unhandled rejection: ${error?.stack || error}\n`);
  await runtimeEvents.record("server_unhandled_rejection", {
    error_code: error?.code || null,
    error_message: error?.message || String(error),
    error_stack: error?.stack || null,
  });
  await close("unhandled_rejection");
  process.exit(1);
});
