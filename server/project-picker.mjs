import { execFile } from "node:child_process";
import { realpath, stat } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

import { HttpError } from "./errors.mjs";

const execFileAsync = promisify(execFile);

const FOLDER_SCRIPT = [
  "try",
  'set picked to choose folder with prompt "选择新 PPT 项目文件夹"',
  "POSIX path of picked",
  "on error number -128",
  'return "__CANCELLED__"',
  "end try",
].join("\n");

const OUTLINE_SCRIPT = [
  "try",
  'set picked to choose file with prompt "选择 Markdown 大纲" of type {"net.daringfireball.markdown", "public.plain-text"}',
  "POSIX path of picked",
  "on error number -128",
  'return "__CANCELLED__"',
  "end try",
].join("\n");

export class MacProjectPicker {
  constructor({ executable = "/usr/bin/osascript", run = execFileAsync } = {}) {
    this.executable = executable;
    this.run = run;
  }

  async pickFolder() {
    return this.#pick("folder", FOLDER_SCRIPT);
  }

  async pickOutline() {
    return this.#pick("outline", OUTLINE_SCRIPT);
  }

  async #pick(kind, script) {
    if (process.platform !== "darwin" && this.run === execFileAsync) {
      throw new HttpError(501, "native picker is available on macOS", "picker_unavailable");
    }
    let stdout;
    try {
      ({ stdout } = await this.run(this.executable, ["-e", script], { encoding: "utf8" }));
    } catch (error) {
      throw new HttpError(503, error.message || "native picker failed", "picker_failed");
    }
    const selected = String(stdout || "").trim();
    if (!selected || selected === "__CANCELLED__") {
      return { contract_version: 1, cancelled: true, selection: null };
    }
    let resolved;
    let info;
    try {
      [resolved, info] = await Promise.all([realpath(selected), stat(selected)]);
    } catch {
      throw new HttpError(404, "selected path is no longer available", "picker_selection_missing");
    }
    if (kind === "folder" && !info.isDirectory()) {
      throw new HttpError(400, "selected path is not a folder", "invalid_picker_selection");
    }
    if (kind === "outline" && (!info.isFile() || ![".md", ".markdown"].includes(path.extname(resolved).toLowerCase()))) {
      throw new HttpError(400, "selected file is not Markdown", "invalid_picker_selection");
    }
    return {
      contract_version: 1,
      cancelled: false,
      selection: { kind, path: resolved },
    };
  }
}
