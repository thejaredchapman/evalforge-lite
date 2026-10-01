# Model Picker, Reasoning Labels & Need/Industry Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "Browse by provider" badge grid with one collapsible checkbox dropdown per provider, show a Reasoning badge on reasoning-capable models, and add curated need/industry tags with filter chips.

**Architecture:** Tag data lives in a new `data/tags.json`; each curated model in `data/providers.json` gains a `tags` list. `catalog.py` exposes `load_tags()`/`models_for_tag()`, and `/api/catalog` plus the MCP `list_models` tool return the tags. The frontend picker is rewritten around `<details>` dropdowns with checkbox rows; the testable pure logic (filtering, target enumeration, cap state) is extracted to `static/picker-core.js` and tested with `node --test`. No run semantics change on the server.

**Tech Stack:** Python 3.12 / Flask / pytest (backend), vanilla JS + CSS variables (frontend), Node 20 `node:test` (JS unit tests, no npm deps), GitHub Actions.

Spec: `docs/superpowers/specs/2026-10-01-model-picker-tags-design.md`

## Global Constraints

- Cap stays `config.MAX_MODELS = 4` targets; `X` and `X@bedrock` count separately. No server-side run changes.
- Tag ids/labels/kinds are fixed: needs `coding, reasoning, long-context, fast-cheap, creative, multilingual, agents`; industries `healthcare, legal, finance, customer-support, education, research`. Each `why` is non-empty and ≤ 140 chars. `verified` is `2026-10-01`.
- Every curated model has 1–6 tags, all known ids; every tag is used by at least one model.
- The existing boolean `reasoning` on models drives the Reasoning badge; it is independent of the `reasoning` *tag*.
- All catalog text enters the DOM via `textContent`/`escapeHtml` — never `innerHTML` interpolation of catalog data.
- Filtering never deselects anything; live OpenRouter extras (untagged) are hidden whenever any filter is active.
- Theme via existing CSS variables (`--bg/--surface/--fg/--muted/--border`, per-provider `--accent`); must work in light and dark; layout stacks on mobile.
- No live network in tests. Full pytest suite stays green.

---

### Task 1: Tag data, catalog helpers, model tag assignments

**Files:**
- Create: `data/tags.json`
- Modify: `config.py` (add `_TAGS_PATH`, `load_tags`)
- Modify: `catalog.py` (add `load_tags`, `models_for_tag`)
- Modify: `data/providers.json` (add `"tags"` to all 16 curated models)
- Test: `tests/test_catalog.py`

**Interfaces:**
- Produces: `config.load_tags() -> dict`; `catalog.load_tags() -> dict` (`{"verified", "disclaimer", "tags": [{id,label,kind,why}]}`); `catalog.models_for_tag(catalog_dict: dict, tag_id: str) -> list[str]`; each model dict in `providers.json` has `"tags": list[str]`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_catalog.py`:

```python
import re

NEED_IDS = {"coding", "reasoning", "long-context", "fast-cheap", "creative", "multilingual", "agents"}
INDUSTRY_IDS = {"healthcare", "legal", "finance", "customer-support", "education", "research"}


def test_load_tags_matches_config():
    assert catalog.load_tags() == config.load_tags()


def test_tags_file_has_expected_shape():
    data = catalog.load_tags()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["verified"])
    assert data["disclaimer"]
    for tag in data["tags"]:
        assert tag["id"] and tag["label"]
        assert tag["kind"] in {"need", "industry"}
        assert 0 < len(tag["why"]) <= 140


def test_tags_file_has_exactly_the_expected_ids():
    tags = catalog.load_tags()["tags"]
    assert {t["id"] for t in tags if t["kind"] == "need"} == NEED_IDS
    assert {t["id"] for t in tags if t["kind"] == "industry"} == INDUSTRY_IDS
    assert len(tags) == len({t["id"] for t in tags})


def test_every_curated_model_has_one_to_six_known_tags():
    known = {t["id"] for t in catalog.load_tags()["tags"]}
    for provider in catalog.load_catalog().values():
        for model in provider["models"]:
            tags = model.get("tags")
            assert tags and 1 <= len(tags) <= 6, model["id"]
            assert len(tags) == len(set(tags)), model["id"]
            assert set(tags) <= known, model["id"]


def test_every_tag_is_used_by_at_least_one_model():
    cat = catalog.load_catalog()
    for tag in catalog.load_tags()["tags"]:
        assert catalog.models_for_tag(cat, tag["id"]), tag["id"]


def test_models_for_tag_returns_ids_carrying_the_tag():
    cat = catalog.load_catalog()
    ids = catalog.models_for_tag(cat, "fast-cheap")
    assert "anthropic/claude-haiku-4.5" in ids
    assert "anthropic/claude-opus-4.5" not in ids
    assert catalog.models_for_tag(cat, "no-such-tag") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_catalog.py -v -k "tags or tag"`
Expected: FAIL (`AttributeError: module 'catalog' has no attribute 'load_tags'`).

- [ ] **Step 3: Create `data/tags.json`** — exactly the JSON in the spec §1 (`"verified": "2026-10-01"`, the disclaimer, and the 13 tags with the `why` strings from the spec).

- [ ] **Step 4: Add loaders**

In `config.py`, next to `_REGIONS_PATH`:

```python
_TAGS_PATH = _DATA_DIR / "tags.json"
```

and after `load_regions`:

```python
def load_tags():
    with open(_TAGS_PATH) as f:
        return json.load(f)
```

In `catalog.py`, after `load_regions`:

```python
def load_tags():
    return config.load_tags()
```

and after `find_model`:

```python
def models_for_tag(catalog_dict, tag_id):
    return [
        model["id"]
        for provider in catalog_dict.values()
        for model in provider["models"]
        if tag_id in (model.get("tags") or [])
    ]
```

- [ ] **Step 5: Assign tags to models.** Save this as `/private/tmp/claude-501/-Users-thejaredchapman-coding-stuff-evalforge-lite/c26079e0-f567-4468-8297-9087895a10ae/scratchpad/add_tags.py` and run it from the repo root (it inserts `"tags": [...]` after each model's `"tier"` and keeps the file's one-model-per-line formatting):

```python
import re

TAGS = {
    "~openai/gpt-latest": ["reasoning", "coding", "agents", "research", "finance"],
    "openai/gpt-5": ["reasoning", "coding", "agents", "research", "finance"],
    "openai/gpt-5-mini": ["fast-cheap", "coding", "customer-support"],
    "openai/gpt-4o": ["creative", "multilingual", "customer-support", "education"],
    "openai/gpt-4o-mini": ["fast-cheap", "customer-support", "education"],
    "~anthropic/claude-opus-latest": ["coding", "reasoning", "long-context", "agents", "legal", "healthcare"],
    "anthropic/claude-opus-4.5": ["coding", "reasoning", "long-context", "agents", "legal", "healthcare"],
    "anthropic/claude-sonnet-4.5": ["coding", "agents", "creative", "long-context", "finance"],
    "anthropic/claude-haiku-4.5": ["fast-cheap", "customer-support", "coding"],
    "~google/gemini-pro-latest": ["long-context", "reasoning", "research", "multilingual", "legal"],
    "google/gemini-2.5-pro": ["long-context", "reasoning", "research", "multilingual", "legal"],
    "google/gemini-3.7-flash": ["fast-cheap", "long-context", "multilingual", "education"],
    "google/gemini-2.5-flash": ["fast-cheap", "long-context", "customer-support"],
    "meta-llama/llama-4-maverick": ["multilingual", "coding", "creative"],
    "meta-llama/llama-4-scout": ["long-context", "fast-cheap", "research"],
    "meta-llama/llama-3.3-70b-instruct": ["fast-cheap", "multilingual", "education"],
}

path = "data/providers.json"
lines = open(path).read().split("\n")
done = set()
for i, line in enumerate(lines):
    m = re.search(r'\{"id": "([^"]+)",', line)
    if m and m.group(1) in TAGS:
        mid = m.group(1)
        tags = ", ".join(f'"{t}"' for t in TAGS[mid])
        lines[i] = re.sub(r'("tier": "[^"]+")', rf'\1, "tags": [{tags}]', line, count=1)
        done.add(mid)
assert done == set(TAGS), set(TAGS) - done
open(path, "w").write("\n".join(lines))
```

Run: `python3 <scratchpad>/add_tags.py && python3 -c "import json; json.load(open('data/providers.json'))" && git diff --stat data/providers.json`
Expected: no error; 16 lines changed.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_catalog.py -v`
Expected: all PASS (including the pre-existing tier/reasoning tests).

- [ ] **Step 7: Commit**

```bash
git add data/tags.json data/providers.json config.py catalog.py tests/test_catalog.py
git commit -m "feat: add curated need/industry tags and catalog helpers"
```

---

### Task 2: Expose tags via `/api/catalog` and MCP `list_models`

**Files:**
- Modify: `app.py` (`api_catalog`, ~line 62)
- Modify: `mcp_server.py` (`list_models`, line 31)
- Test: `tests/test_app.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `catalog.load_tags()` from Task 1.
- Produces: `/api/catalog` JSON gains `"tags": {verified, disclaimer, tags[]}`; models in `providers` already carry `tags`. MCP `list_models()` returns `{"providers", "frontier", "tags"}`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_app.py`:

```python
def test_api_catalog_includes_tags_and_model_tags():
    data = _client().get("/api/catalog").get_json()
    assert data["tags"]["verified"]
    assert {t["id"] for t in data["tags"]["tags"]} >= {"coding", "healthcare"}
    gpt5 = next(m for m in data["providers"]["openai"]["models"] if m["id"] == "openai/gpt-5")
    assert gpt5["tags"] and gpt5["reasoning"] is True
```

Append to `tests/test_mcp_server.py`:

```python
def test_list_models_includes_tags():
    result = mcp_server.list_models()
    assert result["tags"]["verified"]
    assert any(t["id"] == "coding" for t in result["tags"]["tags"])
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_app.py::test_api_catalog_includes_tags_and_model_tags tests/test_mcp_server.py::test_list_models_includes_tags -v`
Expected: FAIL (`KeyError: 'tags'`).

- [ ] **Step 3: Implement**

`app.py`, in the `api_catalog` jsonify dict add after `"regions"`:

```python
        "tags": catalog.load_tags(),
```

`mcp_server.py`:

```python
def list_models() -> dict:
    """List every provider and model in the catalog, plus each provider's frontier (flagship) model.

    Each model carries a `reasoning` flag (supports extended reasoning) and a `tags` list of
    curated need/industry tag ids; `tags` in the result gives their labels, one-line "why"
    explanations and the date they were verified. Tags are a starting point, not benchmarks.
    """
    cat = catalog.load_catalog()
    return {"providers": cat, "frontier": catalog.frontier_models(cat), "tags": catalog.load_tags()}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py mcp_server.py tests/test_app.py tests/test_mcp_server.py
git commit -m "feat: expose tags in /api/catalog and MCP list_models"
```

---

### Task 3: `picker-core.js` pure logic, Node tests, CI

**Files:**
- Create: `static/picker-core.js`
- Create: `tests/js/picker.test.mjs`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Produces (on `globalThis.PickerCore`, and `module.exports` under Node):
  - `filterModels(models, activeTagIds) -> model[]` — AND semantics; empty/absent `activeTagIds` returns a copy of all; models lacking `tags` are excluded when any tag is active.
  - `targetsForModel(model) -> [{target: string, backend: string}]` — OpenRouter first (`target === model.id`), then one entry per key of `model.routes` (`target === "<id>@<backend>"`), in key order.
  - `capState(selectedCount, max) -> {atCap: boolean, remaining: number}`.

- [ ] **Step 1: Write the failing test** — `tests/js/picker.test.mjs`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { filterModels, targetsForModel, capState } = require("../../static/picker-core.js");

const models = [
  { id: "a", tags: ["coding", "reasoning"] },
  { id: "b", tags: ["coding"] },
  { id: "c", tags: ["legal"] },
  { id: "d" },
];

test("filterModels with no active tags returns every model", () => {
  assert.deepEqual(filterModels(models, []).map((m) => m.id), ["a", "b", "c", "d"]);
  assert.deepEqual(filterModels(models, undefined).map((m) => m.id), ["a", "b", "c", "d"]);
});

test("filterModels uses AND semantics", () => {
  assert.deepEqual(filterModels(models, ["coding"]).map((m) => m.id), ["a", "b"]);
  assert.deepEqual(filterModels(models, ["coding", "reasoning"]).map((m) => m.id), ["a"]);
  assert.deepEqual(filterModels(models, ["coding", "legal"]), []);
});

test("filterModels hides untagged models when filtering", () => {
  assert.ok(!filterModels(models, ["coding"]).some((m) => m.id === "d"));
});

test("targetsForModel lists OpenRouter then each route", () => {
  const model = { id: "meta/x", routes: { bedrock: {}, vertex: {}, foundry: {} } };
  assert.deepEqual(targetsForModel(model), [
    { target: "meta/x", backend: "openrouter" },
    { target: "meta/x@bedrock", backend: "bedrock" },
    { target: "meta/x@vertex", backend: "vertex" },
    { target: "meta/x@foundry", backend: "foundry" },
  ]);
});

test("targetsForModel with no routes is OpenRouter only", () => {
  assert.deepEqual(targetsForModel({ id: "z/y" }), [{ target: "z/y", backend: "openrouter" }]);
});

test("capState reports cap and remaining", () => {
  assert.deepEqual(capState(0, 4), { atCap: false, remaining: 4 });
  assert.deepEqual(capState(3, 4), { atCap: false, remaining: 1 });
  assert.deepEqual(capState(4, 4), { atCap: true, remaining: 0 });
  assert.deepEqual(capState(5, 4), { atCap: true, remaining: 0 });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `node --test tests/js/picker.test.mjs`
Expected: FAIL (cannot find `picker-core.js`).

- [ ] **Step 3: Implement `static/picker-core.js`**

```js
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
```

- [ ] **Step 4: Run tests**

Run: `node --test tests/js/picker.test.mjs && node --check static/picker-core.js`
Expected: 6 tests pass.

- [ ] **Step 5: Add Node to CI** — in `.github/workflows/tests.yml`, after the "Run tests" step append:

```yaml

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Check JS syntax
        run: |
          for f in static/*.js; do node --check "$f"; done

      - name: Run JS tests
        run: node --test tests/js/picker.test.mjs
```

(An explicit file path, not the `tests/js/` directory from the spec: Node ≥ 22 treats a directory argument as a glob and fails, while the file path works on every version.)

- [ ] **Step 6: Commit**

```bash
git add static/picker-core.js tests/js/picker.test.mjs .github/workflows/tests.yml
git commit -m "feat: extract picker-core pure logic with node tests and CI step"
```

---

### Task 4: Frontend picker (template, JS, CSS)

**Files:**
- Modify: `templates/index.html` (catalog section ~lines 133-139, script tags ~262)
- Modify: `static/app.js` (state ~line 2; `syncSelectionVisuals` ~151; `syncRegionWarnings` ~271; `loadCatalogAndModels` ~395; `renderFrontier`..`toggleModel` ~431-550; `addCustomModel`/`removeCustomModel` ~552-574; `updateSelectionMeta` ~638; `tryIt` ~965)
- Modify: `static/style.css` (replace `.provider-block`/`.show-more-btn`/`.model-option`/`.backend-chip*` rules, add new ones)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `PickerCore.{filterModels,targetsForModel,capState}` (Task 3); `state.catalog.tags` (`{verified, disclaimer, tags[]}`) and each model's `tags`/`reasoning`/`routes` (Tasks 1–2).
- DOM contract: `#selection-counter`, `#tag-filters`, `#provider-list` (rendered in the page); per-provider `<details class="provider-dropdown" data-provider="<id>">`; rows `.model-row[data-model-id]`; checkboxes `input.backend-check[data-target]`; frontier badges `.model-badge[data-target]`.

- [ ] **Step 1: Write the failing template test** — append to `tests/test_app.py`:

```python
def test_index_renders_picker_containers():
    html = _client().get("/").get_data(as_text=True)
    assert 'id="tag-filters"' in html
    assert 'id="selection-counter"' in html
    assert 'id="provider-list"' in html
    assert "picker-core.js" in html
```

Run: `pytest tests/test_app.py::test_index_renders_picker_containers -v` → FAIL.

- [ ] **Step 2: Template.** In `templates/index.html` replace the heading/`provider-list` lines inside `#catalog-section`:

```html
    <h2>Frontier models</h2>
    <div id="frontier-list" class="model-grid"></div>

    <h2>Browse by provider</h2>
    <div id="provider-list"></div>
```

with:

```html
    <h2>Frontier models</h2>
    <div id="frontier-list" class="model-grid"></div>

    <div id="selection-counter" class="selection-counter" aria-live="polite">Selected 0 / 4</div>

    <h2>Browse by provider</h2>
    <div id="tag-filters" class="tag-filters"></div>
    <div id="provider-list"></div>
```

and add before the `app.js` script tag (~line 263):

```html
  <script src="{{ url_for('static', filename='picker-core.js') }}"></script>
```

- [ ] **Step 3: CSS.** In `static/style.css` delete the rules `.provider-block`, `.provider-block h3`, `.show-more-btn`, `.show-more-btn + .model-grid`, `.model-option`, `.backend-chips`, `.backend-chip`, `.backend-chip.selected`. Keep `.provider-blurb`, `.model-grid`, `.model-badge*`, `.region-warning-mark`. Append:

```css
/* ---- Model picker ---- */
.selection-counter {
  position: sticky; top: 0; z-index: 5;
  background: var(--bg); border-bottom: 1px solid var(--border);
  padding: 6px 0; margin-bottom: 8px; font-size: 12px; font-weight: bold;
}
.tag-filters { margin-bottom: 12px; }
.tag-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 6px; }
.tag-row-label { font-size: 11px; color: var(--muted); min-width: 120px; }
.tag-chip {
  font-size: 11px; padding: 3px 10px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); color: var(--fg); cursor: pointer;
}
.tag-chip[aria-pressed="true"] { background: var(--fg); color: var(--bg); border-color: var(--fg); }
.tag-why { font-size: 12px; color: var(--muted); margin: 4px 0; }
.filter-status { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; font-size: 12px; margin: 6px 0 2px; }
.filter-status button { font-size: 11px; padding: 3px 10px; }
.tag-disclaimer { font-size: 11px; color: var(--muted); margin: 4px 0 0; }

.provider-dropdown { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; background: var(--surface); }
.provider-dropdown > summary { cursor: pointer; padding: 8px 12px; font-size: 13px; display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; }
.provider-name { color: var(--accent, var(--fg)); font-weight: bold; }
.provider-count, .provider-selected { font-size: 11px; color: var(--muted); }
.provider-selected { color: var(--accent, var(--fg)); }
.provider-dropdown .provider-blurb { padding: 0 12px; }
.model-row {
  display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px;
  padding: 6px 12px; border-top: 1px solid var(--border); font-size: 12px;
}
.model-row-name { font-weight: bold; min-width: 160px; }
.reasoning-badge {
  font-size: 10px; padding: 1px 8px; border-radius: 999px;
  background: var(--accent, var(--fg)); color: #fff;
}
.tag-pill { font-size: 10px; padding: 1px 6px; border-radius: 4px; border: 1px solid var(--border); color: var(--muted); }
.backend-checks { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-left: auto; }
.backend-check-label { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; cursor: pointer; }
.backend-check:disabled { cursor: not-allowed; }
.live-heading { font-size: 11px; color: var(--muted); padding: 8px 12px 2px; margin: 0; }
.model-row[hidden], .provider-dropdown[hidden], .live-group[hidden] { display: none; }
@media (max-width: 640px) {
  .model-row-name { min-width: 100%; }
  .backend-checks { margin-left: 0; }
  .tag-row-label { min-width: 100%; }
}
```

- [ ] **Step 4: JS — state and selection core.** In `static/app.js`:

(a) Add `activeTags: new Set(),` to the `state` object (next to `selectedModels`).

(b) Replace `syncSelectionVisuals` with the single source of truth:

```js
function syncSelectionVisuals() {
  const cap = PickerCore.capState(state.selectedModels.size, maxModels());
  document.querySelectorAll("[data-target]").forEach((el) => {
    const selected = state.selectedModels.has(el.dataset.target);
    if (el.type === "checkbox") {
      el.checked = selected;
      el.disabled = cap.atCap && !selected;
      el.title = el.disabled ? capMessage() : "";
    } else {
      el.classList.toggle("selected", selected);
    }
  });
  document.querySelectorAll(".provider-dropdown").forEach((details) => {
    const provider = state.catalog.providers[details.dataset.provider];
    const ids = new Set(provider.models.map((m) => m.id));
    let n = 0;
    state.selectedModels.forEach((target) => {
      const { modelId } = splitTarget(target);
      if (ids.has(modelId) || modelId.startsWith(`${details.dataset.provider}/`)) n += 1;
    });
    details.querySelector(".provider-selected").textContent = n ? `${n} selected` : "";
  });
  updateSelectionMeta();
  syncRegionWarnings();
}
```

(c) In `updateSelectionMeta`, replace the first line with:

```js
  const countText = `Selected ${state.selectedModels.size} / ${maxModels()}`;
  document.getElementById("selection-count").textContent = countText;
  document.getElementById("selection-counter").textContent = countText;
```

(d) In `syncRegionWarnings`, replace the `.backend-chip` loop with one over the checkbox labels:

```js
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
```

(e) Replace `toggleBackendTarget` and `toggleModel` with one function:

```js
async function toggleTarget(target) {
  if (state.selectedModels.has(target)) {
    state.selectedModels.delete(target);
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
```

(f) In `addCustomModel`, `removeCustomModel` and `tryIt`, replace each trailing `updateSelectionMeta(); syncRegionWarnings();` pair (and in `tryIt` the preceding bare `syncSelectionVisuals();` too) with a single `syncSelectionVisuals();`. In `loadCatalogAndModels`, replace the final `updateSelectionMeta(); syncRegionWarnings();` with `syncSelectionVisuals();`.

- [ ] **Step 5: JS — rendering.** Replace `renderFrontier`, `renderProviders`, `modelBadge` (whole old bodies) with the following, and in `loadCatalogAndModels` call `renderTagFilters();` immediately before `renderProviders(catalogData.providers);` and `applyFilters();` immediately after it.

```js
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
    const label = document.createElement("span");
    label.className = "tag-row-label";
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
    row.hidden = !visible.has(row.dataset.modelId);
  });
  document.querySelectorAll(".live-group").forEach((group) => {
    group.hidden = active.length > 0; // live extras have no tags
  });
  document.querySelectorAll(".provider-dropdown").forEach((details) => {
    const hasMatch = !!details.querySelector(".curated-rows .model-row:not([hidden])");
    details.hidden = active.length > 0 && !hasMatch;
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
```

Delete the now-unused old `renderProviders` "show more" toggle code and `toggleBackendTarget`/`toggleModel` if any remain.

- [ ] **Step 6: Verify**

Run:
```bash
node --check static/app.js && node --check static/picker-core.js && node --test tests/js/picker.test.mjs
grep -n "backend-chip\|toggleModel\|toggleBackendTarget\|provider-block\|show-more" static/app.js static/style.css templates/index.html
pytest tests/ -q
```
Expected: node checks pass; the grep prints nothing; pytest all PASS (including `test_index_renders_picker_containers`).

- [ ] **Step 7: Manual browser check** (the pytest/node suites cannot cover DOM behaviour). Start the app (`flask --app app run` from the venv) and in a browser confirm:
  1. All provider dropdowns start collapsed; summaries show name, "N models", and "N selected" once something is checked.
  2. Reasoning badge appears on GPT-5, GPT-5 Mini, GPT (Latest), the Gemini Pro/Flash models, and not on Claude or Llama.
  3. Check 4 boxes → all other boxes disable with the cap tooltip; the counter reads "Selected 4 / 4"; unchecking re-enables them.
  4. Toggling a frontier badge ticks the matching OpenRouter checkbox, and vice versa.
  5. Click "Coding" then "Legal": only models with both tags show, matching dropdowns open, why-lines appear, the count updates, live extras vanish; a selected model hidden by a filter stays in the counter. "Clear filters" restores everything.
  6. With a Bedrock/Vertex/Foundry region chosen that doesn't list a ticked route, the ⚠ appears on that backend's checkbox label.
  7. Dark mode and a ≤640px window both lay out cleanly.

- [ ] **Step 8: Commit**

```bash
git add templates/index.html static/app.js static/style.css tests/test_app.py
git commit -m "feat: per-provider checkbox picker with reasoning badge and tag filters"
```

---

## Self-Review

- **Spec coverage:** data/tags.json + models' tags (T1); `load_tags`/`models_for_tag` (T1); `/api/catalog` + MCP tags (T2); picker-core + Node tests + CI (T3); frontier badges synced, filter chips with AND semantics/why/clear/count/disclaimer, never-deselect, live extras hidden while filtering, `<details>` dropdowns with `textContent` blurb, Reasoning badge, tag pills, per-backend checkboxes with aria-labels, region warnings on checkbox labels, live "More from OpenRouter" sub-heading, sticky `#selection-counter`, disabled-at-cap with title, single-source `syncSelectionVisuals` (T4). pytest coverage per spec §4 is in T1/T2/T4.
- **Deviations:** CI runs `node --test tests/js/picker.test.mjs` instead of the directory (Node ≥ 22 compatibility). `load_tags()` is an uncached read (as `load_regions()` actually is; the spec's "cached" wording is inaccurate). The pre-existing `#selection-count` in the run section is kept and updated alongside the new `#selection-counter`.
- **Type consistency:** `PickerCore.filterModels/targetsForModel/capState`, `toggleTarget`, `applyFilters`, `renderTagFilters`, `modelRow` are named identically wherever used; DOM classes (`curated-rows`, `live-group`, `model-row`, `backend-check`, `provider-dropdown`, `provider-selected`) match between JS and CSS.
