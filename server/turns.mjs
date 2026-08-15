import path from "node:path";

import { STUDIO_APP_SERVER_TRANSPORT } from "../integrations/shawn-single-page.mjs";
import {
  IMAGEGEN_SKILL_PATH,
  SHAWN_SKILL_PATH,
} from "../integrations/skill-paths.mjs";
import { HttpError } from "./errors.mjs";

export const MODES = new Set([
  "chat",
  "outline",
  "image_generate",
  "image_edit",
  "shawn_skill_dry_run",
]);

export { IMAGEGEN_SKILL_PATH, SHAWN_SKILL_PATH } from "../integrations/skill-paths.mjs";

const USER_MESSAGE_START = "[SHAWN_PPT_STUDIO_USER_MESSAGE]";
const USER_MESSAGE_END = "[/SHAWN_PPT_STUDIO_USER_MESSAGE]";

export const STUDIO_COMMUNICATION_RULES = [
  "Treat these user-facing communication rules as global Shawn PPT Studio requirements for every project and every conversation; they are not optional preferences.",
  "Keep progress commentary to a few plain-language milestones. Do not narrate hidden reasoning, every command, routine file inspection, hash check, or other mechanical detail.",
  "In a normal successful user-facing reply, never print SHA or hash values, absolute file paths, internal deck/slide/thread/turn/run/candidate identifiers, status enums, ledger details, control-plane details, or QA bookkeeping. Use human page labels and compact clickable artifact links instead.",
  "Show technical identifiers or diagnostic details only when the user explicitly asks for them or when a failure cannot be made actionable without them; even then, provide only the minimum necessary detail.",
  "Do not repeat progress or task-state information already visible in the Studio interface. After substantial work, give a concise final answer led by the actual outcome and the next useful action, if any.",
];

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

function compactOutlineContext(deck, currentSlideUid) {
  const slides = Array.isArray(deck?.outline?.slides) ? deck.outline.slides : [];
  const current = slides.find((slide) => slide.slide_uid === currentSlideUid) || null;
  return {
    page_index: slides.map((slide) => ({
      page_id: slide.page_id,
      page_label: slide.page_label,
      slide_uid: slide.slide_uid,
      title: slide.title,
      subtitle: slide.subtitle || null,
    })),
    current_slide: current
      ? {
          page_id: current.page_id,
          page_label: current.page_label,
          slide_uid: current.slide_uid,
          title: current.title,
          subtitle: current.subtitle || null,
          markdown: current.markdown,
        }
      : null,
  };
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
    overviewPython = null,
    requestStartedAt = new Date().toISOString(),
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
  const boundOverviewPython =
    typeof overviewPython === "string" && path.isAbsolute(overviewPython)
      ? path.normalize(overviewPython)
      : null;
  if (!boundOverviewPython) {
    throw new HttpError(
      503,
      "Studio overview runtime is unavailable",
      "overview_runtime_unavailable",
    );
  }
  const candidateOutputRoots = (deck.candidate_roots || []).map((root) => path.resolve(root.path));
  const writableRoots = [
    path.resolve(dataRoot),
    outlineRoot,
    ...candidateOutputRoots,
    ...(monitoringRoot ? [path.resolve(monitoringRoot)] : []),
  ].filter((value, index, values) => values.indexOf(value) === index);
  const outlineContext = compactOutlineContext(deck, currentSlideUid);

  const prompt = [
    USER_MESSAGE_START,
    message,
    USER_MESSAGE_END,
    "You are Codex working directly inside Shawn PPT Studio. Follow normal Codex thread, turn, item, streaming, steering, interruption, and approval behavior.",
    "This conversation belongs to the entire PPT deck. The currently viewed slide is context only; it never limits the pages you may discuss or change.",
    "Respond naturally. Do not emit JSON, a proposal schema, or a host-action envelope.",
    "For a question, brainstorming request, or ambiguous request, discuss it naturally and do not make changes that were not requested.",
    "For a clear instruction to change the outline, generate images, or edit formal selected images, carry out the work inside this same turn. Do not end the turn after merely announcing that a hidden job has started.",
    ...STUDIO_COMMUNICATION_RULES,
    "For outline edits, modify the authoritative outline in place, preserve deck_uid and slide_uid identities, and do not create a second authoritative outline.",
    "If the outline is a zero-page draft, use the exact deck_uid supplied below when converting it to canonical front matter and create stable slide_uids for real pages; never replace the project deck_uid with a new one.",
    "For PPT image generation or image editing, use the supplied shawn-ppt-image skill and its canonical control planes, run state, source snapshot, ImageGen path, and existing sole Judge. Do not create another reviewer, state machine, or image concurrency layer.",
    "The supplied skill is already attached by the Studio host. For a formal Fast8 request, do not search memory or reopen the entire skill before preflight. After one short acknowledgement, the first mechanical action must build the preflight manifest and initialize the one formal run; read only the stage-gated references when their stage begins.",
    "For a formal Fast8 run, create its preflight manifest below one supplied candidate_output_root (normally <output_root>/.fast8_preflight), never in /tmp or another unlisted root. In asset_items, the first user-designated style image uses role=primary_style_reference and any additional style images use role=supporting_style_reference. style_anchor_only is an approval scope, never an asset role. Never patch a frozen preflight manifest or canonical state by hand to recover a role mismatch; stop with the exact error instead.",
    "For a new Fast8 run, never use a distinct slide identity sidecar. When building the preflight manifest, the authoritative page source may also be registered as --slide-identity-file only when it is the exact same canonical outline. When calling init_task_dir.py with that frozen preflight manifest, never pass --slide-identity-file again; init reads the optional identity binding from the manifest. This prevents one request from producing a rejected initialization and a second suffixed preflight.",
    "Pass the exact studio_request_started_at below to build_fast8_preflight_manifest.py --request-started-at. Never replace it with the time when preflight work happens.",
    "If the user explicitly requests every Fast8 candidate to use a light or dark background system, pass --tone light or --tone dark to build_fast8_preflight_manifest.py. Do not leave the default mixed A-D dark / E-H light matrix active for an all-light or all-dark request.",
    "For every formal Fast8 run, use the exact studio_overview_python supplied below as init_task_dir.py --overview-python. It is host-bound and already includes Pillow. Never search for another Python, create a virtual environment, run pip/uv/conda, or request network access to install Pillow. If this exact runtime cannot execute or import Pillow, stop with overview_runtime_unavailable before creating the formal run.",
    "The supplied imagegen skill is the image generation/editing engine. Use it only through the shawn-ppt-image workflow when producing formal PPT candidates.",
    "A generated or edited image is a new candidate. Never mark it selected and never overwrite the canonical selection merely because generation completed.",
    "The user may identify formal images by labels such as P04, P04-A, or natural language. Use only the confirmed selected image references supplied below as formal edit parents; if the target is ambiguous, ask one short question.",
    "Use official Codex approval requests for actions outside the granted workspace or other operations that genuinely require approval. Do not invent a separate product confirmation.",
    "Use concise, natural Chinese unless the user asks for another language.",
    `conversation_id: ${conversationId}`,
    `deck_uid: ${deck.outline.deck_uid}`,
    `outline_revision_id: ${deck.outline.revision_id}`,
    `authoritative_outline_path: ${deck.outline.path}`,
    `candidate_output_roots: ${JSON.stringify(candidateOutputRoots)}`,
    `monitoring_root: ${monitoringRoot ? path.resolve(monitoringRoot) : "none"}`,
    `studio_overview_python: ${boundOverviewPython}`,
    `studio_request_started_at: ${requestStartedAt}`,
    `currently_viewed_slide_uid: ${currentSlideUid || "none"}`,
    `reference_image_paths: ${JSON.stringify(validatedReferences)}`,
    `confirmed_selected_image_refs: ${JSON.stringify(confirmedSelections)}`,
    `outline_page_index: ${JSON.stringify(outlineContext.page_index)}`,
    `currently_viewed_slide: ${JSON.stringify(outlineContext.current_slide)}`,
    "The compact index and current slide above are navigation context, not a second outline. When another page or the whole deck is needed, read only the relevant portion of authoritative_outline_path. Re-hash it before any write or formal image run.",
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
      ...STUDIO_COMMUNICATION_RULES,
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
