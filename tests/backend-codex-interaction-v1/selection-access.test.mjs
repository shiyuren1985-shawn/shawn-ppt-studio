import test from "node:test";
import assert from "node:assert/strict";
import { selectionContextForTurn } from "../../server/http-server.mjs";

const deck = { deck_id: "deck", outline: { slides: [{ slide_uid: "one" }] } };
for (const code of ["EPERM", "EACCES"]) {
  const projection = { get: async () => { throw Object.assign(new Error("scandir"), { code }); } };
  test(`${code}: optional selection scan cannot block a new image request`, async () => {
    assert.deepEqual(await selectionContextForTurn(deck, projection, { message: "第7页重新做一版" }), { refs: [], unavailable: true });
  });
  test(`${code}: retouch reports unavailable source without substituting it`, async () => {
    await assert.rejects(selectionContextForTurn(deck, projection, { retouch_context: true }), { code: "selected_image_access_denied" });
  });
}
test("selection context does not conceal unrelated corruption", async () => {
  await assert.rejects(selectionContextForTurn(deck, { get: async () => { throw new Error("corrupt"); } }, {}), /corrupt/);
});
test("readable empty selection is distinct from unavailable selection", async () => {
  assert.deepEqual(await selectionContextForTurn(deck, { get: async () => null }, {}), { refs: [], unavailable: false });
});
