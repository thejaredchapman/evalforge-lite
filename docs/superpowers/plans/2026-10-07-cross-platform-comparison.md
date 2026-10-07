# Cross-Platform Comparison Dropdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend-curated "Compare one model across platforms" dropdown whose entries select the same model on OpenRouter/Bedrock/Vertex/Foundry in one click, plus a front-screen note that the list lives in the backend.

**Architecture:** A new advisory data file `data/comparisons.json` (same pattern as `tags.json`/`regions.json`) is loaded by `config.load_comparisons()`, validated and resolved to `{target, backend}` lists by new `catalog` functions, and served through the existing `/api/catalog` response as `comparisons`. The browser renders it above "Browse by provider"; a click replaces the current selection with the entry's targets. The server's existing run validation (`_validate_run_body`, `MAX_MODELS`) stays the only authority; no new endpoint.

**Tech Stack:** Python 3.12 / Flask / pytest; vanilla JS (`static/app.js`, DOM-free `static/picker-core.js` tested with `node --test`); CSS variables in `static/style.css`.

## Global Constraints

Copied from `docs/superpowers/specs/2026-10-07-cross-platform-comparison-design.md` and `CLAUDE.md`:

- Comparable entries come **only from the backend** (`data/comparisons.json`). No UI or API for creating or editing them.
- Clicking an entry **replaces** the current selection with the entry's targets.
- At most `config.MAX_MODELS` (4) targets per entry and per run.
- An entry is invalid when: model not in catalog; a non-OpenRouter backend has no route for the model; model id starts with `~`; fewer than 2 backends; duplicate backends; more backends than `MAX_MODELS`. Invalid entries are dropped with a logged warning at runtime; the shipped file must have **zero** invalid entries (test-enforced).
- Missing/unreadable `comparisons.json` -> `/api/catalog` returns `"comparisons": []`; dropdown and note hidden; everything else keeps working.
- Front-screen note text (verbatim): `Cross-platform comparisons are defined in the backend (data/comparisons.json). To test other model/platform combinations, clone the repository and edit that file.`
- Every test mocks the network; no live calls in the suite.
- `gateway.py` never reads `comparisons.json` (advisory data only).
- UI base font stays `"Courier New", Courier, monospace`; colours via existing CSS variables (`--bg`/`--surface`/`--fg`/`--muted`/`--border`) and per-provider `--accent`.

## File Structure

| File | Responsibility |
|---|---|
| `data/comparisons.json` (new) | Curated list of cross-platform comparisons |
| `config.py` (modify) | `load_comparisons()` |
| `catalog.py` (modify) | `comparison_problem()`, `resolve_comparison()`, `comparison_entries()` |
| `app.py` (modify) | add `comparisons` to `/api/catalog` |
| `static/picker-core.js` (modify) | pure `targetsForComparison(entry, max)` |
| `templates/index.html` (modify) | dropdown container + note |
| `static/app.js` (modify) | `renderComparisons()`, `applyComparison()`, wiring |
| `static/style.css` (modify) | entry/chip styles |
| `tests/test_config.py`, `tests/test_catalog.py`, `tests/test_app.py`, `tests/js/picker.test.mjs` (modify) | tests |
| `docs/comparing-models.md`, `CLAUDE.md` (modify) | docs |

`pyproject.toml` already packages `data/*.json`; no packaging change needed.

---

### Task 1: Data file, loader, and catalog resolution

**Files:**
- Create: `data/comparisons.json`
- Modify: `config.py` (add path constant + loader)
- Modify: `catalog.py` (add logging import and three functions)
- Test: `tests/test_config.py`, `tests/test_catalog.py`

**Interfaces:**
- Produces: `config.load_comparisons() -> dict` (`{"verified": str, "comparisons": [entry, ...]}`)
- Produces: `catalog.comparison_problem(catalog_dict: dict, entry: dict) -> str | None` (reason string if invalid, else `None`)
- Produces: `catalog.resolve_comparison(catalog_dict: dict, entry: dict) -> dict` with keys `id, label, model_id, model_name, provider, targets` where `targets` is `[{"target": str, "backend": str}, ...]` (`target` is the model id for `openrouter`, `"<model id>@<backend>"` otherwise)
- Produces: `catalog.comparison_entries(catalog_dict: dict) -> list[dict]` (resolved, valid, de-duplicated entries; `[]` if the file is missing/unreadable)

- [ ] **Step 1: Write the failing config test**

Append to `tests/test_config.py`:

```python
def test_load_comparisons_returns_verified_date_and_entries():
    data = config.load_comparisons()
    assert data["verified"]
    assert isinstance(data["comparisons"], list)
    assert len(data["comparisons"]) > 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_config.py::test_load_comparisons_returns_verified_date_and_entries -v`
Expected: FAIL with `AttributeError: module 'config' has no attribute 'load_comparisons'`

- [ ] **Step 3: Create the data file**

Create `data/comparisons.json`:

```json
{
  "verified": "2026-10-07",
  "comparisons": [
    {"id": "llama-4-maverick-all", "label": "Llama 4 Maverick on all four platforms", "model": "meta-llama/llama-4-maverick", "backends": ["openrouter", "bedrock", "vertex", "foundry"]},
    {"id": "llama-4-scout-all", "label": "Llama 4 Scout on all four platforms", "model": "meta-llama/llama-4-scout", "backends": ["openrouter", "bedrock", "vertex", "foundry"]},
    {"id": "llama-3-3-70b-all", "label": "Llama 3.3 70B on all four platforms", "model": "meta-llama/llama-3.3-70b-instruct", "backends": ["openrouter", "bedrock", "vertex", "foundry"]},
    {"id": "claude-opus-4-5-or-vs-bedrock", "label": "Claude Opus 4.5: OpenRouter vs Bedrock", "model": "anthropic/claude-opus-4.5", "backends": ["openrouter", "bedrock"]},
    {"id": "claude-sonnet-4-5-or-vs-bedrock", "label": "Claude Sonnet 4.5: OpenRouter vs Bedrock", "model": "anthropic/claude-sonnet-4.5", "backends": ["openrouter", "bedrock"]},
    {"id": "claude-haiku-4-5-or-vs-bedrock", "label": "Claude Haiku 4.5: OpenRouter vs Bedrock", "model": "anthropic/claude-haiku-4.5", "backends": ["openrouter", "bedrock"]},
    {"id": "gpt-5-or-vs-foundry", "label": "GPT-5: OpenRouter vs Foundry", "model": "openai/gpt-5", "backends": ["openrouter", "foundry"]},
    {"id": "gpt-5-mini-or-vs-foundry", "label": "GPT-5 Mini: OpenRouter vs Foundry", "model": "openai/gpt-5-mini", "backends": ["openrouter", "foundry"]},
    {"id": "gpt-4o-or-vs-foundry", "label": "GPT-4o: OpenRouter vs Foundry", "model": "openai/gpt-4o", "backends": ["openrouter", "foundry"]},
    {"id": "gpt-4o-mini-or-vs-foundry", "label": "GPT-4o Mini: OpenRouter vs Foundry", "model": "openai/gpt-4o-mini", "backends": ["openrouter", "foundry"]},
    {"id": "gemini-2-5-pro-or-vs-vertex", "label": "Gemini 2.5 Pro: OpenRouter vs Vertex", "model": "google/gemini-2.5-pro", "backends": ["openrouter", "vertex"]},
    {"id": "gemini-2-5-flash-or-vs-vertex", "label": "Gemini 2.5 Flash: OpenRouter vs Vertex", "model": "google/gemini-2.5-flash", "backends": ["openrouter", "vertex"]}
  ]
}
```

- [ ] **Step 4: Add the loader**

In `config.py`, after the `_TAGS_PATH` line add:

```python
_COMPARISONS_PATH = _DATA_DIR / "comparisons.json"
```

and at the end of the file add:

```python
def load_comparisons():
    with open(_COMPARISONS_PATH) as f:
        return json.load(f)
```

- [ ] **Step 5: Run the config test to verify it passes**

Run: `pytest tests/test_config.py::test_load_comparisons_returns_verified_date_and_entries -v`
Expected: PASS

- [ ] **Step 6: Write the failing catalog tests**

Append to `tests/test_catalog.py`:

```python
import json as _json
import logging as _logging

import pytest


def _set_comparisons(monkeypatch, entries):
    monkeypatch.setattr(config, "load_comparisons", lambda: {"verified": "2026-10-07", "comparisons": entries})


def _entry(**overrides):
    base = {
        "id": "llama-4-maverick-all",
        "label": "Llama 4 Maverick on all four platforms",
        "model": "meta-llama/llama-4-maverick",
        "backends": ["openrouter", "bedrock", "vertex", "foundry"],
    }
    base.update(overrides)
    return base


def test_resolve_comparison_builds_targets_in_backend_order():
    cat = catalog.load_catalog()
    resolved = catalog.resolve_comparison(cat, _entry())
    assert resolved["id"] == "llama-4-maverick-all"
    assert resolved["model_id"] == "meta-llama/llama-4-maverick"
    assert resolved["model_name"] == "Llama 4 Maverick"
    assert resolved["provider"] == "meta-llama"
    assert resolved["targets"] == [
        {"target": "meta-llama/llama-4-maverick", "backend": "openrouter"},
        {"target": "meta-llama/llama-4-maverick@bedrock", "backend": "bedrock"},
        {"target": "meta-llama/llama-4-maverick@vertex", "backend": "vertex"},
        {"target": "meta-llama/llama-4-maverick@foundry", "backend": "foundry"},
    ]


def test_comparison_problem_accepts_a_valid_entry():
    assert catalog.comparison_problem(catalog.load_catalog(), _entry()) is None


@pytest.mark.parametrize("overrides", [
    {"model": "nobody/not-a-model"},
    {"model": "~openai/gpt-latest", "backends": ["openrouter", "foundry"]},
    {"model": "anthropic/claude-opus-4.5", "backends": ["openrouter", "vertex"]},
    {"backends": ["openrouter"]},
    {"backends": ["openrouter", "openrouter"]},
    {"backends": ["openrouter", "bedrock", "vertex", "foundry", "bedrock"]},
    {"backends": ["openrouter", "mainframe"]},
    {"id": ""},
    {"label": ""},
])
def test_comparison_problem_rejects_invalid_entries(overrides):
    assert catalog.comparison_problem(catalog.load_catalog(), _entry(**overrides)) is not None


def test_comparison_entries_drops_invalid_and_duplicate_entries(monkeypatch, caplog):
    _set_comparisons(monkeypatch, [
        _entry(),
        _entry(id="bad", model="nobody/not-a-model"),
        _entry(),  # duplicate id
        "not an object",
    ])
    with caplog.at_level(_logging.WARNING, logger="catalog"):
        entries = catalog.comparison_entries(catalog.load_catalog())
    assert [e["id"] for e in entries] == ["llama-4-maverick-all"]
    assert "bad" in caplog.text


def test_comparison_entries_returns_empty_when_file_missing(monkeypatch):
    def boom():
        raise FileNotFoundError("comparisons.json")
    monkeypatch.setattr(config, "load_comparisons", boom)
    assert catalog.comparison_entries(catalog.load_catalog()) == []


def test_comparison_entries_returns_empty_when_file_malformed(monkeypatch):
    def boom():
        raise _json.JSONDecodeError("bad", "", 0)
    monkeypatch.setattr(config, "load_comparisons", boom)
    assert catalog.comparison_entries(catalog.load_catalog()) == []


def test_shipped_comparisons_file_has_no_invalid_or_duplicate_entries():
    cat = catalog.load_catalog()
    entries = config.load_comparisons()["comparisons"]
    for entry in entries:
        assert catalog.comparison_problem(cat, entry) is None, entry["id"]
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))
    assert len(catalog.comparison_entries(cat)) == len(entries)
    assert all(len(e["targets"]) <= config.MAX_MODELS for e in catalog.comparison_entries(cat))
```

- [ ] **Step 7: Run them to verify they fail**

Run: `pytest tests/test_catalog.py -k "comparison" -v`
Expected: FAIL with `AttributeError: module 'catalog' has no attribute 'resolve_comparison'` (and the other comparison functions)

- [ ] **Step 8: Implement the catalog functions**

In `catalog.py`, change the imports at the top to:

```python
import logging
import time

import requests

import config

logger = logging.getLogger(__name__)
```

(keep `OPENROUTER_MODELS_URL` etc. below unchanged) and append at the end of the file:

```python
_COMPARISON_BACKENDS = ("openrouter", "bedrock", "vertex", "foundry")


def comparison_problem(catalog_dict, entry):
    """Why a comparisons.json entry is unusable, or None when it is valid."""
    if not entry.get("id") or not entry.get("label"):
        return "missing id or label"
    model_id = entry.get("model") or ""
    if model_id.startswith("~"):
        return "alias models have no stable identity to compare"
    _, model = find_model(catalog_dict, model_id)
    if model is None:
        return f"unknown model {model_id}"
    backends = entry.get("backends")
    if not isinstance(backends, list) or len(backends) < 2:
        return "needs at least 2 backends"
    if len(set(backends)) != len(backends):
        return "duplicate backends"
    if len(backends) > config.MAX_MODELS:
        return f"more than {config.MAX_MODELS} backends"
    for backend in backends:
        if backend not in _COMPARISON_BACKENDS:
            return f"unknown backend {backend}"
        if backend != "openrouter" and not route_for(catalog_dict, model_id, backend):
            return f"{model_id} has no {backend} route"
    return None


def resolve_comparison(catalog_dict, entry):
    provider_id, model = find_model(catalog_dict, entry["model"])
    return {
        "id": entry["id"],
        "label": entry["label"],
        "model_id": model["id"],
        "model_name": model["name"],
        "provider": provider_id,
        "targets": [
            {"target": model["id"] if b == "openrouter" else f"{model['id']}@{b}", "backend": b}
            for b in entry["backends"]
        ],
    }


def comparison_entries(catalog_dict):
    """Valid, resolved cross-platform comparisons. Advisory data: fails soft to []."""
    try:
        entries = config.load_comparisons()["comparisons"]
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("comparisons.json is missing or unreadable; no comparisons offered")
        return []
    resolved, seen = [], set()
    for entry in entries:
        problem = "not an object" if not isinstance(entry, dict) else comparison_problem(catalog_dict, entry)
        if problem is None and entry["id"] in seen:
            problem = "duplicate id"
        if problem is not None:
            name = entry.get("id") if isinstance(entry, dict) else entry
            logger.warning("Skipping comparison %r: %s", name, problem)
            continue
        seen.add(entry["id"])
        resolved.append(resolve_comparison(catalog_dict, entry))
    return resolved
```

- [ ] **Step 9: Run the catalog and config tests to verify they pass**

Run: `pytest tests/test_catalog.py tests/test_config.py -v`
Expected: all PASS

- [ ] **Step 10: Commit**

```bash
git add data/comparisons.json config.py catalog.py tests/test_config.py tests/test_catalog.py
git commit -m "feat: add curated cross-platform comparisons data and catalog resolution

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Expose comparisons through `/api/catalog`

**Files:**
- Modify: `app.py:61-74` (the `api_catalog` function)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `catalog.comparison_entries(catalog_dict) -> list[dict]` (Task 1)
- Produces: `/api/catalog` JSON gains key `"comparisons"`: list of `{id, label, model_id, model_name, provider, targets: [{target, backend}]}`

- [ ] **Step 1: Write the failing tests**

In `tests/test_app.py`, add `import config` to the import block (after `import app as app_module`), then append:

```python
def test_api_catalog_includes_comparisons():
    data = _client().get("/api/catalog").get_json()
    comparisons = data["comparisons"]
    assert len(comparisons) > 0
    maverick = next(c for c in comparisons if c["id"] == "llama-4-maverick-all")
    assert [t["backend"] for t in maverick["targets"]] == ["openrouter", "bedrock", "vertex", "foundry"]
    assert maverick["targets"][1]["target"] == "meta-llama/llama-4-maverick@bedrock"
    assert len(maverick["targets"]) <= data["max_models"]


def test_api_catalog_comparisons_empty_when_file_missing(monkeypatch):
    def boom():
        raise FileNotFoundError("comparisons.json")
    monkeypatch.setattr(config, "load_comparisons", boom)
    resp = _client().get("/api/catalog")
    assert resp.status_code == 200
    assert resp.get_json()["comparisons"] == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_app.py -k "comparisons" -v`
Expected: FAIL with `KeyError: 'comparisons'`

- [ ] **Step 3: Add the key to the response**

In `app.py`, inside the dict returned by `api_catalog`, add after the `"tags"` line:

```python
        "comparisons": catalog.comparison_entries(cat),
```

- [ ] **Step 4: Run them to verify they pass**

Run: `pytest tests/test_app.py -k "catalog" -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: serve cross-platform comparisons from /api/catalog

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Pure picker helper `targetsForComparison`

**Files:**
- Modify: `static/picker-core.js`
- Test: `tests/js/picker.test.mjs`

**Interfaces:**
- Produces: `PickerCore.targetsForComparison(entry, max) -> string[]` — the entry's target ids in order; returns `[]` if the entry has no targets or more than `max` targets (the server already enforces this; this is a defensive guard so a bad payload can never overfill the selection).

- [ ] **Step 1: Write the failing tests**

In `tests/js/picker.test.mjs`, change the `require` line to:

```js
const { filterModels, targetsForModel, capState, targetsForComparison } = require("../../static/picker-core.js");
```

and append:

```js
test("targetsForComparison returns the target ids in order", () => {
  const entry = {
    targets: [
      { target: "meta/x", backend: "openrouter" },
      { target: "meta/x@bedrock", backend: "bedrock" },
    ],
  };
  assert.deepEqual(targetsForComparison(entry, 4), ["meta/x", "meta/x@bedrock"]);
});

test("targetsForComparison returns nothing when the entry would exceed the cap", () => {
  const entry = { targets: [1, 2, 3, 4, 5].map((n) => ({ target: `m${n}`, backend: "openrouter" })) };
  assert.deepEqual(targetsForComparison(entry, 4), []);
});

test("targetsForComparison tolerates a malformed entry", () => {
  assert.deepEqual(targetsForComparison({}, 4), []);
  assert.deepEqual(targetsForComparison(null, 4), []);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `node --test tests/js/picker.test.mjs`
Expected: FAIL with `targetsForComparison is not a function`

- [ ] **Step 3: Implement**

In `static/picker-core.js`, add before `const api = ...`:

```js
  function targetsForComparison(entry, max) {
    const targets = (entry && entry.targets) || [];
    if (targets.length === 0 || targets.length > max) return [];
    return targets.map((t) => t.target);
  }
```

and change the api line to:

```js
  const api = { filterModels, targetsForModel, capState, targetsForComparison };
```

- [ ] **Step 4: Run them to verify they pass**

Run: `node --test tests/js/picker.test.mjs`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add static/picker-core.js tests/js/picker.test.mjs
git commit -m "feat: add pure targetsForComparison picker helper

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Dropdown UI, note, and styles

**Files:**
- Modify: `templates/index.html:139` (insert before the `<h2>Browse by provider</h2>` line)
- Modify: `static/app.js` (`loadCatalogAndModels` ~line 472; new functions after `modelBadge` ~line 522)
- Modify: `static/style.css` (append)

**Interfaces:**
- Consumes: `/api/catalog` `comparisons` (Task 2), `PickerCore.targetsForComparison` (Task 3), existing `state.selectedModels` (Set), `state.customModels` (array), `renderCustomModels()`, `syncSelectionVisuals()`, `maxModels()`, `BACKEND_SHORT`
- Produces: DOM ids `comparison-block`, `comparison-dropdown`, `comparison-list`; classes `comparison-entry`, `comparison-chip`

- [ ] **Step 1: Add the markup**

In `templates/index.html`, immediately above `<h2>Browse by provider</h2>` insert:

```html
    <div id="comparison-block" hidden>
      <h2>Compare one model across platforms</h2>
      <p class="provider-blurb" id="comparison-note">
        Cross-platform comparisons are defined in the backend (<code>data/comparisons.json</code>).
        To test other model/platform combinations, clone the repository and edit that file.
      </p>
      <details id="comparison-dropdown" class="provider-dropdown">
        <summary><span class="provider-name">Choose a comparison</span></summary>
        <div id="comparison-list"></div>
      </details>
    </div>

```

- [ ] **Step 2: Add the render and click handler**

In `static/app.js`, directly after the `modelBadge` function, add:

```js
function renderComparisons(comparisons) {
  const block = document.getElementById("comparison-block");
  const list = document.getElementById("comparison-list");
  list.innerHTML = "";
  const entries = comparisons || [];
  block.hidden = entries.length === 0;
  entries.forEach((entry) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "comparison-entry";
    button.style.setProperty("--accent", state.catalog.providers[entry.provider].color);
    const name = document.createElement("span");
    name.className = "model-row-name";
    name.textContent = entry.label;
    button.appendChild(name);
    entry.targets.forEach(({ backend }) => {
      const chip = document.createElement("span");
      chip.className = "comparison-chip";
      chip.textContent = BACKEND_SHORT[backend];
      button.appendChild(chip);
    });
    button.addEventListener("click", () => applyComparison(entry));
    list.appendChild(button);
  });
}

// A comparison click REPLACES the selection: it can never exceed the cap, and
// the server still re-validates the target list on run.
function applyComparison(entry) {
  const targets = PickerCore.targetsForComparison(entry, maxModels());
  if (targets.length === 0) return;
  state.selectedModels.clear();
  targets.forEach((target) => state.selectedModels.add(target));
  state.customModels = [];
  renderCustomModels();
  document.getElementById("comparison-dropdown").open = false;
  document.getElementById("run-status").textContent =
    `Selected ${entry.model_name} on ${targets.length} platforms.`;
  syncSelectionVisuals();
}
```

- [ ] **Step 3: Wire it into catalog loading**

In `loadCatalogAndModels`, directly after `renderFrontier(catalogData.frontier);` add:

```js
  renderComparisons(catalogData.comparisons);
```

- [ ] **Step 4: Add the styles**

Append to `static/style.css`:

```css
.comparison-entry { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; width: 100%; box-sizing: border-box; text-align: left; padding: 8px 12px; background: none; border: 0; border-top: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 0; color: var(--fg); font: inherit; font-size: 13px; cursor: pointer; }
.comparison-entry:hover, .comparison-entry:focus-visible { background: var(--bg); }
.comparison-chip { font-size: 11px; color: var(--muted); border: 1px solid var(--border); border-radius: 10px; padding: 0 6px; }
#comparison-block[hidden] { display: none; }
```

- [ ] **Step 5: Verify syntax and automated tests**

Run: `for f in static/*.js; do node --check "$f"; done && node --test tests/js/picker.test.mjs && pytest tests/ -v`
Expected: no syntax errors; all JS and Python tests PASS

- [ ] **Step 6: Verify in the browser**

Start the app (`python app.py`; see README for host/port env vars) and open it. Confirm:
1. "Compare one model across platforms" appears above "Browse by provider" with the exact note text from Global Constraints.
2. Opening the dropdown lists 12 entries with platform chips; the three Llama entries show four chips.
3. Clicking "Llama 4 Maverick on all four platforms" collapses the dropdown, shows "Selected 4 / 4", ticks the OpenRouter/Bedrock/Vertex/Foundry boxes on that model's row, and the credential sections for those backends become required as with manual ticking.
4. Clicking a 2-platform entry afterwards replaces (not adds to) the selection and shows "Selected 2 / 4".
5. A custom model added beforehand is cleared by a comparison click.
6. Light and dark themes both look right (toggle `prefers-color-scheme` or `[data-theme="dark"]`), and the layout holds at phone width.

If anything fails, fix it before committing.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html static/app.js static/style.css
git commit -m "feat: add cross-platform comparison dropdown and front-screen note

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Docs

**Files:**
- Modify (uncommitted, untracked file): `CLAUDE.md` (architecture list, after the `data/regions.json` bullet)
- Modify: `docs/comparing-models.md` (new section "Comparing one model across platforms" before "## Latency comparison"; a separate "The judge and the policy gate" section already exists and must not be changed)

- [ ] **Step 1: Add the CLAUDE.md bullet (edit only; NEVER stage or commit this file)**

`CLAUDE.md` is untracked in this repo and the owner decided it stays uncommitted. Edit it in place, but do not `git add` it. After the `**\`data/regions.json\`**` bullet in `CLAUDE.md` add:

```markdown
- **`data/comparisons.json`** — curated list of cross-platform comparisons (one model on 2-4 of OpenRouter/Bedrock/Vertex/Foundry), loaded by `config.load_comparisons()` and validated/resolved by `catalog.comparison_entries()` into `/api/catalog`'s `comparisons` key, which powers the front-screen "Compare one model across platforms" dropdown. Backend-only by design: there is no UI or API for creating entries (users clone the repo and edit the file). Advisory data like `regions.json`: `gateway.py` never reads it, invalid entries are dropped with a logged warning, and a missing file just hides the dropdown. A test fails if the shipped file drifts from `providers.json`.
```

- [ ] **Step 2: Add the user-guide section**

In `docs/comparing-models.md`, before `## Latency comparison`, insert:

```markdown
## Comparing one model across platforms

The same model can behave differently depending on where it is deployed: latency, price and sometimes the answers themselves. The **Compare one model across platforms** dropdown on the front screen selects one model on every platform that offers it (for example Llama 4 Maverick on OpenRouter, Bedrock, Vertex and Foundry) in a single click. Clicking an entry replaces your current selection.

The entries are defined in the backend, in `data/comparisons.json`, and cannot be edited from the web app. To test other model and platform combinations, clone the repository and add an entry to that file. Each entry names a catalog model and 2-4 platforms, and every non-OpenRouter platform must have a route for that model in `data/providers.json`. The test suite checks this.
```

- [ ] **Step 3: Run the full suite**

Run: `pytest tests/ -v && node --test tests/js/picker.test.mjs`
Expected: all PASS

- [ ] **Step 4: Commit (docs/comparing-models.md only; leave CLAUDE.md unstaged)**

```bash
git add docs/comparing-models.md
git commit -m "docs: document the cross-platform comparison dropdown

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
