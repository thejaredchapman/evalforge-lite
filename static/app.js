const state = {
  catalog: null,
  testCases: [],
  selectedModels: new Set(),
  customModels: [],
  runs: [],       // full /api/run responses seen this page load, oldest first
  activeRunId: null,
  categoryChart: null,
};

function apiKey() {
  return document.getElementById("api-key").value.trim();
}

function letterToClass(letter) {
  if (!letter) return "";
  return `grade-${letter[0].toLowerCase()}`;
}

async function loadCatalog() {
  const resp = await fetch("/api/catalog");
  const data = await resp.json();
  state.catalog = data;
  renderFrontier(data.frontier);
  renderProviders(data.providers);
}

async function loadAllModelsDatalist() {
  try {
    const resp = await fetch("/api/openrouter-models");
    const data = await resp.json();
    const datalist = document.getElementById("all-models-datalist");
    datalist.innerHTML = "";
    (data.models || []).forEach((model) => {
      const option = document.createElement("option");
      option.value = model.id;
      option.label = model.name;
      datalist.appendChild(option);
    });
  } catch (e) {
    // Autocomplete is a convenience, not core functionality — fail silently
    // and leave the custom model input usable without suggestions.
  }
}

function renderFrontier(frontier) {
  const container = document.getElementById("frontier-list");
  container.innerHTML = "";
  frontier.forEach((model) => {
    const color = state.catalog.providers[model.provider].color;
    container.appendChild(modelBadge(model, color));
  });
}

function renderProviders(providers) {
  const container = document.getElementById("provider-list");
  container.innerHTML = "";
  Object.entries(providers).forEach(([providerId, provider]) => {
    const block = document.createElement("div");
    block.className = "provider-block";
    block.innerHTML = `<h3 style="color:${provider.color}">${providerId}</h3><p class="provider-blurb">${provider.blurb}</p>`;
    const grid = document.createElement("div");
    grid.className = "model-grid";
    provider.models.forEach((model) => grid.appendChild(modelBadge(model, provider.color)));
    block.appendChild(grid);
    container.appendChild(block);
  });
}

function modelBadge(model, color) {
  const el = document.createElement("div");
  el.className = "model-badge";
  el.textContent = model.name;
  el.style.borderColor = color;
  el.style.color = color;
  el.dataset.modelId = model.id;
  el.addEventListener("click", () => toggleModel(model.id, el, color));
  return el;
}

async function toggleModel(modelId, el, color) {
  if (state.selectedModels.has(modelId)) {
    state.selectedModels.delete(modelId);
    el.style.background = "#fff";
    el.style.color = color;
  } else {
    state.selectedModels.add(modelId);
    el.style.background = color;
    el.style.color = "#fff";
    const resp = await fetch(`/api/suggest?model_id=${encodeURIComponent(modelId)}`);
    const data = await resp.json();
    if (data.suggestions.length) {
      const names = data.suggestions.map((m) => m.name).join(", ");
      document.getElementById("run-status").textContent = `Also consider: ${names}`;
    }
  }
}

function addCustomModel() {
  const input = document.getElementById("custom-model-input");
  const modelId = input.value.trim();
  if (!modelId || state.selectedModels.has(modelId)) return;
  state.selectedModels.add(modelId);
  state.customModels.push(modelId);
  input.value = "";
  renderCustomModels();
}

function removeCustomModel(modelId) {
  state.selectedModels.delete(modelId);
  state.customModels = state.customModels.filter((id) => id !== modelId);
  renderCustomModels();
}

function renderCustomModels() {
  const container = document.getElementById("custom-model-list");
  container.innerHTML = "";
  state.customModels.forEach((modelId) => {
    const chip = document.createElement("span");
    chip.className = "custom-model-chip";
    chip.textContent = modelId;
    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.setAttribute("aria-label", `Remove ${modelId}`);
    removeButton.textContent = "×";
    removeButton.addEventListener("click", () => removeCustomModel(modelId));
    chip.appendChild(removeButton);
    container.appendChild(chip);
  });
}

function addTestCase() {
  state.testCases.push({ prompt: "", rubric: "" });
  renderTestCases();
}

function renderTestCases() {
  const container = document.getElementById("testcase-list");
  container.innerHTML = "";
  state.testCases.forEach((tc, i) => {
    const row = document.createElement("div");
    row.className = "testcase-row";
    row.innerHTML = `
      <textarea placeholder="Prompt" data-idx="${i}" data-field="prompt">${tc.prompt}</textarea>
      <input type="text" placeholder="Rubric (optional)" data-idx="${i}" data-field="rubric" value="${tc.rubric}">
    `;
    container.appendChild(row);
  });
  container.querySelectorAll("[data-field]").forEach((el) => {
    el.addEventListener("input", (e) => {
      const idx = Number(e.target.dataset.idx);
      state.testCases[idx][e.target.dataset.field] = e.target.value;
    });
  });
}

async function uploadPolicy(file) {
  const formData = new FormData();
  formData.append("file", file);
  const resp = await fetch("/api/policy", { method: "POST", body: formData });
  const data = await resp.json();
  document.getElementById("policy-status").textContent = data.ok ? "Policy loaded." : "Failed to load policy.";
}

async function runComparison() {
  const runStatus = document.getElementById("run-status");
  if (!apiKey()) {
    runStatus.textContent = "Enter your OpenRouter API key first.";
    return;
  }
  if (state.selectedModels.size === 0) {
    runStatus.textContent = "Pick at least one model.";
    return;
  }

  runStatus.textContent = "Running...";
  const resp = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      test_cases: state.testCases,
      models: Array.from(state.selectedModels),
      api_key: apiKey(),
    }),
  });

  if (resp.status === 429) {
    const data = await resp.json();
    const resetDate = new Date(data.reset_at * 1000);
    runStatus.textContent = `Rate limit reached. Try again after ${resetDate.toLocaleTimeString()}.`;
    return;
  }

  if (!resp.ok) {
    const data = await resp.json();
    runStatus.textContent = `Error: ${data.error}`;
    return;
  }

  const data = await resp.json();
  runStatus.textContent = "";
  state.runs.push(data);
  showRun(data.run_id);
}

function renderHistory() {
  const section = document.getElementById("history-section");
  const strip = document.getElementById("history-strip");
  if (state.runs.length === 0) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  strip.innerHTML = "";
  [...state.runs].reverse().forEach((run) => {
    const tab = document.createElement("div");
    tab.className = "history-tab" + (run.run_id === state.activeRunId ? " active" : "");
    const time = new Date(run.created_at * 1000).toLocaleTimeString();
    tab.textContent = run.verdict.winner ? `${time} · ${run.verdict.winner}` : time;
    tab.addEventListener("click", () => showRun(run.run_id));
    strip.appendChild(tab);
  });
}

function showRun(runId) {
  const run = state.runs.find((r) => r.run_id === runId);
  if (!run) return;
  state.activeRunId = runId;
  renderHistory();
  renderResults(run);
}

const CATEGORY_LABELS = {
  accuracy: ["Accuracy", "#4285F4"],
  rule_checks: ["Checks", "#0668E1"],
  cost_efficiency: ["Cost Eff.", "#1e8e3e"],
  speed: ["Speed", "#f9ab00"],
};

function renderCategoryChips(categories) {
  if (!categories) return "";
  return Object.entries(CATEGORY_LABELS)
    .filter(([key]) => categories[key] !== undefined && categories[key] !== null)
    .map(([key, [label, color]]) => `
      <span class="category-chip" style="border-color:${color}; color:${color}">
        ${label} ${Math.round(categories[key])}
      </span>
    `)
    .join("");
}

function renderCategoryChart(grades) {
  const canvas = document.getElementById("category-chart");
  if (state.categoryChart) {
    state.categoryChart.destroy();
    state.categoryChart = null;
  }

  const modelIds = Object.keys(grades).filter((id) => grades[id].categories);
  if (modelIds.length === 0) return;

  const datasets = Object.entries(CATEGORY_LABELS).map(([key, [label, color]]) => ({
    label,
    data: modelIds.map((id) => grades[id].categories[key] ?? 0),
    backgroundColor: color,
  }));

  state.categoryChart = new Chart(canvas, {
    type: "bar",
    data: { labels: modelIds, datasets },
    options: {
      responsive: true,
      scales: { y: { beginAtZero: true, max: 100, title: { display: true, text: "Score (0-100)" } } },
      plugins: { legend: { position: "bottom" } },
    },
  });
}

function renderResults(data) {
  document.getElementById("results-section").hidden = false;

  const verdictEl = document.getElementById("verdict-banner");
  verdictEl.textContent = data.verdict.winner
    ? `${data.verdict.winner}: ${data.verdict.rationale}`
    : "No verdict available.";

  renderCategoryChart(data.grades);

  const leaderboardEl = document.getElementById("leaderboard");
  leaderboardEl.innerHTML = "";
  Object.entries(data.grades).forEach(([modelId, grade]) => {
    const modelStats = (data.stats && data.stats[modelId]) || {};
    const row = document.createElement("div");
    row.className = "leaderboard-row";
    const gradeClass = letterToClass(grade.letter);
    const metaBits = [];
    if (modelStats.total_cost_usd !== undefined) metaBits.push(`$${modelStats.total_cost_usd.toFixed(4)}`);
    if (modelStats.avg_latency_ms !== undefined) metaBits.push(`${Math.round(modelStats.avg_latency_ms)}ms avg`);
    row.innerHTML = `
      <span class="leaderboard-model">${modelId}</span>
      <span class="grade-badge ${gradeClass}">${grade.letter || "N/A"}</span>
      <span class="leaderboard-meta">${grade.score ?? "N/A"}/100${metaBits.length ? " · " + metaBits.join(" · ") : ""}</span>
      <span class="category-chips">${renderCategoryChips(grade.categories)}</span>
      <span class="leaderboard-sentence">${grade.sentence}</span>
    `;
    leaderboardEl.appendChild(row);
  });

  const gridEl = document.getElementById("results-grid");
  gridEl.innerHTML = "";
  data.results.forEach((row) => {
    const promptHeader = document.createElement("h3");
    promptHeader.textContent = row.test_case.prompt;
    gridEl.appendChild(promptHeader);

    if (row.best_model && row.best_model.model_id) {
      const recommendationEl = document.createElement("div");
      recommendationEl.className = "best-model-banner";
      recommendationEl.innerHTML = `<strong>Recommended: ${row.best_model.model_id}</strong> — ${row.best_model.reason}`;
      gridEl.appendChild(recommendationEl);
    }

    Object.entries(row.cells).forEach(([modelId, cell]) => {
      const cellEl = document.createElement("div");
      cellEl.className = "results-cell";
      if (cell.blocked) {
        cellEl.innerHTML = `<span class="status-blocked">[${modelId}] BLOCKED: ${cell.policy_clause} — ${cell.policy_reason}</span>`;
      } else if (cell.error) {
        cellEl.innerHTML = `<span class="status-fail">[${modelId}] ERROR: ${cell.error}</span>`;
      } else {
        cellEl.innerHTML = `<strong>${modelId}</strong><p>${cell.response_text}</p>`;
      }
      gridEl.appendChild(cellEl);
    });
  });
}

function triggerDownload(url, filename) {
  // A same-origin <a download> is honored as a forced download by every
  // modern browser, unlike navigating via window.location.href — some
  // browsers (Safari in particular) can still preview a PDF inline on a
  // direct navigation even when the server sends Content-Disposition:
  // attachment.
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function downloadReport() {
  if (!state.activeRunId) return;
  triggerDownload(`/api/report?run_id=${encodeURIComponent(state.activeRunId)}`, "evalforge-report.pdf");
}

function downloadCsv() {
  if (!state.activeRunId) return;
  triggerDownload(`/api/report.csv?run_id=${encodeURIComponent(state.activeRunId)}`, "evalforge-report.csv");
}

document.getElementById("add-testcase").addEventListener("click", addTestCase);
document.getElementById("add-custom-model").addEventListener("click", addCustomModel);
document.getElementById("custom-model-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    addCustomModel();
  }
});
document.getElementById("run-button").addEventListener("click", runComparison);
document.getElementById("download-report").addEventListener("click", downloadReport);
document.getElementById("download-csv").addEventListener("click", downloadCsv);
document.getElementById("policy-file").addEventListener("change", (e) => {
  if (e.target.files[0]) uploadPolicy(e.target.files[0]);
});

function toggleMenu(open) {
  document.getElementById("mobile-menu").classList.toggle("open", open);
  document.getElementById("menu-overlay").hidden = !open;
  document.getElementById("menu-toggle").setAttribute("aria-expanded", String(open));
}

document.getElementById("menu-toggle").addEventListener("click", () => toggleMenu(true));
document.getElementById("menu-overlay").addEventListener("click", () => toggleMenu(false));
document.querySelectorAll("#mobile-menu a").forEach((link) => {
  link.addEventListener("click", () => toggleMenu(false));
});

loadCatalog();
loadAllModelsDatalist();
addTestCase();
