import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
const source = await readFile(new URL("../../web/app.js", import.meta.url), "utf8");
const handler = source.slice(source.indexOf("async function createConversation("), source.indexOf("\nfunction closeConversationDrawerIfOpen("));
function deferred() { let resolve; const promise=new Promise(r=>{resolve=r;}); return {promise,resolve}; }
test("a slow new conversation from project A cannot block or replace project B", async()=>{
  const a=deferred(), b=deferred(); const started=[];
  const state={deckId:"a",activeConversationId:"",creatingConversations:new Set()};
  const el={"drawer-new-conversation":{disabled:false}};
  const context=vm.createContext({state,el,currentDeck:()=>({deck_id:state.deckId}),
    api:{createConversation(id){started.push(id);return id==="a"?a.promise:b.promise;},getConversations:async(id)=>({conversations:[{conversation_id:`chat-${id}`} ]})},
    normalizeConversations:value=>value,advanceConversationView(){},stopEventStream(){},setActiveTurn(){},renderConversationList(){},renderMessages(){},closeConversationDrawerIfOpen(){},toast(){},updateSendState(){},
  });
  vm.runInContext(handler,context);
  const first=context.createConversation();
  state.deckId="b";
  const second=context.createConversation();
  assert.deepEqual(started,["a","b"]);
  b.resolve({conversation:{conversation_id:"chat-b"}}); await second;
  assert.equal(state.activeConversationId,"chat-b");
  a.resolve({conversation:{conversation_id:"chat-a"}}); await first;
  assert.equal(state.deckId,"b");
  assert.equal(state.activeConversationId,"chat-b");
  assert.equal(state.conversations[0].conversation_id,"chat-b");
  assert.equal(state.creatingConversations.size,0);
  assert.equal(el["drawer-new-conversation"].disabled,false);
});
