import { HttpError } from "./errors.mjs";

function suffixFor(index) {
  let value = index + 1;
  let suffix = "";
  while (value > 0) {
    value -= 1;
    suffix = String.fromCharCode(65 + (value % 26)) + suffix;
    value = Math.floor(value / 26);
  }
  return suffix;
}

function baseLabel(slide) {
  return slide?.page_label || slide?.page_id || slide?.slide_uid;
}

export function retouchContextRequested(body) {
  if (Object.hasOwn(body || {}, "retouch_context") && typeof body.retouch_context !== "boolean") {
    throw new HttpError(400, "retouch_context must be a boolean", "invalid_retouch_context");
  }
  return body?.retouch_context === true;
}

export function labelConfirmedSelection(deckUid, slide, selection) {
  if (selection?.status !== "selected" || selection?.confirmed !== true) return [];
  const candidates = Array.isArray(selection.selected_candidates)
    ? selection.selected_candidates
    : [];
  const page = baseLabel(slide);
  if (!page || candidates.length === 0) return [];
  return candidates.map((candidate, index) => ({
    display_label: candidates.length === 1 ? page : `${page}-${suffixFor(index)}`,
    deck_uid: deckUid,
    slide_uid: slide.slide_uid,
    candidate_id: candidate.candidate_id,
  }));
}

export async function collectAvailableRetouchTargets({ deck, selectionProjection }) {
  if (!selectionProjection) {
    throw new HttpError(503, "selected images are unavailable", "selection_projection_unavailable");
  }
  const targets = [];
  for (const slide of deck.outline.slides) {
    const selection = await selectionProjection.get(deck.deck_id, slide.slide_uid);
    targets.push(...labelConfirmedSelection(deck.outline.deck_uid, slide, selection));
  }
  return targets;
}

export async function resolveLegacyRetouchTargets({
  deck,
  selectedCandidates,
  selectionProjection,
}) {
  if (!Array.isArray(selectedCandidates)) {
    throw new HttpError(400, "selected_candidates must be an array", "invalid_selected_candidates");
  }
  if (!selectionProjection) {
    throw new HttpError(503, "selected images are unavailable", "selection_projection_unavailable");
  }
  const slides = new Map(deck.outline.slides.map((slide) => [slide.slide_uid, slide]));
  const labelsBySlide = new Map();
  const resolved = [];
  for (const target of selectedCandidates) {
    if (
      !target ||
      target.deck_uid !== deck.outline.deck_uid ||
      typeof target.slide_uid !== "string" ||
      typeof target.candidate_id !== "string" ||
      !slides.has(target.slide_uid)
    ) {
      throw new HttpError(400, "selected candidate target is invalid", "invalid_selected_candidate");
    }
    if (!labelsBySlide.has(target.slide_uid)) {
      const selection = await selectionProjection.get(deck.deck_id, target.slide_uid);
      labelsBySlide.set(
        target.slide_uid,
        labelConfirmedSelection(deck.outline.deck_uid, slides.get(target.slide_uid), selection),
      );
    }
    const match = labelsBySlide
      .get(target.slide_uid)
      .find((candidate) => candidate.candidate_id === target.candidate_id);
    if (!match) {
      throw new HttpError(
        409,
        "selected candidate is no longer confirmed",
        "selected_candidate_not_confirmed",
      );
    }
    resolved.push(match);
  }
  return resolved;
}

function emptyImageGeneration() {
  return {
    scope_summary: "",
    slide_uids: [],
    prompt_summary: "",
    reference_paths: [],
    estimated_pages: 0,
  };
}

function clarification(message) {
  return {
    response_type: "chat",
    message,
    outline_changes: [],
    image_generation: emptyImageGeneration(),
    retouch: { targets: [], instruction: "", summary: "" },
  };
}

export function constrainRetouchResponse(response, { availableTargets, retouchContext }) {
  if (!retouchContext || response?.response_type !== "retouch_proposal") return response;
  if (!availableTargets.length) {
    return clarification("这套 PPT 目前没有可以修改的正式图片。请先完成选稿。");
  }
  const canonical = new Map(
    availableTargets.map((target) => [
      `${target.deck_uid}\u0000${target.slide_uid}\u0000${target.candidate_id}`,
      target,
    ]),
  );
  const requested = Array.isArray(response.retouch?.targets) ? response.retouch.targets : [];
  const targets = [];
  const seen = new Set();
  for (const target of requested) {
    const key = `${target?.deck_uid || ""}\u0000${target?.slide_uid || ""}\u0000${target?.candidate_id || ""}`;
    const match = canonical.get(key);
    if (!match) {
      return clarification("我还不能确定你指的是哪张正式图片。请使用图片编号，例如 P04 或 P04-A。");
    }
    if (!seen.has(key)) targets.push(match);
    seen.add(key);
  }
  if (!targets.length) {
    return clarification("请告诉我要修改哪张正式图片，例如“这一页”或“P04-A”。");
  }
  return {
    ...response,
    retouch: {
      ...response.retouch,
      targets,
    },
  };
}
