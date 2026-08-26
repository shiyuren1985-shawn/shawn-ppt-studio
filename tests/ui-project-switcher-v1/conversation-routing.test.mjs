import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  beginConversationSubmission,
  captureConversationRoute,
  finishConversationSubmission,
  isConversationSubmitting,
  isCurrentConversationRoute,
} from "../../web/conversation-routing.js";

test("a late stream from an earlier conversation view cannot write after switching away and back", () => {
  const state = { deckId: "deck", activeConversationId: "conversation-a", conversationViewEpoch: 1 };
  const original = captureConversationRoute(state);
  assert.equal(isCurrentConversationRoute(state, original), true);

  state.activeConversationId = "conversation-b";
  state.conversationViewEpoch += 1;
  assert.equal(isCurrentConversationRoute(state, original), false);

  state.activeConversationId = "conversation-a";
  state.conversationViewEpoch += 1;
  assert.equal(isCurrentConversationRoute(state, original), false);
});

test("pending send state is isolated by deck and conversation", () => {
  const pending = new Map();
  const first = beginConversationSubmission(pending, {
    deckId: "deck",
    conversationId: "conversation-a",
    epoch: 1,
  });
  const second = beginConversationSubmission(pending, {
    deckId: "deck",
    conversationId: "conversation-b",
    epoch: 2,
  });

  assert.ok(first);
  assert.ok(second);
  assert.equal(isConversationSubmitting(pending, "deck", "conversation-a"), true);
  assert.equal(isConversationSubmitting(pending, "deck", "conversation-b"), true);
  assert.equal(beginConversationSubmission(pending, first), null);

  assert.equal(finishConversationSubmission(pending, first), true);
  assert.equal(isConversationSubmitting(pending, "deck", "conversation-a"), false);
  assert.equal(isConversationSubmitting(pending, "deck", "conversation-b"), true);
  assert.equal(finishConversationSubmission(pending, first), false);
  assert.equal(finishConversationSubmission(pending, second), true);
});

test("Studio routes both live and resumed events through the captured conversation", async () => {
  const app = await readFile(new URL("../../web/app.js", import.meta.url), "utf8");
  assert.match(app, /\(event\) => onConversationEvent\(event, route\)/);
  assert.match(app, /\(next\) => onConversationEvent\(next, route\)/);
  assert.match(app, /if \(!conversationRouteIsCurrent\(route\)\) return;/);
  assert.match(app, /loadConversationHistory\(conversationId, requestedRoute = currentConversationRoute\(\)\)/);
  assert.doesNotMatch(app, /state\.submitting/);
});
