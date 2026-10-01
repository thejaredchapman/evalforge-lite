# EvalForge Lite — Per-Provider Model Picker, Reasoning Labels & Need/Industry Tags (Sub-project B)

**Date:** 2026-10-01
**Status:** Design (pending user approval)
**Branch:** `feat/model-picker` (from `feat/foundry-regions` @ f06f5e8, which includes A and C)
**Part of:** a larger request split into sub-projects A → C → B → D → E → F. A and C are done. This is **B**.

## Goal

1. Replace the "Browse by provider" badge grid with **one collapsible dropdown per provider**. Each dropdown lists that provider's models as **checkbox rows**, and the total selection stays capped at **4**.
2. Show a **Reasoning** label on every model that supports reasoning.
3. Categorize models by **need** and **industry** using curated, dated tags. **Filter chips** narrow the visible models, and each tag carries a one-line "why".

## Decisions (from brainstorming)

- **Picker:** dropdown + checkboxes, one per provider.
  - Each row shows the model name, a Reasoning badge, and backend checkboxes (OpenRouter plus whichever of Bedrock/Vertex/Foundry the model has routes for).
  - The live "more from OpenRouter" models appear inside the same dropdown, under a sub-heading.
  - A sticky "Selected N / 4" counter sits above the dropdowns. The cap is unchanged (`config.MAX_MODELS = 4`).
- **Categories:** curated tags plus filter chips.
  - Needs: Coding, Reasoning & maths, Long documents, Fast & cheap, Creative writing, Multilingual, Agents & tool use.
  - Industries: Healthcare, Legal, Finance, Customer support, Education, Research.
  - Tags are curated and dated, with a "verify on your own" disclaimer. They are not live benchmarks.

## 1. Data

### `data/tags.json` (new)

```json
{
  "verified": "2026-10-01",
  "disclaimer": "Tags are a curated starting point, not benchmarks. Models change often — verify fit for your own use case before relying on them.",
  "tags": [
    {"id": "coding", "label": "Coding", "kind": "need", "why": "Strong at writing, explaining and fixing code."},
    {"id": "reasoning", "label": "Reasoning & maths", "kind": "need", "why": "Handles multi-step logic, maths and planning problems well."},
    {"id": "long-context", "label": "Long documents", "kind": "need", "why": "Large context window; can read long reports, contracts or codebases in one go."},
    {"id": "fast-cheap", "label": "Fast & cheap", "kind": "need", "why": "Low latency and low price per token; good for high-volume or simple tasks."},
    {"id": "creative", "label": "Creative writing", "kind": "need", "why": "Fluent, natural prose for drafting, marketing copy and storytelling."},
    {"id": "multilingual", "label": "Multilingual", "kind": "need", "why": "Solid quality across many languages, not just English."},
    {"id": "agents", "label": "Agents & tool use", "kind": "need", "why": "Reliable at calling tools/functions and following multi-step plans."},
    {"id": "healthcare", "label": "Healthcare", "kind": "industry", "why": "Careful, well-hedged answers suited to clinical summaries and patient-facing drafts (always with human review)."},
    {"id": "legal", "label": "Legal", "kind": "industry", "why": "Precise reading of long, dense text such as contracts and policies."},
    {"id": "finance", "label": "Finance", "kind": "industry", "why": "Accurate with numbers, tables and structured reasoning over reports."},
    {"id": "customer-support", "label": "Customer support", "kind": "industry", "why": "Fast, friendly, consistent replies at a low cost per conversation."},
    {"id": "education", "label": "Education", "kind": "industry", "why": "Clear step-by-step explanations at an adjustable level."},
    {"id": "research", "label": "Research", "kind": "industry", "why": "Synthesizes long sources and reasons carefully about evidence."}
  ]
}
```

The tag ids, labels and kinds above are fixed. The `why` wording may be edited lightly.

### `data/providers.json`

Every curated model gains `"tags": [<tag id>, ...]`: between 1 and 6 ids, all present in `tags.json`. Assignment is a curated judgment (for example, flagship reasoning models get `reasoning`, `coding`, `research`; mini/flash/haiku tiers get `fast-cheap`, `customer-support`). The existing `reasoning` boolean is unchanged and drives the Reasoning badge. It is independent of the `reasoning` *tag*, which means "good at reasoning tasks".

### `catalog.py`

- `load_tags() -> dict`: reads `data/tags.json` (cached like `load_regions`).
- `models_for_tag(catalog_dict, tag_id) -> list[str]`: the model ids carrying that tag. A pure helper for tests, and usable by D's model suggester later.

### API and MCP

- `/api/catalog` gains `"tags": catalog.load_tags()`. Models already carry their `tags` through `providers`.
- MCP `list_models` gains `"tags": catalog.load_tags()` in its return value. Its docstring mentions tags and the reasoning flag.

## 2. Frontend picker

### Frontier picks

These stay as the quick-pick badge row at the top, and are now also checkbox-synced. Toggling a frontier badge checks/unchecks the matching OpenRouter checkbox in its provider dropdown, and vice versa.

### Filter chips (`#tag-filters`, above the provider dropdowns)

- There are two labelled rows, **"What do you need?"** (needs) and **"Industry"** (industries). Each chip is a `<button aria-pressed>`.
- Clicking a chip toggles it. With one or more chips active, only models that carry **all** active tags are shown (AND), and provider dropdowns with matches open automatically. With no chips active, everything is shown.
- Each active chip's `why` line appears below the chip rows, so the user sees why those models are included.
- A "Clear filters" button and a live count ("Showing 7 of 31 models") update on every change. The count uses `aria-live="polite"`.
- The disclaimer and the `verified` date appear in small text under the chips: "Tags curated as of 2026-10-01. A starting point, not a benchmark — verify on your own."
- Filtering **never deselects** anything. A selected model hidden by a filter stays selected and stays in the counter and the selected list.
- Live OpenRouter extras have no tags, so they are hidden whenever any filter is active.

### Provider dropdowns (`#provider-list`)

- Each provider is a `<details class="provider-dropdown">`. Its `<summary>` shows the provider name in the brand color, the model count, and "N selected" when any target from that provider is selected. All dropdowns start collapsed.
- The blurb is the first line inside the dropdown, set via `textContent`. This replaces the current `innerHTML` interpolation.
- Each model row (`.model-row`) contains:
  - the model name;
  - a **Reasoning** badge (`.reasoning-badge`, text "Reasoning", with `title` "Supports extended reasoning") when `model.reasoning`;
  - tag pills (small, muted, from `tags.json` labels);
  - a checkbox per backend: **OpenRouter** (always present), plus **Bedrock** / **Vertex** / **Foundry** for each route. Every checkbox has `data-target` (`id` or `id@backend`) and an `aria-label` such as "GPT-5 via Microsoft Foundry".
- Region warnings: the existing ⚠ mismatch logic (`regionWarnings`/`syncRegionWarnings`) attaches to the backend checkbox labels instead of the old chips, with the same text and tooltip.
- **More from OpenRouter:** below the curated rows, a sub-heading "More from OpenRouter's live catalog" lists the same ≤10 newest live models as today. Their rows have only the OpenRouter checkbox and no tags or reasoning badge. Reasoning comes from the curated flag, and live models aren't flagged.

### Cap and counter

- `#selection-counter`: "Selected N / 4", sticky at the top of the catalog section, with `aria-live="polite"`.
- At the cap, every unchecked checkbox is **disabled**, with a `title` explaining the cap. The cap message still appears in `#run-status` if the user tries to exceed it through other paths (custom id, Try it).
- `syncSelectionVisuals()` becomes the single source of truth. For every element with `data-target`, it sets `checked` (checkboxes) or the selected class (badges), refreshes disabled states, updates the counter and the per-provider "N selected", and re-runs the region warnings. Custom ids, "Try it" and frontier picks all go through it.

### Unchanged

The custom model id input, priority selector, repeats, cost estimate, judge selector, results/compare views, and everything from C.

### Accessibility and safety

- All catalog text goes into the DOM via `textContent`/`escapeHtml`.
- Checkboxes have labels.
- `<details>`/`<summary>` give keyboard support natively.
- Brand colors come from CSS variables (`--accent`), and the new classes follow the existing theme variables in light and dark modes. Layout stacks on mobile.

## 3. Server-side

There is no change to run semantics. `/api/run` and MCP `run_comparison` still take a list of targets capped at `config.MAX_MODELS`. The picker is purely a UI change plus catalog data.

## 4. Testing (no live network)

- `test_catalog.py`:
  - `tags.json` loads;
  - every tag has an `id`, a `label`, a `kind` ∈ {need, industry} and a non-empty `why` (≤ 140 chars);
  - the exact 7 need ids and 6 industry ids are present;
  - `verified` is an ISO date;
  - every curated model has 1–6 tags, all known ids;
  - every tag is used by at least one model;
  - `models_for_tag`.
- `test_app.py`: `/api/catalog` includes `tags`, and models include `tags`. The `/` render contains `#tag-filters`, `#selection-counter` and `#provider-list`.
- `test_mcp_server.py`: `list_models` includes `tags`.
- Frontend:
  - `node --check static/app.js`;
  - a small Node-run test (`tests/js/picker.test.mjs`, run with `node --test`, no npm deps) for the pure functions extracted into `static/picker-core.js`:
    - `filterModels(models, activeTagIds)` (AND semantics; no tags → all; untagged hidden when filtering);
    - `targetsForModel(model)` (OpenRouter + routes);
    - `capState(selectedCount, max)`.
  - `picker-core.js` is loaded with a plain `<script>` before `app.js` and exports via `globalThis.PickerCore`, plus `module.exports` when `module` exists, so Node can import it.
- CI (`.github/workflows/tests.yml`) gains an `actions/setup-node` step (Node 20) that runs `node --check` on every file in `static/*.js` and `node --test tests/js/`.
- The full pytest suite stays green.

## Out of scope for B

Model suggestions from free text (D), ranking/about/responsibility pages (E), Markdown export (F), and live benchmark-driven tags.
