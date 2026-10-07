# EvalForge Lite — Cross-Platform Comparison Dropdown (Sub-project 1 of 3)

**Date:** 2026-10-07
**Status:** Design (pending user approval)
**Branch:** `docs/cross-platform-comparison-spec` (from `main`)
**Part of:** a larger request split into three sub-projects. This is **1**. Sub-project 2 (judge & policy backend combination, including the deployment-parity judge, judge panel and tiered policy gate; pairs with the saved JEV todo) and sub-project 3 (competitor positioning, blocked on the tool names) get their own specs.

## Goal

1. Let a user test **the same model on different platforms** (OpenRouter, Bedrock, Vertex, Foundry) in one click, to see whether deployment changes the result.
2. Source the comparable entries **only from the backend**. There is no UI or API for creating them; testing other combinations means cloning the repo and editing a data file.
3. Say so on the front screen.

## Context

The per-provider picker already lets a user tick `X` (OpenRouter) and `X@bedrock` side by side, so cross-platform runs are possible today. What is missing is a curated, discoverable shortcut. Today's native routes in `data/providers.json`:

- Llama 4 Maverick, Llama 4 Scout, Llama 3.3 70B: Bedrock, Vertex and Foundry (with OpenRouter, 4 platforms, exactly `config.MAX_MODELS`).
- Claude Opus/Sonnet/Haiku 4.5: Bedrock. GPT-5, GPT-5 Mini, GPT-4o, GPT-4o Mini: Foundry. Gemini 2.5 Pro/Flash: Vertex. Each compares against OpenRouter.

## Decisions

- **Source of entries:** a curated `data/comparisons.json`, validated against `providers.json` (not auto-derived, not hardcoded in `config.py`). Mirrors how `tags.json` and `regions.json` work.
- **Click behavior:** replaces the current selection with the entry's targets. Simple, and cannot exceed the 4-target cap.
- **Trust boundary unchanged:** the browser still sends an ordinary target list. The server's existing validation (`_validate_run_body`, `MAX_MODELS`) remains the only authority. No new write endpoint.

## 1. Data

### `data/comparisons.json` (new)

```json
{
  "verified": "2026-10-07",
  "comparisons": [
    {
      "id": "llama-4-maverick-all",
      "label": "Llama 4 Maverick across all platforms",
      "model": "meta-llama/llama-4-maverick",
      "backends": ["openrouter", "bedrock", "vertex", "foundry"]
    }
  ]
}
```

Seed entries: the three Llama models on all four platforms; each Claude model (`openrouter`, `bedrock`); each GPT model (`openrouter`, `foundry`); each Gemini 2.5 model (`openrouter`, `vertex`). Entry ids are unique.

### Loading and validation

- `config.load_comparisons()` reads the file (same shape as `load_tags()`).
- `catalog.comparison_entries(catalog_dict, data)` resolves each entry to `{id, label, model_id, model_name, provider, targets: [{target, backend}]}`, where `target` is `model` for `openrouter` and `model@backend` otherwise.
- An entry is **invalid** (and is dropped with a logged warning at runtime, but fails the test suite) when: the model is not in the catalog; a non-OpenRouter backend has no route for that model; the model id starts with `~` (alias models have no stable identity to compare); fewer than 2 backends; duplicate backends; or more backends than `config.MAX_MODELS`.
- `/api/catalog` gains a `comparisons` key with the resolved entries. No other endpoint changes.

## 2. Frontend

- A **"Compare one model across platforms"** dropdown (expandable list, same style as `.provider-dropdown`) sits directly above "Browse by provider".
- Each entry shows the model name, the provider accent colour, and a chip per platform.
- Clicking an entry clears `state.selectedModels` and selects the entry's targets, then the existing flow takes over: selection counter, region warnings, credential prompts for the backends now needed.
- A pure `PickerCore.targetsForComparison(entry)` returns the target list (DOM-free, tested under `node --test` in `tests/js/`).

### Front-screen note

Shown directly under the dropdown heading:

> Cross-platform comparisons are defined in the backend (`data/comparisons.json`). To test other model/platform combinations, clone the repository and edit that file.

## 3. Error handling

- Missing or unreadable `comparisons.json`: `/api/catalog` returns an empty `comparisons` list and the dropdown is hidden. The picker and everything else keep working (advisory data, fail soft, like `regions.json`).
- A malformed entry never reaches the browser (dropped server-side, see Validation).
- A user who clicks an entry without credentials for one of its backends gets the same missing-credential handling as manually ticking those targets. No new error path.

## 4. Testing

- `tests/test_catalog.py`: resolution produces correct targets (`X` for OpenRouter, `X@backend` otherwise); each invalid-entry rule drops the entry; **the shipped `comparisons.json` has zero invalid entries** (guards drift from `providers.json`); entry ids unique.
- `tests/test_app.py`: `/api/catalog` includes `comparisons`; missing file yields `[]`.
- `tests/test_config.py`: `load_comparisons()` loads the file.
- `tests/js/picker.test.mjs`: `targetsForComparison` output; never exceeds the cap for shipped entries.
- No network anywhere (matches the repo rule).

## 5. Docs

- `CLAUDE.md`: add `data/comparisons.json` to the architecture list; note it is advisory/curation data and `gateway.py` never reads it.
- README / user guide: one paragraph on the dropdown and how to add an entry by cloning the repo.

## Out of scope

- Any UI for creating or editing comparisons.
- Scoring the *difference* between platforms (deployment-parity judge). That is sub-project 2.
- New backends or new native routes in `providers.json`.
- Competitor positioning (sub-project 3).
