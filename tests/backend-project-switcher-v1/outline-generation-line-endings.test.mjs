import assert from "node:assert/strict";
import test from "node:test";

import { parseOutlineText } from "../../server/discovery.mjs";
import { parseOutlineIdentity } from "../../integrations/shawn-single-page.mjs";

test("a CRLF outline accepted by Studio keeps its identity when preparing image generation", () => {
  const text = [
    "---", "slide_identity_required: true", "deck_uid: DECK", "slide_uids:", "  P1: SLIDE", "---",
    "| 页码 | 标题 |", "| --- | --- |", "| P1 | 示例 |", "",
  ].join("\r\n");
  const outline = parseOutlineText({ text, bytes: Buffer.from(text), outlinePath: "/tmp/outline.md", info: { mtimeMs: 0, size: Buffer.byteLength(text) } });
  assert.equal(outline.slides.length, 1);
  assert.equal(text.slice(...outline.slides[0].span), "| P1 | 示例 |\r\n", "editing spans must still refer to the original CRLF bytes' character offsets");
  assert.deepEqual(parseOutlineIdentity(text), { deck_uid: outline.deck_uid, slide_uids: { P1: outline.slides[0].slide_uid } });
});
