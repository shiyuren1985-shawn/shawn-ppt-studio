import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { resolveConversationImage } from "../../server/conversation-image.mjs";

test("conversation images resolve only below the current PPT output root", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-chat-image-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const outside = path.join(root, "outside.png");
  await mkdir(path.join(output, "run", "overview"), { recursive: true });
  const image = path.join(output, "run", "overview", "ABCDEFGH_2x4.png");
  await writeFile(image, Buffer.from("png"));
  await writeFile(outside, Buffer.from("outside"));
  const deck = { output_root: output, candidate_roots: [{ id: "output", path: output }] };

  const resolved = await resolveConversationImage(deck, image);
  assert.equal(resolved.filename, "ABCDEFGH_2x4.png");
  assert.equal(resolved.contentType, "image/png");

  await assert.rejects(() => resolveConversationImage(deck, outside), { code: "conversation_image_outside_project" });
  const escaped = path.join(output, "escaped.png");
  await symlink(outside, escaped);
  await assert.rejects(() => resolveConversationImage(deck, escaped), { code: "conversation_image_outside_project" });
});
