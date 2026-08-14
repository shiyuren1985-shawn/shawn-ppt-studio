import { HttpError } from "./errors.mjs";

function json(res, statusCode, value) {
  const payload = JSON.stringify(value);
  res.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  res.end(payload);
}

function decoded(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    throw new HttpError(400, "网址参数无效", "invalid_route_parameter");
  }
}

export async function handleSelectorWorkspaceRequest(
  req,
  res,
  requestUrl,
  workspace,
  readJson,
) {
  const root = /^\/api\/selector-workspace\/decks\/([^/]+)(.*)$/.exec(requestUrl.pathname);
  if (!root) return false;
  const deckId = decoded(root[1]);
  const suffix = root[2];

  if (req.method === "GET" && suffix === "/catalog") {
    json(res, 200, workspace.snapshot(deckId));
    return true;
  }
  if (req.method === "POST" && suffix === "/catalog/refresh") {
    await readJson(req);
    json(res, 200, await workspace.refresh(deckId));
    return true;
  }
  if (req.method === "POST" && suffix === "/confirm-defaults") {
    await readJson(req);
    json(res, 200, await workspace.confirmDefaults(deckId));
    return true;
  }

  const slide = /^\/slides\/([^/]+)(.*)$/.exec(suffix);
  if (slide) {
    const slideUid = decoded(slide[1]);
    const action = slide[2];
    if (req.method === "GET" && action === "") {
      json(res, 200, workspace.slide(deckId, slideUid));
      return true;
    }
    if (req.method === "POST" && action === "/select") {
      json(res, 200, await workspace.select(deckId, slideUid, await readJson(req)));
      return true;
    }
    if (req.method === "POST" && action === "/use-baseline") {
      await readJson(req);
      json(res, 200, await workspace.useBaseline(deckId, slideUid));
      return true;
    }
    if (req.method === "POST" && action === "/include") {
      const body = await readJson(req);
      json(res, 200, await workspace.include(deckId, slideUid, body.included));
      return true;
    }
  }

  const image = /^\/candidates\/([^/]+)\/image$/.exec(suffix);
  if (req.method === "GET" && image) {
    await workspace.streamImage(res, {
      deckId,
      candidateId: decoded(image[1]),
      sha256: requestUrl.searchParams.get("sha256"),
    });
    return true;
  }

  const trash = /^\/candidates\/([^/]+)\/trash$/.exec(suffix);
  if (req.method === "POST" && trash) {
    json(res, 200, await workspace.trashCandidate(
      deckId,
      decoded(trash[1]),
      await readJson(req),
    ));
    return true;
  }

  throw new HttpError(404, "route not found", "not_found");
}
