#!/usr/bin/env node

const [sourceUrl, outputPath, widthValue, heightValue, waitValue] = process.argv.slice(2);

if (!sourceUrl || !outputPath) {
  throw new Error("usage: capture_web_visual.js URL OUTPUT WIDTH HEIGHT WAIT_MS");
}

const width = Number(widthValue);
const height = Number(heightValue);
const waitMs = Number(waitValue);
if (!Number.isInteger(width) || !Number.isInteger(height) || !Number.isInteger(waitMs)) {
  throw new Error("viewport and wait values must be integers");
}

const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.SHAWN_PPT_CHROME || undefined,
  });
  try {
    const page = await browser.newPage({ viewport: { width, height } });
    await page.goto(sourceUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
    if (waitMs > 0) await page.waitForTimeout(waitMs);
    await page.screenshot({ path: outputPath, fullPage: false });
  } finally {
    await browser.close();
  }
})().catch((error) => {
  process.stderr.write(`${error && error.stack ? error.stack : error}\n`);
  process.exitCode = 1;
});
