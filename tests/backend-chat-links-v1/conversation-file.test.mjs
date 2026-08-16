import assert from "node:assert/strict";
import { mkdir, mkdtemp, realpath, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  openConversationFile,
  resolveConversationFile,
} from "../../server/conversation-file.mjs";

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "shawn-ppt-conversation-file-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const projectRoot = path.join(root, "project");
  const outsideRoot = path.join(root, "outside");
  await Promise.all([mkdir(projectRoot), mkdir(outsideRoot)]);
  const outlinePath = path.join(projectRoot, "outline.md");
  const outsidePath = path.join(outsideRoot, "private.md");
  await Promise.all([
    writeFile(outlinePath, "# Outline\n"),
    writeFile(outsidePath, "# Outside\n"),
  ]);
  const outlineReal = await realpath(outlinePath);
  return {
    deck: {
      project_root: projectRoot,
      outline: { path: outlinePath },
      candidate_roots: [{ path: projectRoot }],
    },
    projectRoot,
    outlinePath,
    outlineReal,
    outsidePath,
  };
}

test("conversation file links resolve only inside the current PPT", async (t) => {
  const { deck, projectRoot, outlinePath, outlineReal, outsidePath } = await fixture(t);
  assert.deepEqual(await resolveConversationFile(deck, `${outlinePath}:17`), {
    path: outlineReal,
    kind: "file",
  });
  assert.deepEqual(await resolveConversationFile(deck, `${outlinePath}#L17`), {
    path: outlineReal,
    kind: "file",
  });
  await assert.rejects(
    resolveConversationFile(deck, outsidePath),
    (error) => error?.code === "conversation_file_outside_project",
  );

  const linkedOutside = path.join(projectRoot, "linked.md");
  await symlink(outsidePath, linkedOutside);
  await assert.rejects(
    resolveConversationFile(deck, linkedOutside),
    (error) => error?.code === "conversation_file_outside_project",
  );
});

test("opening a conversation file passes one validated path to macOS open", async (t) => {
  const { deck, outlinePath, outlineReal } = await fixture(t);
  const calls = [];
  const result = await openConversationFile(deck, outlinePath, {
    platform: "darwin",
    run: async (...args) => calls.push(args),
  });
  assert.deepEqual(result, { opened: true, kind: "file" });
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/usr/bin/open");
  assert.deepEqual(calls[0][1], [outlineReal]);
});
