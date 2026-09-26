const state = {
  catalog: null,
  allModels: [],  // OpenRouter's full live catalog, used for autocomplete and the
                  // "+N more" expansion under each curated provider section
  testCases: [],
  selectedModels: new Set(),
  vertexServiceAccount: null,   // service-account JSON text; lives only in this tab's memory
  customModels: [],
  runs: [],       // full /api/run responses seen this page load, oldest first
  activeRunId: null,
  categoryChart: null,
  lastGrades: null, // grades from the currently-displayed run, kept so the chart
                     // can be redrawn with correct colors if the theme changes
};

const BACKEND_LABELS = { openrouter: "OpenRouter", bedrock: "Amazon Bedrock", vertex: "Google Vertex AI" };

const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}

function fieldValue(id) {
  return document.getElementById(id).value.trim();
}

function checkedValue(name) {
  return document.querySelector(`input[name="${name}"]:checked`).value;
}

function judgeBackend() {
  return document.getElementById("judge-backend").value;
}

function buildCreds() {
  const creds = {};
  const orKey = fieldValue("api-key");
  if (orKey) creds.openrouter = orKey;

  const bedrockRegion = fieldValue("bedrock-region");
  // A backend only counts as configured once its secret is filled in too, so the
  // "Add … credentials first" check catches a region/project with no key.
  if (bedrockRegion) {
    if (checkedValue("bedrock-auth") === "api_key") {
      const apiKey = fieldValue("bedrock-api-key");
      if (apiKey) creds.bedrock = { region: bedrockRegion, api_key: apiKey };
    } else {
      const accessKeyId = fieldValue("bedrock-access-key-id");
      const secretAccessKey = fieldValue("bedrock-secret-access-key");
      if (accessKeyId && secretAccessKey) {
        creds.bedrock = { region: bedrockRegion, access_key_id: accessKeyId, secret_access_key: secretAccessKey };
        const sessionToken = fieldValue("bedrock-session-token");
        if (sessionToken) creds.bedrock.session_token = sessionToken;
      }
    }
  }

  const vertexProject = fieldValue("vertex-project");
  if (vertexProject) {
    const region = fieldValue("vertex-region") || "us-central1";
    if (checkedValue("vertex-auth") === "access_token") {
      const accessToken = fieldValue("vertex-access-token");
      if (accessToken) creds.vertex = { project: vertexProject, region, access_token: accessToken };
    } else if (state.vertexServiceAccount) {
      creds.vertex = { project: vertexProject, region, service_account_json: state.vertexServiceAccount };
    }
  }
  return creds;
}

function targetBackend(target) {
  const at = target.lastIndexOf("@");
  const suffix = at === -1 ? "" : target.slice(at + 1);
  return BACKEND_LABELS[suffix] ? suffix : "openrouter";
}

function missingBackends(creds) {
  const needed = new Set(Array.from(state.selectedModels).map(targetBackend));
  needed.add(judgeBackend());
  return Array.from(needed).filter((backend) => !creds[backend]);
}

function setupCredsPanel() {
  const tabs = Array.from(document.querySelectorAll("#creds-section .tab"));
  const selectTab = (tab) => {
    tabs.forEach((t) => {
      const active = t === tab;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", active ? "true" : "false");
      t.tabIndex = active ? 0 : -1;
    });
    document.querySelectorAll(".cred-panel").forEach((panel) => {
      panel.hidden = panel.dataset.backend !== tab.dataset.backend;
    });
  };
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      selectTab(next);
      next.focus();
    });
  });
  ["bedrock", "vertex"].forEach((group) => {
    document.querySelectorAll(`input[name="${group}-auth"]`).forEach((radio) => {
      radio.addEventListener("change", () => {
        document.querySelectorAll(`.auth-fields[data-auth-group="${group}"]`).forEach((el) => {
          el.hidden = el.dataset.auth !== radio.value;
        });
      });
    });
  });
  document.getElementById("vertex-sa-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    state.vertexServiceAccount = file ? await file.text() : null;
    document.getElementById("vertex-sa-status").textContent = file ? "Service account loaded (kept in this tab only)." : "";
  });
}

function getStoredTheme() {
  try {
    return localStorage.getItem("evalforge-theme");
  } catch (e) {
    return null;
  }
}

function setStoredTheme(theme) {
  try {
    localStorage.setItem("evalforge-theme", theme);
  } catch (e) {
    // Storage unavailable (private browsing, blocked) — theme just won't persist.
  }
}

function currentTheme() {
  const explicit = document.documentElement.getAttribute("data-theme");
  if (explicit) return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function updateThemeToggleIcon() {
  document.getElementById("theme-toggle").textContent = currentTheme() === "dark" ? "☀️" : "🌙";
}

function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  setStoredTheme(next);
  updateThemeToggleIcon();
  if (state.lastGrades) renderCategoryChart(state.lastGrades);
}

function letterToClass(letter) {
  if (!letter) return "";
  return `grade-${letter[0].toLowerCase()}`;
}

async function loadCatalogAndModels() {
  // Fetched together and rendered only once both resolve, so renderProviders()
  // always has state.allModels available for its "+N more" expansion — rendering
  // providers before the live list arrives would show 0 "more" models every time.
  const catalogPromise = fetch("/api/catalog").then((r) => r.json());
  const modelsPromise = fetch("/api/openrouter-models")
    .then((r) => r.json())
    .catch(() => ({ models: [] })); // autocomplete/expansion is a convenience, fails soft

  const [catalogData, modelsData] = await Promise.all([catalogPromise, modelsPromise]);
  state.catalog = catalogData;
  state.allModels = modelsData.models || [];

  renderFrontier(catalogData.frontier);
  renderProviders(catalogData.providers);
  populateModelsDatalist(state.allModels);
}

function populateModelsDatalist(models) {
  const datalist = document.getElementById("all-models-datalist");
  datalist.innerHTML = "";
  models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.label = model.name;
    datalist.appendChild(option);
  });
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

    const curatedIds = new Set(provider.models.map((m) => m.id));
    const moreModels = state.allModels
      .filter((m) => m.id.startsWith(`${providerId}/`) && !curatedIds.has(m.id) && !m.id.includes(":batch"))
      .sort((a, b) => (b.created || 0) - (a.created || 0))
      .slice(0, 10);
    if (moreModels.length > 0) {
      const moreGrid = document.createElement("div");
      moreGrid.className = "model-grid";
      moreGrid.hidden = true;
      moreModels.forEach((model) => moreGrid.appendChild(modelBadge(model, provider.color)));

      const expandedLabel = "Show fewer";
      const collapsedLabel = `+ ${moreModels.length} more from OpenRouter's live catalog`;
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "secondary show-more-btn";
      toggle.textContent = collapsedLabel;
      toggle.addEventListener("click", () => {
        moreGrid.hidden = !moreGrid.hidden;
        toggle.textContent = moreGrid.hidden ? collapsedLabel : expandedLabel;
      });

      block.appendChild(toggle);
      block.appendChild(moreGrid);
    }

    container.appendChild(block);
  });
}

function modelBadge(model, color) {
  const el = document.createElement("div");
  el.className = "model-badge";
  el.textContent = model.name;
  el.style.setProperty("--accent", color);
  el.dataset.modelId = model.id;
  el.title = "Run via OpenRouter";
  el.addEventListener("click", () => toggleModel(model.id, el));

  const backends = Object.keys(model.routes || {});
  if (!backends.length) return el;

  const wrapper = document.createElement("div");
  wrapper.className = "model-option";
  wrapper.appendChild(el);
  const chips = document.createElement("div");
  chips.className = "backend-chips";
  backends.forEach((backend) => {
    const chip = document.createElement("span");
    chip.className = "backend-chip";
    chip.textContent = backend === "bedrock" ? "Bedrock" : "Vertex";
    chip.title = `Also run via ${BACKEND_LABELS[backend]}`;
    chip.addEventListener("click", () => toggleBackendTarget(`${model.id}@${backend}`, chip));
    chips.appendChild(chip);
  });
  wrapper.appendChild(chips);
  return wrapper;
}

function toggleBackendTarget(target, chip) {
  if (state.selectedModels.has(target)) {
    state.selectedModels.delete(target);
    chip.classList.remove("selected");
  } else {
    state.selectedModels.add(target);
    chip.classList.add("selected");
  }
}

async function toggleModel(modelId, el) {
  if (state.selectedModels.has(modelId)) {
    state.selectedModels.delete(modelId);
    el.classList.remove("selected");
  } else {
    state.selectedModels.add(modelId);
    el.classList.add("selected");
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

async function evaluatePrompt(idx) {
  const feedbackEl = document.querySelector(`.eval-feedback[data-idx="${idx}"]`);
  const prompt = state.testCases[idx].prompt.trim();

  const creds = buildCreds();
  if (!creds[judgeBackend()]) {
    feedbackEl.textContent = `Add ${BACKEND_LABELS[judgeBackend()]} credentials first (the judge runs there).`;
    return;
  }
  if (!prompt) {
    feedbackEl.textContent = "Write a prompt first.";
    return;
  }

  feedbackEl.textContent = "Evaluating...";
  const resp = await fetch("/api/evaluate-prompt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, creds, judge_backend: judgeBackend() }),
  });
  const data = await resp.json();

  if (!resp.ok || data.score === null) {
    feedbackEl.textContent = data.feedback || data.error || "Could not evaluate prompt.";
    return;
  }
  feedbackEl.textContent = `${data.score}/5 — ${data.feedback}`;
}

function renderTestCases() {
  const container = document.getElementById("testcase-list");
  container.innerHTML = "";
  state.testCases.forEach((tc, i) => {
    const row = document.createElement("div");
    row.className = "testcase-row";
    row.innerHTML = `
      <textarea placeholder="Prompt" data-idx="${i}" data-field="prompt">${escapeHtml(tc.prompt)}</textarea>
      <input type="text" placeholder="Rubric (optional)" data-idx="${i}" data-field="rubric" value="${escapeHtml(tc.rubric)}">
      <div class="testcase-eval-row">
        <button type="button" class="secondary evaluate-prompt-btn" data-idx="${i}">Evaluate prompt</button>
        <span class="eval-feedback" data-idx="${i}"></span>
      </div>
    `;
    container.appendChild(row);
  });
  container.querySelectorAll("[data-field]").forEach((el) => {
    el.addEventListener("input", (e) => {
      const idx = Number(e.target.dataset.idx);
      state.testCases[idx][e.target.dataset.field] = e.target.value;
    });
  });
  container.querySelectorAll(".evaluate-prompt-btn").forEach((el) => {
    el.addEventListener("click", (e) => evaluatePrompt(Number(e.target.dataset.idx)));
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
  if (state.selectedModels.size === 0) {
    runStatus.textContent = "Pick at least one model.";
    return;
  }
  const creds = buildCreds();
  const missing = missingBackends(creds);
  if (missing.length) {
    runStatus.textContent = `Add ${missing.map((b) => BACKEND_LABELS[b]).join(" and ")} credentials first.`;
    return;
  }

  runStatus.textContent = "Running...";
  const resp = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      test_cases: state.testCases,
      models: Array.from(state.selectedModels),
      creds,
      judge_backend: judgeBackend(),
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
  state.lastGrades = grades;

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

  const isDark = currentTheme() === "dark";
  const textColor = isDark ? "#e8e8e8" : "#2a2a2a";
  const gridColor = isDark ? "#33363c" : "#eeeeee";

  state.categoryChart = new Chart(canvas, {
    type: "bar",
    data: { labels: modelIds, datasets },
    options: {
      responsive: true,
      scales: {
        y: {
          beginAtZero: true, max: 100,
          title: { display: true, text: "Score (0-100)", color: textColor },
          ticks: { color: textColor },
          grid: { color: gridColor },
        },
        x: { ticks: { color: textColor }, grid: { color: gridColor } },
      },
      plugins: { legend: { position: "bottom", labels: { color: textColor } } },
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
      <span class="leaderboard-model">${escapeHtml(modelId)}</span>
      <span class="grade-badge ${gradeClass}">${escapeHtml(grade.letter || "N/A")}</span>
      <span class="leaderboard-meta">${grade.score ?? "N/A"}/100${metaBits.length ? " · " + metaBits.join(" · ") : ""}</span>
      <span class="category-chips">${renderCategoryChips(grade.categories)}</span>
      <span class="leaderboard-sentence">${escapeHtml(grade.sentence)}</span>
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
      recommendationEl.innerHTML = `<strong>Recommended: ${escapeHtml(row.best_model.model_id)}</strong> — ${escapeHtml(row.best_model.reason)}`;
      gridEl.appendChild(recommendationEl);
    }

    Object.entries(row.cells).forEach(([modelId, cell]) => {
      const cellEl = document.createElement("div");
      cellEl.className = "results-cell";
      if (cell.blocked) {
        cellEl.innerHTML = `<span class="status-blocked">[${escapeHtml(modelId)}] BLOCKED: ${escapeHtml(cell.policy_clause)} — ${escapeHtml(cell.policy_reason)}</span>`;
      } else if (cell.error) {
        cellEl.innerHTML = `<span class="status-fail">[${escapeHtml(modelId)}] ERROR: ${escapeHtml(cell.error)}</span>`;
      } else {
        cellEl.innerHTML = `<strong>${escapeHtml(modelId)}</strong><p>${escapeHtml(cell.response_text)}</p>`;
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

document.getElementById("theme-toggle").addEventListener("click", toggleTheme);
updateThemeToggleIcon();

// Keep the icon and chart in sync if the OS theme changes mid-session and the
// user hasn't made an explicit choice (an explicit choice always wins).
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!document.documentElement.getAttribute("data-theme")) {
    updateThemeToggleIcon();
    if (state.lastGrades) renderCategoryChart(state.lastGrades);
  }
});

setupCredsPanel();
loadCatalogAndModels();
addTestCase();
