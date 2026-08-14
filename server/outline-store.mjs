import { constants as fsConstants } from "node:fs";
import { chmod, mkdir, open, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";

import { parseOutlineText, splitTableCells } from "./discovery.mjs";
import { HttpError } from "./errors.mjs";

function expectedDigest(value) {
  if (typeof value !== "string") return null;
  const match = value.trim().match(/^(?:sha256:)?([a-f0-9]{64})$/i);
  return match?.[1]?.toLowerCase() || null;
}

function normalizedPageId(value) {
  const match = String(value ?? "").trim().match(/^P?0*(\d+)$/i);
  if (!match || Number(match[1]) <= 0) return null;
  return `P${Number(match[1])}`;
}

async function durableAtomicWrite(targetPath, bytes, mode) {
  const tempPath = path.join(
    path.dirname(targetPath),
    `.${path.basename(targetPath)}.ppt-ai-lab-${randomUUID()}.tmp`,
  );
  let handle;
  try {
    handle = await open(tempPath, fsConstants.O_CREAT | fsConstants.O_EXCL | fsConstants.O_WRONLY, mode);
    await handle.writeFile(bytes);
    await handle.sync();
    await handle.close();
    handle = null;
    await chmod(tempPath, mode);
    await rename(tempPath, targetPath);
  } catch (error) {
    await handle?.close().catch(() => {});
    await rm(tempPath, { force: true }).catch(() => {});
    throw error;
  }
}

function safeName(value) {
  return String(value).replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 80) || "deck";
}

export class OutlineStore {
  constructor({ labRoot, discovery }) {
    this.labRoot = path.resolve(labRoot);
    this.discovery = discovery;
    this.writeQueues = new Map();
  }

  async applyRow(body) {
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      throw new HttpError(400, "JSON body must be an object", "invalid_outline_apply");
    }
    for (const field of ["deck_id", "deck_uid", "slide_uid", "replacement_markdown"]) {
      if (typeof body[field] !== "string" || !body[field].trim()) {
        throw new HttpError(400, `${field} is required`, "invalid_outline_apply");
      }
    }
    const expectedSha256 = expectedDigest(body.expected_sha256);
    if (!expectedSha256) {
      throw new HttpError(
        400,
        "expected_sha256 must be a SHA-256 digest",
        "invalid_outline_revision",
      );
    }

    const deckId = body.deck_id.trim();
    const previous = this.writeQueues.get(deckId) || Promise.resolve();
    const operation = previous.then(() => this.#applyRowNow({ ...body, expectedSha256 }));
    const queued = operation.catch(() => {});
    this.writeQueues.set(deckId, queued);
    try {
      return await operation;
    } finally {
      if (this.writeQueues.get(deckId) === queued) this.writeQueues.delete(deckId);
    }
  }

  async applyRows(body) {
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      throw new HttpError(400, "JSON body must be an object", "invalid_outline_apply");
    }
    for (const field of ["deck_id", "deck_uid"]) {
      if (typeof body[field] !== "string" || !body[field].trim()) {
        throw new HttpError(400, `${field} is required`, "invalid_outline_apply");
      }
    }
    const expectedSha256 = expectedDigest(body.expected_sha256);
    if (!expectedSha256) {
      throw new HttpError(
        400,
        "expected_sha256 must be a SHA-256 digest",
        "invalid_outline_revision",
      );
    }
    if (!Array.isArray(body.changes) || body.changes.length === 0) {
      throw new HttpError(400, "changes must not be empty", "invalid_outline_apply");
    }
    const seen = new Set();
    const changes = body.changes.map((change) => {
      if (
        !change ||
        typeof change.slide_uid !== "string" ||
        !change.slide_uid.trim() ||
        typeof change.replacement_markdown !== "string" ||
        !change.replacement_markdown.trim()
      ) {
        throw new HttpError(400, "each change must include slide_uid and replacement_markdown", "invalid_outline_apply");
      }
      const slideUid = change.slide_uid.trim();
      if (seen.has(slideUid)) {
        throw new HttpError(400, `duplicate slide_uid: ${slideUid}`, "invalid_outline_apply");
      }
      seen.add(slideUid);
      return { slide_uid: slideUid, replacement_markdown: change.replacement_markdown.trim() };
    });

    const deckId = body.deck_id.trim();
    const previous = this.writeQueues.get(deckId) || Promise.resolve();
    const operation = previous.then(() =>
      this.#applyRowsNow({
        ...body,
        deck_id: deckId,
        deck_uid: body.deck_uid.trim(),
        expectedSha256,
        changes,
      }),
    );
    const queued = operation.catch(() => {});
    this.writeQueues.set(deckId, queued);
    try {
      return await operation;
    } finally {
      if (this.writeQueues.get(deckId) === queued) this.writeQueues.delete(deckId);
    }
  }

  async #applyRowsNow(body) {
    const beforeDeck = await this.discovery.readDeck(body.deck_id);
    const before = beforeDeck.outline;
    if (before.sha256 !== body.expectedSha256) {
      throw new HttpError(409, "outline revision changed", "outline_revision_conflict");
    }
    if (before.deck_uid !== body.deck_uid) {
      throw new HttpError(403, "deck_uid does not match the authoritative outline", "deck_uid_mismatch");
    }

    const replacements = [];
    for (const change of body.changes) {
      const slide = before.slides.find((candidate) => candidate.slide_uid === change.slide_uid);
      if (!slide) {
        throw new HttpError(404, `unknown slide_uid: ${change.slide_uid}`, "slide_not_found");
      }
      const replacement = change.replacement_markdown;
      if (replacement.includes("\n") || replacement.includes("\r")) {
        throw new HttpError(400, "replacement_markdown must be one complete page table row", "invalid_outline_replacement");
      }
      const cells = splitTableCells(replacement);
      if (cells.length !== slide.column_count) {
        throw new HttpError(400, `replacement row must keep ${slide.column_count} columns`, "outline_column_count_changed");
      }
      if (normalizedPageId(cells[0]) !== slide.page_id) {
        throw new HttpError(403, "replacement cannot change page identity", "page_identity_changed");
      }
      replacements.push({ slide, replacement });
    }

    let candidateText = before.text;
    for (const { slide, replacement } of replacements.sort(
      (left, right) => right.slide.span[0] - left.slide.span[0],
    )) {
      const original = candidateText.slice(slide.span[0], slide.span[1]);
      const newline = original.endsWith("\r\n") ? "\r\n" : original.endsWith("\n") ? "\n" : "";
      candidateText =
        candidateText.slice(0, slide.span[0]) +
        replacement +
        newline +
        candidateText.slice(slide.span[1]);
    }
    const candidateBytes = Buffer.from(candidateText, "utf8");
    const info = await stat(before.path);
    const candidate = parseOutlineText({
      text: candidateText,
      bytes: candidateBytes,
      outlinePath: before.path,
      info: { ...info, size: candidateBytes.length },
    });
    if (
      candidate.deck_uid !== before.deck_uid ||
      JSON.stringify(candidate.slide_uids) !== JSON.stringify(before.slide_uids)
    ) {
      throw new HttpError(403, "replacement cannot change deck_uid or slide_uids", "outline_identity_changed");
    }

    const liveDeck = await this.discovery.readDeck(body.deck_id);
    if (liveDeck.outline.sha256 !== body.expectedSha256) {
      throw new HttpError(409, "outline revision changed", "outline_revision_conflict");
    }
    const backupRoot = path.join(this.labRoot, "runtime", "outline-backups", safeName(body.deck_id));
    await mkdir(backupRoot, { recursive: true });
    const backupPath = path.join(
      backupRoot,
      `${safeName(path.basename(before.path, path.extname(before.path)))}.${body.expectedSha256.slice(0, 12)}.${randomUUID()}.md`,
    );
    await writeFile(backupPath, before.bytes, { flag: "wx", mode: 0o600 });

    const currentBytes = await readFile(before.path);
    const current = parseOutlineText({
      text: currentBytes.toString("utf8"),
      bytes: currentBytes,
      outlinePath: before.path,
      info: await stat(before.path),
    });
    if (current.sha256 !== body.expectedSha256) {
      throw new HttpError(409, "outline revision changed", "outline_revision_conflict");
    }

    try {
      await durableAtomicWrite(before.path, candidateBytes, info.mode & 0o777);
      const after = (await this.discovery.readDeck(body.deck_id)).outline;
      if (
        after.deck_uid !== before.deck_uid ||
        JSON.stringify(after.slide_uids) !== JSON.stringify(before.slide_uids)
      ) {
        throw new Error("post-write identity verification failed");
      }
      return {
        contract_version: 2,
        deck_id: body.deck_id,
        deck_uid: after.deck_uid,
        previous_sha256: before.sha256,
        sha256: after.sha256,
        revision_id: after.revision_id,
        applied_count: body.changes.length,
        applied_slide_uids: body.changes.map((change) => change.slide_uid),
        backup_path: backupPath,
        change_note: typeof body.change_note === "string" ? body.change_note : "",
        updated_at: new Date().toISOString(),
      };
    } catch (error) {
      await durableAtomicWrite(before.path, before.bytes, info.mode & 0o777).catch(() => {});
      throw error;
    }
  }

  async #applyRowNow(body) {
    const beforeDeck = await this.discovery.readDeck(body.deck_id.trim());
    const before = beforeDeck.outline;
    if (before.sha256 !== body.expectedSha256) {
      throw new HttpError(409, "outline revision changed", "outline_revision_conflict");
    }
    if (before.deck_uid !== body.deck_uid.trim()) {
      throw new HttpError(403, "deck_uid does not match the authoritative outline", "deck_uid_mismatch");
    }
    const slide = before.slides.find((candidate) => candidate.slide_uid === body.slide_uid.trim());
    if (!slide) {
      throw new HttpError(404, `unknown slide_uid: ${body.slide_uid}`, "slide_not_found");
    }

    const replacement = body.replacement_markdown.trim();
    if (replacement.includes("\n") || replacement.includes("\r")) {
      throw new HttpError(
        400,
        "replacement_markdown must be one complete page table row",
        "invalid_outline_replacement",
      );
    }
    const cells = splitTableCells(replacement);
    if (cells.length !== slide.column_count) {
      throw new HttpError(
        400,
        `replacement row must keep ${slide.column_count} columns`,
        "outline_column_count_changed",
      );
    }
    if (normalizedPageId(cells[0]) !== slide.page_id) {
      throw new HttpError(403, "replacement cannot change page identity", "page_identity_changed");
    }

    const originalSlice = before.text.slice(slide.span[0], slide.span[1]);
    const newline = originalSlice.endsWith("\r\n") ? "\r\n" : originalSlice.endsWith("\n") ? "\n" : "";
    const candidateText =
      before.text.slice(0, slide.span[0]) + replacement + newline + before.text.slice(slide.span[1]);
    const candidateBytes = Buffer.from(candidateText, "utf8");
    const info = await stat(before.path);
    const candidate = parseOutlineText({
      text: candidateText,
      bytes: candidateBytes,
      outlinePath: before.path,
      info: { ...info, size: candidateBytes.length },
    });
    if (
      candidate.deck_uid !== before.deck_uid ||
      JSON.stringify(candidate.slide_uids) !== JSON.stringify(before.slide_uids)
    ) {
      throw new HttpError(
        403,
        "replacement cannot change deck_uid or slide_uids",
        "outline_identity_changed",
      );
    }

    const liveDeck = await this.discovery.readDeck(body.deck_id.trim());
    if (liveDeck.outline.sha256 !== body.expectedSha256) {
      throw new HttpError(409, "outline revision changed", "outline_revision_conflict");
    }

    const backupRoot = path.join(
      this.labRoot,
      "runtime",
      "outline-backups",
      safeName(body.deck_id),
    );
    await mkdir(backupRoot, { recursive: true });
    const backupPath = path.join(
      backupRoot,
      `${safeName(path.basename(before.path, path.extname(before.path)))}.${body.expectedSha256.slice(0, 12)}.${randomUUID()}.md`,
    );
    await writeFile(backupPath, before.bytes, { flag: "wx", mode: 0o600 });

    const currentBytes = await readFile(before.path);
    const current = parseOutlineText({
      text: currentBytes.toString("utf8"),
      bytes: currentBytes,
      outlinePath: before.path,
      info: await stat(before.path),
    });
    if (current.sha256 !== body.expectedSha256) {
      throw new HttpError(409, "outline revision changed", "outline_revision_conflict");
    }

    try {
      await durableAtomicWrite(before.path, candidateBytes, info.mode & 0o777);
      const afterDeck = await this.discovery.readDeck(body.deck_id.trim());
      const after = afterDeck.outline;
      if (
        after.deck_uid !== before.deck_uid ||
        JSON.stringify(after.slide_uids) !== JSON.stringify(before.slide_uids)
      ) {
        throw new Error("post-write identity verification failed");
      }
      return {
        contract_version: 2,
        deck_id: body.deck_id.trim(),
        deck_uid: after.deck_uid,
        slide_uid: body.slide_uid.trim(),
        previous_sha256: before.sha256,
        sha256: after.sha256,
        revision_id: after.revision_id,
        backup_path: backupPath,
        change_note: typeof body.change_note === "string" ? body.change_note : "",
        updated_at: new Date().toISOString(),
      };
    } catch (error) {
      await durableAtomicWrite(before.path, before.bytes, info.mode & 0o777).catch(() => {});
      throw error;
    }
  }
}
