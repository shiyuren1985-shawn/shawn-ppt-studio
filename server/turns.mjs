import { homedir } from "node:os";
import path from "node:path";

import { STUDIO_APP_SERVER_TRANSPORT } from "../integrations/shawn-single-page.mjs";
import { HttpError } from "./errors.mjs";

export const MODES = new Set([
  "chat",
  "outline",
  "image_generate",
  "image_edit",
  "shawn_skill_dry_run",
]);

const CODEX_HOME = path.resolve(process.env.CODEX_HOME || path.join(homedir(), ".codex"));
export const IMAGEGEN_SKILL_PATH = path.join(CODEX_HOME, "skills", ".system", "imagegen", "SKILL.md");
export const SHAWN_SKILL_PATH = path.join(CODEX_HOME, "skills", "Shawn-PPT-image", "SKILL.md");

const USER_MESSAGE_START = "[SHAWN_PPT_STUDIO_USER_MESSAGE]";
const USER_MESSAGE_END = "[/SHAWN_PPT_STUDIO_USER_MESSAGE]";

function outlineSchema(deckUid, slideUid) {
  return {
    type: "object",
    properties: {
      action: { type: "string", const: "outline_patch" },
      deck_uid: { type: "string", const: deckUid },
      slide_uid: { type: "string", const: slideUid },
      summary: { type: "string" },
      before_markdown: { type: "string" },
      replacement_markdown: { type: "string" },
      rationale: { type: "array", items: { type: "string" }, minItems: 1 },
    },
    required: [
      "action",
      "deck_uid",
      "slide_uid",
      "summary",
      "before_markdown",
      "replacement_markdown",
      "rationale",
    ],
    additionalProperties: false,
  };
}

function requireString(value, name) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new HttpError(400, `${name} is required`, "invalid_turn_request");
  }
  return value;
}

function cleanReferences(references) {
  if (references === undefined) return [];
  if (!Array.isArray(references)) {
    throw new HttpError(400, "reference_images must be an array", "invalid_reference_images");
  }
  return references.map((item) => {
    const value = typeof item === "string" ? item : item?.path;
    if (typeof value !== "string" || !path.isAbsolute(value) || /^data:/i.test(value)) {
      throw new HttpError(
        400,
        "each reference image must use a local absolute path",
        "invalid_reference_image",
      );
    }
    return path.resolve(value);
  });
}

export function extractWorkspaceUserMessage(value) {
  if (typeof value !== "string") return null;
  const start = value.indexOf(USER_MESSAGE_START);
  const end = value.indexOf(USER_MESSAGE_END);
  if (start < 0 || end <= start) return null;
  return value.slice(start + USER_MESSAGE_START.length, end).trim();
}

export function parseWorkspaceResponse(value) {
  if (typeof value !== "string") return null;
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch {
    return null;
  }
  if (
    !parsed ||
    !["chat", "outline_proposal", "image_generation_proposal", "retouch_proposal"].includes(
      parsed.response_type,
    ) ||
    typeof parsed.message !== "string"
  ) {
    return null;
  }
  return parsed;
}

export async function buildWorkspaceTurn(
  body,
  {
    dataRoot,
    deck,
    conversationId,
    threadId,
    pathPolicy,
    confirmedSelections = [],
    monitoringRoot = null,
  },
) {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new HttpError(400, "JSON body must be an object", "invalid_turn_request");
  }
  const message = requireString(body.message, "message");
  const currentSlideUid =
    typeof body.current_slide_uid === "string" && body.current_slide_uid.trim()
      ? body.current_slide_uid.trim()
      : null;
  if (
    currentSlideUid &&
    !deck.outline.slides.some((slide) => slide.slide_uid === currentSlideUid)
  ) {
    throw new HttpError(404, "current slide was not found", "slide_not_found");
  }

  const referencePaths = cleanReferences(body.reference_images);
  const validatedReferences = [];
  for (const referencePath of referencePaths) {
    validatedReferences.push(await pathPolicy.requireReferenceImage(referencePath));
  }
  const outlineRoot = path.dirname(deck.outline.path);
  const writableRoots = [
    path.resolve(dataRoot),
    outlineRoot,
    ...(deck.candidate_roots || []).map((root) => path.resolve(root.path)),
    ...(monitoringRoot ? [path.resolve(monitoringRoot)] : []),
  ].filter((value, index, values) => values.indexOf(value) === index);

  const prompt = [
    USER_MESSAGE_START,
    message,
    USER_MESSAGE_END,
    "You are Codex working directly inside Shawn PPT Studio. Follow normal Codex thread, turn, item, streaming, steering, interruption, and approval behavior.",
    "This conversation belongs to the entire PPT deck. The currently viewed slide is context only; it never limits the pages you may discuss or change.",
    "Respond naturally. Do not emit JSON, a proposal schema, or a host-action envelope.",
    "For a question, brainstorming request, or ambiguous request, discuss it naturally and do not make changes that were not requested.",
    "For a clear instruction to change the outline, generate images, or edit formal selected images, carry out the work inside this same turn. Do not end the turn after merely announcing that a hidden job has started.",
    "Give concise commentary updates while doing substantial work, then a clear final answer based only on what actually completed.",
    "For outline edits, modify the authoritative outline in place, preserve deck_uid and slide_uid identities, and do not create a second authoritative outline.",
    "If the outline is a zero-page draft, use the exact deck_uid supplied below when converting it to canonical front matter and create stable slide_uids for real pages; never replace the project deck_uid with a new one.",
    "For PPT image generation or image editing, use the supplied shawn-ppt-image skill and its canonical control planes, run state, source snapshot, ImageGen path, and existing sole Judge. Do not create another reviewer, state machine, or image concurrency layer.",
    "The supplied imagegen skill is the image generation/editing engine. Use it only through the shawn-ppt-image workflow when producing formal PPT candidates.",
    "A generated or edited image is a new candidate. Never mark it selected and never overwrite the canonical selection merely because generation completed.",
    "The user may identify formal images by labels such as P04, P04-A, or natural language. Use only the confirmed selected image references supplied below as formal edit parents; if the target is ambiguous, ask one short question.",
    "Use official Codex approval requests for actions outside the granted workspace or other operations that genuinely require approval. Do not invent a separate product confirmation.",
    "Use concise, natural Chinese unless the user asks for another language.",
    `conversation_id: ${conversationId}`,
    `deck_uid: ${deck.outline.deck_uid}`,
    `outline_revision_id: ${deck.outline.revision_id}`,
    `currently_viewed_slide_uid: ${currentSlideUid || "none"}`,
    `reference_image_paths: ${JSON.stringify(validatedReferences)}`,
    `confirmed_selected_image_refs: ${JSON.stringify(confirmedSelections)}`,
    "Authoritative outline begins:",
    deck.outline.text,
    "Authoritative outline ends.",
  ].join("\n");

  return {
    message,
    params: {
      threadId,
      cwd: outlineRoot,
      approvalPolicy: "on-request",
      sandboxPolicy: {
        type: "workspaceWrite",
        writableRoots,
        readOnlyAccess: { type: "fullAccess" },
        networkAccess: false,
      },
      additionalContext: {
        shawn_ppt_studio_transport: {
          kind: "application",
          value: `transport=${STUDIO_APP_SERVER_TRANSPORT}`,
        },
      },
      input: [
        { type: "text", text: prompt },
        ...validatedReferences.map((referencePath) => ({
          type: "localImage",
          path: referencePath,
        })),
        { type: "skill", name: "shawn-ppt-image", path: SHAWN_SKILL_PATH },
        { type: "skill", name: "imagegen", path: IMAGEGEN_SKILL_PATH },
      ],
    },
  };
}

export async function buildWorkspaceSteerInput(body, { pathPolicy }) {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new HttpError(400, "JSON body must be an object", "invalid_turn_request");
  }
  const message = requireString(body.message, "message");
  const referencePaths = cleanReferences(body.reference_images);
  const validatedReferences = [];
  for (const referencePath of referencePaths) {
    validatedReferences.push(await pathPolicy.requireReferenceImage(referencePath));
  }
  return {
    message,
    input: [
      { type: "text", text: message },
      ...validatedReferences.map((referencePath) => ({ type: "localImage", path: referencePath })),
    ],
  };
}

export async function buildTurn(body, { labRoot, imageRoot, pathPolicy }) {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new HttpError(400, "JSON body must be an object", "invalid_turn_request");
  }

  const threadId = requireString(body.thread_id, "thread_id");
  const message = requireString(body.message, "message");
  if (!MODES.has(body.mode)) {
    throw new HttpError(400, "mode is invalid", "invalid_turn_mode");
  }

  const scope = body.scope && typeof body.scope === "object" ? body.scope : {};
  const common = {
    threadId,
    cwd: labRoot,
    approvalPolicy: "never",
    sandboxPolicy: {
      type: "workspaceWrite",
      writableRoots: [labRoot],
      networkAccess: body.mode === "image_generate" || body.mode === "image_edit",
    },
  };

  if (body.mode === "chat") {
    return { params: { ...common, input: [{ type: "text", text: message }] } };
  }

  if (body.mode === "outline") {
    const outline = typeof scope.outline_markdown === "string" ? scope.outline_markdown : "";
    const deckUid =
      typeof scope.deck_uid === "string" && scope.deck_uid.trim() ? scope.deck_uid.trim() : "LAB_DECK";
    const slideUid =
      typeof scope.slide_uid === "string" && scope.slide_uid.trim()
        ? scope.slide_uid.trim()
        : "LAB_SLIDE_001";
    const prompt = [
      "This is a Shawn PPT Studio outline proposal exercise.",
      "Propose a patch only. Do not read or write any file and do not edit an authoritative outline.",
      "The final response must be only the JSON object required by the supplied output schema.",
      `deck_uid: ${deckUid}`,
      `slide_uid: ${slideUid}`,
      `revision_id: ${scope.revision_id || "unrecorded"}`,
      "Current complete page table row begins:",
      outline,
      "Current complete page table row ends.",
      `User request: ${message}`,
      "Copy the supplied row exactly into before_markdown.",
      "replacement_markdown must be one complete single-line Markdown table row with the same page id and column count.",
      "A later explicit CAS endpoint, not this AI turn, is the only component allowed to apply the proposal.",
    ].join("\n");

    return {
      params: {
        ...common,
        input: [{ type: "text", text: prompt }],
        outputSchema: outlineSchema(deckUid, slideUid),
      },
    };
  }

  if (body.mode === "image_generate") {
    const prompt = [
      "$imagegen Create exactly one prototype PPT slide image for this isolated lab.",
      "Required canvas: 16:9 landscape.",
      "Use ImageGen once and wait for its completed imageGeneration item with savedPath.",
      `The bridge will safely import that savedPath into ${imageRoot}. Do not run shell commands, resize, copy, move, or rename the generated image yourself.`,
      "Do not access or modify EPC, SI, monitoring, selections, production run state, or any production image directory.",
      `Creative request: ${message}`,
    ].join("\n");
    return {
      params: {
        ...common,
        input: [
          { type: "text", text: prompt },
          { type: "skill", name: "imagegen", path: IMAGEGEN_SKILL_PATH },
        ],
      },
    };
  }

  if (body.mode === "image_edit") {
    const sourcePath = await pathPolicy.requireImageFile(body.image_path);
    const prompt = [
      "$imagegen Edit the supplied local prototype image exactly once.",
      "Preserve a 16:9 landscape canvas and never overwrite the source image.",
      "Use ImageGen once and wait for its completed imageGeneration item with savedPath.",
      `The bridge will safely import that savedPath into ${imageRoot}. Do not run shell commands, resize, copy, move, or rename the edited image yourself.`,
      "Do not access or modify EPC, SI, monitoring, selections, production run state, or any production image directory.",
      `Requested visible change: ${message}`,
    ].join("\n");
    return {
      params: {
        ...common,
        input: [
          { type: "text", text: prompt },
          { type: "localImage", path: sourcePath },
          { type: "skill", name: "imagegen", path: IMAGEGEN_SKILL_PATH },
        ],
      },
    };
  }

  const prompt = [
    "$shawn-ppt-image Perform a read-only routing dry run for the isolated PPT AI Lab.",
    "Read the supplied skill instructions and explain which existing route and canonical control-plane entrypoints would apply to the request.",
    "Absolutely do not call ImageGen, do not spawn subagents, do not create a project or run directory, and do not write or modify any file.",
    "Do not inspect or modify EPC, SI, monitoring, selections, production run state, or production images.",
    "Return only a concise routing report including route, inputs that would be required, control-plane commands that would be used, and explicit no-write/no-image confirmation.",
    `Hypothetical request: ${message}`,
  ].join("\n");
  return {
    params: {
      ...common,
      sandboxPolicy: {
        type: "readOnly",
        networkAccess: false,
      },
      input: [
        { type: "text", text: prompt },
        { type: "skill", name: "shawn-ppt-image", path: SHAWN_SKILL_PATH },
      ],
    },
  };
}

export function threadStartParams(labRoot) {
  return {
    cwd: path.resolve(labRoot),
    approvalPolicy: "on-request",
    sandbox: "workspace-write",
    ephemeral: false,
    serviceName: "shawn_ppt_studio",
    developerInstructions: [
      "You are the AI collaborator inside Shawn PPT Studio.",
      "Each conversation belongs to an entire PPT deck; a currently viewed slide is context only and never an authority boundary.",
      "Follow normal Codex interaction: natural messages, real streamed work items, commentary while working, and a final answer after the requested work actually finishes.",
      "Do not return a structured proposal or hand work off to an invisible secondary conversation.",
      "Questions, hypotheticals, and brainstorming remain conversation only. Clear instructions are carried out directly in the active turn with no extra Studio confirmation.",
      "For formal PPT image work, use the supplied shawn-ppt-image and imagegen skills and preserve their canonical state, source snapshot, sole Judge, and selection boundaries.",
      "Use official Codex permission requests when access outside the configured workspace is genuinely needed.",
    ].join(" "),
  };
}

export function threadResumeParams(labRoot, threadId) {
  return {
    threadId,
    cwd: path.resolve(labRoot),
    approvalPolicy: "on-request",
    sandbox: "workspace-write",
    developerInstructions: threadStartParams(labRoot).developerInstructions,
  };
}
