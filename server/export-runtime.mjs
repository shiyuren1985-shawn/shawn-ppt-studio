import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { access, copyFile, mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";

const RUNTIME_ROOT = path.resolve(
  process.env.SHAWN_PPT_STUDIO_RUNTIME_ROOT ||
    path.join(
      homedir(),
      ".cache",
      "codex-runtimes",
      "codex-primary-runtime",
      "dependencies",
    ),
);

export const DEFAULT_EXPORT_RUNTIME = Object.freeze({
  node: path.join(RUNTIME_ROOT, "node", "bin", "node"),
  python: path.join(RUNTIME_ROOT, "python", "bin", "python3"),
  artifactToolEntry: path.join(
    RUNTIME_ROOT,
    "node",
    "node_modules",
    "@oai",
    "artifact-tool",
    "dist",
    "artifact_tool.mjs",
  ),
  soffice: path.join(RUNTIME_ROOT, "bin", "override", "soffice"),
  pdfinfo: path.join(RUNTIME_ROOT, "bin", "override", "pdfinfo"),
  pdftoppm: path.join(RUNTIME_ROOT, "bin", "override", "pdftoppm"),
  zip: "/usr/bin/zip",
  open: "/usr/bin/open",
});

export function runProcess(executable, args, { cwd = undefined, env = undefined, input = null } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, {
      cwd,
      env: env ? { ...process.env, ...env } : process.env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.once("error", reject);
    child.once("close", (code) => {
      const result = {
        code,
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8"),
      };
      if (code !== 0) {
        reject(Object.assign(new Error(result.stderr.trim() || result.stdout.trim() || `${executable} failed`), {
          code: "export_tool_failed",
          result,
        }));
        return;
      }
      resolve(result);
    });
    if (input !== null) child.stdin.end(input);
    else child.stdin.end();
  });
}

export async function probeExportRuntime(runtime = DEFAULT_EXPORT_RUNTIME) {
  const required = ["node", "python", "artifactToolEntry", "soffice", "pdfinfo", "pdftoppm", "zip", "open"];
  const missing = [];
  for (const key of required) {
    try {
      await access(runtime[key]);
    } catch {
      missing.push(key);
    }
  }
  if (missing.length) {
    return { ready: false, missing, message: `导出运行环境缺少：${missing.join("、")}` };
  }
  try {
    await runProcess(runtime.python, ["-c", "import PIL, reportlab; print('ok')"]);
  } catch {
    return { ready: false, missing: ["python_packages"], message: "导出运行环境缺少 PDF 组件。" };
  }
  return { ready: true, missing: [], message: null };
}

export async function sha256File(filePath) {
  const digest = createHash("sha256");
  digest.update(await readFile(filePath));
  return digest.digest("hex");
}

const PDF_PROGRAM = String.raw`
import json, os, sys
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

request=json.load(sys.stdin)
width=float(request.get('width',960))
height=float(request.get('height',540))
pdf=canvas.Canvas(request['output_path'],pagesize=(width,height),pageCompression=1)
for item in request['slides']:
    with Image.open(item['source_path']) as image:
        iw,ih=image.size
        scale=min(width/iw,height/ih)
        dw,dh=iw*scale,ih*scale
        left=(width-dw)/2
        top=(height-dh)/2
        pdf.setFillColorRGB(0,0,0)
        pdf.rect(0,0,width,height,fill=1,stroke=0)
        pdf.drawImage(ImageReader(image.convert('RGB')),left,top,width=dw,height=dh,preserveAspectRatio=True,mask='auto')
        pdf.showPage()
pdf.save()
`;

export async function buildPdf({ manifest, outputPath, runtime = DEFAULT_EXPORT_RUNTIME }) {
  await runProcess(runtime.python, ["-c", PDF_PROGRAM], {
    input: JSON.stringify({ output_path: outputPath, slides: manifest.slides }),
  });
}

export async function buildPptx({ manifestPath, outputPath, integrationPath, runtime = DEFAULT_EXPORT_RUNTIME }) {
  await runProcess(runtime.node, [integrationPath, manifestPath, outputPath], {
    env: { SHAWN_PPT_ARTIFACT_TOOL_ENTRY: runtime.artifactToolEntry },
  });
}

export async function buildPageCopies({ manifest, pagesRoot }) {
  await mkdir(pagesRoot, { recursive: true });
  const copies = [];
  for (const [index, item] of manifest.slides.entries()) {
    const extension = path.extname(item.source_path).toLowerCase();
    const stem = `${String(index + 1).padStart(3, "0")}_${item.page_label}${item.variant_label ? `-${item.variant_label}` : ""}`;
    const filename = `${stem}${extension}`;
    await copyFile(item.source_path, path.join(pagesRoot, filename));
    copies.push({ ...item, filename });
  }
  return copies;
}

export async function zipPages({ exportRoot, zipPath, runtime = DEFAULT_EXPORT_RUNTIME }) {
  await runProcess(runtime.zip, ["-q", "-r", zipPath, "pages"], { cwd: exportRoot });
}

export async function verifyPdf({ pdfPath, expectedPages, qaRoot, runtime = DEFAULT_EXPORT_RUNTIME }) {
  const info = await runProcess(runtime.pdfinfo, [pdfPath]);
  const pages = Number(info.stdout.match(/^Pages:\s+(\d+)/m)?.[1] || 0);
  if (pages !== expectedPages) throw new Error(`PDF page count is ${pages}, expected ${expectedPages}`);
  await mkdir(qaRoot, { recursive: true });
  await runProcess(runtime.pdftoppm, ["-png", "-r", "72", pdfPath, path.join(qaRoot, "pdf-page")]);
  const rendered = (await import("node:fs/promises")).readdir(qaRoot);
  const files = (await rendered).filter((name) => /^pdf-page-\d+\.png$/.test(name));
  if (files.length !== expectedPages) throw new Error("PDF render did not produce every page");
  return { page_count: pages, rendered_page_count: files.length };
}

export async function verifyPptxRender({ pptxPath, expectedPages, qaRoot, runtime = DEFAULT_EXPORT_RUNTIME }) {
  const officeRoot = path.join(qaRoot, "office");
  await mkdir(officeRoot, { recursive: true });
  await runProcess(runtime.soffice, ["--headless", "--convert-to", "pdf", "--outdir", officeRoot, pptxPath]);
  const pdfPath = path.join(officeRoot, `${path.basename(pptxPath, path.extname(pptxPath))}.pdf`);
  const info = await runProcess(runtime.pdfinfo, [pdfPath]);
  const pages = Number(info.stdout.match(/^Pages:\s+(\d+)/m)?.[1] || 0);
  if (pages !== expectedPages) throw new Error(`PPTX render page count is ${pages}, expected ${expectedPages}`);
  await runProcess(runtime.pdftoppm, ["-png", "-r", "72", pdfPath, path.join(officeRoot, "pptx-page")]);
  const files = (await (await import("node:fs/promises")).readdir(officeRoot))
    .filter((name) => /^pptx-page-\d+\.png$/.test(name));
  if (files.length !== expectedPages) throw new Error("PPTX render did not produce every page");
  return { page_count: pages, rendered_page_count: files.length };
}

export async function artifactDescriptor(filePath, downloadUrl, extra = {}) {
  const info = await stat(filePath);
  return {
    filename: path.basename(filePath),
    download_url: downloadUrl,
    size: info.size,
    sha256: await sha256File(filePath),
    ...extra,
  };
}

export async function writeJson(filePath, value) {
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}
