const COMPLETED_STATUS = "completed";

function artifactVersion(task) {
  return JSON.stringify([String(task?.status || ""), Number(task?.completed_units) || 0]);
}

function taskId(task) {
  return String(task?.task_id || "");
}

function taskDeckId(task) {
  return String(task?.deck_id || "");
}

export function createTaskCatalogRefreshTracker({ refreshCatalog } = {}) {
  if (typeof refreshCatalog !== "function") throw new TypeError("refreshCatalog is required");

  let previousStatuses = new Map();
  const pendingDeckIds = new Set();

  return async function observe(tasks = []) {
    const normalized = Array.isArray(tasks) ? tasks : [];
    const nextStatuses = new Map();
    for (const task of normalized) {
      const id = taskId(task);
      if (id) nextStatuses.set(id, artifactVersion(task));
    }

    const newlyCompletedDeckIds = [...new Set(normalized
      .filter((task) => String(task?.status || "") === COMPLETED_STATUS || Number(task?.completed_units) > 0)
      .filter((task) => {
        const id = taskId(task);
        return id && previousStatuses.get(id) !== artifactVersion(task);
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
