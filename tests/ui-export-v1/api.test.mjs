import assert from "node:assert/strict";
import test from "node:test";

import { createSelectorApi } from "../../web/selector/api.js";

function response(body = {}, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("export uses the frozen deck-scoped routes exactly once", async () => {
  const calls = [];
  const api = createSelectorApi(async (url, options = {}) => {
    calls.push({ url, options });
    if (url.endsWith("export-readiness")) return response({ ready: true });
    if (url.endsWith("open-folder")) return response({ opened: true });
    return response({ status: "completed" }, 201);
  });

  await api.getExportReadiness("EPC deck");
  await api.createExport("EPC deck");
  await api.openExportFolder("EPC deck", "export/1");

  assert.equal(calls[0].url, "/api/decks/EPC%20deck/export-readiness");
  assert.equal(calls[0].options.cache, "no-store");
  assert.equal(calls[1].url, "/api/decks/EPC%20deck/exports");
  assert.deepEqual(JSON.parse(calls[1].options.body), {});
  assert.equal(calls[2].url, "/api/decks/EPC%20deck/exports/export%2F1/open-folder");
  assert.equal(calls.filter((call) => call.url.endsWith("/exports")).length, 1);
});

test("an export name is optional and trimmed before sending", async () => {
  let body;
  const api = createSelectorApi(async (_url, options) => {
    body = JSON.parse(options.body);
    return response({ status: "completed" }, 201);
  });
  await api.createExport("epc", "  客户评审版  ");
  assert.deepEqual(body, { name: "客户评审版" });
});

test("export errors show the backend's human message while retaining the code", async () => {
  const api = createSelectorApi(async () => response({
    error: "export_not_ready",
    message: "还有 2 页没有确认图片",
    missing_pages: [],
  }, 409));
  await assert.rejects(api.createExport("epc"), (error) => {
    assert.equal(error.code, "export_not_ready");
    assert.equal(error.message, "还有 2 页没有确认图片");
    return true;
  });
});
