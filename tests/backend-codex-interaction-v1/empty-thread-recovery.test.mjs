import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { ConversationIndex } from "../../server/conversations.mjs";
import { resumeStudioConversation } from "../../server/http-server.mjs";

test("unused thread lost across restart recovers once and preserves conversation identity", async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-empty-thread-"));
  t.after(() => rm(root, {recursive:true,force:true}));
  const index = new ConversationIndex({dataRoot:root});
  await index.initialize();
  const conv = await index.create({deckId:"deck",deckUid:"deck",threadId:"old"});
  await index.activate("deck",conv.conversation_id);
  let starts = 0;
  const context = {dataRoot:root,conversations:index,client:{async request(method,params){
    if(method === "thread/resume" && params.threadId === "old") throw new Error("no rollout found for thread id old");
    if(method === "thread/start") { starts++;return {thread:{id:"new",turns:[]}}; }
    return {thread:{id:params.threadId,turns:[]}};
  }}};
  await Promise.all([resumeStudioConversation(context,"deck",conv.conversation_id),resumeStudioConversation(context,"deck",conv.conversation_id)]);
  assert.equal(starts,1);
  assert.equal(index.threadIdFor("deck",conv.conversation_id),"new");
  const reopened = new ConversationIndex({dataRoot:root});await reopened.initialize();
  assert.equal(reopened.threadIdFor("deck",conv.conversation_id),"new");
  await index.touch("deck",conv.conversation_id,{firstMessage:"actual user message"});
  context.client.request = async()=>{throw new Error("no rollout found for thread id new")};
  await assert.rejects(resumeStudioConversation(context,"deck",conv.conversation_id),/no rollout/);
  assert.equal(index.threadIdFor("deck",conv.conversation_id),"new");
});
