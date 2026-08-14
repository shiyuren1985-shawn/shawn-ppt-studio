#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

function contentType(filePath) {
  const extension = path.extname(filePath).toLowerCase();
  if (extension === ".png") return "image/png";
  if (extension === ".jpg" || extension === ".jpeg") return "image/jpeg";
  if (extension === ".webp") return "image/webp";
  throw new Error(`Unsupported slide image type: ${extension || "unknown"}`);
}

async function main() {
  const [manifestPath, outputPath] = process.argv.slice(2);
  if (!manifestPath || !outputPath) {
    throw new Error("usage: export-image-deck.mjs <assembly-manifest.json> <output.pptx>");
  }
  const artifactEntry = process.env.SHAWN_PPT_ARTIFACT_TOOL_ENTRY;
  if (!artifactEntry || !path.isAbsolute(artifactEntry)) {
    throw new Error("SHAWN_PPT_ARTIFACT_TOOL_ENTRY must point to artifact_tool.mjs");
  }
  const { Presentation, PresentationFile } = await import(pathToFileURL(artifactEntry).href);
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  if (!Array.isArray(manifest.slides) || manifest.slides.length === 0) {
    throw new Error("assembly manifest has no slides");
  }

  const slideSize = manifest.slide_size || { width: 1280, height: 720 };
  const presentation = Presentation.create({ slideSize });
  for (const item of manifest.slides) {
    const bytes = await readFile(item.source_path);
    const slide = presentation.slides.add();
    slide.background.fill = "#000000";
    slide.images.add({
      blob: bytes,
      contentType: contentType(item.source_path),
      alt: `${item.page_label || item.slide_uid || "PPT page"}${item.variant_label ? ` ${item.variant_label}` : ""}`,
      fit: "contain",
      position: { left: 0, top: 0, width: slideSize.width, height: slideSize.height },
    });
  }

  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(outputPath);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
