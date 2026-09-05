import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import { beginConversationSubmission, finishConversationSubmission, captureConversationRoute, isCurrentConversationRoute } from "../../web/conversation-routing.js";

const source = await readFile(new URL("../../web/app.js", import.meta.url), "utf8");
const handler = source.slice(source.indexOf("function onConversationEvent("), source.indexOf("\nasync function submitConversation("));
function fixture() {
  const calls = [];
  const state = { deckId: "deck", activeConversationId: "chat", conversationViewEpoch: 1, activeTurnId: "turn", interrupting: true, eventSequence: 0,
    pendingConversationSubmissions: new Map(), pendingApprovals: new Map([["permission", {turn_id:"turn"}]]),
    itemViews: new Map([["item", {article:{classList:{remove(value){calls.push(["remove", value]);}}}}]]) };
  const route = beginConversationSubmission(state.pendingConversationSubmissions, captureConversationRoute(state));
  const context = vm.createContext({ state, finishConversationSubmission,
    currentConversationRoute: () => captureConversationRoute(state), conversationRouteIsCurrent: (value) => isCurrentConversationRoute(state, value),
    updateSendState() {}, toast: (value) => calls.push(["toast",value]), finishTurnProcess: (...args) => calls.push(["process",...args]),
    stopEventStream: () => calls.push(["stopStream"]), setActiveTurn: () => {state.activeTurnId = "";},
    renderApprovalCards: () => calls.push(["permissions"]), loadTasks: () => calls.push(["tasks"]),
  });
  vm.runInContext(handler,context);
  return {state, route, calls, onEvent:context.onConversationEvent};
}
test("a terminal relay failure releases send, interrupt, approvals and streaming UI while preserving content", () => {
  const {state,route,calls,onEvent}=fixture();
  onEvent({event:"error",data:{terminal:true,code:"app_server_exited",message:"连接已断开"}},route);
  assert.equal(state.activeTurnId, "");
  assert.equal(state.interrupting,false);
  assert.equal(state.pendingConversationSubmissions.size,0);
  assert.equal(state.pendingApprovals.size,0);
  assert.equal(state.itemViews.size,1);
  assert.ok(calls.some(([name])=>name === "stopStream"));
  assert.ok(calls.some(([name])=>name === "permissions"));
});
test("recoverable errors and late errors from another view do not end the active work", () => {
  const {state,route,onEvent}=fixture();
  onEvent({event:"error",data:{message:"可恢复的提示"}},route);
  assert.equal(state.activeTurnId,"turn");
  assert.equal(state.pendingApprovals.size,1);
  state.conversationViewEpoch++;
  onEvent({event:"error",data:{terminal:true,message:"旧连接断开"}},route);
  assert.equal(state.activeTurnId,"turn");
  assert.equal(state.pendingApprovals.size,1);
});
