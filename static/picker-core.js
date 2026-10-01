// Pure picker logic, kept DOM-free so `node --test` can exercise it.
// Loaded with a plain <script> before app.js (-> globalThis.PickerCore);
// also exported via module.exports when run under Node.
(function (root) {
  function filterModels(models, activeTagIds) {
    if (!activeTagIds || activeTagIds.length === 0) return models.slice();
    return models.filter((m) => {
      const tags = m.tags || [];
      return activeTagIds.every((id) => tags.includes(id));
    });
  }

  function targetsForModel(model) {
    const targets = [{ target: model.id, backend: "openrouter" }];
    Object.keys(model.routes || {}).forEach((backend) => {
      targets.push({ target: `${model.id}@${backend}`, backend });
    });
    return targets;
  }

  function capState(selectedCount, max) {
    return { atCap: selectedCount >= max, remaining: Math.max(0, max - selectedCount) };
  }

  const api = { filterModels, targetsForModel, capState };
  root.PickerCore = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
