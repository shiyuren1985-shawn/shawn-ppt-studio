import { realpath, stat } from "node:fs/promises";
import path from "node:path";

import { HttpError } from "./errors.mjs";

export function createPathPolicy(labRoot) {
  const root = path.resolve(labRoot);
  const allowedImageExtensions = new Set([".png", ".jpg", ".jpeg", ".webp"]);

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
    requireReferenceImage,
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
