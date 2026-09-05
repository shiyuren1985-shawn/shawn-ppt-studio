import { conversationRouteKey } from "./conversation-routing.js";

function draftKey(route) {
  return route?.deckId && route?.conversationId
    ? conversationRouteKey(route.deckId, route.conversationId)
    : null;
}

function copyDraft(draft) {
  return {
    text: String(draft?.text || ""),
    attachments: (draft?.attachments || []).map((attachment) => ({ ...attachment })),
  };
}

// Draft identity follows the conversation, not its current view epoch or slide.
// Keep this transient: attachment paths and unsent requests are not persisted.
export function createConversationDraftStore() {
  const drafts = new Map();
  const uploads = new Map();

  function read(route) {
    return copyDraft(drafts.get(draftKey(route)));
  }

  function save(route, draft) {
    const key = draftKey(route);
    if (!key) return;
    const copy = copyDraft(draft);
    if (copy.text || copy.attachments.length) drafts.set(key, copy);
    else drafts.delete(key);
  }

  return {
    read,
    save,
    clear(route) {
      const key = draftKey(route);
      if (key) drafts.delete(key);
    },
    beginUpload(route) {
      const key = draftKey(route);
      if (!key) return null;
      const token = {};
      uploads.set(token, key);
      return token;
    },
    completeUpload(token, attachments = []) {
      const key = uploads.get(token);
      if (!key) return false;
      uploads.delete(token);
      const draft = copyDraft(drafts.get(key));
      draft.attachments.push(...attachments.filter(Boolean).map((attachment) => ({ ...attachment })));
      if (draft.text || draft.attachments.length) drafts.set(key, draft);
      return true;
    },
    hasPendingUploads(route) {
      const key = draftKey(route);
      return Boolean(key) && [...uploads.values()].includes(key);
    },
  };
}
