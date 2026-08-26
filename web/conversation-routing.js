export function conversationRouteKey(deckId, conversationId) {
  return `${String(deckId || "")}\u0000${String(conversationId || "")}`;
}

export function captureConversationRoute(state) {
  return {
    deckId: String(state?.deckId || ""),
    conversationId: String(state?.activeConversationId || ""),
    epoch: Number(state?.conversationViewEpoch || 0),
  };
}

export function isCurrentConversationRoute(state, route) {
  return Boolean(route)
    && String(state?.deckId || "") === route.deckId
    && String(state?.activeConversationId || "") === route.conversationId
    && Number(state?.conversationViewEpoch || 0) === route.epoch;
}

export function beginConversationSubmission(pending, route) {
  const key = conversationRouteKey(route?.deckId, route?.conversationId);
  if (!route?.deckId || !route?.conversationId || pending.has(key)) return null;
  const token = {};
  pending.set(key, token);
  return { ...route, submissionKey: key, submissionToken: token };
}

export function finishConversationSubmission(pending, route) {
  if (!route?.submissionKey || pending.get(route.submissionKey) !== route.submissionToken) return false;
  pending.delete(route.submissionKey);
  return true;
}

export function isConversationSubmitting(pending, deckId, conversationId) {
  return pending.has(conversationRouteKey(deckId, conversationId));
}
