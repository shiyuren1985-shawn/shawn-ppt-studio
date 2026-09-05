import assert from "node:assert/strict";
import test from "node:test";

import { parseOutlineText } from "../../server/discovery.mjs";

function parse(text) {
  const bytes = Buffer.from(text);
  return parseOutlineText({
    text,
    bytes,
    outlinePath: "/tmp/studio-outline-contract.md",
    info: { mtimeMs: 0, size: bytes.length },
  });
}

test("a YAML list of slide UIDs is rejected instead of silently becoming zero pages", () => {
  assert.throws(
    () => parse(`---
deck_uid: STUDIO_LIST_TEST
slide_uids:
  - P01_UID
  - P02_UID
---

## P01 第一页

内容
`),
    (error) => error?.code === "outline_slide_uids_not_mapping",
  );
});

test("page headings without a page-to-UID mapping are rejected instead of silently becoming zero pages", () => {
  assert.throws(
    () => parse(`---
deck_uid: STUDIO_HEADING_TEST
slide_uids:
---

## P01 第一页

内容
`),
    (error) => error?.code === "outline_page_structure_unrecognized",
  );
});

test("an intentional zero-page outline remains valid", () => {
  const outline = parse(`---
deck_uid: STUDIO_EMPTY_TEST
slide_uids:
---

# 新的 PPT
`);
  assert.equal(outline.slides.length, 0);
  assert.deepEqual(outline.slide_uids, {});
});
