const state = {
  catalog: null,
  allModels: [],  // OpenRouter's full live catalog, used for autocomplete and the
                  // "+N more" expansion under each curated provider section
  testCases: [],
  selectedModels: new Set(),
  activeTags: new Set(),  // picker filter chips; filtering never alters selectedModels
  vertexServiceAccount: null,   // service-account JSON text; lives only in this tab's memory
  customModels: [],
  runs: [],       // full /api/run responses seen this page load, oldest first
  activeRunId: null,
  categoryChart: null,
  lastGrades: null, // grades from the currently-displayed run, kept so the chart
                     // can be redrawn with correct colors if the theme changes
};

const BACKEND_LABELS = { openrouter: "OpenRouter", bedrock: "Amazon Bedrock", vertex: "Google Vertex AI", foundry: "Microsoft Foundry" };

const PROVIDER_LINKS = {
  openrouter: { status: "https://status.openrouter.ai",
                report: "https://openrouter.ai/docs/guides/overview/report-feedback" },
  bedrock: { status: "https://health.aws.amazon.com/health/status",
             report: "https://console.aws.amazon.com/support/home" },
  vertex: { status: "https://status.cloud.google.com",
            report: "https://cloud.google.com/support-hub" },
  foundry: { status: "https://azure.status.microsoft/en-us/status",
             report: "https://azure.microsoft.com/en-us/support/create-ticket" },
};

const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}

// ---------- Error popup ----------
// Shows the full error text (including the provider's response body, already
// scrubbed of credentials server-side) so users can troubleshoot, copy it, or
// file a GitHub issue.
const ISSUES_URL = "https://github.com/thejaredchapman/evalforge-lite/issues/new";
const MAX_ISSUE_DETAILS = 4000;

function showErrorDialog(title, summary, details, backend) {
  const dialog = document.getElementById("error-dialog");
  document.getElementById("error-dialog-title").textContent = title;
  document.getElementById("error-dialog-summary").textContent = summary;
  document.getElementById("error-dialog-details").textContent = details;
  document.getElementById("error-dialog-status").textContent = "";

  const issueDetails = details.length > MAX_ISSUE_DETAILS
    ? `${details.slice(0, MAX_ISSUE_DETAILS)}\n[truncated]`
    : details;
  const params = new URLSearchParams({
    template: "bug_report.md",
    title: `[Error] ${title}`,
    body: `**What happened:** ${summary}\n\n**Error details:**\n\`\`\`\n${issueDetails}\n\`\`\`\n\n**Steps to reproduce:**\n1. \n\n**Backend(s) and model(s):**\n`,
  });
  document.getElementById("error-dialog-report").href = `${ISSUES_URL}?${params}`;

  const statusLink = document.getElementById("error-dialog-status-link");
  const providerReportLink = document.getElementById("error-dialog-provider-report-link");
  const links = backend && PROVIDER_LINKS[backend];
  if (links) {
    statusLink.href = links.status;
    statusLink.textContent = `Check ${BACKEND_LABELS[backend]} status`;
    statusLink.hidden = false;
    providerReportLink.href = links.report;
    providerReportLink.textContent = `Report to ${BACKEND_LABELS[backend]}`;
    providerReportLink.hidden = false;
  } else {
    statusLink.hidden = true;
    providerReportLink.hidden = true;
  }

  if (!dialog.open) dialog.showModal();
}

function errorText(data, fallback) {
  return (data && typeof data.error === "string" && data.error) || fallback;
}

async function readJson(resp) {
  try {
    return await resp.json();
  } catch {
    return null;
  }
}

function showCellErrors(run) {
  const failures = [];
  (run.results || []).forEach((row) => {
    Object.entries(row.cells || {}).forEach(([modelId, cell]) => {
      if (cell.error) failures.push({ modelId, prompt: row.test_case.prompt, error: cell.error });
    });
  });
  if (failures.length === 0) return;
  const details = failures
    .map((f) => `Model: ${f.modelId}\nPrompt: ${f.prompt}\n${f.error}`)
    .join("\n\n----------\n\n");
  const backends = new Set(failures.map((f) => targetBackend(f.modelId)));
  const backend = backends.size === 1 ? [...backends][0] : null;
  showErrorDialog(
    failures.length === 1 ? "A model call failed" : `${failures.length} model calls failed`,
    "The run finished, but some models returned errors. The provider's full response is below.",
    details,
    backend,
  );
}

// Network failures (server down, connection dropped) reject fetch() before any
// response exists; surface those in the same popup instead of failing silently.
window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  const details = (reason && (reason.stack || reason.message)) || String(reason);
  const runStatus = document.getElementById("run-status");
  if (runStatus && runStatus.textContent === "Running...") runStatus.textContent = "Error: request failed.";
  showErrorDialog(
    "Request failed",
    "The app couldn't reach the server or got an unexpected response. Check that the app is still running and try again.",
    details,
  );
});

document.getElementById("error-dialog-close").addEventListener("click", () => {
  document.getElementById("error-dialog").close();
});

document.getElementById("error-dialog-copy").addEventListener("click", async () => {
  const status = document.getElementById("error-dialog-status");
  const details = document.getElementById("error-dialog-details").textContent;
  try {
    await navigator.clipboard.writeText(details);
    status.textContent = "Copied to clipboard.";
  } catch {
    status.textContent = "Copy failed. Select the text above and copy it manually.";
  }
});

function maxModels() {
  return (state.catalog && state.catalog.max_models) || 4;
}

function capMessage() {
  return `You can compare up to ${maxModels()} models — deselect one first.`;
}

function atCap() {
  return state.selectedModels.size >= maxModels();
}

// How many selected targets belong to this provider (curated ids or live "<provider>/..." ids).
function providerSelectedCount(providerId) {
  const ids = new Set(state.catalog.providers[providerId].models.map((m) => m.id));
  let n = 0;
  state.selectedModels.forEach((target) => {
    const { modelId } = splitTarget(target);
    if (ids.has(modelId) || modelId.startsWith(`${providerId}/`)) n += 1;
  });
  return n;
}

function rowHasSelection(row) {
  return Array.from(row.querySelectorAll("[data-target]")).some((el) => state.selectedModels.has(el.dataset.target));
}

function syncSelectionVisuals() {
  const cap = PickerCore.capState(state.selectedModels.size, maxModels());
  document.querySelectorAll("[data-target]").forEach((el) => {
    const selected = state.selectedModels.has(el.dataset.target);
    if (el.type === "checkbox") {
      el.checked = selected;
      el.disabled = cap.atCap && !selected;
      if (el.disabled) el.title = capMessage();
      else el.removeAttribute("title");
    } else {
      el.classList.toggle("selected", selected);
    }
  });
  if (state.catalog) document.querySelectorAll(".provider-dropdown").forEach((details) => {
    const n = providerSelectedCount(details.dataset.provider);
    details.querySelector(".provider-selected").textContent = n ? `${n} selected` : "";
  });
  updateSelectionMeta();
  syncRegionWarnings();
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

  const foundryResource = fieldValue("foundry-resource");
  const foundryRegion = fieldValue("foundry-region");
  if (foundryResource && foundryRegion) {
    if (checkedValue("foundry-auth") === "api_key") {
      const apiKey = fieldValue("foundry-api-key");
      if (apiKey) creds.foundry = { resource: foundryResource, region: foundryRegion, api_key: apiKey };
    } else {
      const accessToken = fieldValue("foundry-access-token");
      if (accessToken) creds.foundry = { resource: foundryResource, region: foundryRegion, access_token: accessToken };
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

function populateRegionSelect(selectId, regions) {
  const select = document.getElementById(selectId);
  const previous = select.value;
  select.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Select a region";
  select.appendChild(placeholder);
  regions.forEach((region) => {
    const option = document.createElement("option");
    option.value = region.id;
    option.textContent = `${region.label} (${region.id})`;
    select.appendChild(option);
  });
  if (regions.some((r) => r.id === previous)) select.value = previous;
}

function selectedRegion(backend) {
  const el = document.getElementById(`${backend}-region`);
  return el ? el.value : "";
}

function regionWarnings() {
  const warnings = [];
  state.selectedModels.forEach((target) => {
    const { backend, modelId } = splitTarget(target);
    if (backend === "openrouter") return;
    const region = selectedRegion(backend);
    if (!region) return;
    const model = catalogModel(modelId);
    const route = model && model.routes && model.routes[backend];
    const regions = route && route.regions;
    if (!regions || regions.includes(region)) return;
    warnings.push({ target, backend, region, regions });
  });
  return warnings;
}

function warningText(w) {
  return `Not listed in ${w.region} — available in ${w.regions.join(", ")}. Switch region in the ${BACKEND_LABELS[w.backend]} tab.`;
}

function syncRegionWarnings() {
  const warnings = regionWarnings();
  const warningByTarget = new Map(warnings.map((w) => [w.target, w]));

  document.querySelectorAll(".backend-check[data-target]").forEach((checkbox) => {
    const target = checkbox.dataset.target;
    const label = checkbox.closest("label");
    const warning = warningByTarget.get(target);
    let markEl = label.querySelector(".region-warning-mark");
    if (warning) {
      if (!markEl) {
        markEl = document.createElement("span");
        markEl.className = "region-warning-mark";
        markEl.textContent = "⚠";
        label.appendChild(markEl);
      }
      label.title = warningText(warning);
    } else {
      if (markEl) markEl.remove();
      label.title = `Run via ${BACKEND_LABELS[targetBackend(target)]}`;
    }
  });

  const lineEl = document.getElementById("region-warning-line");
  if (warnings.length === 0) {
    lineEl.hidden = true;
    lineEl.textContent = "";
    return;
  }
  lineEl.hidden = false;
  lineEl.innerHTML = "";
  const intro = document.createElement("p");
  intro.textContent = `${warnings.length} selected model${warnings.length > 1 ? "s" : ""} may not be available in your chosen region:`;
  lineEl.appendChild(intro);
  warnings.forEach((w) => {
    const p = document.createElement("p");
    p.textContent = warningText(w);
    lineEl.appendChild(p);
  });
  const link = document.createElement("a");
  link.href = "/availability";
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "See full availability";
  lineEl.appendChild(link);
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
  ["bedrock", "vertex", "foundry"].forEach((group) => {
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
  renderTagFilters();
  renderProviders(catalogData.providers);
  applyFilters();
  populateModelsDatalist(state.allModels);
  if (catalogData.regions) {
    populateRegionSelect("bedrock-region", catalogData.regions.bedrock.regions);
    populateRegionSelect("vertex-region", catalogData.regions.vertex.regions);
    populateRegionSelect("foundry-region", catalogData.regions.foundry.regions);
  }
  syncSelectionVisuals();
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

const BACKEND_SHORT = { openrouter: "OpenRouter", bedrock: "Bedrock", vertex: "Vertex", foundry: "Foundry" };

function tagLabel(tagId) {
  const tag = state.catalog.tags.tags.find((t) => t.id === tagId);
  return tag ? tag.label : tagId;
}

function renderFrontier(frontier) {
  const container = document.getElementById("frontier-list");
  container.innerHTML = "";
  frontier.forEach((model) => {
    container.appendChild(modelBadge(model, state.catalog.providers[model.provider].color));
  });
}

function modelBadge(model, color) {
  const el = document.createElement("div");
  el.className = "model-badge";
  el.textContent = model.name;
  el.style.setProperty("--accent", color);
  el.dataset.target = model.id;
  el.title = "Run via OpenRouter";
  el.addEventListener("click", () => toggleTarget(model.id));
  return el;
}

function renderTagFilters() {
  const root = document.getElementById("tag-filters");
  const tagData = state.catalog.tags;
  root.innerHTML = "";
  [["need", "What do you need?"], ["industry", "Industry"]].forEach(([kind, heading]) => {
    const row = document.createElement("div");
    row.className = "tag-row";
    row.setAttribute("role", "group");
    row.setAttribute("aria-labelledby", `tag-row-label-${kind}`);
    const label = document.createElement("span");
    label.className = "tag-row-label";
    label.id = `tag-row-label-${kind}`;
    label.textContent = heading;
    row.appendChild(label);
    tagData.tags.filter((t) => t.kind === kind).forEach((tag) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "tag-chip";
      chip.dataset.tagId = tag.id;
      chip.textContent = tag.label;
      chip.setAttribute("aria-pressed", "false");
      chip.addEventListener("click", () => {
        if (state.activeTags.has(tag.id)) state.activeTags.delete(tag.id);
        else state.activeTags.add(tag.id);
        applyFilters();
      });
      row.appendChild(chip);
    });
    root.appendChild(row);
  });

  const why = document.createElement("div");
  why.id = "tag-why";
  root.appendChild(why);

  const status = document.createElement("div");
  status.className = "filter-status";
  const count = document.createElement("span");
  count.id = "filter-count";
  count.setAttribute("aria-live", "polite");
  const clear = document.createElement("button");
  clear.type = "button";
  clear.id = "clear-filters";
  clear.className = "secondary";
  clear.textContent = "Clear filters";
  clear.addEventListener("click", () => {
    state.activeTags.clear();
    applyFilters();
  });
  status.appendChild(count);
  status.appendChild(clear);
  root.appendChild(status);

  const note = document.createElement("p");
  note.className = "tag-disclaimer";
  note.textContent = `Tags curated as of ${tagData.verified}. A starting point, not a benchmark — verify on your own.`;
  root.appendChild(note);
}

// Filtering only hides rows; it never touches state.selectedModels.
function applyFilters() {
  const active = Array.from(state.activeTags);
  const curated = Object.values(state.catalog.providers).flatMap((p) => p.models);
  const visible = new Set(PickerCore.filterModels(curated, active).map((m) => m.id));

  document.querySelectorAll(".curated-rows .model-row").forEach((row) => {
    // a selected model's row stays visible so it can always be unticked
    row.hidden = !visible.has(row.dataset.modelId) && !rowHasSelection(row);
  });
  document.querySelectorAll(".live-group").forEach((group) => {
    // live extras have no tags: hide them while filtering, except selected ones
    let any = false;
    group.querySelectorAll(".model-row").forEach((row) => {
      row.hidden = active.length > 0 && !rowHasSelection(row);
      if (!row.hidden) any = true;
    });
    group.hidden = !any;
  });
  document.querySelectorAll(".provider-dropdown").forEach((details) => {
    const hasMatch = !!details.querySelector(".model-row:not([hidden])");
    details.hidden = active.length > 0 && !hasMatch && providerSelectedCount(details.dataset.provider) === 0;
    if (active.length > 0 && hasMatch) details.open = true;
  });

  document.querySelectorAll(".tag-chip").forEach((chip) => {
    chip.setAttribute("aria-pressed", String(state.activeTags.has(chip.dataset.tagId)));
  });
  const why = document.getElementById("tag-why");
  why.innerHTML = "";
  active.forEach((id) => {
    const tag = state.catalog.tags.tags.find((t) => t.id === id);
    const p = document.createElement("p");
    p.className = "tag-why";
    p.textContent = `${tag.label}: ${tag.why}`;
    why.appendChild(p);
  });
  document.getElementById("filter-count").textContent = `Showing ${visible.size} of ${curated.length} models`;
  document.getElementById("clear-filters").hidden = active.length === 0;
}

function modelRow(model, color) {
  const row = document.createElement("div");
  row.className = "model-row";
  row.dataset.modelId = model.id;
  row.style.setProperty("--accent", color);

  const name = document.createElement("span");
  name.className = "model-row-name";
  name.textContent = model.name;
  row.appendChild(name);

  if (model.reasoning) {
    const badge = document.createElement("span");
    badge.className = "reasoning-badge";
    badge.textContent = "Reasoning";
    badge.title = "Supports extended reasoning";
    row.appendChild(badge);
  }
  (model.tags || []).forEach((id) => {
    const pill = document.createElement("span");
    pill.className = "tag-pill";
    pill.textContent = tagLabel(id);
    row.appendChild(pill);
  });

  const checks = document.createElement("div");
  checks.className = "backend-checks";
  PickerCore.targetsForModel(model).forEach(({ target, backend }) => {
    const label = document.createElement("label");
    label.className = "backend-check-label";
    label.title = `Run via ${BACKEND_LABELS[backend]}`;
    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "backend-check";
    box.dataset.target = target;
    box.setAttribute("aria-label", `${model.name} via ${BACKEND_LABELS[backend]}`);
    box.addEventListener("change", () => toggleTarget(target));
    label.appendChild(box);
    label.appendChild(document.createTextNode(BACKEND_SHORT[backend]));
    checks.appendChild(label);
  });
  row.appendChild(checks);
  return row;
}

function renderProviders(providers) {
  const container = document.getElementById("provider-list");
  container.innerHTML = "";
  Object.entries(providers).forEach(([providerId, provider]) => {
    const details = document.createElement("details");
    details.className = "provider-dropdown";
    details.dataset.provider = providerId;
    details.style.setProperty("--accent", provider.color);

    const summary = document.createElement("summary");
    const nameEl = document.createElement("span");
    nameEl.className = "provider-name";
    nameEl.textContent = providerId;
    const countEl = document.createElement("span");
    countEl.className = "provider-count";
    countEl.textContent = `${provider.models.length} models`;
    const selectedEl = document.createElement("span");
    selectedEl.className = "provider-selected";
    summary.append(nameEl, countEl, selectedEl);
    details.appendChild(summary);

    const blurb = document.createElement("p");
    blurb.className = "provider-blurb";
    blurb.textContent = provider.blurb;
    details.appendChild(blurb);

    const curatedRows = document.createElement("div");
    curatedRows.className = "curated-rows";
    provider.models.forEach((model) => curatedRows.appendChild(modelRow(model, provider.color)));
    details.appendChild(curatedRows);

    const curatedIds = new Set(provider.models.map((m) => m.id));
    const moreModels = state.allModels
      .filter((m) => m.id.startsWith(`${providerId}/`) && !curatedIds.has(m.id) && !m.id.includes(":batch"))
      .sort((a, b) => (b.created || 0) - (a.created || 0))
      .slice(0, 10);
    if (moreModels.length > 0) {
      const group = document.createElement("div");
      group.className = "live-group";
      const heading = document.createElement("p");
      heading.className = "live-heading";
      heading.textContent = "More from OpenRouter's live catalog";
      group.appendChild(heading);
      moreModels.forEach((model) => group.appendChild(modelRow(model, provider.color)));
      details.appendChild(group);
    }
    container.appendChild(details);
  });
}

async function toggleTarget(target) {
  if (state.selectedModels.has(target)) {
    state.selectedModels.delete(target);
    if (state.customModels.includes(target)) {
      state.customModels = state.customModels.filter((id) => id !== target);
      renderCustomModels();
    }
    syncSelectionVisuals();
    return;
  }
  if (atCap()) {
    document.getElementById("run-status").textContent = capMessage();
    syncSelectionVisuals(); // un-check a box the browser just ticked
    return;
  }
  state.selectedModels.add(target);
  syncSelectionVisuals();
  if (targetBackend(target) !== "openrouter") return;
  try {
    const resp = await fetch(`/api/suggest?model_id=${encodeURIComponent(target)}`);
    const data = await resp.json();
    if (data.suggestions.length) {
      const names = data.suggestions.map((m) => m.name).join(", ");
      document.getElementById("run-status").textContent = `Also consider: ${names}`;
    }
  } catch (e) {
    // suggestions are a convenience; fail soft
  }
}

function addCustomModel() {
  const input = document.getElementById("custom-model-input");
  const modelId = input.value.trim();
  if (!modelId || state.selectedModels.has(modelId)) return;
  if (atCap()) {
    document.getElementById("run-status").textContent = capMessage();
    return;
  }
  state.selectedModels.add(modelId);
  state.customModels.push(modelId);
  input.value = "";
  renderCustomModels();
  syncSelectionVisuals();
}

function removeCustomModel(modelId) {
  state.selectedModels.delete(modelId);
  state.customModels = state.customModels.filter((id) => id !== modelId);
  renderCustomModels();
  syncSelectionVisuals();
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

const OUTPUT_TOKENS_GUESS = 500;

function catalogModel(modelId) {
  if (!state.catalog) return null;
  for (const provider of Object.values(state.catalog.providers)) {
    const model = provider.models.find((m) => m.id === modelId);
    if (model) return model;
  }
  return null;
}

function splitTarget(target) {
  const backend = targetBackend(target);
  return { backend, modelId: backend === "openrouter" ? target : target.slice(0, target.lastIndexOf("@")) };
}

function priceForTarget(target) {
  const { backend, modelId } = splitTarget(target);
  if (backend !== "openrouter") {
    const model = catalogModel(modelId);
    const price = model && model.routes && model.routes[backend] && model.routes[backend].price;
    return price ? { input: price.input_per_m / 1e6, output: price.output_per_m / 1e6 } : null;
  }
  const live = state.allModels.find((m) => m.id === modelId);
  return live && live.pricing ? { input: live.pricing.prompt, output: live.pricing.completion } : null;
}

function estimateCost() {
  const repeats = Number(document.getElementById("repeats").value || 1);
  let total = 0;
  const unpriced = [];
  state.selectedModels.forEach((target) => {
    const price = priceForTarget(target);
    if (!price) {
      unpriced.push(target);
      return;
    }
    state.testCases.forEach((tc) => {
      const inputTokens = Math.ceil((tc.prompt || "").length / 4);
      total += repeats * (inputTokens * price.input + OUTPUT_TOKENS_GUESS * price.output);
    });
  });
  return { total, unpriced };
}

function updateSelectionMeta() {
  const countText = `Selected ${state.selectedModels.size} / ${maxModels()}`;
  document.getElementById("selection-count").textContent = countText;
  document.getElementById("selection-counter").textContent = countText;
  const el = document.getElementById("cost-estimate");
  if (state.selectedModels.size === 0) {
    el.textContent = "";
    return;
  }
  const { total, unpriced } = estimateCost();
  let text;
  if (unpriced.length === state.selectedModels.size) {
    text = `· Estimated cost: unavailable for ${unpriced.length} model(s)`;
  } else {
    text = `· Estimated cost: ~$${total.toFixed(4)} (rough; excludes judge calls)`;
    if (unpriced.length) text += ` · unavailable for ${unpriced.length} model(s)`;
  }
  el.textContent = text;
}

function addTestCase() {
  state.testCases.push({ prompt: "", rubric: "" });
  renderTestCases();
  updateSelectionMeta();
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
  const data = await readJson(resp);

  if (!resp.ok || !data || data.score === null) {
    const message = (data && (data.error || data.feedback)) || `HTTP ${resp.status} ${resp.statusText}`;
    feedbackEl.textContent = message;
    if (!resp.ok || (data && data.error)) {
      showErrorDialog("Prompt evaluation failed", "The prompt judge could not score this prompt.", message);
    }
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
      updateSelectionMeta();
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
  if (state.selectedModels.size > maxModels()) {
    runStatus.textContent = capMessage();
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
      repeats: Number(document.getElementById("repeats").value || 1),
    }),
  });

  if (resp.status === 429) {
    const data = await resp.json();
    const resetDate = new Date(data.reset_at * 1000);
    runStatus.textContent = `Rate limit reached. Try again after ${resetDate.toLocaleTimeString()}.`;
    return;
  }

  if (!resp.ok) {
    const data = await readJson(resp);
    const message = errorText(data, `HTTP ${resp.status} ${resp.statusText}`);
    runStatus.textContent = `Error: ${message.split("\n")[0]}`;
    showErrorDialog("The comparison run failed", "The server could not complete this run.", message);
    return;
  }

  const data = await resp.json();
  runStatus.textContent = "";
  state.runs.push(data);
  showRun(data.run_id);
  showCellErrors(data);
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

function rawWeightedScore(grade, priority) {
  const weights = state.catalog.priority_weights[priority];
  const cats = grade.categories || {};
  const values = { quality: grade.score, response_time: cats.response_time, throughput: cats.throughput, cost_efficiency: cats.cost_efficiency };
  let total = 0;
  let sum = 0;
  Object.entries(weights).forEach(([key, w]) => {
    if (w > 0 && values[key] !== null && values[key] !== undefined) {
      total += w;
      sum += values[key] * w;
    }
  });
  return total ? sum / total : null;
}

function rankTargets(data, priority) {
  const scored = Object.keys(data.grades).filter((t) => {
    const s = data.stats[t] || {};
    return (s.ok_cells || 0) > 0 && rawWeightedScore(data.grades[t], priority) !== null;
  });
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  return scored.sort((a, b) => {
    const diff = rawWeightedScore(data.grades[b], priority) - rawWeightedScore(data.grades[a], priority);
    if (diff !== 0) return diff;
    const qa = data.grades[a].score ?? -1;
    const qb = data.grades[b].score ?? -1;
    if (qa !== qb) return qb - qa;
    const la = data.stats[a].avg_latency_ms ?? Infinity;
    const lb = data.stats[b].avg_latency_ms ?? Infinity;
    if (la !== lb) return la - lb;
    return cmp(a, b);
  });
}

const COMPARE_METRICS = [["quality", "Quality"], ["response_time", "Response time"], ["throughput", "Speed"], ["cost_efficiency", "Cost"]];

function metricRow(label, value) {
  const wrap = document.createElement("div");
  wrap.className = "metric";
  const text = value === null || value === undefined ? `${label} n/a` : `${label} ${Math.round(value)}/100`;
  wrap.textContent = text;
  const bar = document.createElement("div");
  bar.className = "metric-bar";
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", text);
  const fill = document.createElement("div");
  fill.className = "metric-fill";
  fill.style.width = `${value === null || value === undefined ? 0 : Math.max(0, Math.min(100, value))}%`;
  bar.appendChild(fill);
  wrap.appendChild(bar);
  return wrap;
}

function renderCompareGrid(data) {
  const grid = document.getElementById("compare-grid");
  grid.innerHTML = "";
  const priority = document.getElementById("priority").value;
  const ranking = rankTargets(data, priority);
  const best = ranking.length > 1 ? ranking[0] : null;

  Object.entries(data.grades).forEach(([target, grade]) => {
    const stats = data.stats[target] || {};
    const cats = grade.categories || {};
    const col = document.createElement("div");
    col.className = "compare-col" + (target === best ? " best" : "");

    if (target === best) {
      const badge = document.createElement("span");
      badge.className = "best-badge";
      badge.textContent = `Best for ${state.catalog.priority_labels[priority]}`;
      col.appendChild(badge);
    }
    const title = document.createElement("p");
    title.className = "compare-title";
    title.textContent = `${target} · ${grade.letter || "N/A"}`;
    col.appendChild(title);

    if ((stats.ok_cells || 0) === 0) {
      const none = document.createElement("p");
      none.className = "status-fail";
      none.textContent = `No successful responses (${stats.error_cells || 0} errors, ${stats.blocked_cells || 0} blocked)`;
      col.appendChild(none);
      grid.appendChild(col);
      return;
    }

    COMPARE_METRICS.forEach(([key, label]) => col.appendChild(metricRow(label, key === "quality" ? grade.score : cats[key])));

    const model = catalogModel(splitTarget(target).modelId);
    const approx = model && model.reasoning ? "≈ " : "";
    const raw = document.createElement("p");
    raw.className = "compare-raw";
    const latency = `${Math.round(stats.avg_latency_ms)} ms${stats.avg_latency_stdev_ms ? ` ± ${Math.round(stats.avg_latency_stdev_ms)}` : ""}`;
    const speed = stats.avg_tokens_per_sec ? `${approx}${stats.avg_tokens_per_sec} tok/s` : "speed n/a";
    raw.textContent = `${latency} · ${speed} · $${(stats.total_cost_usd || 0).toFixed(4)}`;
    col.appendChild(raw);

    const evalAvg = (stats.evaluation_avg || {}).overall_avg;
    if (evalAvg !== null && evalAvg !== undefined) {
      const evalP = document.createElement("p");
      evalP.className = "compare-eval";
      evalP.textContent = `Overall eval ${evalAvg.toFixed(1)}/5`;
      col.appendChild(evalP);
    }

    const vsFastest = stats.latency_vs_fastest;
    if (vsFastest !== null && vsFastest !== undefined) {
      const latencyP = document.createElement("p");
      latencyP.className = "compare-latency";
      latencyP.textContent = vsFastest === 1
        ? "Fastest"
        : `${vsFastest.toFixed(1)}x slower than fastest (${Math.round(stats.avg_latency_ms)} ms)`;
      col.appendChild(latencyP);
    }

    const suggestion = (data.suggestions || {})[target];
    const sugEl = document.createElement("div");
    sugEl.className = "compare-suggestion";
    if (suggestion) {
      const text = document.createElement("p");
      text.textContent = `Try ${suggestion.name}: ${suggestion.reason}`;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = "Try it";
      button.setAttribute("aria-label", `Swap ${target} for ${suggestion.model_id} in your selection`);
      button.addEventListener("click", () => tryIt(target, suggestion.model_id));
      sugEl.append(text, button);
    } else {
      sugEl.textContent = "Good fit — no better option in this catalog.";
    }
    col.appendChild(sugEl);
    grid.appendChild(col);
  });

  const judgeLine = document.getElementById("judge-line");
  judgeLine.textContent = data.judge ? `Judged by ${data.judge.model} via ${BACKEND_LABELS[data.judge.backend] || data.judge.backend}` : "";

  const adviceBox = document.getElementById("advice-box");
  adviceBox.innerHTML = "";
  const lines = [];
  if (data.advice) {
    lines.push(data.advice);
  } else {
    Object.values(data.suggestions || {}).filter(Boolean).forEach((s) => lines.push(s.reason));
  }
  if (data.bias_note) lines.push(data.bias_note);
  lines.forEach((line) => {
    const p = document.createElement("p");
    p.textContent = line;
    adviceBox.appendChild(p);
  });
  adviceBox.hidden = lines.length === 0;
}

function tryIt(oldTarget, newTarget) {
  const status = document.getElementById("run-status");
  if (state.selectedModels.has(newTarget)) {
    status.textContent = `${newTarget} is already selected.`;
    return;
  }
  if (!state.selectedModels.has(oldTarget) && atCap()) {
    status.textContent = capMessage();
    return;
  }
  state.selectedModels.delete(oldTarget);
  state.selectedModels.add(newTarget);
  if (state.customModels.includes(oldTarget)) {
    state.customModels = state.customModels.filter((id) => id !== oldTarget);
    renderCustomModels();
  }
  syncSelectionVisuals();
  status.textContent = `Swapped ${oldTarget} → ${newTarget}. Click Run comparison to test it.`;
}

const CATEGORY_LABELS = {
  accuracy: ["Accuracy", "#4285F4"],
  rule_checks: ["Checks", "#0668E1"],
  cost_efficiency: ["Cost Eff.", "#1e8e3e"],
  response_time: ["Resp. Time", "#f9ab00"],
  throughput: ["Speed", "#e8710a"],
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

const EVALUATION_CRITERIA = [
  ["quality", "Quality"],
  ["instruction_following", "Instruction following"],
  ["completeness", "Completeness"],
  ["helpfulness", "Helpfulness"],
  ["safety", "Safety"],
];

function answeredBadge(score) {
  if (score === null || score === undefined) return "?";
  if (score >= 4) return "✓";
  if (score === 3) return "~";
  return "✗";
}

function evaluationCardHtml(evaluation) {
  if (!evaluation || !evaluation.available) {
    return `<p class="eval-unavailable">Evaluation unavailable.</p>`;
  }
  const answered = evaluation.answered || {};
  const rows = EVALUATION_CRITERIA.map(([key, label]) => {
    const entry = evaluation[key] || {};
    const score = entry.score;
    const scoreText = score === null || score === undefined ? "n/a" : `${score}/5`;
    const pct = score ? Math.max(0, Math.min(100, (score / 5) * 100)) : 0;
    return `
      <div class="eval-row">
        <span class="eval-row-label">${escapeHtml(label)} <strong>${escapeHtml(scoreText)}</strong></span>
        <div class="eval-bar" role="img" aria-label="${escapeHtml(label)}: ${escapeHtml(scoreText)}">
          <div class="eval-bar-fill" style="width:${pct}%"></div>
        </div>
        <p class="eval-explanation">${escapeHtml(entry.explanation || "")}</p>
      </div>
    `;
  }).join("");

  const strengths = (evaluation.strengths || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("");
  const weaknesses = (evaluation.weaknesses || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("");
  const overallText = evaluation.overall === null || evaluation.overall === undefined ? "n/a" : evaluation.overall;

  return `
    <span class="eval-answered-badge">${escapeHtml(answeredBadge(answered.score))} Answered the question?</span>
    <p class="eval-explanation">${escapeHtml(answered.explanation || "")}</p>
    ${rows}
    ${strengths ? `<p class="eval-list-label">Strengths</p><ul class="eval-list">${strengths}</ul>` : ""}
    ${weaknesses ? `<p class="eval-list-label">Weaknesses</p><ul class="eval-list">${weaknesses}</ul>` : ""}
    <p class="eval-reasoning">${escapeHtml(evaluation.reasoning || "")}</p>
    <span class="eval-overall-badge">Overall ${escapeHtml(overallText)}/5</span>
  `;
}

function latencyNoteFor(row, modelId) {
  const ranking = (row && row.latency_ranking) || [];
  if (ranking.length === 0) return "";
  const idx = ranking.findIndex((r) => r.model_id === modelId);
  if (idx === -1) return "";
  const fastestMs = ranking[0].latency_ms;
  const ms = ranking[idx].latency_ms;
  if (idx === 0) return `Fastest (${Math.round(ms).toLocaleString()} ms)`;
  if (!fastestMs) return `${Math.round(ms).toLocaleString()} ms`;
  const factor = ms / fastestMs;
  return `${factor.toFixed(1)}x slower than fastest (${Math.round(ms).toLocaleString()} ms)`;
}

function renderLatencyPanel(data) {
  const panel = document.getElementById("latency-panel");
  panel.innerHTML = "";
  (data.results || []).forEach((row) => {
    const ranking = row.latency_ranking || [];
    if (ranking.length === 0) return;
    const fastestMs = ranking[0].latency_ms || 1;
    const block = document.createElement("div");
    block.className = "latency-prompt-block";
    const title = document.createElement("p");
    title.className = "latency-prompt-title";
    title.textContent = row.test_case.prompt;
    block.appendChild(title);
    ranking.forEach((entry, i) => {
      const line = document.createElement("div");
      line.className = "latency-bar-row" + (i === 0 ? " fastest" : "");
      const label = document.createElement("span");
      label.className = "latency-bar-label";
      label.textContent = i === 0 ? `${entry.model_id} (fastest)` : entry.model_id;
      const bar = document.createElement("div");
      bar.className = "latency-bar";
      bar.setAttribute("role", "img");
      const pct = entry.latency_ms > 0 ? Math.min(100, (fastestMs / entry.latency_ms) * 100) : 0;
      const msText = `${Math.round(entry.latency_ms).toLocaleString()} ms`;
      bar.setAttribute("aria-label", `${entry.model_id}: ${msText}`);
      const fill = document.createElement("div");
      fill.className = "latency-bar-fill";
      fill.style.width = `${pct}%`;
      bar.appendChild(fill);
      const msLabel = document.createElement("span");
      msLabel.className = "latency-bar-ms";
      msLabel.textContent = msText;
      line.append(label, bar, msLabel);
      block.appendChild(line);
    });
    panel.appendChild(block);
  });

  const avgEntries = Object.entries(data.stats || {}).filter(([, s]) => (s.ok_cells || 0) > 0);
  if (avgEntries.length) {
    const statsBlock = document.createElement("div");
    statsBlock.className = "latency-averages";
    const title = document.createElement("p");
    title.className = "latency-averages-title";
    title.textContent = "Averages across all prompts";
    statsBlock.appendChild(title);
    avgEntries
      .sort((a, b) => (a[1].avg_latency_ms || 0) - (b[1].avg_latency_ms || 0))
      .forEach(([modelId, s], i) => {
        const p = document.createElement("p");
        p.className = "latency-average-line";
        const fastestSuffix = i === 0 ? " (fastest)" : "";
        p.textContent = `${modelId}: ${Math.round(s.avg_latency_ms || 0).toLocaleString()} ms avg${fastestSuffix}`;
        statsBlock.appendChild(p);
      });
    panel.appendChild(statsBlock);
  }

  if (!panel.hasChildNodes()) {
    panel.textContent = "No successful responses to compare.";
  }
}

function renderCostBanner(data) {
  const banner = document.getElementById("cost-banner");
  const cost = data.cost;
  if (!cost) {
    banner.textContent = "";
    return;
  }
  const hasEstimatedBackend = (data.results || []).some((row) =>
    Object.keys(row.cells || {}).some((modelId) => targetBackend(modelId) !== "openrouter")
  );
  const estimateNote = hasEstimatedBackend ? " Estimates for Bedrock/Vertex/Foundry are from catalog prices." : "";
  const callWord = cost.judge_calls === 1 ? "call" : "calls";
  banner.textContent =
    `This run cost ≈ $${cost.total_usd.toFixed(4)} — models $${cost.model_usd.toFixed(4)} + ` +
    `judge $${cost.judge_usd.toFixed(4)} (${cost.judge_calls} judge ${callWord}).${estimateNote}`;
}

function renderResults(data) {
  document.getElementById("results-section").hidden = false;

  renderCostBanner(data);

  const verdictEl = document.getElementById("verdict-banner");
  verdictEl.textContent = data.verdict.winner
    ? `${data.verdict.winner}: ${data.verdict.rationale}`
    : "No verdict available.";

  renderCompareGrid(data);

  renderCategoryChart(data.grades);

  renderLatencyPanel(data);

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
  data.results.forEach((row, rowIndex) => {
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
        cellEl.innerHTML = `<span class="status-fail">[${escapeHtml(modelId)}] ERROR: ${escapeHtml(cell.error.split("\n")[0])}</span>`;
        const detailsButton = document.createElement("button");
        detailsButton.type = "button";
        detailsButton.className = "secondary error-details-button";
        detailsButton.textContent = "Details";
        detailsButton.setAttribute("aria-label", `Show error details for ${modelId}`);
        detailsButton.addEventListener("click", () => {
          showErrorDialog(`${modelId} failed`, `Prompt: ${row.test_case.prompt}`, cell.error, targetBackend(modelId));
        });
        cellEl.appendChild(detailsButton);
      } else {
        const latencyNote = latencyNoteFor(row, modelId);
        cellEl.innerHTML = `
          <strong>${escapeHtml(modelId)}</strong>
          <p>${escapeHtml(cell.response_text)}</p>
          ${latencyNote ? `<p class="eval-latency-note">${escapeHtml(latencyNote)}</p>` : ""}
        `;
        const evalDetails = document.createElement("details");
        evalDetails.className = "eval-card";
        if (rowIndex === 0) evalDetails.open = true;
        const summary = document.createElement("summary");
        summary.textContent = "Evaluation";
        evalDetails.appendChild(summary);
        const evalBody = document.createElement("div");
        evalBody.className = "eval-card-body";
        evalBody.innerHTML = evaluationCardHtml(cell.evaluation);
        evalDetails.appendChild(evalBody);
        cellEl.appendChild(evalDetails);
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
  triggerDownload(`/api/report?run_id=${encodeURIComponent(state.activeRunId)}&priority=${encodeURIComponent(document.getElementById("priority").value)}`, "evalforge-report.pdf");
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
document.getElementById("priority").addEventListener("change", () => {
  const run = state.runs.find((r) => r.run_id === state.activeRunId);
  if (run) renderCompareGrid(run);
});
document.getElementById("repeats").addEventListener("change", updateSelectionMeta);
["bedrock-region", "vertex-region", "foundry-region"].forEach((id) => {
  document.getElementById(id).addEventListener("change", syncRegionWarnings);
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
