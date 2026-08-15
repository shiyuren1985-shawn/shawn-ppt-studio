import { realpath, stat } from "node:fs/promises";
import path from "node:path";

import { HttpError } from "./errors.mjs";

const CONTENT_TYPES = new Map([
  [".png", "image/png"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".webp", "image/webp"],
]);

function isInside(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== "..");
}

export async function resolveConversationImage(deck, requestedPath) {
  if (typeof requestedPath !== "string" || !path.isAbsolute(requestedPath)) {
    throw new HttpError(400, "图片链接无效", "invalid_conversation_image_path");
  }
  const extension = path.extname(requestedPath).toLowerCase();
  if (!CONTENT_TYPES.has(extension)) {
    throw new HttpError(400, "这不是可预览的图片", "invalid_conversation_image_type");
  }

  let fileReal;
  let info;
  try {
    [fileReal, info] = await Promise.all([realpath(requestedPath), stat(requestedPath)]);
  } catch {
    throw new HttpError(404, "图片暂时找不到", "conversation_image_not_found");
  }
  if (!info.isFile()) {
    throw new HttpError(404, "图片暂时找不到", "conversation_image_not_found");
  }

  const roots = [...new Set([
    deck?.output_root,
    ...(deck?.candidate_roots || []).map((item) => item?.path),
  ].filter((value) => typeof value === "string" && path.isAbsolute(value)))];
  const rootReals = (await Promise.all(roots.map((root) => realpath(root).catch(() => null)))).filter(Boolean);
  if (!rootReals.some((root) => fileReal !== root && isInside(root, fileReal))) {
    throw new HttpError(403, "图片不属于当前 PPT", "conversation_image_outside_project");
  }
  return {
    path: fileReal,
    filename: path.basename(fileReal),
    contentType: CONTENT_TYPES.get(extension),
    size: info.size,
  };
}
