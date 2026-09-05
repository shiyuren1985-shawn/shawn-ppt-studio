import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  buildPptx,
  DEFAULT_EXPORT_RUNTIME,
  openFolderDetached,
  runProcess,
  writeJson,
} from "../../server/export-runtime.mjs";

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAABAAAAAJCAIAAAC0SDtlAAAAGElEQVR4nGP8z0AaYCJRPcOoBmIAyaEEAMeRAREzvAXuAAAAAElFTkSuQmCC",
  "base64",
);

test("the production PPTX assembler is an artifact-tool ES module and creates one image per slide", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "studio-artifact-pptx-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const imagePath = path.join(root, "page.png");
  const manifestPath = path.join(root, "assembly.json");
  const pptxPath = path.join(root, "deck.pptx");
  await writeFile(imagePath, PNG);
  await writeJson(manifestPath, {
    slide_size: { width: 1280, height: 720 },
    slides: [
      { source_path: imagePath, page_label: "P01", slide_uid: "one", variant_label: null },
      { source_path: imagePath, page_label: "P02", slide_uid: "two", variant_label: null },
    ],
  });
  const integrationPath = path.resolve("integrations/export-image-deck.mjs");
  const source = await readFile(integrationPath, "utf8");
  assert.match(source, /@oai\/artifact-tool|SHAWN_PPT_ARTIFACT_TOOL_ENTRY/);
  assert.doesNotMatch(source, /python-pptx|pptxgenjs/i);
  await buildPptx({ manifestPath, outputPath: pptxPath, integrationPath });

  const probe = await runProcess(DEFAULT_EXPORT_RUNTIME.python, ["-c", String.raw`
import json, sys, zipfile
from xml.etree import ElementTree as ET
with zipfile.ZipFile(sys.argv[1]) as z:
    slides=sorted(name for name in z.namelist() if name.startswith('ppt/slides/slide') and name.endswith('.xml'))
    pics=[]
    for name in slides:
        root=ET.fromstring(z.read(name))
        pics.append(len(root.findall('.//{http://schemas.openxmlformats.org/presentationml/2006/main}pic')))
    print(json.dumps({'slides':len(slides),'pictures':pics,'corrupt':z.testzip()}))
`, pptxPath]);
  const result = JSON.parse(probe.stdout);
  assert.deepEqual(result, { slides: 2, pictures: [1, 1], corrupt: null });
});

test("opening an export folder returns after launch instead of waiting for Finder to exit", async () => {
  const startedAt = Date.now();
  await openFolderDetached("/tmp", { ...DEFAULT_EXPORT_RUNTIME, open: "/usr/bin/true" });
  assert.ok(Date.now() - startedAt < 1_000);
});
