const state = { data: null, sortKey: "model", sortDir: 1 };

function currentTheme() {
  const explicit = document.documentElement.getAttribute("data-theme");
  if (explicit) return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function updateThemeToggleIcon() {
  document.getElementById("theme-toggle").textContent = currentTheme() === "dark" ? "☀️" : "🌙";
}

document.getElementById("theme-toggle").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem("evalforge-theme", next);
  } catch (e) {
    // Storage unavailable (private browsing, blocked) — theme just won't persist.
  }
  updateThemeToggleIcon();
});
updateThemeToggleIcon();

function providerOf(modelId, catalogProviders) {
  for (const [providerId, provider] of Object.entries(catalogProviders || {})) {
    if (provider.models.some((m) => m.id === modelId)) return providerId;
  }
  return "";
}

function buildRows(data) {
  if (!data) return [];
  const orModels = (data.availability.openrouter && data.availability.openrouter.models) || {};
  return Object.keys(orModels).map((modelId) => ({
    model: modelId,
    provider: providerOf(modelId, data.catalog),
    openrouter: orModels[modelId].listed,
    bedrock: (data.availability.backends.bedrock.models || {})[modelId] || [],
    vertex: (data.availability.backends.vertex.models || {})[modelId] || [],
    foundry: (data.availability.backends.foundry.models || {})[modelId] || [],
  }));
}

function regionLabels(regionIds, backend) {
  const known = state.data.availability.backends[backend].regions;
  return regionIds.map((id) => {
    const found = known.find((r) => r.id === id);
    return found ? found.label : id;
  });
}

function matchesFilters(row) {
  const text = document.getElementById("availability-filter").value.trim().toLowerCase();
  const backend = document.getElementById("availability-backend-filter").value;
  const region = document.getElementById("availability-region-filter").value;
  if (text && !row.model.toLowerCase().includes(text) && !row.provider.toLowerCase().includes(text)) return false;
  if (backend === "openrouter" && !row.openrouter) return false;
  if ((backend === "bedrock" || backend === "vertex" || backend === "foundry") && row[backend].length === 0) return false;
  if (region) {
    if (backend === "openrouter") return false; // OpenRouter has no regions; never matches a region filter.
    const backendsToCheck = backend ? [backend] : ["bedrock", "vertex", "foundry"];
    if (!backendsToCheck.some((b) => row[b].includes(region))) return false;
  }
  return true;
}

function sortValue(row, key) {
  if (key === "openrouter") return Number(row[key]);
  if (Array.isArray(row[key])) return row[key].length;
  return row[key];
}

function sortRows(rows) {
  const { sortKey, sortDir } = state;
  return [...rows].sort((a, b) => {
    const av = sortValue(a, sortKey);
    const bv = sortValue(b, sortKey);
    if (av < bv) return -1 * sortDir;
    if (av > bv) return 1 * sortDir;
    return 0;
  });
}

function renderTable() {
  const tbody = document.getElementById("availability-tbody");
  tbody.innerHTML = "";
  if (!state.data) return;
  const rows = sortRows(buildRows(state.data).filter(matchesFilters));
  if (rows.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.textContent = "No models match the current filters.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const cells = [
      row.model,
      row.provider,
      row.openrouter ? "✓" : "✗",
      row.bedrock.length ? regionLabels(row.bedrock, "bedrock").join(", ") : "—",
      row.vertex.length ? regionLabels(row.vertex, "vertex").join(", ") : "—",
      row.foundry.length ? regionLabels(row.foundry, "foundry").join(", ") : "—",
    ];
    cells.forEach((text) => {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function renderMeta(data) {
  const meta = document.getElementById("availability-meta");
  meta.innerHTML = "";
  const orLine = document.createElement("p");
  const refreshed = new Date(data.availability.openrouter.refreshed_at * 1000).toLocaleString();
  orLine.textContent = `OpenRouter last refreshed: ${refreshed}` +
    (data.availability.openrouter.stale ? " (stale — refresh failed, showing last known data)" : "");
  meta.appendChild(orLine);
  ["bedrock", "vertex", "foundry"].forEach((backend) => {
    const section = data.availability.backends[backend];
    const p = document.createElement("p");
    p.textContent = `${section.label} curated as of ${section.verified} — `;
    const link = document.createElement("a");
    link.href = section.source;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "source";
    p.appendChild(link);
    meta.appendChild(p);
  });
}

function populateRegionFilter(data) {
  const select = document.getElementById("availability-region-filter");
  select.innerHTML = '<option value="">All regions</option>';
  const seen = new Set();
  ["bedrock", "vertex", "foundry"].forEach((backend) => {
    data.availability.backends[backend].regions.forEach((region) => {
      if (seen.has(region.id)) return;
      seen.add(region.id);
      const option = document.createElement("option");
      option.value = region.id;
      option.textContent = `${region.label} (${region.id})`;
      select.appendChild(option);
    });
  });
}

function updateSortIndicators() {
  document.querySelectorAll("#availability-table th[data-sort]").forEach((th) => {
    if (th.dataset.sort !== state.sortKey) {
      th.setAttribute("aria-sort", "none");
      return;
    }
    th.setAttribute("aria-sort", state.sortDir === 1 ? "ascending" : "descending");
  });
}

function setupSorting() {
  document.querySelectorAll("#availability-table th[data-sort]").forEach((th) => {
    th.setAttribute("aria-sort", "none");
    const activate = () => {
      const key = th.dataset.sort;
      state.sortDir = state.sortKey === key ? -state.sortDir : 1;
      state.sortKey = key;
      updateSortIndicators();
      renderTable();
    };
    th.addEventListener("click", activate);
    th.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activate();
      }
    });
  });
  updateSortIndicators();
}

function showLoadError() {
  state.data = null;
  const meta = document.getElementById("availability-meta");
  meta.innerHTML = "";
  const p = document.createElement("p");
  p.textContent = "Couldn't load availability data — the server may be down. Try refreshing.";
  meta.appendChild(p);
  const tbody = document.getElementById("availability-tbody");
  tbody.innerHTML = "";
}

async function fetchJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} responded with ${resp.status}`);
  return resp.json();
}

async function load() {
  try {
    const [availabilityResp, catalogResp] = await Promise.all([
      fetchJson("/api/availability"),
      fetchJson("/api/catalog"),
    ]);
    state.data = { availability: availabilityResp, catalog: catalogResp.providers };
    populateRegionFilter(state.data);
    renderMeta(state.data);
    renderTable();
  } catch (e) {
    showLoadError();
  }
}

document.getElementById("availability-filter").addEventListener("input", renderTable);
document.getElementById("availability-backend-filter").addEventListener("change", renderTable);
document.getElementById("availability-region-filter").addEventListener("change", renderTable);
setupSorting();
load();
