const COMPLETED_STATUS = "completed";

function taskId(task) {
  return String(task?.task_id || "");
}

function taskDeckId(task) {
  return String(task?.deck_id || "");
}

export function createTaskCatalogRefreshTracker({ refreshCatalog } = {}) {
  if (typeof refreshCatalog !== "function") throw new TypeError("refreshCatalog is required");

  let initialized = false;
  let previousStatuses = new Map();
  const pendingDeckIds = new Set();

  return async function observe(tasks = []) {
    const normalized = Array.isArray(tasks) ? tasks : [];
    const nextStatuses = new Map();
    for (const task of normalized) {
      const id = taskId(task);
      if (id) nextStatuses.set(id, String(task?.status || ""));
    }

    if (!initialized) {
      initialized = true;
      previousStatuses = nextStatuses;
      return [];
    }

    const newlyCompletedDeckIds = [...new Set(normalized
      .filter((task) => String(task?.status || "") === COMPLETED_STATUS)
      .filter((task) => {
        const id = taskId(task);
        return id && previousStatuses.has(id) && previousStatuses.get(id) !== COMPLETED_STATUS;
      })
      .map(taskDeckId)
      .filter(Boolean))];

    previousStatuses = nextStatuses;
    for (const deckId of newlyCompletedDeckIds) pendingDeckIds.add(deckId);

    const attemptedDeckIds = [...pendingDeckIds];
    const results = await Promise.allSettled(
      attemptedDeckIds.map((deckId) => refreshCatalog(deckId)),
    );
    const failures = [];
    for (const [index, result] of results.entries()) {
      const deckId = attemptedDeckIds[index];
      if (result.status === "fulfilled") pendingDeckIds.delete(deckId);
      else failures.push(result.reason);
    }
    if (failures.length) {
      throw new AggregateError(failures, "selector catalog refresh failed");
    }
    return attemptedDeckIds;
  };
}
