import { createHash, randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdir, realpath, stat, writeFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { URL } from "node:url";

import { HttpError, publicError } from "./errors.mjs";
import {
  approvalResult,
  CodexInteractionRelay,
} from "./codex-interaction.mjs";
import { sanitizeForBrowser } from "./path-policy.mjs";
import { resolveConversationImage } from "./conversation-image.mjs";
import { openConversationFile } from "./conversation-file.mjs";
import { rememberedStudioRule } from "./studio-rules.mjs";
import { studioLibraryRoot } from "./studio-library.mjs";
import { classifyImageTaskRequest } from "./image-task-intent.mjs";
import { handleSelectorProjectionRequest } from "./selector-http.mjs";
import { handleSelectorWorkspaceRequest } from "./selector-workspace-http.mjs";
import {
  buildWorkspaceTurn,
  buildWorkspaceSteerInput,
  extractWorkspaceUserMessage,
  parseWorkspaceResponse,
  threadResumeParams,
  threadStartParams,
} from "./turns.mjs";

const BODY_LIMIT = 1024 * 1024;
const ATTACHMENT_LIMIT = 20 * 1024 * 1024;
const APP_ID = "shawn-ppt-studio";
const APP_VERSION = process.env.SHAWN_PPT_STUDIO_VERSION || "development";
const BUILD_KIND = process.env.SHAWN_PPT_STUDIO_BUILD_KIND || "source";
const WRITE_HEADER = "x-shawn-ppt-studio";

const CONTENT_TYPES = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".mjs", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".webp", "image/webp"],
  [".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"],
  [".pdf", "application/pdf"],
  [".zip", "application/zip"],
]);

function json(res, statusCode, value) {
  const payload = JSON.stringify(sanitizeForBrowser(value));
  res.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  res.end(payload);
}

function attachmentName(value) {
  return `attachment; filename*=UTF-8''${encodeURIComponent(value).replaceAll("'", "%27")}`;
}

async function serveExportFile(res, resolved) {
  const info = await stat(resolved.path);
  res.writeHead(200, {
    "content-type": CONTENT_TYPES.get(path.extname(resolved.path).toLowerCase()) || "application/octet-stream",
    "content-length": info.size,
    "content-disposition": attachmentName(resolved.filename),
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  createReadStream(resolved.path).pipe(res);
}

async function readJson(req) {
  if (!String(req.headers["content-type"] || "").toLowerCase().startsWith("application/json")) {
    throw new HttpError(415, "content-type must be application/json", "unsupported_media_type");
  }

  const chunks = [];
  let length = 0;
  for await (const chunk of req) {
    length += chunk.length;
    if (length > BODY_LIMIT) {
      throw new HttpError(413, "request body is too large", "body_too_large");
    }
    chunks.push(chunk);
  }

  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  } catch {
    throw new HttpError(400, "request body is not valid JSON", "invalid_json");
  }
}

async function readBytes(req, limit = ATTACHMENT_LIMIT) {
  const chunks = [];
  let length = 0;
  for await (const chunk of req) {
    length += chunk.length;
    if (length > limit) throw new HttpError(413, "attachment is too large", "attachment_too_large");
    chunks.push(chunk);
  }
  if (!length) throw new HttpError(400, "attachment is empty", "empty_attachment");
  return Buffer.concat(chunks);
}

function sanitizeAccount(account) {
  if (!account) return { authenticated: false, type: null, plan_type: null };
  return {
    authenticated: true,
    type: account.type || account.authMode || null,
    plan_type: account.planType || null,
  };
}

function sse(res, event, value) {
  if (res.destroyed || res.writableEnded) return;
  res.write(`event: ${event}\n`);
  res.write(`data: ${JSON.stringify(sanitizeForBrowser(value))}\n\n`);
}

function sseRecord(res, record) {
  if (res.destroyed || res.writableEnded) return;
  res.write(`id: ${record.sequence}\n`);
  res.write(`event: ${record.event}\n`);
  res.write(`data: ${JSON.stringify(sanitizeForBrowser(record))}\n\n`);
}

function historyContent(item) {
  if (!item || typeof item !== "object") return null;
  if (item.type === "userMessage") {
    const content = item.content || [];
    const text = content
      .filter((content) => content?.type === "text")
      .map((content) => content.text || "")
      .join("\n");
    const message = extractWorkspaceUserMessage(text) || text;
    const attachments = content
      .filter((entry) => entry?.type === "localImage" && typeof entry.path === "string")
      .map((entry) => ({ type: "local_image", path: entry.path }));
    return message ? { role: "user", text: message, attachments } : null;
  }
  if (item.type === "agentMessage" && typeof item.text === "string") {
    const structured = parseWorkspaceResponse(item.text);
    return structured
      ? { role: "assistant", text: structured.message, response: structured }
      : { role: "assistant", text: item.text, response: null };
  }
  if (item.type === "message" && item.role === "assistant" && Array.isArray(item.content)) {
    const text = item.content
      .filter((entry) => entry?.type === "output_text" && typeof entry.text === "string")
      .map((entry) => entry.text)
      .join("\n");
    return text ? { role: "assistant", text, response: null } : null;
  }
  return null;
}

function projectConversationHistory(thread) {
  return (thread?.turns || []).map((turn) => ({
    turn_id: turn.id || null,
    status: turn.status || null,
    messages: (turn.items || []).map(historyContent).filter(Boolean),
  }));
}

function requestOriginAllowed(req) {
  const origin = req.headers.origin;
  if (!origin) return true;
  try {
    const parsed = new URL(origin);
    return (
      parsed.protocol === "http:" &&
      ["127.0.0.1", "localhost", "[::1]", "::1"].includes(parsed.hostname)
    );
  } catch {
    return false;
  }
}

function enforceLoopbackRequest(req) {
  const host = String(req.headers.host || "").split(":")[0].replace(/^\[|\]$/g, "");
  if (!["127.0.0.1", "localhost", "::1"].includes(host)) {
    throw new HttpError(403, "request host is not allowed", "invalid_host");
  }
  if (!requestOriginAllowed(req)) {
    throw new HttpError(403, "request origin is not allowed", "invalid_origin");
  }
  const fetchSite = String(req.headers["sec-fetch-site"] || "").toLowerCase();
  if (fetchSite === "cross-site") {
    throw new HttpError(403, "cross-site requests are not allowed", "cross_site_request");
  }
  if (
    !["GET", "HEAD", "OPTIONS"].includes(req.method || "GET") &&
    (req.headers.origin || req.headers["sec-fetch-site"]) &&
    req.headers[WRITE_HEADER] !== "1"
  ) {
    throw new HttpError(403, `missing ${WRITE_HEADER} request header`, "missing_write_header");
  }
}

async function confirmedSelectionRefs(deck, selectionProjection) {
  if (!selectionProjection) return [];
  const refs = [];
  for (const slide of deck.outline.slides) {
    const selection = await selectionProjection.get(deck.deck_id, slide.slide_uid);
    if (selection?.status !== "selected" || selection.confirmed !== true) continue;
    const candidates = selection.selected_candidates || [];
    candidates.forEach((candidate, index) => {
      refs.push({
        display_label: candidates.length === 1
          ? slide.page_label
          : `${slide.page_label}-${String.fromCharCode(65 + index)}`,
        deck_uid: deck.outline.deck_uid,
        slide_uid: slide.slide_uid,
        candidate_id: candidate.candidate_id,
        path: candidate.path,
        file_sha256: candidate.file_sha256,
        width: candidate.width,
        height: candidate.height,
      });
    });
  }
  return refs;
}

function isArchivedThreadError(error) {
  const message = String(error?.message || "");
  return /\b(?:session|thread)\s+\S+\s+is archived\b/i.test(message)
    && /\bunarchive\b/i.test(message);
}

async function startTurnWithArchivedRecovery(client, { threadId, params, resumeParams }) {
  try {
    return await client.request("turn/start", params);
  } catch (error) {
    if (!isArchivedThreadError(error)) throw error;
    await client.request("thread/unarchive", { threadId });
    await client.request("thread/resume", resumeParams);
    return client.request("turn/start", params);
  }
}

async function streamWorkspaceTurn(req, res, context, route) {
  const requestStartedAt = new Date().toISOString();
  const body = await readJson(req);
  if (!context.client.ready) {
    throw new HttpError(503, "Codex App Server is not ready", "app_server_unavailable");
  }
  if (!context.conversations?.ready) {
    throw new HttpError(503, "conversation history is unavailable", "conversation_index_unavailable");
  }
  const rememberIntent = rememberedStudioRule(body?.message);
  if (rememberIntent && !context.studioRules?.ready) {
    throw new HttpError(503, "Studio long-term rules are unavailable", "studio_rules_unavailable");
  }
  const rememberedRule = context.studioRules?.ready
    ? await context.studioRules.rememberFromMessage(body?.message)
    : null;
  const studioRules = context.studioRules?.ready ? context.studioRules.list().rules : undefined;
  const deck = await context.discovery.readDeck(route.deckId);
  const threadId = context.conversations.threadIdFor(
    deck.outline.deck_uid,
    route.conversationId,
  );
  const resumeParams = threadResumeParams(
    context.dataRoot || context.labRoot,
    threadId,
    studioRules,
  );
  await context.client.request("thread/resume", resumeParams);
  const relay = context.codexInteraction;
  if (!relay.markStarting(threadId)) {
    throw new HttpError(409, "this conversation already has an active turn", "turn_already_active");
  }
  let params;
  let message;
  try {
    ({ params, message } = await buildWorkspaceTurn(body, {
      dataRoot: context.dataRoot || context.labRoot,
      deck,
      conversationId: route.conversationId,
      threadId,
      pathPolicy: context.pathPolicy,
      confirmedSelections: await confirmedSelectionRefs(deck, context.selectionProjection),
      monitoringRoot: context.monitoringRoot,
      overviewPython: context.overviewPython,
      requestStartedAt,
      studioRules,
    }));
    context.singleEditTurnFinalizer?.registerStarting?.(threadId, {
      transport: "studio_app_server_v1",
      deckUid: deck.outline.deck_uid,
      candidateRoots: (deck.candidate_roots || []).map((root) => root.path),
    });
    await context.taskProjection?.associations?.rememberRequest?.(
      deck.outline.deck_uid,
      requestStartedAt,
      route.conversationId,
    )?.catch(() => {});
    const imageTask = classifyImageTaskRequest({
      message: body?.message,
      retouchContext: body?.retouch_context === true,
      referenceImages: body?.reference_images,
    });
    if (imageTask) {
      await context.taskProjection?.associations?.rememberImageRequest?.(
        deck.outline.deck_uid,
        requestStartedAt,
        route.conversationId,
        {
          title: imageTask.title,
          modeHint: imageTask.mode_hint,
          slideUid: body?.current_slide_uid,
        },
      )?.catch(() => {});
    }
  } catch (error) {
    relay.clearStarting(threadId);
    context.singleEditTurnFinalizer?.clearStarting?.(threadId);
    throw error;
  }

  let ended = false;
  res.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-store",
    connection: "keep-alive",
    "x-accel-buffering": "no",
    "x-content-type-options": "nosniff",
  });
  res.flushHeaders?.();
  if (rememberedRule?.remembered) {
    sse(res, "studio_rule_saved", {
      contract_version: 1,
      added: rememberedRule.added,
      rule: rememberedRule.rule,
      rule_count: rememberedRule.rules.length,
    });
  }
  const unsubscribe = relay.subscribe({
    threadId,
    listener(record) {
      sseRecord(res, record);
      if (record.method !== "turn/completed") return;
      ended = true;
      void context.conversations.touch(deck.outline.deck_uid, route.conversationId, {
        firstMessage: message,
      }).catch(() => {});
      unsubscribe();
      res.end();
    },
  });
  res.once("close", () => {
    if (!ended) unsubscribe();
  });

  try {
    await startTurnWithArchivedRecovery(context.client, {
      threadId,
      params,
      resumeParams,
    });
  } catch (error) {
    relay.clearStarting(threadId);
    context.singleEditTurnFinalizer?.clearStarting?.(threadId);
    unsubscribe();
    sse(res, "error", {
      contract_version: 1,
      message: error.message,
      code: error.code || "turn_start_failed",
    });
    res.end();
  }
}

async function serveConversationImage(res, requestUrl, context, deckId) {
  const deck = await context.discovery.readDeck(deckId);
  const resolved = await resolveConversationImage(deck, requestUrl.searchParams.get("path"));
  res.writeHead(200, {
    "content-type": resolved.contentType,
    "content-length": resolved.size,
    "content-disposition": `inline; filename*=UTF-8''${encodeURIComponent(resolved.filename).replaceAll("'", "%27")}`,
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  createReadStream(resolved.path).pipe(res);
}

async function serveStatic(res, pathname, context) {
  const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  const webRoot = path.join(context.codeRoot || context.labRoot, "web");
  const candidate = path.resolve(webRoot, relative);
  const rel = path.relative(webRoot, candidate);
  if (rel.startsWith(`..${path.sep}`) || rel === "..") return false;

  let rootReal;
  let fileReal;
  let info;
  try {
    [rootReal, fileReal, info] = await Promise.all([realpath(webRoot), realpath(candidate), stat(candidate)]);
  } catch {
    return false;
  }
  if (!fileReal.startsWith(`${rootReal}${path.sep}`) || !info.isFile()) return false;

  res.writeHead(200, {
    "content-type": CONTENT_TYPES.get(path.extname(fileReal).toLowerCase()) || "application/octet-stream",
    "content-length": info.size,
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "content-security-policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
  });
  createReadStream(fileReal).pipe(res);
  return true;
}

export function createLabHttpServer(context) {
  if (context.client) {
    context.codexInteraction ||= new CodexInteractionRelay({
      client: context.client,
      turnObserver: context.singleEditTurnFinalizer || null,
    });
  }
  return http.createServer(async (req, res) => {
    try {
      enforceLoopbackRequest(req);
      const requestUrl = new URL(req.url, "http://127.0.0.1");

      if (req.method === "GET" && requestUrl.pathname === "/api/health") {
        json(res, 200, {
          app_id: context.appId || APP_ID,
          app_version: APP_VERSION,
          build_kind: BUILD_KIND,
          contract_version: 1,
          ok: context.client.ready,
          app_server: {
            ready: context.client.ready,
            pid: context.client.pid,
            error: context.client.lastError?.message || null,
          },
          account: sanitizeAccount(context.client.account),
          runtime: {
            data_root: context.dataRoot || context.labRoot,
            studio_library_root: studioLibraryRoot(context.dataRoot || context.labRoot),
          },
          services: {
            projects: context.projects?.health?.() || {
              ready: false,
              project_count: 0,
              error: "project registry is not configured",
            },
            conversations: context.conversations?.health?.() || {
              ready: false,
              conversation_count: 0,
              error: "conversation adapter is not configured",
            },
            discovery: context.discovery?.health?.() || {
              ready: false,
              deck_count: null,
              error: "discovery adapter is not configured",
            },
            selector_workspace: context.selectorWorkspace?.health?.() || {
              ready: false,
              refreshed_deck_count: 0,
            },
            exports: context.exports?.health?.() || {
              ready: false,
              missing: [],
              message: "export service is not configured",
            },
            tasks: context.taskProjection?.health?.() || {
              ready: false,
              task_count: 0,
              error: "task projection is not configured",
            },
            studio_rules: context.studioRules?.health?.() || {
              ready: false,
              rule_count: 0,
              error: "Studio rules are not configured",
            },
          },
        });
        return;
      }

      if (req.method === "GET" && requestUrl.pathname === "/api/studio-rules") {
        if (!context.studioRules?.ready) {
          throw new HttpError(503, "Studio long-term rules are unavailable", "studio_rules_unavailable");
        }
        json(res, 200, context.studioRules.list());
        return;
      }

      if (req.method === "PUT" && requestUrl.pathname === "/api/studio-rules") {
        if (!context.studioRules?.ready) {
          throw new HttpError(503, "Studio long-term rules are unavailable", "studio_rules_unavailable");
        }
        const body = await readJson(req);
        json(res, 200, await context.studioRules.replace(body?.rules));
        return;
      }

      if (req.method === "GET" && requestUrl.pathname === "/api/tasks") {
        if (!context.taskProjection) {
          throw new HttpError(503, "task center is unavailable", "task_center_unavailable");
        }
        json(res, 200, await context.taskProjection.list({ codexInteraction: context.codexInteraction }));
        return;
      }

      const taskInterruptMatch = requestUrl.pathname.match(/^\/api\/tasks\/([^/]+)\/interrupt$/);
      if (req.method === "POST" && taskInterruptMatch) {
        await readJson(req);
        if (!context.taskProjection) {
          throw new HttpError(503, "task center is unavailable", "task_center_unavailable");
        }
        await context.taskProjection.list({ codexInteraction: context.codexInteraction, force: true });
        const taskId = decodeURIComponent(taskInterruptMatch[1]);
        const target = context.taskProjection.interruptTarget(taskId);
        if (!target || context.codexInteraction.activeTurn(target.threadId) !== target.turnId) {
          throw new HttpError(409, "this task is no longer running", "turn_not_active");
        }
        await context.client.request("turn/interrupt", { threadId: target.threadId, turnId: target.turnId });
        json(res, 202, { contract_version: 1, task_id: taskId, interrupt_requested: true });
        return;
      }

      const approvalMatch = requestUrl.pathname.match(/^\/api\/codex\/approvals\/([^/]+)$/);
      if (req.method === "POST" && approvalMatch) {
        const requestId = decodeURIComponent(approvalMatch[1]);
        const request = context.client.serverRequest(requestId);
        if (!request) {
          throw new HttpError(404, "permission request is no longer active", "approval_request_not_found");
        }
        const body = await readJson(req);
        if (!body || !Object.hasOwn(body, "decision")) {
          throw new HttpError(400, "decision is required", "invalid_approval_decision");
        }
        let result;
        try {
          result = approvalResult(request, body.decision);
        } catch (error) {
          throw new HttpError(400, error.message, error.code || "invalid_approval_decision");
        }
        context.client.respondToServerRequest(requestId, result);
        context.codexInteraction.resolveApproval(request, body.decision);
        json(res, 200, { resolved: true, decision: body.decision });
        return;
      }

      if (req.method === "GET" && requestUrl.pathname === "/api/projects") {
        json(res, 200, await context.discovery.listDecks());
        return;
      }

      if (req.method === "POST" && requestUrl.pathname === "/api/projects/pick-folder") {
        await readJson(req);
        if (!context.projectPicker) throw new HttpError(503, "project picker is unavailable", "picker_unavailable");
        json(res, 200, await context.projectPicker.pickFolder());
        return;
      }

      if (req.method === "POST" && requestUrl.pathname === "/api/projects/pick-outline") {
        await readJson(req);
        if (!context.projectPicker) throw new HttpError(503, "project picker is unavailable", "picker_unavailable");
        json(res, 200, await context.projectPicker.pickOutline());
        return;
      }

      if (req.method === "POST" && requestUrl.pathname === "/api/projects") {
        if (!context.projects?.ready) {
          throw new HttpError(503, "project registry is unavailable", "project_registry_unavailable");
        }
        const body = await readJson(req);
        let record;
        if (body.mode === "blank") {
          record = await context.projects.createBlank({
            folderPath: body.folder_path,
            label: body.label,
          });
        } else if (body.mode === "existing") {
          const restored = await context.discovery.restoreExistingOutline(body.outline_path);
          if (restored) {
            json(res, 200, { contract_version: 1, project: restored, reused: true, restored: true });
            return;
          }
          let requestedOutline = null;
          try {
            requestedOutline = await realpath(body.outline_path);
          } catch {
            // The registry provides the user-facing not-found error below.
          }
          const existing = requestedOutline
            ? (await context.discovery.listDecks()).decks.find(
                (project) => project.outline_path === requestedOutline,
              )
            : null;
          if (existing) {
            json(res, 200, { contract_version: 1, project: existing, reused: true });
            return;
          }
          record = await context.projects.openExisting({
            outlinePath: body.outline_path,
            label: body.label,
            outputRoot: body.output_root,
          });
        } else {
          throw new HttpError(400, "mode must be blank or existing", "invalid_project_mode");
        }
        const reused = record.already_registered === true;
        json(res, reused ? 200 : 201, {
          contract_version: 1,
          project: await context.discovery.getOutline(record.deck_id),
          reused,
        });
        return;
      }

      const hideProjectMatch = requestUrl.pathname.match(/^\/api\/projects\/([^/]+)\/hide$/);
      if (req.method === "POST" && hideProjectMatch) {
        await readJson(req);
        const deckId = decodeURIComponent(hideProjectMatch[1]);
        await context.discovery.hideDeck(deckId);
        const listing = await context.discovery.listDecks();
        json(res, 200, {
          contract_version: 1,
          hidden: true,
          deck_id: deckId,
          default_deck: listing.default_deck,
          remaining_count: listing.decks.length,
        });
        return;
      }

      const conversationCollectionMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/conversations$/,
      );
      if (req.method === "GET" && conversationCollectionMatch) {
        if (!context.conversations?.ready) {
          throw new HttpError(503, "conversation history is unavailable", "conversation_index_unavailable");
        }
        const deck = await context.discovery.readDeck(
          decodeURIComponent(conversationCollectionMatch[1]),
        );
        const listing = context.conversations.list(deck.outline.deck_uid);
        const records = context.conversations.records(deck.outline.deck_uid);
        const summaries = await Promise.all(
          records.map(async (record) => {
            try {
              const result = await context.client.request("thread/read", {
                threadId: record.thread_id,
                includeTurns: false,
              });
              return [record.conversation_id, result?.thread?.preview || null];
            } catch {
              return [record.conversation_id, null];
            }
          }),
        );
        const summaryById = new Map(summaries);
        json(res, 200, {
          ...listing,
          conversations: listing.conversations.map((conversation) => ({
            ...conversation,
            summary: summaryById.get(conversation.conversation_id) || null,
          })),
        });
        return;
      }

      if (req.method === "POST" && conversationCollectionMatch) {
        if (!context.client.ready || !context.conversations?.ready) {
          throw new HttpError(503, "conversation service is unavailable", "conversation_unavailable");
        }
        const body = await readJson(req);
        const deck = await context.discovery.readDeck(
          decodeURIComponent(conversationCollectionMatch[1]),
        );
        const result = await context.client.request(
          "thread/start",
          threadStartParams(
            context.dataRoot || context.labRoot,
            context.studioRules?.ready ? context.studioRules.list().rules : undefined,
          ),
        );
        if (!result?.thread?.id) throw new Error("Codex App Server did not return a thread id");
        const conversation = await context.conversations.create({
          deckId: deck.deck_id,
          deckUid: deck.outline.deck_uid,
          threadId: result.thread.id,
          title: body.title,
        });
        await context.client.request("thread/name/set", {
          threadId: result.thread.id,
          name: `${deck.label} · ${conversation.title}`,
        }).catch(() => {});
        json(res, 201, { contract_version: 1, deck_uid: deck.outline.deck_uid, conversation });
        return;
      }

      const archivedConversationCollectionMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/conversations\/archived$/,
      );
      if (req.method === "GET" && archivedConversationCollectionMatch) {
        if (!context.conversations?.ready) {
          throw new HttpError(503, "conversation history is unavailable", "conversation_index_unavailable");
        }
        const deck = await context.discovery.readDeck(
          decodeURIComponent(archivedConversationCollectionMatch[1]),
        );
        json(res, 200, context.conversations.listArchived(deck.outline.deck_uid));
        return;
      }

      const conversationRestoreMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/conversations\/([^/]+)\/restore$/,
      );
      if (req.method === "POST" && conversationRestoreMatch) {
        await readJson(req);
        if (!context.client.ready || !context.conversations?.ready) {
          throw new HttpError(503, "conversation service is unavailable", "conversation_unavailable");
        }
        const deck = await context.discovery.readDeck(decodeURIComponent(conversationRestoreMatch[1]));
        const conversationId = decodeURIComponent(conversationRestoreMatch[2]);
        const localConversation = context.conversations.get(deck.outline.deck_uid, conversationId);
        if (!localConversation.archived_at) {
          throw new HttpError(404, "archived conversation was not found", "conversation_not_found");
        }
        const threadId = context.conversations.threadIdFor(deck.outline.deck_uid, conversationId);
        await context.client.request("thread/unarchive", { threadId });
        let conversation;
        try {
          conversation = await context.conversations.restore(deck.outline.deck_uid, conversationId);
        } catch (error) {
          await context.client.request("thread/archive", { threadId }).catch(() => {});
          throw error;
        }
        json(res, 200, { contract_version: 1, conversation });
        return;
      }

      const conversationMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/conversations\/([^/]+)$/,
      );
      if (req.method === "PATCH" && conversationMatch) {
        const body = await readJson(req);
        if (!context.client.ready || !context.conversations?.ready) {
          throw new HttpError(503, "conversation service is unavailable", "conversation_unavailable");
        }
        const deck = await context.discovery.readDeck(decodeURIComponent(conversationMatch[1]));
        const conversationId = decodeURIComponent(conversationMatch[2]);
        const localConversation = context.conversations.get(deck.outline.deck_uid, conversationId);
        if (localConversation.archived_at) {
          throw new HttpError(404, "conversation was not found", "conversation_not_found");
        }
        const threadId = context.conversations.threadIdFor(deck.outline.deck_uid, conversationId);
        const title = typeof body?.title === "string" ? body.title.trim() : "";
        if (!title) throw new HttpError(400, "title is required", "invalid_conversation_request");
        await context.client.request("thread/name/set", {
          threadId,
          name: `${deck.label} · ${title.slice(0, 80)}`,
        });
        const conversation = await context.conversations.rename(
          deck.outline.deck_uid,
          conversationId,
          title,
        );
        json(res, 200, { contract_version: 1, conversation });
        return;
      }

      if (req.method === "DELETE" && conversationMatch) {
        if (!context.client.ready || !context.conversations?.ready) {
          throw new HttpError(503, "conversation service is unavailable", "conversation_unavailable");
        }
        const deck = await context.discovery.readDeck(decodeURIComponent(conversationMatch[1]));
        const conversationId = decodeURIComponent(conversationMatch[2]);
        const localConversation = context.conversations.get(deck.outline.deck_uid, conversationId);
        if (localConversation.archived_at) {
          throw new HttpError(404, "conversation was not found", "conversation_not_found");
        }
        const threadId = context.conversations.threadIdFor(deck.outline.deck_uid, conversationId);
        if (context.codexInteraction.activeTurn(threadId)) {
          throw new HttpError(409, "running conversations cannot be deleted", "conversation_active");
        }
        await context.client.request("thread/archive", { threadId });
        let archived;
        try {
          archived = await context.conversations.archive(deck.outline.deck_uid, conversationId);
        } catch (error) {
          await context.client.request("thread/unarchive", { threadId }).catch(() => {});
          throw error;
        }
        json(res, 200, {
          contract_version: 1,
          archived: true,
          conversation: archived.conversation,
          active_conversation_id: archived.active_conversation_id,
        });
        return;
      }

      if (req.method === "GET" && conversationMatch) {
        if (!context.client.ready || !context.conversations?.ready) {
          throw new HttpError(503, "conversation service is unavailable", "conversation_unavailable");
        }
        const deck = await context.discovery.readDeck(decodeURIComponent(conversationMatch[1]));
        const conversationId = decodeURIComponent(conversationMatch[2]);
        const conversation = context.conversations.get(deck.outline.deck_uid, conversationId);
        const threadId = context.conversations.threadIdFor(deck.outline.deck_uid, conversationId);
        const result = await context.client.request("thread/read", {
          threadId,
          includeTurns: true,
        });
        context.codexInteraction.observeThreadSnapshot?.(result?.thread);
        const storedActiveTurn = [...(result?.thread?.turns || [])]
          .reverse()
          .find((turn) => turn?.status === "inProgress")?.id || null;
        const activeTurnId = context.codexInteraction.activeTurn(threadId) || storedActiveTurn;
        json(res, 200, {
          contract_version: 1,
          deck_uid: deck.outline.deck_uid,
          conversation,
          thread: result?.thread || null,
          active_turn: activeTurnId
            ? { turn_id: activeTurnId, status: "inProgress" }
            : null,
          turns: result?.thread?.turns || [],
        });
        return;
      }

      const conversationOpenMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/conversations\/([^/]+)\/open$/,
      );
      if (req.method === "POST" && conversationOpenMatch) {
        if (!context.client.ready || !context.conversations?.ready) {
          throw new HttpError(503, "conversation service is unavailable", "conversation_unavailable");
        }
        const deck = await context.discovery.readDeck(decodeURIComponent(conversationOpenMatch[1]));
        const conversationId = decodeURIComponent(conversationOpenMatch[2]);
        const threadId = context.conversations.threadIdFor(deck.outline.deck_uid, conversationId);
        await context.client.request(
          "thread/resume",
          threadResumeParams(
            context.dataRoot || context.labRoot,
            threadId,
            context.studioRules?.ready ? context.studioRules.list().rules : undefined,
          ),
        );
        const conversation = await context.conversations.activate(
          deck.outline.deck_uid,
          conversationId,
        );
        json(res, 200, { contract_version: 1, deck_uid: deck.outline.deck_uid, conversation });
        return;
      }

      const conversationMessageMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/conversations\/([^/]+)\/messages$/,
      );
      if (req.method === "POST" && conversationMessageMatch) {
        await streamWorkspaceTurn(req, res, context, {
          deckId: decodeURIComponent(conversationMessageMatch[1]),
          conversationId: decodeURIComponent(conversationMessageMatch[2]),
        });
        return;
      }

      const conversationSteerMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/conversations\/([^/]+)\/steer$/,
      );
      if (req.method === "POST" && conversationSteerMatch) {
        const body = await readJson(req);
        const deck = await context.discovery.readDeck(decodeURIComponent(conversationSteerMatch[1]));
        const conversationId = decodeURIComponent(conversationSteerMatch[2]);
        const threadId = context.conversations.threadIdFor(deck.outline.deck_uid, conversationId);
        const expectedTurnId = typeof body.expected_turn_id === "string" ? body.expected_turn_id : "";
        if (!expectedTurnId || context.codexInteraction.activeTurn(threadId) !== expectedTurnId) {
          throw new HttpError(409, "the expected turn is no longer active", "turn_not_active");
        }
        const rememberIntent = rememberedStudioRule(body?.message);
        if (rememberIntent && !context.studioRules?.ready) {
          throw new HttpError(503, "Studio long-term rules are unavailable", "studio_rules_unavailable");
        }
        const rememberedRule = context.studioRules?.ready
          ? await context.studioRules.rememberFromMessage(body?.message)
          : null;
        const { input } = await buildWorkspaceSteerInput(body, {
          pathPolicy: context.pathPolicy,
          studioRules: context.studioRules?.ready ? context.studioRules.list().rules : undefined,
        });
        let result;
        try {
          result = await context.client.request("turn/steer", {
            threadId,
            input,
            expectedTurnId,
          });
        } catch (error) {
          throw new HttpError(409, error.message, "turn_not_active");
        }
        json(res, 202, {
          contract_version: 1,
          thread_id: threadId,
          turn_id: result?.turnId || expectedTurnId,
          accepted: true,
          studio_rule: rememberedRule?.remembered
            ? { added: rememberedRule.added, rule: rememberedRule.rule }
            : null,
        });
        return;
      }

      const conversationInterruptMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/conversations\/([^/]+)\/interrupt$/,
      );
      if (req.method === "POST" && conversationInterruptMatch) {
        const body = await readJson(req);
        const deck = await context.discovery.readDeck(decodeURIComponent(conversationInterruptMatch[1]));
        const conversationId = decodeURIComponent(conversationInterruptMatch[2]);
        const threadId = context.conversations.threadIdFor(deck.outline.deck_uid, conversationId);
        const turnId = typeof body.turn_id === "string" ? body.turn_id : "";
        if (!turnId || context.codexInteraction.activeTurn(threadId) !== turnId) {
          throw new HttpError(409, "the requested turn is no longer active", "turn_not_active");
        }
        await context.client.request("turn/interrupt", { threadId, turnId });
        json(res, 202, {
          contract_version: 1,
          thread_id: threadId,
          turn_id: turnId,
          interrupt_requested: true,
        });
        return;
      }

      const conversationEventsMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/conversations\/([^/]+)\/events$/,
      );
      if (req.method === "GET" && conversationEventsMatch) {
        const deck = await context.discovery.readDeck(decodeURIComponent(conversationEventsMatch[1]));
        const conversationId = decodeURIComponent(conversationEventsMatch[2]);
        const threadId = context.conversations.threadIdFor(deck.outline.deck_uid, conversationId);
        const turnId = requestUrl.searchParams.get("turn_id");
        const after = Number(requestUrl.searchParams.get("after") || 0);
        if (!turnId || !Number.isSafeInteger(after) || after < 0) {
          throw new HttpError(400, "turn_id and a valid after cursor are required", "invalid_event_cursor");
        }
        const records = context.codexInteraction.records(threadId, turnId, after);
        if (records === null) {
          throw new HttpError(404, "turn event stream is unknown", "turn_events_not_found");
        }
        res.writeHead(200, {
          "content-type": "text/event-stream; charset=utf-8",
          "cache-control": "no-store",
          connection: "keep-alive",
          "x-accel-buffering": "no",
        });
        res.flushHeaders?.();
        records.forEach((record) => sseRecord(res, record));
        if (records.some((record) => record.method === "turn/completed")) {
          res.end();
          return;
        }
        const unsubscribe = context.codexInteraction.subscribe({
          threadId,
          turnId,
          listener(record) {
            sseRecord(res, record);
            if (record.method === "turn/completed") {
              unsubscribe();
              res.end();
            }
          },
        });
        res.once("close", unsubscribe);
        return;
      }

      const exportReadinessMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/export-readiness$/,
      );
      if (req.method === "GET" && exportReadinessMatch) {
        if (!context.exports) {
          throw new HttpError(503, "导出服务暂时不可用。", "export_unavailable");
        }
        const { publicReadiness } = await import("./export-service.mjs");
        json(
          res,
          200,
          publicReadiness(await context.exports.readiness(decodeURIComponent(exportReadinessMatch[1]))),
        );
        return;
      }

      const exportCollectionMatch = requestUrl.pathname.match(/^\/api\/decks\/([^/]+)\/exports$/);
      if (req.method === "POST" && exportCollectionMatch) {
        if (!context.exports) {
          throw new HttpError(503, "导出服务暂时不可用。", "export_unavailable");
        }
        const result = await context.exports.create(
          decodeURIComponent(exportCollectionMatch[1]),
          await readJson(req),
        );
        json(res, 201, result);
        return;
      }

      const exportFileMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/exports\/([^/]+)\/files\/(pptx|pdf|images_zip|manifest|qa)$/,
      );
      if (req.method === "GET" && exportFileMatch) {
        if (!context.exports) {
          throw new HttpError(503, "导出服务暂时不可用。", "export_unavailable");
        }
        await serveExportFile(
          res,
          await context.exports.resolveFile(
            decodeURIComponent(exportFileMatch[1]),
            decodeURIComponent(exportFileMatch[2]),
            exportFileMatch[3],
          ),
        );
        return;
      }

      const exportOpenMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/exports\/([^/]+)\/open-folder$/,
      );
      if (req.method === "POST" && exportOpenMatch) {
        if (!context.exports) {
          throw new HttpError(503, "导出服务暂时不可用。", "export_unavailable");
        }
        await readJson(req);
        json(
          res,
          200,
          await context.exports.showInFinder(
            decodeURIComponent(exportOpenMatch[1]),
            decodeURIComponent(exportOpenMatch[2]),
          ),
        );
        return;
      }

      const outlineMatch = requestUrl.pathname.match(/^\/api\/decks\/([^/]+)\/outline$/);
      if (req.method === "GET" && outlineMatch) {
        if (!context.discovery) {
          throw new HttpError(503, "deck discovery is unavailable", "deck_discovery_unavailable");
        }
        json(res, 200, await context.discovery.getOutline(decodeURIComponent(outlineMatch[1])));
        return;
      }

      if (req.method === "POST" && requestUrl.pathname === "/api/attachments") {
        const mediaType = String(req.headers["content-type"] || "").split(";", 1)[0].toLowerCase();
        const extension = new Map([
          ["image/png", ".png"],
          ["image/jpeg", ".jpg"],
          ["image/webp", ".webp"],
        ]).get(mediaType);
        if (!extension) {
          throw new HttpError(415, "attachment must be PNG, JPEG, or WebP", "unsupported_attachment");
        }
        const bytes = await readBytes(req);
        const root = path.join(studioLibraryRoot(context.dataRoot || context.labRoot), "attachments");
        await mkdir(root, { recursive: true });
        const attachmentPath = path.join(root, `${randomUUID()}${extension}`);
        await writeFile(attachmentPath, bytes, { flag: "wx", mode: 0o600 });
        json(res, 201, {
          contract_version: 1,
          attachment: {
            path: attachmentPath,
            media_type: mediaType,
            size: bytes.length,
            sha256: createHash("sha256").update(bytes).digest("hex"),
            created_at: new Date().toISOString(),
          },
        });
        return;
      }

      const slideMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/slides\/([^/]+)$/,
      );
      if (req.method === "GET" && slideMatch) {
        if (!context.discovery) {
          throw new HttpError(503, "deck discovery is unavailable", "deck_discovery_unavailable");
        }
        json(
          res,
          200,
          await context.discovery.getSlide(
            decodeURIComponent(slideMatch[1]),
            decodeURIComponent(slideMatch[2]),
          ),
        );
        return;
      }

      const conversationImageMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/conversation-image$/,
      );
      if (req.method === "GET" && conversationImageMatch) {
        await serveConversationImage(
          res,
          requestUrl,
          context,
          decodeURIComponent(conversationImageMatch[1]),
        );
        return;
      }

      const conversationFileOpenMatch = requestUrl.pathname.match(
        /^\/api\/decks\/([^/]+)\/conversation-file\/open$/,
      );
      if (req.method === "POST" && conversationFileOpenMatch) {
        const body = await readJson(req);
        const deck = await context.discovery.readDeck(
          decodeURIComponent(conversationFileOpenMatch[1]),
        );
        const opener = context.conversationFileOpener || openConversationFile;
        json(res, 200, await opener(deck, body?.path));
        return;
      }

      if (
        context.selectorWorkspace &&
        (await handleSelectorWorkspaceRequest(
          req,
          res,
          requestUrl,
          context.selectorWorkspace,
          readJson,
        ))
      ) {
        return;
      }

      if (
        context.selectionProjection &&
        (await handleSelectorProjectionRequest(
          req,
          res,
          requestUrl,
          context.selectionProjection,
        ))
      ) {
        return;
      }

      if (req.method === "GET" && !requestUrl.pathname.startsWith("/api/")) {
        if (await serveStatic(res, requestUrl.pathname, context)) return;
      }

      throw new HttpError(404, "route not found", "not_found");
    } catch (error) {
      if (res.headersSent) {
        if (!res.writableEnded) res.end();
        return;
      }
      if (error?.code === "export_not_ready") {
        json(res, 409, {
          error: "export_not_ready",
          message: error.message,
          missing_pages: error.missingPages || [],
        });
        return;
      }
      const failure = publicError(error);
      json(res, failure.statusCode, failure.body);
    }
  });
}
