import { execFile } from "node:child_process";
import { realpath, stat } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

import { HttpError } from "./errors.mjs";

const execFileAsync = promisify(execFile);

function isInside(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== "..");
}

function pathWithoutLocation(value) {
  return value
    .replace(/#L\d+(?:C\d+)?$/i, "")
    .replace(/:(\d+)(?::\d+)?$/, "");
}

async function resolveExistingPath(requestedPath) {
  try {
    return await realpath(requestedPath);
  } catch (firstError) {
    const withoutLocation = pathWithoutLocation(requestedPath);
    if (withoutLocation === requestedPath) throw firstError;
    return realpath(withoutLocation);
  }
}

export async function resolveConversationFile(deck, requestedPath) {
  if (typeof requestedPath !== "string" || !path.isAbsolute(requestedPath)) {
    throw new HttpError(400, "文件链接无效", "invalid_conversation_file_path");
  }

  let fileReal;
  let info;
  try {
    fileReal = await resolveExistingPath(requestedPath);
    info = await stat(fileReal);
  } catch {
    throw new HttpError(404, "这个文件暂时找不到", "conversation_file_not_found");
  }
  if (!info.isFile() && !info.isDirectory()) {
    throw new HttpError(400, "这个链接不是文件或文件夹", "invalid_conversation_file_type");
  }

  const roots = [...new Set([
    deck?.project_root,
    deck?.outline?.path ? path.dirname(deck.outline.path) : null,
    deck?.output_root,
    ...(deck?.candidate_roots || []).map((item) => item?.path),
  ].filter((value) => typeof value === "string" && path.isAbsolute(value)))];
  const rootReals = (await Promise.all(roots.map((root) => realpath(root).catch(() => null)))).filter(Boolean);
  if (!rootReals.some((root) => isInside(root, fileReal))) {
    throw new HttpError(403, "这个文件不属于当前 PPT", "conversation_file_outside_project");
  }
  return { path: fileReal, kind: info.isDirectory() ? "directory" : "file" };
}

export async function openConversationFile(
  deck,
  requestedPath,
  { platform = process.platform, run = execFileAsync } = {},
) {
  const resolved = await resolveConversationFile(deck, requestedPath);
  if (platform !== "darwin") {
    throw new HttpError(501, "当前系统暂不支持打开本地文件", "conversation_file_open_unsupported");
  }
  await run("/usr/bin/open", [resolved.path], { timeout: 10_000, windowsHide: true });
  return { opened: true, kind: resolved.kind };
}
