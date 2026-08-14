import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { open } from "node:fs/promises";
import path from "node:path";

const MAX_HEADER_BYTES = 1024 * 1024;

export const IMAGE_CONTENT_TYPES = new Map([
  [".png", "image/png"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".webp", "image/webp"],
]);

export async function sha256File(filePath) {
  const digest = createHash("sha256");
  for await (const chunk of createReadStream(filePath)) digest.update(chunk);
  return digest.digest("hex");
}
function pngDimensions(buffer) {
  if (buffer.length < 24 || buffer.toString("hex", 0, 8) !== "89504e470d0a1a0a") return null;
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

function jpegDimensions(buffer) {
  if (buffer.length < 4 || buffer[0] !== 0xff || buffer[1] !== 0xd8) return null;
  const startOfFrame = new Set([
    0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7,
    0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf,
  ]);
  let offset = 2;
  while (offset + 3 < buffer.length) {
    if (buffer[offset] !== 0xff) {
      offset += 1;
      continue;
    }
    while (offset < buffer.length && buffer[offset] === 0xff) offset += 1;
    const marker = buffer[offset];
    offset += 1;
    if (marker === 0xd8 || marker === 0xd9 || marker === 0x01) continue;
    if (offset + 2 > buffer.length) break;
    const length = buffer.readUInt16BE(offset);
    if (length < 2 || offset + length > buffer.length) break;
    if (startOfFrame.has(marker) && length >= 7) {
      return {
        width: buffer.readUInt16BE(offset + 5),
        height: buffer.readUInt16BE(offset + 3),
      };
    }
    offset += length;
  }
  return null;
}

function readUInt24LE(buffer, offset) {
  return buffer[offset] | (buffer[offset + 1] << 8) | (buffer[offset + 2] << 16);
}

function webpDimensions(buffer) {
  if (
    buffer.length < 30 ||
    buffer.toString("ascii", 0, 4) !== "RIFF" ||
    buffer.toString("ascii", 8, 12) !== "WEBP"
  ) {
    return null;
  }
  const kind = buffer.toString("ascii", 12, 16);
  if (kind === "VP8X") {
    return {
      width: readUInt24LE(buffer, 24) + 1,
      height: readUInt24LE(buffer, 27) + 1,
    };
  }
  if (kind === "VP8 " && buffer.length >= 30) {
    return {
      width: buffer.readUInt16LE(26) & 0x3fff,
      height: buffer.readUInt16LE(28) & 0x3fff,
    };
  }
  if (kind === "VP8L" && buffer.length >= 25 && buffer[20] === 0x2f) {
    return {
      width: 1 + buffer[21] + ((buffer[22] & 0x3f) << 8),
      height: 1 + ((buffer[22] & 0xc0) >> 6) + (buffer[23] << 2) + ((buffer[24] & 0x0f) << 10),
    };
  }
  return null;
}

export async function readImageDimensions(filePath, sizeBytes) {
  const extension = path.extname(filePath).toLowerCase();
  if (!IMAGE_CONTENT_TYPES.has(extension)) return null;
  const handle = await open(filePath, "r");
  try {
    const length = Math.min(sizeBytes, MAX_HEADER_BYTES);
    const buffer = Buffer.alloc(length);
    const { bytesRead } = await handle.read(buffer, 0, length, 0);
    const header = buffer.subarray(0, bytesRead);
    if (extension === ".png") return pngDimensions(header);
    if (extension === ".jpg" || extension === ".jpeg") return jpegDimensions(header);
    return webpDimensions(header);
  } finally {
    await handle.close();
  }
}
