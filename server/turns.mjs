import path from "node:path";

import { STUDIO_APP_SERVER_TRANSPORT } from "../integrations/shawn-single-page.mjs";
import {
  IMAGEGEN_SKILL_PATH,
  SHAWN_SKILL_PATH,
} from "../integrations/skill-paths.mjs";
import { HttpError } from "./errors.mjs";
import { DEFAULT_STUDIO_RULES } from "./studio-rules.mjs";

export { IMAGEGEN_SKILL_PATH, SHAWN_SKILL_PATH } from "../integrations/skill-paths.mjs";

const USER_MESSAGE_START = "[SHAWN_PPT_STUDIO_USER_MESSAGE]";
const USER_MESSAGE_END = "[/SHAWN_PPT_STUDIO_USER_MESSAGE]";

export const STUDIO_MODEL = "gpt-5.6-sol";
export const STUDIO_REASONING_EFFORT = "medium";

const STUDIO_IMAGE_REPAIR_RULE = "When the canonical Judge requests a repair, continue the existing Skill run and its targeted repair path; do not repeat Directors or completed pages. Start a new run only for a genuinely new user request or changed frozen source.";

export const STUDIO_COMMUNICATION_RULES = [
  "Treat these user-facing communication rules as global Shawn PPT Studio requirements for every project and every conversation; they are not optional preferences.",
  "Keep progress commentary to a few plain-language milestones. Do not narrate hidden reasoning, every command, routine file inspection, hash check, or other mechanical detail.",
  "Do not repeat progress or task-state information already visible in the Studio interface. After substantial work, give a concise final answer led by the actual outcome and the next useful action, if any.",
];

export function studioUserRuleLines(rules = []) {
  const normalized = Array.isArray(rules)
    ? rules
        .filter((rule) => typeof rule === "string")
        .map((rule) => rule.replace(/\s+/g, " ").trim())
        .filter(Boolean)
    : [];
  if (!normalized.length) return [];
  return [
    "The following editable Studio long-term rules apply to every project and every conversation. Treat them as persistent user requirements:",
    ...normalized.map((rule, index) => `${index + 1}. ${rule}`),
  ];
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
    editCandidate = null,
    monitoringRoot = null,
    overviewPython = null,
    requestStartedAt = new Date().toISOString(),
    studioRules = DEFAULT_STUDIO_RULES,
  },
) {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new HttpError(400, "JSON body must be an object", "invalid_turn_request");
  }
  const message = requireString(body.message, "message");
  const requestedSlideUid = editCandidate?.slide_uid || (
    typeof body.current_slide_uid === "string" && body.current_slide_uid.trim()
      ? body.current_slide_uid.trim()
      : null
  );
  const currentSlideUid = deck.outline.slides.some((slide) => slide.slide_uid === requestedSlideUid)
    ? requestedSlideUid : null;
  const viewedPageRemoved = Boolean(requestedSlideUid && !currentSlideUid);
  if (viewedPageRemoved && body.retouch_context === true) {
    throw new HttpError(409, "当前修图页面已从大纲移除，请重新选择要修改的页面。", "slide_not_found");
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
  const candidateOutputRoots = (deck.candidate_roots || []).map((root) => path.resolve(root.path));
  const outlineContext = compactOutlineContext(deck, currentSlideUid);
  const projectGenerationSources = Array.isArray(deck.generation_sources)
    ? deck.generation_sources
        .filter((source) =>
          source?.role === "global_chrome_contract" &&
          source?.scope === "deck" &&
          typeof source?.path === "string" &&
          path.isAbsolute(source.path))
        .map((source) => ({
          role: source.role,
          scope: source.scope,
          path: path.resolve(source.path),
        }))
    : [];

  const prompt = [
    USER_MESSAGE_START,
    message,
    USER_MESSAGE_END,
    "You are Codex working directly inside Shawn PPT Studio. Follow normal Codex thread, turn, item, streaming, steering, interruption, and approval behavior.",
    "This conversation belongs to the entire PPT deck. The currently viewed slide is context only; it never limits the pages you may discuss or change.",
    ...(viewedPageRemoved ? ["The previously viewed page has been removed from the current outline. No current page is selected; do not substitute another page by its former number. Follow explicitly named targets in the user message using the current outline; ask briefly if the request only says this page or otherwise has no clear target."] : []),
    "Respond naturally. Do not emit JSON, a proposal schema, or a host-action envelope.",
    "For a question, brainstorming request, or ambiguous request, discuss it naturally and do not make changes that were not requested.",
    "For a clear instruction to change the outline, generate images, or edit formal selected images, carry out the work inside this same turn. Do not end the turn after merely announcing that a hidden job has started.",
    ...STUDIO_COMMUNICATION_RULES,
    ...studioUserRuleLines(studioRules),
    "For outline edits, modify the authoritative outline in place, preserve deck_uid and slide_uid identities, and do not create a second authoritative outline.",
    "If the outline is a zero-page draft, use the exact deck_uid supplied below when converting it to canonical front matter; never replace the project deck_uid with a new one. In that front matter, slide_uids must be a page-to-UID mapping such as `slide_uids:` followed by `  P01: stable_slide_uid`, never a YAML list. The body must be a Markdown table whose first column is `页码`, with one `| P01 | ... |` data row per real page; use the standard seven columns `页码｜客户钩子／页面标题｜核心命题｜信息密度／上屏层级｜页面必讲内容｜页面说明／资产引用｜视觉表达目标／用户硬约束` unless the authoritative outline already requires additional structured columns. After writing, re-read the file and verify that the slide_uids mapping count equals the page table row count and both are greater than zero; do not report success when they differ or when Studio would still see zero pages.",
    "For PPT image work, use the attached shawn-ppt-image Skill's stage-gated control plane and sole Judge. Do not add a reviewer, state machine, or concurrency layer.",
    STUDIO_IMAGE_REPAIR_RULE,
    "For every image route, register each supplied project_generation_source before freezing. Pass a supplied global_chrome_contract as the exact deck supporting source (--supporting-source <path>::deck); if none is supplied, do not invent a title system.",
    "For Fast8, use the attached Skill's stage-gated instructions. Enumerate only mandatory assets for the target page before freezing; the first state-mutating command must build the preflight manifest under a candidate_output_root and initialize one run. Use the canonical outline for slide identity, not a sidecar; do not pass --slide-identity-file again to init_task_dir.py. Pass studio_request_started_at, the user's explicit --tone when given, and the supplied studio_overview_python. Never hand-patch a frozen manifest or state.",
    ...(!boundOverviewPython ? ["Studio image overview runtime is unavailable. Continue ordinary conversation and outline editing normally. If formal image generation is requested, report overview_runtime_unavailable before creating a formal run; do not install dependencies or invent a runtime path."] : []),
    "For Fast8, use the exact studio_overview_python as init_task_dir.py --overview-python; do not install or search for another runtime. If it cannot run or import Pillow, report overview_runtime_unavailable before initialization.",
    "A generated or edited image is a new candidate. Never mark it selected and never overwrite the canonical selection merely because generation completed.",
    "The user may identify formal images by labels such as P04, P04-A, or natural language. Use confirmed selected image references as formal edit parents; if the target is ambiguous, ask one short question. An edit_source_candidate_ref supplied below is an exact candidate the user clicked in the selector and is also an authorized edit parent even when not selected. Use that exact file as the parent, not a different selected image or a style-only reference. Return the edit as a new candidate on the same slide; never auto-select it or overwrite the parent.",
    "Use official Codex approval requests for actions outside the granted workspace or other operations that genuinely require approval. Do not invent a separate product confirmation.",
    "Use concise, natural Chinese unless the user asks for another language.",
    `conversation_id: ${conversationId}`,
    `deck_uid: ${deck.outline.deck_uid}`,
    `outline_revision_id: ${deck.outline.revision_id}`,
    `authoritative_outline_path: ${deck.outline.path}`,
    `candidate_output_roots: ${JSON.stringify(candidateOutputRoots)}`,
    `monitoring_root: ${monitoringRoot ? path.resolve(monitoringRoot) : "none"}`,
    `studio_overview_python: ${boundOverviewPython || "unavailable"}`,
    `studio_request_started_at: ${requestStartedAt}`,
    `shawn_ppt_image_skill_path: ${SHAWN_SKILL_PATH}`,
    `imagegen_skill_path: ${IMAGEGEN_SKILL_PATH}`,
    `currently_viewed_slide_uid: ${currentSlideUid || "none"}`,
    `reference_image_paths: ${JSON.stringify(validatedReferences)}`,
    `project_generation_sources: ${JSON.stringify(projectGenerationSources)}`,
    `confirmed_selected_image_refs: ${JSON.stringify(confirmedSelections)}`,
    `edit_source_candidate_ref: ${JSON.stringify(editCandidate)}`,
    `outline_page_index: ${JSON.stringify(outlineContext.page_index)}`,
    `currently_viewed_slide: ${JSON.stringify(outlineContext.current_slide)}`,
    "The compact index and current slide above are navigation context, not a second outline. When another page or the whole deck is needed, read only the relevant portion of authoritative_outline_path. Re-hash it before any write or formal image run.",
  ].join("\n");

  return {
    message,
    params: {
      threadId,
      cwd: outlineRoot,
      model: STUDIO_MODEL,
      effort: STUDIO_REASONING_EFFORT,
      approvalPolicy: "never",
      sandboxPolicy: { type: "dangerFullAccess" },
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
        ...(editCandidate ? [{ type: "localImage", path: editCandidate.path }] : []),
        { type: "skill", name: "shawn-ppt-image", path: SHAWN_SKILL_PATH },
        { type: "skill", name: "imagegen", path: IMAGEGEN_SKILL_PATH },
      ],
    },
  };
}

export async function buildWorkspaceSteerInput(body, { pathPolicy, studioRules = DEFAULT_STUDIO_RULES, editCandidate = null }) {
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
      {
        type: "text",
        text: [
          USER_MESSAGE_START,
          message,
          USER_MESSAGE_END,
          ...studioUserRuleLines(studioRules),
          ...(editCandidate ? [
            `The user clicked this exact selector candidate as the edit parent: ${JSON.stringify(editCandidate)}. Use this file, even if unselected. Return a new candidate on the same slide; do not overwrite or auto-select either image.`,
          ] : []),
        ].join("\n"),
      },
      ...validatedReferences.map((referencePath) => ({ type: "localImage", path: referencePath })),
      ...(editCandidate ? [{ type: "localImage", path: editCandidate.path }] : []),
    ],
  };
}

export function threadStartParams(labRoot, studioRules = DEFAULT_STUDIO_RULES) {
  return {
    model: STUDIO_MODEL,
    config: { model_reasoning_effort: STUDIO_REASONING_EFFORT, "sandbox_workspace_write.network_access": true },
    cwd: path.resolve(labRoot),
    approvalPolicy: "never",
    sandbox: "danger-full-access",
    ephemeral: false,
    serviceName: "shawn_ppt_studio",
    developerInstructions: [
      "You are the AI collaborator inside Shawn PPT Studio.",
      "Each conversation belongs to an entire PPT deck; a currently viewed slide is context only and never an authority boundary.",
      "Follow normal Codex interaction: natural messages, real streamed work items, commentary while working, and a final answer after the requested work actually finishes.",
      ...STUDIO_COMMUNICATION_RULES,
      ...studioUserRuleLines(studioRules),
      "Do not return a structured proposal or hand work off to an invisible secondary conversation.",
      "Questions, hypotheticals, and brainstorming remain conversation only. Clear instructions are carried out directly in the active turn with no extra Studio confirmation.",
      "For formal PPT image work, use the supplied shawn-ppt-image and imagegen skills and preserve their canonical state, source snapshot, sole Judge, and selection boundaries.",
      STUDIO_IMAGE_REPAIR_RULE,
      "The user has enabled full execution access for Studio: ordinary file, command, and network operations do not require permission prompts. This does not expand the requested task or authorize unrelated destructive actions.",
    ].join("\n"),
  };
}

export function threadResumeParams(labRoot, threadId, studioRules = DEFAULT_STUDIO_RULES) {
  return {
    model: STUDIO_MODEL,
    config: { model_reasoning_effort: STUDIO_REASONING_EFFORT, "sandbox_workspace_write.network_access": true },
    threadId,
    cwd: path.resolve(labRoot),
    approvalPolicy: "never",
    sandbox: "danger-full-access",
    developerInstructions: threadStartParams(labRoot, studioRules).developerInstructions,
  };
}
