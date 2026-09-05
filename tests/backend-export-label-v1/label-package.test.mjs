import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  preserveOfficeLabelMetadata,
  PUBLIC_LABEL_ID,
  verifyPreservedPublicLabel,
} from "../../server/export-office-label.mjs";
import {
  buildPptx,
  DEFAULT_EXPORT_RUNTIME,
  runProcess,
  verifyPptxRender,
  writeJson,
} from "../../server/export-runtime.mjs";

const ROOT = path.resolve(".");
const BASELINE = path.join(ROOT, "assets", "Public_Label_Template.pptx");
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAABAAAAAJCAIAAAC0SDtlAAAAGElEQVR4nGP8z0AaYCJRPcOoBmIAyaEEAMeRAREzvAXuAAAAAElFTkSuQmCC",
  "base64",
);

test("artifact-tool two-page image deck preserves the complete Public custom-properties package part", async (t) => {
  const work = await mkdtemp(path.join(os.tmpdir(), "studio-label-package-"));
  t.after(() => rm(work, { recursive: true, force: true }));
  const imagePath = path.join(work, "page.png");
  await writeFile(imagePath, PNG);
  const manifestPath = path.join(work, "assembly.json");
  const pptxPath = path.join(work, "two-page-public.pptx");
  await writeJson(manifestPath, {
    slide_size: { width: 1280, height: 720 },
    slides: [
      { source_path: imagePath, page_label: "P01", slide_uid: "label-smoke-1", variant_label: null },
      { source_path: imagePath, page_label: "P02", slide_uid: "label-smoke-2", variant_label: null },
    ],
  });
  await buildPptx({
    manifestPath,
    outputPath: pptxPath,
    integrationPath: path.join(ROOT, "integrations", "export-image-deck.mjs"),
  });
  const evidence = await preserveOfficeLabelMetadata({
    pptxPath,
    sourcePptx: BASELINE,
    pythonPath: DEFAULT_EXPORT_RUNTIME.python,
    expectedLabelId: PUBLIC_LABEL_ID,
  });
  assert.equal(evidence.id, PUBLIC_LABEL_ID);
  assert.equal(evidence.name, "Public");
  assert.equal(evidence.package_part_preserved, true);
  assert.equal(evidence.source_custom_xml_sha256, evidence.target_custom_xml_sha256);
  assert.equal(evidence.powerpoint_ui_verified, false);
  assert.equal(verifyPreservedPublicLabel({ metadata: evidence }).verified, true);
  assert.equal(verifyPreservedPublicLabel({ metadata: evidence }).name, "Public");

  const packageProbe = await runProcess(DEFAULT_EXPORT_RUNTIME.python, ["-c", String.raw`
import hashlib,json,sys,zipfile
from xml.etree import ElementTree as ET
P='http://schemas.openxmlformats.org/presentationml/2006/main'
def custom(path):
  with zipfile.ZipFile(path) as z: return z.read('docProps/custom.xml')
with zipfile.ZipFile(sys.argv[1]) as z:
  slides=sorted(name for name in z.namelist() if name.startswith('ppt/slides/slide') and name.endswith('.xml'))
  pictures=[len(ET.fromstring(z.read(name)).findall('.//{%s}pic' % P)) for name in slides]
  corrupt=z.testzip()
print(json.dumps({
  'slides':len(slides),
  'pictures':pictures,
  'corrupt':corrupt,
  'same_custom_part':custom(sys.argv[1])==custom(sys.argv[2]),
  'custom_sha256':hashlib.sha256(custom(sys.argv[1])).hexdigest(),
}))
`, pptxPath, BASELINE]);
  assert.deepEqual(JSON.parse(packageProbe.stdout), {
    slides: 2,
    pictures: [1, 1],
    corrupt: null,
    same_custom_part: true,
    custom_sha256: evidence.source_custom_xml_sha256,
  });

  const render = await verifyPptxRender({
    pptxPath,
    expectedPages: 2,
    qaRoot: path.join(work, "render"),
  });
  assert.deepEqual(render, { page_count: 2, rendered_page_count: 2 });
});

test("label package preservation fails closed for the wrong expected label", async (t) => {
  const work = await mkdtemp(path.join(os.tmpdir(), "studio-label-reject-"));
  t.after(() => rm(work, { recursive: true, force: true }));
  const source = path.join(work, "copy.pptx");
  await (await import("node:fs/promises")).copyFile(BASELINE, source);
  await assert.rejects(
    preserveOfficeLabelMetadata({
      pptxPath: source,
      sourcePptx: BASELINE,
      pythonPath: DEFAULT_EXPORT_RUNTIME.python,
      expectedLabelId: "00000000-0000-0000-0000-000000000000",
    }),
    (error) => error.code === "office_label_failed" && /required company label/.test(error.message),
  );
});
