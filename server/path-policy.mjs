import { constants as fsConstants } from "node:fs";
import { copyFile, mkdir, realpath, stat } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";

import { HttpError } from "./errors.mjs";
import { studioLibraryRoot } from "./studio-library.mjs";

function isInside(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== "..");
}

export function createPathPolicy(labRoot) {
  const root = path.resolve(labRoot);
  const imageRoot = path.join(studioLibraryRoot(root), "images");
  const codexGeneratedImageRoot = path.join(homedir(), ".codex", "generated_images");
  const allowedImageExtensions = new Set([".png", ".jpg", ".jpeg", ".webp"]);

  async function ensureRuntime() {
    await mkdir(imageRoot, { recursive: true });
  }

  function assertLexicalImagePath(value) {
    if (typeof value !== "string" || !path.isAbsolute(value)) {
      throw new HttpError(400, "image path must be an absolute path", "invalid_image_path");
    }

    const resolved = path.resolve(value);
    if (!isInside(imageRoot, resolved) || resolved === imageRoot) {
      throw new HttpError(
        403,
        "image path must be below the Studio Library images directory",
        "image_path_outside_runtime",
      );
    }
    return resolved;
  }

  async function requireImageFile(value) {
    const lexicalPath = assertLexicalImagePath(value);
    let rootReal;
    let targetReal;
    let targetStat;
    try {
      [rootReal, targetReal, targetStat] = await Promise.all([
        realpath(imageRoot),
        realpath(lexicalPath),
        stat(lexicalPath),
      ]);
    } catch {
      throw new HttpError(404, "Studio Library image file was not found", "image_not_found");
    }

    if (!isInside(rootReal, targetReal) || !targetStat.isFile()) {
      throw new HttpError(403, "Studio Library image must be a regular file", "invalid_image_file");
    }
    return targetReal;
  }

  async function validateGeneratedImage(value) {
    try {
      return await requireImageFile(value);
    } catch (error) {
      if (error?.code !== "image_path_outside_runtime") throw error;
    }

    if (typeof value !== "string" || !path.isAbsolute(value)) {
      throw new HttpError(400, "generated image path must be absolute", "invalid_image_path");
    }

    let generatedRootReal;
    let sourceReal;
    let sourceStat;
    try {
      [generatedRootReal, sourceReal, sourceStat] = await Promise.all([
        realpath(codexGeneratedImageRoot),
        realpath(value),
        stat(value),
      ]);
    } catch {
      throw new HttpError(404, "generated image file was not found", "image_not_found");
    }

    const extension = path.extname(sourceReal).toLowerCase();
    if (
      !isInside(generatedRootReal, sourceReal) ||
      sourceReal === generatedRootReal ||
      !sourceStat.isFile() ||
      !allowedImageExtensions.has(extension)
    ) {
      throw new HttpError(
        403,
        "generated image must come from the Codex generated_images directory",
        "image_path_outside_allowed_sources",
      );
    }

    await ensureRuntime();
    const destination = path.join(imageRoot, `imagegen-${randomUUID()}${extension}`);
    await copyFile(sourceReal, destination, fsConstants.COPYFILE_EXCL);
    return requireImageFile(destination);
  }

  async function requireReferenceImage(value) {
    if (typeof value !== "string" || !path.isAbsolute(value) || /^data:/i.test(value)) {
      throw new HttpError(
        400,
        "reference image path must be a local absolute path",
        "invalid_reference_image",
      );
    }
    let targetReal;
    let targetStat;
    try {
      [targetReal, targetStat] = await Promise.all([realpath(value), stat(value)]);
    } catch {
      throw new HttpError(404, "reference image was not found", "reference_image_not_found");
    }
    if (
      !targetStat.isFile() ||
      !allowedImageExtensions.has(path.extname(targetReal).toLowerCase())
    ) {
      throw new HttpError(
        400,
        "reference image must be a PNG, JPG, or WebP file",
        "invalid_reference_image",
      );
    }
    return targetReal;
  }

  return {
    root,
    imageRoot,
    codexGeneratedImageRoot,
    ensureRuntime,
    assertLexicalImagePath,
    requireImageFile,
    requireReferenceImage,
    validateGeneratedImage,
  };
}

export function sanitizeForBrowser(value) {
  if (Array.isArray(value)) {
    return value.map(sanitizeForBrowser);
  }
  if (!value || typeof value !== "object") {
    if (typeof value === "string" && /^data:/i.test(value)) return "[payload omitted]";
    return value;
  }

  const clean = {};
  for (const [key, child] of Object.entries(value)) {
    if (/^(data|base64|imageData|audioData)$/i.test(key)) continue;
    clean[key] = sanitizeForBrowser(child);
  }
  return clean;
}
