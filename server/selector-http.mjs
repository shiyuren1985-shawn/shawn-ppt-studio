import { createReadStream } from "node:fs";

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
export async function handleSelectorProjectionRequest(req, res, requestUrl, projection) {
  const selectionMatch = requestUrl.pathname.match(
    /^\/api\/decks\/([^/]+)\/slides\/([^/]+)\/selection$/,
  );
  if (req.method === "GET" && selectionMatch) {
    json(
      res,
      200,
      await projection.get(
        decodeURIComponent(selectionMatch[1]),
        decodeURIComponent(selectionMatch[2]),
      ),
    );
    return true;
  }

  if (req.method === "GET" && requestUrl.pathname === "/api/selected-image") {
    const image = await projection.resolveImage({
      deckId: requestUrl.searchParams.get("deck_id"),
      slideUid: requestUrl.searchParams.get("slide_uid"),
      candidateId: requestUrl.searchParams.get("candidate_id"),
      sha256: requestUrl.searchParams.get("sha256"),
    });
    res.writeHead(200, {
      "content-type": image.content_type,
      "content-length": image.size_bytes,
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "content-security-policy": "default-src 'none'",
    });
    createReadStream(image.path).pipe(res);
    return true;
  }

  return false;
}
