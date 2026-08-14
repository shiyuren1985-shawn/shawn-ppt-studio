const MUTATION_HEADERS = Object.freeze({
  "Content-Type": "application/json",
  "X-Shawn-PPT-Studio": "1",
});

async function readJson(response) {
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { message: text };
    }
  }
  if (!response.ok) {
    const detail = payload?.error;
    const detailMessage = detail && typeof detail === "object" ? detail.message : "";
    const error = new Error(
      detailMessage || payload?.message || (typeof detail === "string" ? detail : "") || `请求失败（${response.status}）`,
    );
    error.status = response.status;
    error.code = (detail && typeof detail === "object" ? detail.code : "")
      || payload?.code
      || (typeof detail === "string" ? detail : null);
    error.payload = payload;
    throw error;
  }
  return payload;
}

function route(deckId, suffix = "") {
  return `/api/selector-workspace/decks/${encodeURIComponent(deckId)}${suffix}`;
}

function deckRoute(deckId, suffix = "") {
  return `/api/decks/${encodeURIComponent(deckId)}${suffix}`;
}

export function createSelectorApi(fetchImpl = globalThis.fetch?.bind(globalThis)) {
  if (typeof fetchImpl !== "function") throw new TypeError("fetch is required");

  const request = async (url, options = {}) => readJson(await fetchImpl(url, options));
  const mutate = (url, body = {}) => request(url, {
    method: "POST",
    headers: MUTATION_HEADERS,
    body: JSON.stringify(body),
  });

  return Object.freeze({
    refreshCatalog(deckId) {
      return mutate(route(deckId, "/catalog/refresh"));
    },
    getCatalog(deckId) {
      return request(route(deckId, "/catalog"), { cache: "no-store" });
    },
    getSlide(deckId, slideUid) {
      return request(route(deckId, `/slides/${encodeURIComponent(slideUid)}`), {
        cache: "no-store",
      });
    },
    selectCandidate(deckId, slideUid, candidateId, selected) {
      return mutate(route(deckId, `/slides/${encodeURIComponent(slideUid)}/select`), {
        candidate_id: candidateId,
        selected: selected === true,
      });
    },
    trashCandidate(deckId, candidateId, sha256) {
      return mutate(route(deckId, `/candidates/${encodeURIComponent(candidateId)}/trash`), {
        sha256,
        confirmed: true,
      });
    },
    useBaseline(deckId, slideUid) {
      return mutate(route(deckId, `/slides/${encodeURIComponent(slideUid)}/use-baseline`));
    },
    includePage(deckId, slideUid, included) {
      return mutate(route(deckId, `/slides/${encodeURIComponent(slideUid)}/include`), {
        included: included === true,
      });
    },
    confirmDefaults(deckId) {
      return mutate(route(deckId, "/confirm-defaults"));
    },
    getExportReadiness(deckId) {
      return request(deckRoute(deckId, "/export-readiness"), { cache: "no-store" });
    },
    createExport(deckId, name) {
      const body = typeof name === "string" && name.trim() ? { name: name.trim() } : {};
      return mutate(deckRoute(deckId, "/exports"), body);
    },
    openExportFolder(deckId, exportId) {
      return mutate(deckRoute(deckId, `/exports/${encodeURIComponent(exportId)}/open-folder`));
    },
  });
}

export const selectorApi = createSelectorApi();
