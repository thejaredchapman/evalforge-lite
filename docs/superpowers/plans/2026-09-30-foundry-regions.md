# Foundry, Regions & Availability, Status Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Microsoft Foundry as a fourth model backend; replace free-text Bedrock/Vertex region fields with region dropdowns that warn when a model isn't listed for the chosen region; add a "Where models run" availability page (live OpenRouter + curated Bedrock/Vertex/Foundry regions, refreshed at most every 6 hours); and link to each backend's status page and report-a-problem page, including from the error popup.

**Architecture:** `foundry.py` is a thin REST client mirroring `vertex.py` exactly (pure function + `call_model`, no gateway/catalog dependency). `gateway.py` gains a fourth backend through the same `_prepare_<backend>` / `call_backend` dispatch pattern already used for Bedrock and Vertex, now also validating regions against a new curated `data/regions.json` (loaded via `config.load_regions()` / `catalog.load_regions()`, mirroring `load_providers()`/`load_catalog()`). `catalog.region_availability()` is a small pure helper the API and frontend both use to warn about region mismatches. `availability.py` is a new single-responsibility module — a 6-hour-TTL cache wrapping `catalog.fetch_openrouter_models()` plus a read of the curated backend region data — exposed via `/api/availability` and an MCP `list_availability` tool. The frontend gets a 4th credentials tab, turns the two existing region text inputs into `<select>`s, adds inline ⚠ warnings on backend chips, and gains a new server-rendered `/availability` page with its own small JS file. Status/report-a-problem links live in one `PROVIDER_LINKS` map, duplicated deliberately in JS and Python (matching the existing `BACKEND_LABELS` duplication) and also exposed through `/api/catalog` for the availability page to use.

**Tech Stack:** Python 3.12 (Flask, requests), vanilla JS (no build step), pytest with `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-09-30-foundry-regions-design.md`.

## Global Constraints

- Branch `feat/foundry-regions` (already checked out — do not switch or create a new branch). Python: `venv/bin/python`, `venv/bin/pytest` (Python 3.12). Run the suite with `venv/bin/pytest tests/ -q`; it is green at 387 tests before Task 1. Node is at `/opt/homebrew/bin/node` (used only for `node --check <file>.js` syntax checks — no JS test runner in this repo).
- **No live network in any test.** Mock `requests.*`, `gateway.*`, `catalog.fetch_openrouter_models`, or `availability.*` — never let a test reach OpenRouter, AWS, GCP, or Azure. Mock `time.time`/pass explicit `now=` arguments for anything TTL-related instead of sleeping.
- **Every new secret-bearing path gets a key-leak assertion**: Foundry's `api_key`/`access_token` must never appear in an API JSON response, a log line (`caplog`), run history, an MCP tool result, or a PDF/CSV report. Task 3 covers `scrub.py` unit coverage (JWT pattern + exact-value redaction); Task 5 covers the end-to-end `/api/run` and `run_comparison` key-leak tests.
- **Pathspec commits only.** Every commit step in this plan uses `git add <exact files> && git commit -m "<subject>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- <exact files>`. Never `git reset`, `git stash`, `git clean`, `git checkout --`, or `--amend` unless a human explicitly asks for it in this session.
- **`CLAUDE.md` is untracked.** Task 8 edits it for future readers, but it must never be passed to `git add` or appear in any commit's pathspec.
- **All model/user/server text reaching the DOM goes through `textContent` or `escapeHtml()`** — never string-interpolated into `innerHTML` unescaped. This applies to every new frontend element added in Tasks 6 and 7 (region warning text, availability table cells, status/report links' visible text where it's server data, etc.).
- **Foundry's host is fixed to `*.services.ai.azure.com`.** The client (`foundry.py`) never accepts a caller-supplied full URL — only a `resource` string that gets interpolated into a fixed template. `gateway._prepare_foundry` validates `resource` against `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$` and `region` against the curated Foundry region list in `data/regions.json` *before* `foundry.call_model` is ever reached, exactly like Bedrock's region regex and Vertex's project regex are checked before their clients run.
- **Fail-closed / fail-soft, per the existing pattern**: Foundry credential validation fails closed (`check_run_creds` rejects it up front, before the rate limiter, exactly like Bedrock/Vertex today — no new code needed there since it already iterates `gateway.BACKENDS`). `availability.snapshot()` fails *soft*: a failed OpenRouter refresh keeps the last good snapshot and flags it `stale: true` rather than raising or blanking the data. Neither `policy.py` nor `judge.py`'s existing fail-closed behavior changes in this plan.
- Match surrounding style: no docstrings on simple functions, `_PRIVATE` module constants, `openrouter.py`-style error mapping (`RequestException` → wrapped error with response body, `ValueError` → malformed JSON, `KeyError/IndexError/TypeError` on parsing → unexpected shape).
- Curated prices, model ids, and region lists for Foundry (Task 4) and the `data/regions.json` region catalogs (Task 1) are **best-known estimates as of 2026-09-30** — the plan gives concrete values (no `TBD`s), and Task 8's docs note they should be verified against the provider's own page.

---

### Task 1: Region data (`data/regions.json`), `catalog.load_regions`/`region_availability`, Bedrock/Vertex region membership validation

**Files:**
- Create: `data/regions.json`
- Modify: `data/providers.json` (add `"regions"` to every existing Bedrock/Vertex route)
- Modify: `config.py` (add `load_regions()`)
- Modify: `catalog.py` (add `load_regions()`, `region_availability()`)
- Modify: `gateway.py` (Bedrock/Vertex region checks also validate membership in the curated list)
- Test: `tests/test_config.py`, `tests/test_catalog.py`, `tests/test_gateway.py`

**Interfaces:**
- Produces:
  - `config.load_regions() -> dict` — parses `data/regions.json`, same pattern as `config.load_providers()`.
  - `catalog.load_regions() -> dict` — thin wrapper over `config.load_regions()`, same pattern as `catalog.load_catalog()`.
  - `catalog.region_availability(catalog_dict, model_id, backend, region) -> {"listed": bool, "known_regions": list[str]}`.
  - Every Bedrock/Vertex route object in `data/providers.json` gains `"regions": [<region id>, ...]`.
  - `gateway._prepare_bedrock`/`_prepare_vertex` reject a syntactically-valid but uncurated region with the same existing messages (`"Bedrock region is missing or invalid."` / `"Vertex region is missing or invalid."`).
- Consumes: nothing new (pure additions to existing modules).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python


def test_load_regions_returns_dict_with_expected_backends():
    regions = config.load_regions()
    assert set(regions) == {"bedrock", "vertex", "foundry"}
```

Append to `tests/test_catalog.py`:

```python


def test_load_regions_matches_config():
    assert catalog.load_regions() == config.load_regions()


def test_load_regions_covers_bedrock_vertex_and_foundry():
    regions = catalog.load_regions()
    assert set(regions) == {"bedrock", "vertex", "foundry"}
    for data in regions.values():
        assert data["label"]
        assert data["verified"]
        assert data["source"].startswith("https://")
        assert len(data["regions"]) > 0
        for region in data["regions"]:
            assert set(region) == {"id", "label", "geo"}


def test_region_availability_listed():
    cat = catalog.load_catalog()
    result = catalog.region_availability(cat, "anthropic/claude-sonnet-4.5", "bedrock", "us-east-1")
    assert result["listed"] is True
    assert "us-east-1" in result["known_regions"]


def test_region_availability_not_listed():
    cat = catalog.load_catalog()
    result = catalog.region_availability(cat, "anthropic/claude-sonnet-4.5", "bedrock", "sa-east-1")
    assert result["listed"] is False
    assert "sa-east-1" not in result["known_regions"]


def test_region_availability_missing_route_returns_no_known_regions():
    cat = catalog.load_catalog()
    assert catalog.region_availability(cat, "openai/gpt-5", "bedrock", "us-east-1") == {
        "listed": False, "known_regions": [],
    }
```

Replace the existing `test_every_route_is_well_formed` in `tests/test_catalog.py` with:

```python
def test_every_route_is_well_formed():
    cat = catalog.load_catalog()
    regions_by_backend = catalog.load_regions()
    for provider in cat.values():
        for model in provider["models"]:
            for backend, route in (model.get("routes") or {}).items():
                assert backend in ("bedrock", "vertex")
                assert isinstance(route["id"], str) and route["id"]
                assert set(route["price"]) == {"input_per_m", "output_per_m"}
                assert all(isinstance(v, (int, float)) and v >= 0 for v in route["price"].values())
                known_ids = {r["id"] for r in regions_by_backend[backend]["regions"]}
                assert route["regions"] and set(route["regions"]) <= known_ids
```

Append to `tests/test_gateway.py`:

```python


def test_prepare_creds_rejects_bedrock_region_not_in_curated_list():
    prepared = gateway.prepare_creds({"bedrock": {"region": "af-south-1", "api_key": "ABSKexample"}})
    assert prepared["bedrock"] == {"error": "Bedrock region is missing or invalid."}


def test_prepare_creds_rejects_vertex_region_not_in_curated_list():
    prepared = gateway.prepare_creds({"vertex": {"project": "my-project-123", "region": "us-west4",
                                                 "access_token": "ya29.x"}})
    assert prepared["vertex"] == {"error": "Vertex region is missing or invalid."}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_config.py tests/test_catalog.py tests/test_gateway.py -q`
Expected: FAIL — `AttributeError: module 'config' has no attribute 'load_regions'` (and similar for `catalog.load_regions`/`catalog.region_availability`); the two new gateway tests fail because "af-south-1"/"us-west4" are currently accepted (regex-valid).

- [ ] **Step 3: Create `data/regions.json`**

```json
{
  "bedrock": {
    "label": "Amazon Bedrock",
    "verified": "2026-09-30",
    "source": "https://docs.aws.amazon.com/bedrock/latest/userguide/models-regions.html",
    "regions": [
      {"id": "us-east-1", "label": "US East (N. Virginia)", "geo": "US"},
      {"id": "us-east-2", "label": "US East (Ohio)", "geo": "US"},
      {"id": "us-west-2", "label": "US West (Oregon)", "geo": "US"},
      {"id": "ca-central-1", "label": "Canada (Central)", "geo": "CA"},
      {"id": "sa-east-1", "label": "South America (Sao Paulo)", "geo": "SA"},
      {"id": "eu-central-1", "label": "Europe (Frankfurt)", "geo": "EU"},
      {"id": "eu-west-1", "label": "Europe (Ireland)", "geo": "EU"},
      {"id": "eu-west-3", "label": "Europe (Paris)", "geo": "EU"},
      {"id": "ap-northeast-1", "label": "Asia Pacific (Tokyo)", "geo": "APAC"},
      {"id": "ap-south-1", "label": "Asia Pacific (Mumbai)", "geo": "APAC"},
      {"id": "ap-southeast-2", "label": "Asia Pacific (Sydney)", "geo": "APAC"},
      {"id": "us-gov-west-1", "label": "AWS GovCloud (US-West)", "geo": "US-GOV"}
    ]
  },
  "vertex": {
    "label": "Google Vertex AI",
    "verified": "2026-09-30",
    "source": "https://cloud.google.com/vertex-ai/generative-ai/docs/learn/locations",
    "regions": [
      {"id": "global", "label": "Global", "geo": "GLOBAL"},
      {"id": "us-central1", "label": "Iowa", "geo": "US"},
      {"id": "us-east1", "label": "South Carolina", "geo": "US"},
      {"id": "us-east4", "label": "N. Virginia", "geo": "US"},
      {"id": "us-east5", "label": "Columbus", "geo": "US"},
      {"id": "us-south1", "label": "Dallas", "geo": "US"},
      {"id": "us-west1", "label": "Oregon", "geo": "US"},
      {"id": "europe-west1", "label": "Belgium", "geo": "EU"},
      {"id": "europe-west4", "label": "Netherlands", "geo": "EU"},
      {"id": "europe-west9", "label": "Paris", "geo": "EU"},
      {"id": "asia-northeast1", "label": "Tokyo", "geo": "APAC"},
      {"id": "asia-southeast1", "label": "Singapore", "geo": "APAC"}
    ]
  },
  "foundry": {
    "label": "Microsoft Foundry",
    "verified": "2026-09-30",
    "source": "https://learn.microsoft.com/azure/ai-foundry/foundry-models/concepts/models",
    "regions": [
      {"id": "eastus", "label": "East US", "geo": "US"},
      {"id": "eastus2", "label": "East US 2", "geo": "US"},
      {"id": "westus", "label": "West US", "geo": "US"},
      {"id": "westus3", "label": "West US 3", "geo": "US"},
      {"id": "northcentralus", "label": "North Central US", "geo": "US"},
      {"id": "southcentralus", "label": "South Central US", "geo": "US"},
      {"id": "canadaeast", "label": "Canada East", "geo": "CA"},
      {"id": "swedencentral", "label": "Sweden Central", "geo": "EU"},
      {"id": "francecentral", "label": "France Central", "geo": "EU"},
      {"id": "uksouth", "label": "UK South", "geo": "EU"},
      {"id": "japaneast", "label": "Japan East", "geo": "APAC"},
      {"id": "australiaeast", "label": "Australia East", "geo": "APAC"}
    ]
  }
}
```

Validate: `venv/bin/python -c "import json; json.load(open('data/regions.json'))"` (no output = valid).

- [ ] **Step 4: Replace `data/providers.json`** with the full content below (adds `"regions"` to every existing Bedrock/Vertex route; nothing else changes):

```json
{
  "openai": {
    "blurb": "OpenAI builds the GPT model family and popularized the modern chat-assistant interface; broad general-purpose strength and the widest third-party tooling support.",
    "color": "#10A37F",
    "frontier": "~openai/gpt-latest",
    "models": [
      {"id": "~openai/gpt-latest", "name": "GPT (Latest)", "family": "gpt-5", "tier": "flagship", "reasoning": true},
      {"id": "openai/gpt-5", "name": "GPT-5", "family": "gpt-5", "tier": "flagship", "reasoning": true},
      {"id": "openai/gpt-5-mini", "name": "GPT-5 Mini", "family": "gpt-5", "tier": "fast", "reasoning": true},
      {"id": "openai/gpt-4o", "name": "GPT-4o", "family": "gpt-4o", "tier": "balanced"},
      {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "family": "gpt-4o", "tier": "fast"}
    ]
  },
  "anthropic": {
    "blurb": "Anthropic builds the Claude model family with a focus on reliability and steerability; strong at careful reasoning, following detailed instructions, and long-context work.",
    "color": "#D97757",
    "frontier": "~anthropic/claude-opus-latest",
    "models": [
      {"id": "~anthropic/claude-opus-latest", "name": "Claude Opus (Latest)", "family": "claude-opus", "tier": "flagship"},
      {"id": "anthropic/claude-opus-4.5", "name": "Claude Opus 4.5", "family": "claude-opus", "tier": "flagship", "routes": {"bedrock": {"id": "{geo}.anthropic.claude-opus-4-5-20251101-v1:0", "price": {"input_per_m": 5.0, "output_per_m": 25.0}, "regions": ["us-east-1", "us-east-2", "us-west-2", "eu-central-1", "eu-west-1", "ap-northeast-1", "ap-southeast-2"]}}},
      {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5", "family": "claude-sonnet", "tier": "balanced", "routes": {"bedrock": {"id": "{geo}.anthropic.claude-sonnet-4-5-20250929-v1:0", "price": {"input_per_m": 3.0, "output_per_m": 15.0}, "regions": ["us-east-1", "us-east-2", "us-west-2", "eu-central-1", "eu-west-1", "eu-west-3", "ap-northeast-1", "ap-south-1", "ap-southeast-2"]}}},
      {"id": "anthropic/claude-haiku-4.5", "name": "Claude Haiku 4.5", "family": "claude-haiku", "tier": "fast", "routes": {"bedrock": {"id": "{geo}.anthropic.claude-haiku-4-5-20251001-v1:0", "price": {"input_per_m": 1.0, "output_per_m": 5.0}, "regions": ["us-east-1", "us-east-2", "us-west-2", "eu-central-1", "eu-west-1", "ap-northeast-1", "ap-southeast-2"]}}}
    ]
  },
  "google": {
    "blurb": "Google DeepMind builds the Gemini model family with native multimodal training and very large context windows, integrated tightly with Google's own products.",
    "color": "#4285F4",
    "frontier": "~google/gemini-pro-latest",
    "models": [
      {"id": "~google/gemini-pro-latest", "name": "Gemini Pro (Latest)", "family": "gemini-pro", "tier": "flagship", "reasoning": true},
      {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro", "family": "gemini-pro", "tier": "flagship", "reasoning": true, "routes": {"vertex": {"id": "google/gemini-2.5-pro", "price": {"input_per_m": 1.25, "output_per_m": 10.0}, "regions": ["global", "us-central1", "us-east1", "us-east4", "us-west1", "europe-west1", "europe-west4", "asia-northeast1", "asia-southeast1"]}}},
      {"id": "google/gemini-3.7-flash", "name": "Gemini 3.7 Flash", "family": "gemini-flash", "tier": "balanced", "reasoning": true},
      {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "family": "gemini-flash", "tier": "fast", "reasoning": true, "routes": {"vertex": {"id": "google/gemini-2.5-flash", "price": {"input_per_m": 0.3, "output_per_m": 2.5}, "regions": ["global", "us-central1", "us-east1", "us-east4", "us-west1", "europe-west1", "europe-west4", "asia-northeast1", "asia-southeast1"]}}}
    ]
  },
  "meta-llama": {
    "blurb": "Meta builds the open-weight Llama model family, widely used for self-hosting and fine-tuning where control over weights and cost matters more than using a closed API.",
    "color": "#0668E1",
    "frontier": "meta-llama/llama-4-maverick",
    "models": [
      {"id": "meta-llama/llama-4-maverick", "name": "Llama 4 Maverick", "family": "llama-4", "tier": "flagship", "routes": {"bedrock": {"id": "{geo}.meta.llama4-maverick-17b-instruct-v1:0", "price": {"input_per_m": 0.24, "output_per_m": 0.97}, "regions": ["us-east-1", "us-east-2", "us-west-2"]}, "vertex": {"id": "meta/llama-4-maverick-17b-128e-instruct-maas", "price": {"input_per_m": 0.35, "output_per_m": 1.15}, "regions": ["us-east5"]}}},
      {"id": "meta-llama/llama-4-scout", "name": "Llama 4 Scout", "family": "llama-4", "tier": "fast", "routes": {"bedrock": {"id": "{geo}.meta.llama4-scout-17b-instruct-v1:0", "price": {"input_per_m": 0.17, "output_per_m": 0.66}, "regions": ["us-east-1", "us-east-2", "us-west-2"]}, "vertex": {"id": "meta/llama-4-scout-17b-16e-instruct-maas", "price": {"input_per_m": 0.25, "output_per_m": 0.7}, "regions": ["us-east5"]}}},
      {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "family": "llama-3", "tier": "balanced", "routes": {"bedrock": {"id": "{geo}.meta.llama3-3-70b-instruct-v1:0", "price": {"input_per_m": 0.72, "output_per_m": 0.72}, "regions": ["us-east-1", "us-east-2", "us-west-2", "eu-central-1", "eu-west-1", "ap-northeast-1"]}, "vertex": {"id": "meta/llama-3.3-70b-instruct-maas", "price": {"input_per_m": 0.72, "output_per_m": 0.72}, "regions": ["us-east5"]}}}
    ]
  }
}
```

Validate: `venv/bin/python -c "import json; json.load(open('data/providers.json'))"`.

- [ ] **Step 5: Implement `config.load_regions()`**

In `config.py`, after `_PROVIDERS_PATH = _DATA_DIR / "providers.json"` add:

```python
_REGIONS_PATH = _DATA_DIR / "regions.json"
```

After `load_providers()` add:

```python
def load_regions():
    with open(_REGIONS_PATH) as f:
        return json.load(f)
```

- [ ] **Step 6: Implement `catalog.load_regions()` and `catalog.region_availability()`**

In `catalog.py`, after `load_catalog()` add:

```python
def load_regions():
    return config.load_regions()
```

At the end of `catalog.py` add:

```python
def region_availability(catalog_dict, model_id, backend, region):
    route = route_for(catalog_dict, model_id, backend)
    known_regions = list((route or {}).get("regions") or [])
    return {"listed": region in known_regions, "known_regions": known_regions}
```

- [ ] **Step 7: Add Bedrock/Vertex region membership validation to `gateway.py`**

After the existing regex constants (`_BEDROCK_REGION_RE`, `_VERTEX_REGION_RE`, `_VERTEX_PROJECT_RE`), add:

```python
def _known_region_ids(backend):
    return {r["id"] for r in catalog.load_regions()[backend]["regions"]}
```

In `_prepare_bedrock`, change:

```python
    if not _nonempty_str(region) or not _BEDROCK_REGION_RE.match(region):
        raise GatewayError("Bedrock region is missing or invalid.")
```

to:

```python
    if not _nonempty_str(region) or not _BEDROCK_REGION_RE.match(region) or region not in _known_region_ids("bedrock"):
        raise GatewayError("Bedrock region is missing or invalid.")
```

In `_prepare_vertex`, change:

```python
    if not _nonempty_str(region) or not _VERTEX_REGION_RE.match(region):
        raise GatewayError("Vertex region is missing or invalid.")
```

to:

```python
    if not _nonempty_str(region) or not _VERTEX_REGION_RE.match(region) or region not in _known_region_ids("vertex"):
        raise GatewayError("Vertex region is missing or invalid.")
```

(`catalog` is already imported at the top of `gateway.py` — no new import needed.)

- [ ] **Step 8: Run tests**

Run: `venv/bin/pytest tests/test_config.py tests/test_catalog.py tests/test_gateway.py -q` → PASS.
Run: `venv/bin/pytest tests/ -q` → PASS (full suite).

- [ ] **Step 9: Commit**

```bash
git add data/regions.json data/providers.json config.py catalog.py gateway.py tests/test_config.py tests/test_catalog.py tests/test_gateway.py
git commit -m "feat: curated region data, catalog.region_availability, and Bedrock/Vertex region membership checks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- data/regions.json data/providers.json config.py catalog.py gateway.py tests/test_config.py tests/test_catalog.py tests/test_gateway.py
```

---

### Task 2: `foundry.py` — Microsoft Foundry REST client

**Files:**
- Create: `foundry.py`
- Test: `tests/test_foundry.py`

**Interfaces:**
- Consumes: `errors.GatewayError`, `errors.describe_request_error`.
- Produces:
  - `foundry.FoundryError(GatewayError)`.
  - `foundry.endpoint_url(resource) -> str` — pure function: `https://{resource}.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview`.
  - `foundry.call_model(model_id, messages, creds, timeout=60) -> dict` with keys `text`, `latency_ms`, `cost_usd` (always `0.0`), `tokens`, `input_tokens`, `output_tokens`. `creds` is `{"resource": str, "region": str, "api_key": str}` or `{"resource": str, "region": str, "access_token": str}` (region isn't part of the request — it's validated by `gateway.py` for UI/availability purposes only).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_foundry.py`:

```python
from unittest.mock import Mock, patch

import pytest
import requests

import foundry
from errors import GatewayError

API_KEY_CREDS = {"resource": "my-resource", "region": "eastus", "api_key": "fake-api-key-12345678"}
TOKEN_CREDS = {"resource": "my-resource", "region": "eastus",
              "access_token": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123signature"}


def _mock_response(json_body):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_body
    return resp


def _chat_body(text="Paris."):
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11},
    }


def test_foundry_error_is_a_gateway_error():
    assert issubclass(foundry.FoundryError, GatewayError)


def test_endpoint_url_uses_resource_subdomain():
    assert foundry.endpoint_url("my-resource") == (
        "https://my-resource.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview"
    )


@patch("foundry.requests.post")
def test_call_model_returns_text_latency_tokens(mock_post):
    mock_post.return_value = _mock_response(_chat_body())

    result = foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], API_KEY_CREDS)

    assert result["text"] == "Paris."
    assert result["tokens"] == 11
    assert result["input_tokens"] == 9
    assert result["output_tokens"] == 2
    assert result["cost_usd"] == 0.0


@patch("foundry.requests.post")
def test_call_model_sends_api_key_header_when_api_key_present(mock_post):
    mock_post.return_value = _mock_response(_chat_body())

    foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], API_KEY_CREDS)

    args, kwargs = mock_post.call_args
    assert args[0] == foundry.endpoint_url("my-resource")
    assert kwargs["headers"]["api-key"] == "fake-api-key-12345678"
    assert "Authorization" not in kwargs["headers"]
    assert kwargs["json"] == {"model": "openai/gpt-5", "messages": [{"role": "user", "content": "hi"}]}


@patch("foundry.requests.post")
def test_call_model_sends_bearer_token_when_access_token_present(mock_post):
    mock_post.return_value = _mock_response(_chat_body())

    foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], TOKEN_CREDS)

    args, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN_CREDS['access_token']}"
    assert "api-key" not in kwargs["headers"]


def test_call_model_without_any_auth_raises():
    with pytest.raises(foundry.FoundryError, match="Foundry credentials were not prepared."):
        foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}],
                           {"resource": "my-resource", "region": "eastus"})


@patch("foundry.requests.post")
def test_call_model_raises_on_request_exception(mock_post):
    mock_post.side_effect = requests.RequestException("boom")

    with pytest.raises(foundry.FoundryError):
        foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], API_KEY_CREDS)


@patch("foundry.requests.post")
def test_call_model_raises_on_malformed_json(mock_post):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.side_effect = ValueError("bad json")
    mock_post.return_value = resp

    with pytest.raises(foundry.FoundryError):
        foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], API_KEY_CREDS)


@patch("foundry.requests.post")
def test_call_model_raises_on_unexpected_shape(mock_post):
    mock_post.return_value = _mock_response({"unexpected": "shape"})

    with pytest.raises(foundry.FoundryError):
        foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], API_KEY_CREDS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_foundry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry'`.

- [ ] **Step 3: Implement `foundry.py`**

```python
import time

import requests

from errors import GatewayError, describe_request_error

HOST_TEMPLATE = "https://{resource}.services.ai.azure.com"
API_VERSION = "2024-05-01-preview"


class FoundryError(GatewayError):
    pass


def endpoint_url(resource):
    return f"{HOST_TEMPLATE.format(resource=resource)}/models/chat/completions?api-version={API_VERSION}"


def _auth_headers(creds):
    headers = {"Content-Type": "application/json"}
    if creds.get("api_key"):
        headers["api-key"] = creds["api_key"]
    elif creds.get("access_token"):
        headers["Authorization"] = f"Bearer {creds['access_token']}"
    else:
        raise FoundryError("Foundry credentials were not prepared.")
    return headers


def call_model(model_id, messages, creds, timeout=60):
    headers = _auth_headers(creds)

    start = time.monotonic()
    try:
        resp = requests.post(
            endpoint_url(creds["resource"]),
            headers=headers,
            json={"model": model_id, "messages": messages},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise FoundryError(describe_request_error(e)) from e
    except ValueError as e:
        raise FoundryError(f"Malformed JSON in Foundry response: {str(e)}") from e

    latency_ms = int((time.monotonic() - start) * 1000)

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise FoundryError(f"Unexpected Foundry response shape: {data!r}") from e

    usage = data.get("usage", {}) or {}
    return {
        "text": text,
        "latency_ms": latency_ms,
        "cost_usd": 0.0,
        "tokens": usage.get("total_tokens", 0),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/test_foundry.py -q` → PASS.
Run: `venv/bin/pytest tests/ -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add foundry.py tests/test_foundry.py
git commit -m "feat: add foundry.py, a REST client for Microsoft Foundry" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- foundry.py tests/test_foundry.py
```

---

### Task 3: Wire Foundry into `gateway`/`config`/`scrub`/`analysis` (incl. JWT scrub pattern)

**Files:**
- Modify: `gateway.py`, `config.py`, `scrub.py`, `analysis.py`, `.env.example`
- Test: `tests/test_gateway.py`, `tests/test_config.py`, `tests/test_scrub.py`, `tests/test_analysis.py`

**Interfaces:**
- Consumes: `foundry.call_model` (Task 2), `catalog.load_regions`/`_known_region_ids("foundry")` (Task 1, reused for Foundry region membership).
- Produces:
  - `gateway.BACKENDS == ("openrouter", "bedrock", "vertex", "foundry")`.
  - `gateway.BACKEND_LABELS["foundry"] == "Microsoft Foundry"`.
  - `gateway._prepare_foundry(raw) -> {"resource", "region", "api_key"}` or `{"resource", "region", "access_token"}`, or raises `GatewayError`.
  - `gateway.call_backend("foundry", ...)` dispatches to `foundry.call_model`.
  - `config.JUDGE_MODELS["foundry"] == "gpt-4o-mini"` (overridable via `FOUNDRY_JUDGE_MODEL`).
  - `scrub._SECRET_FIELDS["foundry"] == ("api_key", "access_token")`; a new JWT-shaped-bearer-token pattern in `scrub._PATTERNS`.
  - `analysis._BACKEND_LABEL_TERMS` includes `"Microsoft Foundry"` and `"Foundry"`.
  - Because `gateway.BACKENDS` now includes `"foundry"`, `gateway.check_run_creds`, `gateway.parse_target`, `gateway.prepare_creds`, and `gateway.call_target` all support `@foundry` targets and a `"foundry"` judge backend automatically — no changes needed to those functions themselves.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gateway.py`:

```python


FOUNDRY_API_KEY_CREDS = {"resource": "my-resource", "region": "eastus", "api_key": "fake-api-key-12345678"}
FOUNDRY_TOKEN_CREDS = {"resource": "my-resource", "region": "eastus",
                      "access_token": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.sig"}


def test_backends_include_foundry():
    assert gateway.BACKENDS == ("openrouter", "bedrock", "vertex", "foundry")
    assert gateway.BACKEND_LABELS["foundry"] == "Microsoft Foundry"


def test_prepare_creds_accepts_foundry_api_key():
    prepared = gateway.prepare_creds({"foundry": FOUNDRY_API_KEY_CREDS})
    assert prepared["foundry"] == FOUNDRY_API_KEY_CREDS


def test_prepare_creds_accepts_foundry_access_token():
    prepared = gateway.prepare_creds({"foundry": FOUNDRY_TOKEN_CREDS})
    assert prepared["foundry"] == FOUNDRY_TOKEN_CREDS


@pytest.mark.parametrize("resource", ["evil.com#", "EVIL-RESOURCE", "a" * 70])
def test_prepare_creds_rejects_bad_foundry_resource(resource):
    raw = {"resource": resource, "region": "eastus", "api_key": "fake-api-key-12345678"}
    prepared = gateway.prepare_creds({"foundry": raw})
    assert prepared["foundry"] == {"error": "Foundry resource name is missing or invalid."}


def test_prepare_creds_rejects_unknown_foundry_region():
    raw = {"resource": "my-resource", "region": "centralus", "api_key": "fake-api-key-12345678"}
    prepared = gateway.prepare_creds({"foundry": raw})
    assert prepared["foundry"] == {"error": "Foundry region is missing or invalid."}


def test_prepare_creds_rejects_foundry_with_both_auth_methods():
    raw = {"resource": "my-resource", "region": "eastus", "api_key": "fake-api-key-12345678",
           "access_token": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.sig"}
    prepared = gateway.prepare_creds({"foundry": raw})
    assert prepared["foundry"] == {"error": "Foundry credentials need exactly one of api_key or access_token."}


def test_prepare_creds_rejects_foundry_with_neither_auth_method():
    raw = {"resource": "my-resource", "region": "eastus"}
    prepared = gateway.prepare_creds({"foundry": raw})
    assert prepared["foundry"] == {"error": "Foundry credentials need an api_key or access_token."}


@pytest.mark.parametrize("bad_value", ["fake-api-key\n", " fake-api-key", "fake-api\tkey"])
def test_prepare_creds_rejects_foundry_api_key_with_whitespace_or_control_chars(bad_value):
    raw = {"resource": "my-resource", "region": "eastus", "api_key": bad_value}
    prepared = gateway.prepare_creds({"foundry": raw})
    assert prepared["foundry"] == {"error": "Foundry credentials contain whitespace or control characters."}


def test_prepare_creds_is_idempotent_for_foundry():
    once = gateway.prepare_creds({"foundry": FOUNDRY_API_KEY_CREDS})
    twice = gateway.prepare_creds(once)
    assert twice == once


@patch("gateway.foundry.call_model", return_value=FAKE_RESULT)
def test_call_backend_foundry_passes_backend_creds(mock_call):
    gateway.call_backend("foundry", "openai/gpt-5", MESSAGES, {"foundry": FOUNDRY_API_KEY_CREDS})
    args, _ = mock_call.call_args
    assert args == ("openai/gpt-5", MESSAGES, FOUNDRY_API_KEY_CREDS)


def test_call_backend_incomplete_foundry_creds_raise_gateway_error():
    with pytest.raises(GatewayError):
        gateway.call_backend("foundry", "openai/gpt-5", MESSAGES, {"foundry": {"resource": "my-resource"}})
```

Append to `tests/test_config.py`:

```python


def test_judge_models_cover_foundry():
    assert config.JUDGE_MODELS["foundry"] == "gpt-4o-mini"
```

(Update the existing `test_judge_models_cover_every_backend` to expect `{"openrouter", "bedrock", "vertex", "foundry"}` instead of `{"openrouter", "bedrock", "vertex"}`.)

Append to `tests/test_scrub.py`:

```python


def test_scrub_redacts_foundry_api_key_by_exact_value():
    creds = {"foundry": {"resource": "my-resource", "region": "eastus", "api_key": "fake-foundry-api-key-1234"}}
    out = scrub.scrub("request failed using fake-foundry-api-key-1234 today", creds)
    assert "fake-foundry-api-key-1234" not in out


def test_scrub_redacts_foundry_access_token_by_exact_value():
    token = "some-nonstandard-entra-token-value-1234567890"
    creds = {"foundry": {"resource": "my-resource", "region": "eastus", "access_token": token}}
    out = scrub.scrub(f"authorization failed for {token}", creds)
    assert token not in out


def test_scrub_redacts_jwt_shaped_bearer_tokens_without_creds():
    jwt = ("eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9."
           "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0."
           "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U")
    out = scrub.scrub(f"Authorization: Bearer {jwt}")
    assert jwt not in out
    assert "[REDACTED]" in out
```

Append to `tests/test_analysis.py`:

```python


@patch("analysis.judge.explain_recommendations", return_value="")
@patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""})
def test_explainer_allowed_terms_include_foundry_label(mock_verdict, mock_explain):
    analysis.build_run_result(RESULTS, TARGETS, {"openrouter": "k"}, "openrouter")
    allowed = mock_explain.call_args[1]["allowed_terms"]
    assert "Microsoft Foundry" in allowed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_gateway.py tests/test_config.py tests/test_scrub.py tests/test_analysis.py -q`
Expected: FAIL — `KeyError: 'foundry'` / `AssertionError` (BACKENDS doesn't include foundry yet, `_prepare_foundry` doesn't exist, etc.).

- [ ] **Step 3: Implement**

`gateway.py`: add `import foundry` alongside the existing backend imports. Change:

```python
BACKENDS = ("openrouter", "bedrock", "vertex")
BACKEND_LABELS = {"openrouter": "OpenRouter", "bedrock": "Bedrock", "vertex": "Vertex AI"}
```

to:

```python
BACKENDS = ("openrouter", "bedrock", "vertex", "foundry")
BACKEND_LABELS = {"openrouter": "OpenRouter", "bedrock": "Bedrock", "vertex": "Vertex AI", "foundry": "Microsoft Foundry"}
```

After `_VERTEX_PROJECT_RE`, add:

```python
_FOUNDRY_RESOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
```

After `_prepare_vertex`, add:

```python
def _prepare_foundry(raw):
    if not isinstance(raw, dict):
        raise GatewayError("Foundry credentials must be an object.")
    resource = raw.get("resource")
    if not _nonempty_str(resource) or not _FOUNDRY_RESOURCE_RE.match(resource):
        raise GatewayError("Foundry resource name is missing or invalid.")
    region = raw.get("region")
    if not _nonempty_str(region) or region not in _known_region_ids("foundry"):
        raise GatewayError("Foundry region is missing or invalid.")
    _check_clean_fields(
        raw, ("api_key", "access_token"), "Foundry credentials contain whitespace or control characters.",
    )
    has_key = _nonempty_str(raw.get("api_key"))
    has_token = _nonempty_str(raw.get("access_token"))
    if has_key and has_token:
        raise GatewayError("Foundry credentials need exactly one of api_key or access_token.")
    if has_key:
        return {"resource": resource, "region": region, "api_key": raw["api_key"]}
    if has_token:
        return {"resource": resource, "region": region, "access_token": raw["access_token"]}
    raise GatewayError("Foundry credentials need an api_key or access_token.")
```

In `prepare_creds`, change:

```python
    for backend, prepare in (("bedrock", _prepare_bedrock), ("vertex", _prepare_vertex)):
```

to:

```python
    for backend, prepare in (("bedrock", _prepare_bedrock), ("vertex", _prepare_vertex), ("foundry", _prepare_foundry)):
```

In `call_backend`, change:

```python
    if backend == "bedrock":
        return bedrock.call_model(native_model_id, messages, backend_creds, timeout=timeout)
    return vertex.call_model(native_model_id, messages, backend_creds, timeout=timeout)
```

to:

```python
    if backend == "bedrock":
        return bedrock.call_model(native_model_id, messages, backend_creds, timeout=timeout)
    if backend == "vertex":
        return vertex.call_model(native_model_id, messages, backend_creds, timeout=timeout)
    return foundry.call_model(native_model_id, messages, backend_creds, timeout=timeout)
```

`config.py`: change

```python
JUDGE_MODELS = {
    "openrouter": os.environ.get("JUDGE_MODEL", "openai/gpt-4o-mini"),
    "bedrock": os.environ.get("BEDROCK_JUDGE_MODEL", "{geo}.anthropic.claude-haiku-4-5-20251001-v1:0"),
    "vertex": os.environ.get("VERTEX_JUDGE_MODEL", "google/gemini-2.5-flash"),
}
```

to:

```python
JUDGE_MODELS = {
    "openrouter": os.environ.get("JUDGE_MODEL", "openai/gpt-4o-mini"),
    "bedrock": os.environ.get("BEDROCK_JUDGE_MODEL", "{geo}.anthropic.claude-haiku-4-5-20251001-v1:0"),
    "vertex": os.environ.get("VERTEX_JUDGE_MODEL", "google/gemini-2.5-flash"),
    "foundry": os.environ.get("FOUNDRY_JUDGE_MODEL", "gpt-4o-mini"),
}
```

`.env.example`: after `# VERTEX_JUDGE_MODEL=google/gemini-2.5-flash` add:

```
# FOUNDRY_JUDGE_MODEL=gpt-4o-mini
```

`scrub.py`: change

```python
_SECRET_FIELDS = {
    "bedrock": ("api_key", "access_key_id", "secret_access_key", "session_token"),
    "vertex": ("access_token", "service_account_json"),
}
```

to:

```python
_SECRET_FIELDS = {
    "bedrock": ("api_key", "access_key_id", "secret_access_key", "session_token"),
    "vertex": ("access_token", "service_account_json"),
    "foundry": ("api_key", "access_token"),
}
```

and add a new entry to `_PATTERNS` (after the `ya29.` pattern, before the PEM pattern):

```python
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
```

`analysis.py`: change

```python
_BACKEND_LABEL_TERMS = ["OpenRouter", "Amazon Bedrock", "Bedrock", "Google Vertex AI", "Vertex AI"]
```

to:

```python
_BACKEND_LABEL_TERMS = ["OpenRouter", "Amazon Bedrock", "Bedrock", "Google Vertex AI", "Vertex AI",
                        "Microsoft Foundry", "Foundry"]
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/test_gateway.py tests/test_config.py tests/test_scrub.py tests/test_analysis.py -q` → PASS.
Run: `venv/bin/pytest tests/ -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add gateway.py config.py scrub.py analysis.py .env.example tests/test_gateway.py tests/test_config.py tests/test_scrub.py tests/test_analysis.py
git commit -m "feat: wire Microsoft Foundry into gateway, config, scrub, and analysis" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- gateway.py config.py scrub.py analysis.py .env.example tests/test_gateway.py tests/test_config.py tests/test_scrub.py tests/test_analysis.py
```

---

### Task 4: Foundry catalog routes (prices/regions) in `data/providers.json`

**Files:**
- Modify: `data/providers.json`
- Test: `tests/test_catalog.py`, `tests/test_gateway.py`

**Interfaces:**
- Consumes: `gateway.call_backend`/`call_target` (Task 3), `catalog.load_regions()["foundry"]` (Task 1).
- Produces: `"foundry"` routes on `openai/gpt-5`, `openai/gpt-5-mini`, `openai/gpt-4o`, `openai/gpt-4o-mini`, `meta-llama/llama-4-maverick`, `meta-llama/llama-4-scout`, `meta-llama/llama-3.3-70b-instruct`. `catalog.route_for(cat, "openai/gpt-5", "foundry")["id"] == "gpt-5"`. `gateway.call_target("openai/gpt-5@foundry", ...)` resolves and prices correctly.

Curated (best-known, 2026-09-30) Foundry model ids, prices (USD per 1M tokens), and regions:

| Catalog id | Foundry model id | input/output per M | Regions |
|---|---|---|---|
| `openai/gpt-5` | `gpt-5` | 1.25 / 10.0 | eastus, eastus2, westus, westus3, northcentralus, southcentralus, swedencentral, francecentral, uksouth |
| `openai/gpt-5-mini` | `gpt-5-mini` | 0.25 / 2.0 | (same as gpt-5) |
| `openai/gpt-4o` | `gpt-4o` | 2.5 / 10.0 | eastus, eastus2, westus, westus3, northcentralus, southcentralus, canadaeast, swedencentral, francecentral, uksouth, japaneast, australiaeast |
| `openai/gpt-4o-mini` | `gpt-4o-mini` | 0.15 / 0.6 | (same as gpt-4o) |
| `meta-llama/llama-4-maverick` | `Llama-4-Maverick-17B-128E-Instruct-FP8` | 0.22 / 0.88 | eastus2, westus3, swedencentral |
| `meta-llama/llama-4-scout` | `Llama-4-Scout-17B-16E-Instruct` | 0.15 / 0.6 | eastus2, westus3, swedencentral |
| `meta-llama/llama-3.3-70b-instruct` | `Llama-3.3-70B-Instruct` | 0.71 / 0.71 | eastus2, westus3, swedencentral, southcentralus |

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catalog.py`:

```python


FOUNDRY_ROUTED_MODELS = {
    "openai/gpt-5", "openai/gpt-5-mini", "openai/gpt-4o", "openai/gpt-4o-mini",
    "meta-llama/llama-4-maverick", "meta-llama/llama-4-scout", "meta-llama/llama-3.3-70b-instruct",
}


def test_every_expected_model_has_a_foundry_route():
    cat = catalog.load_catalog()
    routed = {m["id"] for p in cat.values() for m in p["models"] if "foundry" in (m.get("routes") or {})}
    assert routed == FOUNDRY_ROUTED_MODELS


def test_route_for_returns_foundry_route():
    cat = catalog.load_catalog()
    route = catalog.route_for(cat, "openai/gpt-5", "foundry")
    assert route["id"] == "gpt-5"


def test_region_availability_for_foundry_route():
    cat = catalog.load_catalog()
    assert catalog.region_availability(cat, "openai/gpt-5", "foundry", "eastus")["listed"] is True
    assert catalog.region_availability(cat, "openai/gpt-5", "foundry", "japaneast")["listed"] is False
```

In `tests/test_catalog.py`, change `assert backend in ("bedrock", "vertex")` (inside `test_every_route_is_well_formed`) to `assert backend in ("bedrock", "vertex", "foundry")`.

Append to `tests/test_gateway.py`:

```python


@patch("gateway.foundry.call_model", return_value=dict(FAKE_RESULT))
def test_call_target_foundry_resolves_route_and_prices_it(mock_call):
    result = gateway.call_target(
        "openai/gpt-5@foundry", MESSAGES,
        {"foundry": {"resource": "my-resource", "region": "eastus", "api_key": "fake-api-key-12345678"}},
    )
    assert mock_call.call_args[0][0] == "gpt-5"
    # 10 input tokens * $1.25/M + 20 output tokens * $10/M
    assert result["cost_usd"] == pytest.approx(0.0002125)


def test_call_target_foundry_model_without_route_raises():
    with pytest.raises(GatewayError, match="anthropic/claude-opus-4.5 is not available on Microsoft Foundry."):
        gateway.call_target(
            "anthropic/claude-opus-4.5@foundry", MESSAGES,
            {"foundry": {"resource": "my-resource", "region": "eastus", "api_key": "fake-api-key-12345678"}},
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_catalog.py tests/test_gateway.py -q`
Expected: FAIL — `test_every_expected_model_has_a_foundry_route` gets an empty set; `route_for(..., "foundry")` returns `None`.

- [ ] **Step 3: Replace `data/providers.json`** with the full content below (adds Foundry routes on top of Task 1's version; the `openai` and `google` sections' non-Foundry content is unchanged from Task 1):

```json
{
  "openai": {
    "blurb": "OpenAI builds the GPT model family and popularized the modern chat-assistant interface; broad general-purpose strength and the widest third-party tooling support.",
    "color": "#10A37F",
    "frontier": "~openai/gpt-latest",
    "models": [
      {"id": "~openai/gpt-latest", "name": "GPT (Latest)", "family": "gpt-5", "tier": "flagship", "reasoning": true},
      {"id": "openai/gpt-5", "name": "GPT-5", "family": "gpt-5", "tier": "flagship", "reasoning": true, "routes": {"foundry": {"id": "gpt-5", "price": {"input_per_m": 1.25, "output_per_m": 10.0}, "regions": ["eastus", "eastus2", "westus", "westus3", "northcentralus", "southcentralus", "swedencentral", "francecentral", "uksouth"]}}},
      {"id": "openai/gpt-5-mini", "name": "GPT-5 Mini", "family": "gpt-5", "tier": "fast", "reasoning": true, "routes": {"foundry": {"id": "gpt-5-mini", "price": {"input_per_m": 0.25, "output_per_m": 2.0}, "regions": ["eastus", "eastus2", "westus", "westus3", "northcentralus", "southcentralus", "swedencentral", "francecentral", "uksouth"]}}},
      {"id": "openai/gpt-4o", "name": "GPT-4o", "family": "gpt-4o", "tier": "balanced", "routes": {"foundry": {"id": "gpt-4o", "price": {"input_per_m": 2.5, "output_per_m": 10.0}, "regions": ["eastus", "eastus2", "westus", "westus3", "northcentralus", "southcentralus", "canadaeast", "swedencentral", "francecentral", "uksouth", "japaneast", "australiaeast"]}}},
      {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "family": "gpt-4o", "tier": "fast", "routes": {"foundry": {"id": "gpt-4o-mini", "price": {"input_per_m": 0.15, "output_per_m": 0.6}, "regions": ["eastus", "eastus2", "westus", "westus3", "northcentralus", "southcentralus", "canadaeast", "swedencentral", "francecentral", "uksouth", "japaneast", "australiaeast"]}}}
    ]
  },
  "anthropic": {
    "blurb": "Anthropic builds the Claude model family with a focus on reliability and steerability; strong at careful reasoning, following detailed instructions, and long-context work.",
    "color": "#D97757",
    "frontier": "~anthropic/claude-opus-latest",
    "models": [
      {"id": "~anthropic/claude-opus-latest", "name": "Claude Opus (Latest)", "family": "claude-opus", "tier": "flagship"},
      {"id": "anthropic/claude-opus-4.5", "name": "Claude Opus 4.5", "family": "claude-opus", "tier": "flagship", "routes": {"bedrock": {"id": "{geo}.anthropic.claude-opus-4-5-20251101-v1:0", "price": {"input_per_m": 5.0, "output_per_m": 25.0}, "regions": ["us-east-1", "us-east-2", "us-west-2", "eu-central-1", "eu-west-1", "ap-northeast-1", "ap-southeast-2"]}}},
      {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5", "family": "claude-sonnet", "tier": "balanced", "routes": {"bedrock": {"id": "{geo}.anthropic.claude-sonnet-4-5-20250929-v1:0", "price": {"input_per_m": 3.0, "output_per_m": 15.0}, "regions": ["us-east-1", "us-east-2", "us-west-2", "eu-central-1", "eu-west-1", "eu-west-3", "ap-northeast-1", "ap-south-1", "ap-southeast-2"]}}},
      {"id": "anthropic/claude-haiku-4.5", "name": "Claude Haiku 4.5", "family": "claude-haiku", "tier": "fast", "routes": {"bedrock": {"id": "{geo}.anthropic.claude-haiku-4-5-20251001-v1:0", "price": {"input_per_m": 1.0, "output_per_m": 5.0}, "regions": ["us-east-1", "us-east-2", "us-west-2", "eu-central-1", "eu-west-1", "ap-northeast-1", "ap-southeast-2"]}}}
    ]
  },
  "google": {
    "blurb": "Google DeepMind builds the Gemini model family with native multimodal training and very large context windows, integrated tightly with Google's own products.",
    "color": "#4285F4",
    "frontier": "~google/gemini-pro-latest",
    "models": [
      {"id": "~google/gemini-pro-latest", "name": "Gemini Pro (Latest)", "family": "gemini-pro", "tier": "flagship", "reasoning": true},
      {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro", "family": "gemini-pro", "tier": "flagship", "reasoning": true, "routes": {"vertex": {"id": "google/gemini-2.5-pro", "price": {"input_per_m": 1.25, "output_per_m": 10.0}, "regions": ["global", "us-central1", "us-east1", "us-east4", "us-west1", "europe-west1", "europe-west4", "asia-northeast1", "asia-southeast1"]}}},
      {"id": "google/gemini-3.7-flash", "name": "Gemini 3.7 Flash", "family": "gemini-flash", "tier": "balanced", "reasoning": true},
      {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "family": "gemini-flash", "tier": "fast", "reasoning": true, "routes": {"vertex": {"id": "google/gemini-2.5-flash", "price": {"input_per_m": 0.3, "output_per_m": 2.5}, "regions": ["global", "us-central1", "us-east1", "us-east4", "us-west1", "europe-west1", "europe-west4", "asia-northeast1", "asia-southeast1"]}}}
    ]
  },
  "meta-llama": {
    "blurb": "Meta builds the open-weight Llama model family, widely used for self-hosting and fine-tuning where control over weights and cost matters more than using a closed API.",
    "color": "#0668E1",
    "frontier": "meta-llama/llama-4-maverick",
    "models": [
      {"id": "meta-llama/llama-4-maverick", "name": "Llama 4 Maverick", "family": "llama-4", "tier": "flagship", "routes": {"bedrock": {"id": "{geo}.meta.llama4-maverick-17b-instruct-v1:0", "price": {"input_per_m": 0.24, "output_per_m": 0.97}, "regions": ["us-east-1", "us-east-2", "us-west-2"]}, "vertex": {"id": "meta/llama-4-maverick-17b-128e-instruct-maas", "price": {"input_per_m": 0.35, "output_per_m": 1.15}, "regions": ["us-east5"]}, "foundry": {"id": "Llama-4-Maverick-17B-128E-Instruct-FP8", "price": {"input_per_m": 0.22, "output_per_m": 0.88}, "regions": ["eastus2", "westus3", "swedencentral"]}}},
      {"id": "meta-llama/llama-4-scout", "name": "Llama 4 Scout", "family": "llama-4", "tier": "fast", "routes": {"bedrock": {"id": "{geo}.meta.llama4-scout-17b-instruct-v1:0", "price": {"input_per_m": 0.17, "output_per_m": 0.66}, "regions": ["us-east-1", "us-east-2", "us-west-2"]}, "vertex": {"id": "meta/llama-4-scout-17b-16e-instruct-maas", "price": {"input_per_m": 0.25, "output_per_m": 0.7}, "regions": ["us-east5"]}, "foundry": {"id": "Llama-4-Scout-17B-16E-Instruct", "price": {"input_per_m": 0.15, "output_per_m": 0.6}, "regions": ["eastus2", "westus3", "swedencentral"]}}},
      {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "family": "llama-3", "tier": "balanced", "routes": {"bedrock": {"id": "{geo}.meta.llama3-3-70b-instruct-v1:0", "price": {"input_per_m": 0.72, "output_per_m": 0.72}, "regions": ["us-east-1", "us-east-2", "us-west-2", "eu-central-1", "eu-west-1", "ap-northeast-1"]}, "vertex": {"id": "meta/llama-3.3-70b-instruct-maas", "price": {"input_per_m": 0.72, "output_per_m": 0.72}, "regions": ["us-east5"]}, "foundry": {"id": "Llama-3.3-70B-Instruct", "price": {"input_per_m": 0.71, "output_per_m": 0.71}, "regions": ["eastus2", "westus3", "swedencentral", "southcentralus"]}}}
    ]
  }
}
```

Validate: `venv/bin/python -c "import json; json.load(open('data/providers.json'))"`.

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/test_catalog.py tests/test_gateway.py -q` → PASS.
Run: `venv/bin/pytest tests/ -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add data/providers.json tests/test_catalog.py tests/test_gateway.py
git commit -m "feat: add curated Microsoft Foundry catalog routes (prices and regions)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- data/providers.json tests/test_catalog.py tests/test_gateway.py
```

---

### Task 5: `availability.py`, `/api/availability`, MCP `list_availability`, `/api/catalog` additions

**Files:**
- Create: `availability.py`
- Modify: `app.py`, `mcp_server.py`
- Test: `tests/test_availability.py` (new), `tests/test_app.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `catalog.load_catalog`, `catalog.load_regions`, `catalog.fetch_openrouter_models` (all Task 1/existing).
- Produces:
  - `availability.snapshot(now=None) -> dict` with keys `generated_at`, `openrouter` (`{"refreshed_at", "stale", "models": {model_id: {"listed": bool}}}`), `backends` (`{"bedrock"|"vertex"|"foundry": {"label", "verified", "source", "regions", "models": {model_id: [region_id, ...]}}}`). 6-hour TTL (`availability._TTL_SECONDS`), guarded by `availability._lock`. A failed/empty refresh keeps the previous snapshot and marks it `stale: true`.
  - `gateway.PROVIDER_LINKS: dict[str, {"status": str, "report": str}]` for all 4 backends.
  - `GET /api/availability` → `jsonify(availability.snapshot())`.
  - `/api/catalog` gains `"regions": catalog.load_regions()` and `"provider_links": gateway.PROVIDER_LINKS`.
  - MCP `list_availability() -> dict` returns `availability.snapshot()`.
  - `run_comparison`/`evaluate_prompt` docstrings mention Foundry and the `foundry` creds shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_availability.py`:

```python
from unittest.mock import patch

import availability
import catalog


def setup_function():
    availability._cache["snapshot"] = None
    availability._cache["fetched_at"] = 0.0
    catalog._cache["data"] = None
    catalog._cache["fetched_at"] = 0.0


@patch("availability.catalog.fetch_openrouter_models")
def test_first_call_fetches_openrouter_models(mock_fetch):
    mock_fetch.return_value = [{"id": "openai/gpt-5", "name": "GPT-5"}]
    snap = availability.snapshot(now=1000.0)
    mock_fetch.assert_called_once()
    assert snap["openrouter"]["stale"] is False
    assert snap["openrouter"]["models"]["openai/gpt-5"]["listed"] is True
    assert snap["openrouter"]["models"]["openai/gpt-4o"]["listed"] is False


@patch("availability.catalog.fetch_openrouter_models")
def test_second_call_within_six_hours_does_not_refetch(mock_fetch):
    mock_fetch.return_value = [{"id": "openai/gpt-5"}]
    availability.snapshot(now=1000.0)
    availability.snapshot(now=1000.0 + 3600)
    mock_fetch.assert_called_once()


@patch("availability.catalog.fetch_openrouter_models")
def test_call_after_six_hours_refetches(mock_fetch):
    mock_fetch.return_value = [{"id": "openai/gpt-5"}]
    availability.snapshot(now=1000.0)
    availability.snapshot(now=1000.0 + availability._TTL_SECONDS + 1)
    assert mock_fetch.call_count == 2


@patch("availability.catalog.fetch_openrouter_models")
def test_failed_refresh_keeps_old_data_and_marks_stale(mock_fetch):
    mock_fetch.return_value = [{"id": "openai/gpt-5"}]
    first = availability.snapshot(now=1000.0)
    mock_fetch.return_value = []  # fetch_openrouter_models fails soft to [] on any request error
    second = availability.snapshot(now=1000.0 + availability._TTL_SECONDS + 1)
    assert second["openrouter"]["stale"] is True
    assert second["openrouter"]["models"] == first["openrouter"]["models"]


@patch("availability.catalog.fetch_openrouter_models", return_value=[])
def test_no_prior_data_and_failed_fetch_marks_everything_unlisted_and_stale(mock_fetch):
    snap = availability.snapshot(now=1000.0)
    assert snap["openrouter"]["stale"] is True
    assert all(not v["listed"] for v in snap["openrouter"]["models"].values())


def test_backend_sections_have_curated_metadata_and_model_regions():
    snap = availability.snapshot(now=1000.0)
    assert set(snap["backends"]) == {"bedrock", "vertex", "foundry"}
    bedrock_section = snap["backends"]["bedrock"]
    assert bedrock_section["label"] == "Amazon Bedrock"
    assert "us-east-1" in bedrock_section["models"]["anthropic/claude-sonnet-4.5"]
    vertex_section = snap["backends"]["vertex"]
    assert "google/gemini-2.5-pro" in vertex_section["models"]
    foundry_section = snap["backends"]["foundry"]
    assert "openai/gpt-5" in foundry_section["models"]


def test_snapshot_includes_generated_at():
    snap = availability.snapshot(now=1234.5)
    assert snap["generated_at"] == 1234.5
```

Append to `tests/test_app.py`:

```python


@patch("app.availability.snapshot")
def test_api_availability_returns_snapshot(mock_snapshot):
    mock_snapshot.return_value = {"generated_at": 123, "openrouter": {}, "backends": {}}
    resp = _client().get("/api/availability")
    assert resp.get_json() == {"generated_at": 123, "openrouter": {}, "backends": {}}


def test_api_catalog_exposes_regions_and_provider_links():
    body = _client().get("/api/catalog").get_json()
    assert set(body["regions"]) == {"bedrock", "vertex", "foundry"}
    assert set(body["provider_links"]) == {"openrouter", "bedrock", "vertex", "foundry"}
    assert body["provider_links"]["foundry"]["status"] == "https://azure.status.microsoft/en-us/status"


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_accepts_foundry_target_and_judge_backend(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    creds = {"foundry": {"resource": "my-resource", "region": "eastus", "api_key": "fake-api-key-12345678"}}

    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5@foundry"],
        "creds": creds, "judge_backend": "foundry",
    })

    assert resp.status_code == 200
    _, run_kwargs = mock_run.call_args
    assert run_kwargs["creds"] == creds
    assert run_kwargs["judge_backend"] == "foundry"


def test_api_run_error_response_scrubs_foundry_api_key(caplog):
    secret = "fake-foundry-secret-key-1234567890"
    with patch("app.runner.run", side_effect=Exception(f"request failed using {secret}")):
        resp = _client().post("/api/run", json={
            "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5@foundry"],
            "creds": {"foundry": {"resource": "my-resource", "region": "eastus", "api_key": secret}},
            "judge_backend": "foundry",
        })
    assert resp.status_code == 503
    body = resp.get_json()
    assert secret not in body["error"]
    assert secret not in caplog.text
```

Append to `tests/test_mcp_server.py`:

```python


@patch("mcp_server.availability.snapshot")
def test_list_availability_returns_snapshot(mock_snapshot):
    mock_snapshot.return_value = {"generated_at": 1, "openrouter": {}, "backends": {}}
    assert mcp_server.list_availability() == {"generated_at": 1, "openrouter": {}, "backends": {}}


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_run_comparison_accepts_foundry_target_and_judge_backend(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    creds = {"foundry": {"resource": "my-resource", "region": "eastus", "api_key": "fake-api-key-12345678"}}

    result = mcp_server.run_comparison(
        test_cases=[{"prompt": "q1"}], models=["openai/gpt-5@foundry"], creds=creds, judge_backend="foundry",
    )

    assert "error" not in result
    _, run_kwargs = mock_run.call_args
    assert run_kwargs["creds"] == creds
    assert run_kwargs["judge_backend"] == "foundry"


def test_run_comparison_scrubs_foundry_api_key_on_error():
    secret = "fake-foundry-secret-key-1234567890"
    with patch("mcp_server.runner.run", side_effect=Exception(f"request failed using {secret}")):
        result = mcp_server.run_comparison(
            test_cases=[{"prompt": "q1"}], models=["openai/gpt-5@foundry"],
            creds={"foundry": {"resource": "my-resource", "region": "eastus", "api_key": secret}},
            judge_backend="foundry",
        )
    assert secret not in result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_availability.py tests/test_app.py tests/test_mcp_server.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'availability'`; `/api/availability` 404s; `/api/catalog` response lacks `regions`/`provider_links`.

- [ ] **Step 3: Implement `availability.py`**

```python
import threading
import time

import catalog

_TTL_SECONDS = 6 * 3600
_lock = threading.Lock()
_cache = {"snapshot": None, "fetched_at": 0.0}


def _openrouter_section(now):
    curated_ids = [m["id"] for provider in catalog.load_catalog().values() for m in provider["models"]]

    with _lock:
        cached = _cache["snapshot"]
        if cached is not None and (now - _cache["fetched_at"]) < _TTL_SECONDS:
            return cached

        models = catalog.fetch_openrouter_models()
        if models:
            live_ids = {m["id"] for m in models}
            section = {
                "refreshed_at": now,
                "stale": False,
                "models": {model_id: {"listed": model_id in live_ids} for model_id in curated_ids},
            }
            _cache["snapshot"] = section
            _cache["fetched_at"] = now
            return section

        if cached is not None:
            return {**cached, "stale": True}
        return {"refreshed_at": now, "stale": True,
               "models": {model_id: {"listed": False} for model_id in curated_ids}}


def _backend_section(backend):
    regions = catalog.load_regions()[backend]
    models = {}
    for provider in catalog.load_catalog().values():
        for model in provider["models"]:
            route = (model.get("routes") or {}).get(backend)
            if route:
                models[model["id"]] = route.get("regions", [])
    return {
        "label": regions["label"],
        "verified": regions["verified"],
        "source": regions["source"],
        "regions": regions["regions"],
        "models": models,
    }


def snapshot(now=None):
    now = time.time() if now is None else now
    return {
        "generated_at": now,
        "openrouter": _openrouter_section(now),
        "backends": {backend: _backend_section(backend) for backend in ("bedrock", "vertex", "foundry")},
    }
```

- [ ] **Step 4: Wire `app.py`**

Add `import availability` alongside the other imports (alphabetical, after `analysis`). Add a new route after `api_openrouter_models`:

```python
@app.route("/api/availability")
def api_availability():
    return jsonify(availability.snapshot())
```

Change `api_catalog`:

```python
@app.route("/api/catalog")
def api_catalog():
    cat = catalog.load_catalog()
    return jsonify({
        "providers": cat,
        "frontier": catalog.frontier_models(cat),
        "max_models": config.MAX_MODELS,
        "priority_weights": grading.PRIORITY_WEIGHTS,
        "priority_labels": grading.PRIORITY_LABELS,
        "regions": catalog.load_regions(),
        "provider_links": gateway.PROVIDER_LINKS,
    })
```

- [ ] **Step 5: Add `gateway.PROVIDER_LINKS`**

In `gateway.py`, after `BACKEND_LABELS`, add:

```python
PROVIDER_LINKS = {
    "openrouter": {"status": "https://status.openrouter.ai",
                  "report": "https://openrouter.ai/docs/guides/overview/report-feedback"},
    "bedrock": {"status": "https://health.aws.amazon.com/health/status",
               "report": "https://console.aws.amazon.com/support/home"},
    "vertex": {"status": "https://status.cloud.google.com",
              "report": "https://cloud.google.com/support-hub"},
    "foundry": {"status": "https://azure.status.microsoft/en-us/status",
               "report": "https://azure.microsoft.com/en-us/support/create-ticket"},
}
```

- [ ] **Step 6: Wire `mcp_server.py`**

Add `import availability` alongside the other imports. Add a new tool after `suggest_models`:

```python
@mcp.tool()
def list_availability() -> dict:
    """Return the current model-availability snapshot: live OpenRouter listing status
    (refreshed at most every 6 hours) plus curated Bedrock/Vertex/Foundry region coverage.
    """
    return availability.snapshot()
```

In `run_comparison`'s docstring, change:

```
    Models are "<catalog id>" (OpenRouter) or "<catalog id>@bedrock" / "<catalog id>@vertex";
    pass matching creds ({"openrouter"?, "bedrock"?, "vertex"?}) or a bare OpenRouter api_key.
```

to:

```
    Models are "<catalog id>" (OpenRouter) or "<catalog id>@bedrock" / "<catalog id>@vertex" /
    "<catalog id>@foundry"; pass matching creds ({"openrouter"?, "bedrock"?, "vertex"?, "foundry"?})
    or a bare OpenRouter api_key.
```

In `evaluate_prompt`'s docstring, change:

```
    An explicit, separately-triggered LLM call (uses your credentials) — not run
    automatically as part of run_comparison. Rate-limited independently from
    run_comparison's 3-per-8h budget. Pass `creds` as {"openrouter"?: str,
    "bedrock"?: {...}, "vertex"?: {...}} to use Amazon Bedrock or Google Vertex AI;
    a bare `api_key` is treated as an OpenRouter key. `judge_backend` picks which
    backend runs the evaluation.
```

to:

```
    An explicit, separately-triggered LLM call (uses your credentials) — not run
    automatically as part of run_comparison. Rate-limited independently from
    run_comparison's 3-per-8h budget. Pass `creds` as {"openrouter"?: str,
    "bedrock"?: {...}, "vertex"?: {...}, "foundry"?: {...}} to use Amazon Bedrock,
    Google Vertex AI, or Microsoft Foundry; a bare `api_key` is treated as an
    OpenRouter key. `judge_backend` picks which backend runs the evaluation.
```

- [ ] **Step 7: Run tests**

Run: `venv/bin/pytest tests/test_availability.py tests/test_app.py tests/test_mcp_server.py -q` → PASS.
Run: `venv/bin/pytest tests/ -q` → PASS.

- [ ] **Step 8: Commit**

```bash
git add availability.py app.py mcp_server.py gateway.py tests/test_availability.py tests/test_app.py tests/test_mcp_server.py
git commit -m "feat: availability snapshot (/api/availability, MCP list_availability, catalog regions/provider_links)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- availability.py app.py mcp_server.py gateway.py tests/test_availability.py tests/test_app.py tests/test_mcp_server.py
```

---

### Task 6: Frontend — Foundry tab, region selects, ⚠ warnings, status menu, footer links, error-popup links

**Files:**
- Modify: `templates/index.html`, `static/app.js`, `static/style.css`
- Test: none (no pytest test file changes; verified via `node --check` + a template-render smoke script, run in Step 3 below)

**Interfaces:**
- Consumes: `/api/catalog`'s new `regions`/`provider_links` fields (Task 5), `model.routes[backend].regions` from `data/providers.json` (Tasks 1/4).
- Produces: no new Python interfaces. New DOM ids: `tab-foundry`, `panel-foundry`, `foundry-resource`, `foundry-region`, `foundry-api-key`, `foundry-access-token`, `region-warning-line`, `error-dialog-status-link`, `error-dialog-provider-report-link`. New JS globals: `PROVIDER_LINKS`, and functions `populateRegionSelect`, `selectedRegion`, `regionWarnings`, `warningText`, `syncRegionWarnings`.

- [ ] **Step 1: Edit `templates/index.html`**

Replace the `<header>`/`<nav id="mobile-menu">`/`<div id="menu-overlay">` block:

```html
  <header>
    <h1>EvalForge <span class="accent-brand">Lite</span></h1>
    <p class="tagline">Compare text LLMs via OpenRouter, Amazon Bedrock, or Google Vertex AI with your own credentials.</p>
    <button id="theme-toggle" class="theme-toggle" aria-label="Toggle dark mode">&#127769;</button>
    <button id="menu-toggle" class="menu-toggle" aria-label="Open menu" aria-expanded="false" aria-controls="mobile-menu">&#9776;</button>
  </header>

  <nav id="mobile-menu" class="mobile-menu" aria-label="Section navigation">
    <a href="#creds-section">Credentials</a>
    <a href="#catalog-section">Models</a>
    <a href="#policy-section">Policy</a>
    <a href="#testcase-section">Test Cases</a>
    <a href="#run-section">Run</a>
    <a href="#results-section">Results</a>
  </nav>
  <div id="menu-overlay" class="menu-overlay" hidden></div>
```

with:

```html
  <header>
    <h1>EvalForge <span class="accent-brand">Lite</span></h1>
    <p class="tagline">Compare text LLMs via OpenRouter, Amazon Bedrock, Google Vertex AI, or Microsoft Foundry with your own credentials.</p>
    <button id="theme-toggle" class="theme-toggle" aria-label="Toggle dark mode">&#127769;</button>
    <button id="menu-toggle" class="menu-toggle" aria-label="Open menu" aria-expanded="false" aria-controls="mobile-menu">&#9776;</button>
  </header>

  <nav id="mobile-menu" class="mobile-menu" aria-label="Section navigation">
    <a href="#creds-section">Credentials</a>
    <a href="#catalog-section">Models</a>
    <a href="#policy-section">Policy</a>
    <a href="#testcase-section">Test Cases</a>
    <a href="#run-section">Run</a>
    <a href="#results-section">Results</a>
    <a href="/availability">Where models run</a>
  </nav>
  <div id="menu-overlay" class="menu-overlay" hidden></div>

  <nav class="top-links" aria-label="Site links">
    <a href="/availability">Where models run</a>
    <details class="status-menu">
      <summary>Provider status</summary>
      <div class="status-menu-panel">
        <a href="https://status.openrouter.ai" target="_blank" rel="noopener">OpenRouter</a>
        <a href="https://health.aws.amazon.com/health/status" target="_blank" rel="noopener">AWS</a>
        <a href="https://status.cloud.google.com" target="_blank" rel="noopener">Google Cloud</a>
        <a href="https://azure.status.microsoft/en-us/status" target="_blank" rel="noopener">Azure</a>
      </div>
    </details>
  </nav>
```

Replace the whole `#creds-section` (from `<section id="creds-section" class="card">` through its closing `</section>`) with:

```html
  <section id="creds-section" class="card">
    <div class="tab-row" role="tablist" aria-label="Credentials backend">
      <button type="button" class="tab active" role="tab" id="tab-openrouter" aria-controls="panel-openrouter" aria-selected="true" data-backend="openrouter">OpenRouter</button>
      <button type="button" class="tab" role="tab" id="tab-bedrock" aria-controls="panel-bedrock" aria-selected="false" tabindex="-1" data-backend="bedrock">Amazon Bedrock</button>
      <button type="button" class="tab" role="tab" id="tab-vertex" aria-controls="panel-vertex" aria-selected="false" tabindex="-1" data-backend="vertex">Google Vertex AI</button>
      <button type="button" class="tab" role="tab" id="tab-foundry" aria-controls="panel-foundry" aria-selected="false" tabindex="-1" data-backend="foundry">Microsoft Foundry</button>
    </div>

    <div class="cred-panel" role="tabpanel" id="panel-openrouter" aria-labelledby="tab-openrouter" data-backend="openrouter">
      <label for="api-key">OpenRouter API key</label>
      <input type="password" id="api-key" placeholder="sk-or-v1-..." autocomplete="off">
      <p class="provider-blurb">
        Don't have a key? <a href="https://openrouter.ai/workspaces/default/keys" target="_blank" rel="noopener">Get one at OpenRouter &rarr;</a>
      </p>
    </div>

    <div class="cred-panel" role="tabpanel" id="panel-bedrock" aria-labelledby="tab-bedrock" data-backend="bedrock" hidden>
      <label for="bedrock-region">AWS region</label>
      <select id="bedrock-region"><option value="">Select a region</option></select>
      <div class="auth-toggle">
        <label><input type="radio" name="bedrock-auth" value="api_key" checked> Bedrock API key</label>
        <label><input type="radio" name="bedrock-auth" value="access_keys"> Access keys</label>
      </div>
      <div class="auth-fields" data-auth-group="bedrock" data-auth="api_key">
        <input type="password" id="bedrock-api-key" placeholder="ABSK... or bedrock-api-key-..." autocomplete="off" aria-label="Bedrock API key">
      </div>
      <div class="auth-fields" data-auth-group="bedrock" data-auth="access_keys" hidden>
        <input type="password" id="bedrock-access-key-id" placeholder="Access key ID" autocomplete="off" aria-label="AWS access key ID">
        <input type="password" id="bedrock-secret-access-key" placeholder="Secret access key" autocomplete="off" aria-label="AWS secret access key">
        <input type="password" id="bedrock-session-token" placeholder="Session token (optional)" autocomplete="off" aria-label="AWS session token (optional)">
      </div>
    </div>

    <div class="cred-panel" role="tabpanel" id="panel-vertex" aria-labelledby="tab-vertex" data-backend="vertex" hidden>
      <label for="vertex-project">GCP project ID</label>
      <input type="text" id="vertex-project" placeholder="my-project-123">
      <label for="vertex-region">Region</label>
      <select id="vertex-region"><option value="">Select a region</option></select>
      <div class="auth-toggle">
        <label><input type="radio" name="vertex-auth" value="access_token" checked> Access token</label>
        <label><input type="radio" name="vertex-auth" value="service_account"> Service-account JSON</label>
      </div>
      <div class="auth-fields" data-auth-group="vertex" data-auth="access_token">
        <input type="password" id="vertex-access-token" placeholder="ya29... (gcloud auth print-access-token)" autocomplete="off" aria-label="Vertex AI access token">
      </div>
      <div class="auth-fields" data-auth-group="vertex" data-auth="service_account" hidden>
        <input type="file" id="vertex-sa-file" accept=".json,application/json" aria-label="Vertex AI service-account JSON file">
        <span id="vertex-sa-status" class="status-text"></span>
      </div>
    </div>

    <div class="cred-panel" role="tabpanel" id="panel-foundry" aria-labelledby="tab-foundry" data-backend="foundry" hidden>
      <label for="foundry-resource">Azure AI Foundry resource name</label>
      <input type="text" id="foundry-resource" placeholder="my-foundry-resource">
      <label for="foundry-region">Region</label>
      <select id="foundry-region"><option value="">Select a region</option></select>
      <div class="auth-toggle">
        <label><input type="radio" name="foundry-auth" value="api_key" checked> API key</label>
        <label><input type="radio" name="foundry-auth" value="access_token"> Entra ID access token</label>
      </div>
      <div class="auth-fields" data-auth-group="foundry" data-auth="api_key">
        <input type="password" id="foundry-api-key" placeholder="Foundry API key" autocomplete="off" aria-label="Microsoft Foundry API key">
      </div>
      <div class="auth-fields" data-auth-group="foundry" data-auth="access_token" hidden>
        <input type="password" id="foundry-access-token" placeholder="Entra ID access token" autocomplete="off" aria-label="Microsoft Entra ID access token">
      </div>
      <p class="provider-blurb">
        Get an Entra ID access token with <code>az account get-access-token --resource https://cognitiveservices.azure.com</code>.
      </p>
    </div>

    <label for="judge-backend">Judge &amp; policy backend</label>
    <select id="judge-backend">
      <option value="openrouter">OpenRouter</option>
      <option value="bedrock">Amazon Bedrock</option>
      <option value="vertex">Google Vertex AI</option>
      <option value="foundry">Microsoft Foundry</option>
    </select>
  </section>
```

In `#run-section`, insert a new line right before `<button id="run-button">Run comparison</button>`:

```html
    <div id="region-warning-line" class="region-warning-line" hidden></div>
```

Replace the footer:

```html
  <footer class="page-footer">
    <a href="https://github.com/thejaredchapman/evalforge-lite/issues/new?template=bug_report.md" target="_blank" rel="noopener">Report an issue</a>
    <a href="https://github.com/thejaredchapman/evalforge-lite/blob/main/CONTRIBUTING.md" target="_blank" rel="noopener">Contribute</a>
    <a href="https://openrouter.ai/docs/guides/overview/report-feedback" target="_blank" rel="noopener">Report an OpenRouter problem</a>
  </footer>
```

with:

```html
  <footer class="page-footer">
    <a href="https://github.com/thejaredchapman/evalforge-lite/issues/new?template=bug_report.md" target="_blank" rel="noopener">Report an issue</a>
    <a href="https://github.com/thejaredchapman/evalforge-lite/blob/main/CONTRIBUTING.md" target="_blank" rel="noopener">Contribute</a>
    <a href="https://openrouter.ai/docs/guides/overview/report-feedback" target="_blank" rel="noopener">Report an OpenRouter problem</a>
    <a href="https://console.aws.amazon.com/support/home" target="_blank" rel="noopener">Report an AWS problem</a>
    <a href="https://cloud.google.com/support-hub" target="_blank" rel="noopener">Report a Google Cloud problem</a>
    <a href="https://azure.microsoft.com/en-us/support/create-ticket" target="_blank" rel="noopener">Report an Azure problem</a>
  </footer>
```

In the `<dialog id="error-dialog">`, replace:

```html
    <div class="error-dialog-actions">
      <button type="button" id="error-dialog-copy" class="secondary">Copy details</button>
      <a id="error-dialog-report" class="button-link secondary" target="_blank" rel="noopener">Report an issue on GitHub</a>
      <button type="button" id="error-dialog-close">Close</button>
    </div>
```

with:

```html
    <div class="error-dialog-actions">
      <button type="button" id="error-dialog-copy" class="secondary">Copy details</button>
      <a id="error-dialog-report" class="button-link secondary" target="_blank" rel="noopener">Report an issue on GitHub</a>
      <a id="error-dialog-status-link" class="button-link secondary" target="_blank" rel="noopener" hidden></a>
      <a id="error-dialog-provider-report-link" class="button-link secondary" target="_blank" rel="noopener" hidden></a>
      <button type="button" id="error-dialog-close">Close</button>
    </div>
```

- [ ] **Step 2: Edit `static/app.js`**

Change the `BACKEND_LABELS` constant:

```js
const BACKEND_LABELS = { openrouter: "OpenRouter", bedrock: "Amazon Bedrock", vertex: "Google Vertex AI" };
```

to:

```js
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
```

Change `showErrorDialog`:

```js
function showErrorDialog(title, summary, details) {
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

  if (!dialog.open) dialog.showModal();
}
```

to:

```js
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
```

Change `showCellErrors`:

```js
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
  showErrorDialog(
    failures.length === 1 ? "A model call failed" : `${failures.length} model calls failed`,
    "The run finished, but some models returned errors. The provider's full response is below.",
    details,
  );
}
```

to:

```js
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
```

In `renderResults`, change the per-cell details-button handler:

```js
        detailsButton.addEventListener("click", () => {
          showErrorDialog(`${modelId} failed`, `Prompt: ${row.test_case.prompt}`, cell.error);
        });
```

to:

```js
        detailsButton.addEventListener("click", () => {
          showErrorDialog(`${modelId} failed`, `Prompt: ${row.test_case.prompt}`, cell.error, targetBackend(modelId));
        });
```

In `buildCreds`, change:

```js
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
```

to:

```js
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
  if (foundryResource) {
    const region = fieldValue("foundry-region");
    if (checkedValue("foundry-auth") === "api_key") {
      const apiKey = fieldValue("foundry-api-key");
      if (apiKey) creds.foundry = { resource: foundryResource, region, api_key: apiKey };
    } else {
      const accessToken = fieldValue("foundry-access-token");
      if (accessToken) creds.foundry = { resource: foundryResource, region, access_token: accessToken };
    }
  }
  return creds;
}
```

In `setupCredsPanel`, change:

```js
  ["bedrock", "vertex"].forEach((group) => {
```

to:

```js
  ["bedrock", "vertex", "foundry"].forEach((group) => {
```

Immediately before the `function setupCredsPanel() {` definition, add:

```js
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

  document.querySelectorAll(".backend-chip[data-target]").forEach((chip) => {
    const target = chip.dataset.target;
    const warning = warningByTarget.get(target);
    let markEl = chip.querySelector(".region-warning-mark");
    if (warning) {
      if (!markEl) {
        markEl = document.createElement("span");
        markEl.className = "region-warning-mark";
        markEl.textContent = "⚠";
        chip.appendChild(markEl);
      }
      chip.title = warningText(warning);
    } else if (markEl) {
      markEl.remove();
      chip.title = `Also run via ${BACKEND_LABELS[targetBackend(target)]}`;
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

```

In `modelBadge`, change:

```js
    chip.textContent = backend === "bedrock" ? "Bedrock" : "Vertex";
```

to:

```js
    chip.textContent = backend === "bedrock" ? "Bedrock" : backend === "vertex" ? "Vertex" : "Foundry";
```

Change `toggleBackendTarget`:

```js
function toggleBackendTarget(target, chip) {
  if (state.selectedModels.has(target)) {
    state.selectedModels.delete(target);
  } else {
    if (atCap()) {
      document.getElementById("run-status").textContent = capMessage();
      return;
    }
    state.selectedModels.add(target);
  }
  syncSelectionVisuals();
  updateSelectionMeta();
}
```

to:

```js
function toggleBackendTarget(target, chip) {
  if (state.selectedModels.has(target)) {
    state.selectedModels.delete(target);
  } else {
    if (atCap()) {
      document.getElementById("run-status").textContent = capMessage();
      return;
    }
    state.selectedModels.add(target);
  }
  syncSelectionVisuals();
  updateSelectionMeta();
  syncRegionWarnings();
}
```

Change `toggleModel` (add `syncRegionWarnings();` to both branches):

```js
async function toggleModel(modelId, el) {
  if (state.selectedModels.has(modelId)) {
    state.selectedModels.delete(modelId);
    syncSelectionVisuals();
    updateSelectionMeta();
  } else {
    if (atCap()) {
      document.getElementById("run-status").textContent = capMessage();
      return;
    }
    state.selectedModels.add(modelId);
    syncSelectionVisuals();
    updateSelectionMeta();
    const resp = await fetch(`/api/suggest?model_id=${encodeURIComponent(modelId)}`);
    const data = await resp.json();
    if (data.suggestions.length) {
      const names = data.suggestions.map((m) => m.name).join(", ");
      document.getElementById("run-status").textContent = `Also consider: ${names}`;
    }
  }
}
```

to:

```js
async function toggleModel(modelId, el) {
  if (state.selectedModels.has(modelId)) {
    state.selectedModels.delete(modelId);
    syncSelectionVisuals();
    updateSelectionMeta();
    syncRegionWarnings();
  } else {
    if (atCap()) {
      document.getElementById("run-status").textContent = capMessage();
      return;
    }
    state.selectedModels.add(modelId);
    syncSelectionVisuals();
    updateSelectionMeta();
    syncRegionWarnings();
    const resp = await fetch(`/api/suggest?model_id=${encodeURIComponent(modelId)}`);
    const data = await resp.json();
    if (data.suggestions.length) {
      const names = data.suggestions.map((m) => m.name).join(", ");
      document.getElementById("run-status").textContent = `Also consider: ${names}`;
    }
  }
}
```

Change `addCustomModel`/`removeCustomModel`:

```js
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
  updateSelectionMeta();
}

function removeCustomModel(modelId) {
  state.selectedModels.delete(modelId);
  state.customModels = state.customModels.filter((id) => id !== modelId);
  renderCustomModels();
  updateSelectionMeta();
}
```

to:

```js
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
  updateSelectionMeta();
  syncRegionWarnings();
}

function removeCustomModel(modelId) {
  state.selectedModels.delete(modelId);
  state.customModels = state.customModels.filter((id) => id !== modelId);
  renderCustomModels();
  updateSelectionMeta();
  syncRegionWarnings();
}
```

Change `tryIt`:

```js
  syncSelectionVisuals();
  updateSelectionMeta();
  status.textContent = `Swapped ${oldTarget} → ${newTarget}. Click Run comparison to test it.`;
}
```

to:

```js
  syncSelectionVisuals();
  updateSelectionMeta();
  syncRegionWarnings();
  status.textContent = `Swapped ${oldTarget} → ${newTarget}. Click Run comparison to test it.`;
}
```

In `loadCatalogAndModels`, change:

```js
  renderFrontier(catalogData.frontier);
  renderProviders(catalogData.providers);
  populateModelsDatalist(state.allModels);
  updateSelectionMeta();
}
```

to:

```js
  renderFrontier(catalogData.frontier);
  renderProviders(catalogData.providers);
  populateModelsDatalist(state.allModels);
  if (catalogData.regions) {
    populateRegionSelect("bedrock-region", catalogData.regions.bedrock.regions);
    populateRegionSelect("vertex-region", catalogData.regions.vertex.regions);
    populateRegionSelect("foundry-region", catalogData.regions.foundry.regions);
  }
  updateSelectionMeta();
  syncRegionWarnings();
}
```

Near the bottom, change:

```js
document.getElementById("repeats").addEventListener("change", updateSelectionMeta);
```

to:

```js
document.getElementById("repeats").addEventListener("change", updateSelectionMeta);
["bedrock-region", "vertex-region", "foundry-region"].forEach((id) => {
  document.getElementById(id).addEventListener("change", syncRegionWarnings);
});
```

- [ ] **Step 3: Edit `static/style.css`**

Append:

```css

.top-links { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; margin: -12px 0 20px; font-size: 12px; }
.top-links a { color: var(--muted); text-decoration: none; }
.top-links a:hover { color: #10A37F; }
.status-menu { position: relative; }
.status-menu summary { cursor: pointer; color: var(--muted); list-style: none; }
.status-menu summary::-webkit-details-marker { display: none; }
.status-menu[open] summary { color: var(--fg); }
.status-menu-panel {
  position: absolute;
  top: 100%;
  left: 0;
  z-index: 15;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 14px;
  min-width: 160px;
  box-shadow: 0 4px 12px var(--overlay);
}
.status-menu-panel a { display: block; padding: 4px 0; color: var(--fg); text-decoration: none; }
.status-menu-panel a:hover { color: #10A37F; }
.region-warning-line { font-size: 12px; color: var(--status-fail); margin: 0 0 8px; }
.region-warning-line a { color: inherit; }
.region-warning-line p { margin: 4px 0; }
.region-warning-mark { margin-left: 3px; }
```

- [ ] **Step 4: Verify**

```bash
node --check static/app.js
venv/bin/pytest tests/ -q
venv/bin/python -c "
import app
c = app.app.test_client()
r = c.get('/')
assert r.status_code == 200
for needle in (b'id=\"tab-foundry\"', b'id=\"panel-foundry\"', b'id=\"region-warning-line\"', b'class=\"top-links\"', b'id=\"error-dialog-status-link\"'):
    assert needle in r.data, needle
print('index renders')
"
```

Expected: `node --check` is silent, the suite passes, and the script prints `index renders`.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html static/app.js static/style.css
git commit -m "feat: Foundry credentials tab, region selects with availability warnings, status menu, and error-popup provider links" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- templates/index.html static/app.js static/style.css
```

---

### Task 7: `/availability` page (template + JS, sortable/filterable table, banner)

**Files:**
- Create: `templates/availability.html`, `static/availability.js`
- Modify: `app.py`, `static/style.css`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `/api/availability` (Task 5), `/api/catalog` (existing + Task 5's `regions`/`providers`).
- Produces: `GET /availability` → renders `templates/availability.html`. No new Python functions beyond the route.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python


def test_availability_page_returns_200():
    resp = _client().get("/availability")
    assert resp.status_code == 200
    assert b"availability-table" in resp.data
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/pytest tests/test_app.py -k availability_page -q`
Expected: FAIL — 404 (route doesn't exist yet).

- [ ] **Step 3: Add the route in `app.py`**

After the `index()` view, add:

```python
@app.route("/availability")
def availability_page():
    return render_template("availability.html")
```

- [ ] **Step 4: Create `templates/availability.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Where models run — EvalForge Lite</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
  <script>
    (function () {
      try {
        var theme = localStorage.getItem("evalforge-theme");
        if (theme === "light" || theme === "dark") {
          document.documentElement.setAttribute("data-theme", theme);
        }
      } catch (e) {}
    })();
  </script>
</head>
<body>
  <header>
    <h1>EvalForge <span class="accent-brand">Lite</span></h1>
    <p class="tagline">Where models run — live OpenRouter listing plus curated Bedrock, Vertex, and Foundry region coverage.</p>
    <button id="theme-toggle" class="theme-toggle" aria-label="Toggle dark mode">&#127769;</button>
  </header>

  <nav class="top-links" aria-label="Site links">
    <a href="/">Back to comparison</a>
  </nav>

  <section id="availability-banner" class="card availability-banner">
    Not every model is offered in every region. If a model isn't listed for your region, switch regions or backends. Curated data can lag — verify on the provider's page.
  </section>

  <section id="availability-controls" class="card">
    <label for="availability-filter">Filter by model or provider</label>
    <input type="text" id="availability-filter" placeholder="e.g. claude, gpt-5, meta-llama">
    <div class="availability-filter-row">
      <label for="availability-backend-filter">Backend</label>
      <select id="availability-backend-filter">
        <option value="">All backends</option>
        <option value="openrouter">OpenRouter</option>
        <option value="bedrock">Amazon Bedrock</option>
        <option value="vertex">Google Vertex AI</option>
        <option value="foundry">Microsoft Foundry</option>
      </select>
      <label for="availability-region-filter">Region</label>
      <select id="availability-region-filter">
        <option value="">All regions</option>
      </select>
    </div>
  </section>

  <section id="availability-meta" class="status-text"></section>

  <section id="availability-table-section" class="card">
    <table id="availability-table">
      <thead>
        <tr>
          <th data-sort="model" tabindex="0" role="button">Model</th>
          <th data-sort="provider" tabindex="0" role="button">Provider</th>
          <th data-sort="openrouter" tabindex="0" role="button">OpenRouter</th>
          <th data-sort="bedrock" tabindex="0" role="button">Bedrock regions</th>
          <th data-sort="vertex" tabindex="0" role="button">Vertex regions</th>
          <th data-sort="foundry" tabindex="0" role="button">Foundry regions</th>
        </tr>
      </thead>
      <tbody id="availability-tbody"></tbody>
    </table>
  </section>

  <footer class="page-footer">
    <a href="https://github.com/thejaredchapman/evalforge-lite/issues/new?template=bug_report.md" target="_blank" rel="noopener">Report an issue</a>
  </footer>

  <script src="{{ url_for('static', filename='availability.js') }}"></script>
</body>
</html>
```

- [ ] **Step 5: Create `static/availability.js`**

```js
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
  const rows = sortRows(buildRows(state.data).filter(matchesFilters));
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

function setupSorting() {
  document.querySelectorAll("#availability-table th[data-sort]").forEach((th) => {
    const activate = () => {
      const key = th.dataset.sort;
      state.sortDir = state.sortKey === key ? -state.sortDir : 1;
      state.sortKey = key;
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
}

async function load() {
  const [availabilityResp, catalogResp] = await Promise.all([
    fetch("/api/availability").then((r) => r.json()),
    fetch("/api/catalog").then((r) => r.json()),
  ]);
  state.data = { availability: availabilityResp, catalog: catalogResp.providers };
  populateRegionFilter(state.data);
  renderMeta(state.data);
  renderTable();
}

document.getElementById("availability-filter").addEventListener("input", renderTable);
document.getElementById("availability-backend-filter").addEventListener("change", renderTable);
document.getElementById("availability-region-filter").addEventListener("change", renderTable);
setupSorting();
load();
```

- [ ] **Step 6: Append to `static/style.css`**

```css

.availability-banner { font-size: 13px; color: var(--muted); }
.availability-filter-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; margin-top: 10px; }
.availability-filter-row label { margin: 0; }
.availability-filter-row select {
  font-family: inherit; font-size: 13px; padding: 4px 8px;
  border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--fg);
}
#availability-table { width: 100%; border-collapse: collapse; font-size: 12px; }
#availability-table th, #availability-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
#availability-table th { cursor: pointer; color: var(--muted); user-select: none; white-space: nowrap; }
#availability-table th:hover { color: var(--fg); }
```

- [ ] **Step 7: Run tests and verify**

```bash
node --check static/availability.js
venv/bin/pytest tests/test_app.py -q
venv/bin/pytest tests/ -q
venv/bin/python -c "
import app
c = app.app.test_client()
r = c.get('/availability')
assert r.status_code == 200 and b'availability-table' in r.data
print('availability page renders')
"
```

Expected: `node --check` is silent, both pytest runs pass, and the script prints `availability page renders`.

- [ ] **Step 8: Commit**

```bash
git add templates/availability.html static/availability.js app.py static/style.css tests/test_app.py
git commit -m "feat: add the Where models run availability page" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- templates/availability.html static/availability.js app.py static/style.css tests/test_app.py
```

---

### Task 8: Docs (README, CLAUDE.md)

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md` (untracked — edit, never `git add`)

- [ ] **Step 1: README — Backends section**

Change the heading:

```
## Backends: OpenRouter, Amazon Bedrock, Google Vertex AI
```

to:

```
## Backends: OpenRouter, Amazon Bedrock, Google Vertex AI, Microsoft Foundry
```

Update the "Try it out" step-1 link, changing:

```
1. Open the credentials panel and fill in the backend(s) you'll use (see
   [Backends](#backends-openrouter-amazon-bedrock-google-vertex-ai) below).
```

to:

```
1. Open the credentials panel and fill in the backend(s) you'll use (see
   [Backends](#backends-openrouter-amazon-bedrock-google-vertex-ai-microsoft-foundry) below).
```

In the Backends section body, change:

```
- **Google Vertex AI** — either an OAuth access token or a service-account
  JSON key, plus a GCP project id and a region.
```

to:

```
- **Google Vertex AI** — either an OAuth access token or a service-account
  JSON key, plus a GCP project id and a region.
- **Microsoft Foundry** — either an API key or a Microsoft Entra ID access
  token, plus an Azure AI Foundry resource name and a region.
```

Change:

```
A model *target* is `"<catalog id>"` for OpenRouter, or `"<catalog
id>@bedrock"` / `"<catalog id>@vertex"` to run that same model on Bedrock or
Vertex instead. In the UI, pick a target by clicking a model's Bedrock or
Vertex chip (shown under any model the catalog has a route for) rather than
typing the `@backend` suffix by hand.
```

to:

```
A model *target* is `"<catalog id>"` for OpenRouter, or `"<catalog
id>@bedrock"` / `"<catalog id>@vertex"` / `"<catalog id>@foundry"` to run
that same model on Bedrock, Vertex, or Foundry instead. In the UI, pick a
target by clicking a model's Bedrock, Vertex, or Foundry chip (shown under
any model the catalog has a route for) rather than typing the `@backend`
suffix by hand.
```

Change:

```
Bedrock/Vertex costs shown in the leaderboard and reports are *estimates*,
computed from the per-token prices in `data/providers.json`, not costs
reported back by AWS/GCP billing.

Some Bedrock/Vertex routes are region-restricted: Vertex's Llama MaaS
models are only offered in certain regions (e.g. `us-east5`), and Gemini
preview models may need the `global` region instead of a specific one. If a
run fails with a routing/availability error, try a different region.
```

to:

```
Bedrock/Vertex/Foundry costs shown in the leaderboard and reports are
*estimates*, computed from the per-token prices in `data/providers.json`,
not costs reported back by AWS/GCP/Azure billing.

Some Bedrock/Vertex/Foundry routes are region-restricted: Vertex's Llama
MaaS models are only offered in certain regions (e.g. `us-east5`), Gemini
preview models may need the `global` region instead of a specific one, and
Foundry's Llama routes are only curated for a handful of regions. The
region dropdowns warn with a ⚠ when a selected model isn't listed for your
chosen region on that backend, and suggest which regions it is listed in —
see [Where models run](#where-models-run) below for the full picture.
```

- [ ] **Step 2: README — new "Where models run" and "Provider status" sections**

After the "### Judge disclosure" subsection (end of "## Comparing up to 4 models"), add:

```markdown

## Where models run

The `/availability` page (linked from the header) shows, for every catalog
model: whether it's currently listed on OpenRouter (checked live, cached
for up to 6 hours) and which regions it's curated for on Bedrock, Vertex,
and Foundry. It's filterable by model/provider name, backend, and region,
and sortable by clicking any column header. Curated region data is
dated and sourced — it can lag reality, so verify on the provider's own
page before relying on it for a production decision.

## Provider status & reporting problems

The header's "Provider status" menu links to each backend's live status
page (OpenRouter, AWS, Google Cloud, Azure), and the footer links to each
backend's own place to report a problem (GitHub issues for this app itself,
plus each cloud provider's support/feedback page). When a model call fails,
the error popup also adds "Check \<backend\> status" and "Report to
\<backend\>" links for the specific backend that failed.
```

- [ ] **Step 3: README — MCP section**

Change:

```
Exposes 8 tools: `list_models`, `suggest_models`, `set_policy`, `evaluate_prompt`,
`run_comparison`, `list_runs`, `get_report`, `get_report_csv` — the same
functionality as the web app's API, minus file-upload policy support
(`set_policy` takes plain text).
```

to:

```
Exposes 9 tools: `list_models`, `suggest_models`, `set_policy`, `evaluate_prompt`,
`run_comparison`, `list_availability`, `list_runs`, `get_report`, `get_report_csv`
— the same functionality as the web app's API, minus file-upload policy support
(`set_policy` takes plain text).
```

Change:

```
`run_comparison` and `evaluate_prompt` both take a `creds` argument —
`{"openrouter"?: str, "bedrock"?: {region, api_key} | {region, access_key_id,
secret_access_key, session_token?}, "vertex"?: {project, region, access_token}
| {project, region, service_account_json}}` — plus a `judge_backend` (default
`"openrouter"`) picking which backend runs the judge and policy gate.
```

to:

```
`run_comparison` and `evaluate_prompt` both take a `creds` argument —
`{"openrouter"?: str, "bedrock"?: {region, api_key} | {region, access_key_id,
secret_access_key, session_token?}, "vertex"?: {project, region, access_token}
| {project, region, service_account_json}, "foundry"?: {resource, region, api_key}
| {resource, region, access_token}}` — plus a `judge_backend` (default
`"openrouter"`) picking which backend runs the judge and policy gate.
```

After the `bias_note` bullet in the `run_comparison` result description, add a new bullet before the "### Publishing to the official MCP registry" heading:

```
- `list_availability` returns the same snapshot as `/api/availability`: live
  OpenRouter listing status (6-hour cache) plus curated Bedrock/Vertex/Foundry
  region coverage.
```

- [ ] **Step 4: README — Notes and Upgrading sections**

In `## Notes`, add a bullet after the existing "Rate-limited to 3 runs..." bullet:

```
- Bedrock/Vertex/Foundry region data in `data/regions.json` and each
  model's `routes.<backend>.regions` in `data/providers.json` are curated
  snapshots (dated, with a source link on the `/availability` page) — not
  a live per-account listing. They can go stale as providers add or drop
  regions; verify on the provider's own page if a run fails with a
  region/availability error.
```

- [ ] **Step 5: Verify**

Run: `venv/bin/pytest tests/ -q` → PASS (docs-only change).

- [ ] **Step 6: Edit `CLAUDE.md`** (untracked, do not `git add` it)

In the "Backend modules ... are complete" sentence, change:

```
Backend modules (`config.py`, `openrouter.py`, `catalog.py`, `checks.py`, `judge.py`,
`grading.py`, `policy.py`, `limiter.py`, `runner.py`) are complete. Still to build per the
plan: `report.py` (PDF export), `app.py` (Flask routes), and the frontend
(`templates/index.html`, `static/style.css`, `static/app.js`) — `templates/` and `static/`
are currently empty.
```

to:

```
Backend modules (`config.py`, `openrouter.py`, `bedrock.py`, `vertex.py`, `foundry.py`,
`catalog.py`, `checks.py`, `judge.py`, `grading.py`, `policy.py`, `advisor.py`,
`analysis.py`, `limiter.py`, `runner.py`, `availability.py`, `gateway.py`, `scrub.py`,
`report.py`) are complete, along with `app.py` (Flask routes), `mcp_server.py`, and the
frontend (`templates/index.html`, `templates/availability.html`, `static/style.css`,
`static/app.js`, `static/availability.js`).
```

In the "## Architecture" bullet list, after the `runner.py` bullet, add:

```
- **`foundry.py`** — thin REST client for Microsoft Foundry (`{resource}.services.ai.azure.com`),
  mirroring `vertex.py`'s structure: `FoundryError(GatewayError)`, a pure `endpoint_url(resource)`,
  and `call_model()` authenticating with either an `api-key` header or a `Bearer` access token.
- **`availability.py`** — a 6-hour-TTL cache (`snapshot()`) combining live OpenRouter listing
  status with curated Bedrock/Vertex/Foundry region data from `data/regions.json`; fails soft
  (keeps the last good data, flags `stale: true`) rather than raising on a refresh failure.
- **`data/regions.json`** — curated, dated region lists per non-OpenRouter backend, each with a
  source URL; `catalog.load_regions()`/`region_availability()` and `gateway.py`'s region
  validation both read from it.
```

- [ ] **Step 7: Commit** (README only — CLAUDE.md stays uncommitted)

```bash
git add README.md
git commit -m "docs: document Microsoft Foundry, region warnings, availability page, and status links" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- README.md
```
