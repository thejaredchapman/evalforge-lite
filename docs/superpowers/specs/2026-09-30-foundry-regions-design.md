# EvalForge Lite — Microsoft Foundry Backend, Regions & Availability, Status Links (Sub-project A)

**Date:** 2026-09-30
**Status:** Design, approved in conversation
**Branch:** `feat/foundry-regions` (from `feat/error-details-contributing` @ f83c533)
**Part of:** a larger request split into sub-projects A → C → B → D → E → F. This is **A**.

## Goal

1. Add **Microsoft Foundry** as a fourth model backend alongside OpenRouter, Amazon Bedrock and Google Vertex AI.
2. Replace free-text region fields with **region dropdowns**. Warn clearly when a model isn't listed for the chosen region, and suggest regions to switch to.
3. Add a **"Where models run"** availability page covering all four backends, refreshed at most every 6 hours.
4. Link to each backend's **status page** and **report-a-problem** page, including from the error popup.

Non-goals (other sub-projects): per-response scoring (C), per-provider pickers and industry tags (B), prompt help (D), content pages (E), and Markdown export plus the full key-leak suite (F). A still adds key-leak tests for everything it introduces.

## Decisions (from brainstorming)

- Foundry auth: **API key or Microsoft Entra ID access token**, the same pattern as the other backends.
- Region/availability data: a **curated, dated list** for Bedrock, Vertex and Foundry, plus **live OpenRouter data** refreshed at most every 6 hours. No server-held credentials.
- The comparison cap stays at **4 models total**.

## 1. Foundry backend — `foundry.py` (new)

- `FoundryError(GatewayError)`.
- Endpoint: `https://{resource}.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview`, with body `{"model": model_id, "messages": messages}`.
- Auth header: `api-key: <key>` when `api_key` is present, otherwise `Authorization: Bearer <access_token>`.
- Response: OpenAI shape. `choices[0].message.content` is the text; `usage.prompt_tokens`, `completion_tokens` and `total_tokens` map to `input_tokens`, `output_tokens` and `tokens`. `cost_usd` is `0.0` from the client; the gateway prices it from the route.
- Error mapping mirrors `vertex.py`: request exception, malformed JSON, or unexpected shape → `FoundryError`. The client never raises bare `KeyError`, and `call_model` refuses missing auth with `FoundryError("Foundry credentials were not prepared.")`.
- `endpoint_url(resource)` is a pure function (tested).

## 2. Gateway, config, scrub

- `gateway.BACKENDS = ("openrouter", "bedrock", "vertex", "foundry")`; `BACKEND_LABELS["foundry"] = "Microsoft Foundry"`.
- `_prepare_foundry(raw)`:
  - `resource` must match `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$`;
  - `region` must be one of the Foundry regions in `data/regions.json`;
  - it must have exactly one of `api_key` / `access_token`, and that value must pass `_clean_secret`.

  Failures become `{"error": "..."}`, as with the other backends.
- `call_backend` dispatches `"foundry"` to `foundry.call_model`.
- `config.JUDGE_MODELS["foundry"] = os.environ.get("FOUNDRY_JUDGE_MODEL", "gpt-4o-mini")`.
- `scrub._SECRET_FIELDS["foundry"] = ("api_key", "access_token")`, plus a new pattern for JWT-shaped bearer tokens: `\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b`.
- `analysis._BACKEND_LABEL_TERMS` gains `"Microsoft Foundry"` and `"Foundry"`.
- Bedrock and Vertex region validation also checks membership in `data/regions.json`, on top of the existing regex. Unknown region → "… region is missing or invalid."

## 3. Region data — `data/regions.json` (new) + catalog route `regions`

```json
{
  "bedrock": {"label": "Amazon Bedrock", "verified": "2026-09-30",
              "source": "https://docs.aws.amazon.com/bedrock/latest/userguide/models-regions.html",
              "regions": [{"id": "us-east-1", "label": "US East (N. Virginia)", "geo": "US"}, ...]},
  "vertex":  {..., "source": "https://cloud.google.com/vertex-ai/generative-ai/docs/learn/locations", ...},
  "foundry": {..., "source": "https://learn.microsoft.com/azure/ai-foundry/foundry-models/concepts/models", ...}
}
```

Region lists:
- Bedrock: us-east-1, us-east-2, us-west-2, ca-central-1, sa-east-1, eu-central-1, eu-west-1, eu-west-3, ap-northeast-1, ap-south-1, ap-southeast-2, us-gov-west-1.
- Vertex: global, us-central1, us-east1, us-east4, us-east5, us-south1, us-west1, europe-west1, europe-west4, europe-west9, asia-northeast1, asia-southeast1.
- Foundry: eastus, eastus2, westus, westus3, northcentralus, southcentralus, canadaeast, swedencentral, francecentral, uksouth, japaneast, australiaeast.

Each non-OpenRouter catalog route gains `"regions": [...]`, the curated regions where that model is known to be offered on that backend. New `foundry` routes are added for `openai/gpt-5`, `openai/gpt-5-mini`, `openai/gpt-4o`, `openai/gpt-4o-mini`, `meta-llama/llama-4-maverick`, `meta-llama/llama-4-scout` and `meta-llama/llama-3.3-70b-instruct`, each with a Foundry model id, a price, and regions. The data is best-known; the UI says to verify on the provider's page.

`catalog.region_availability(catalog_dict, model_id, backend, region) -> {"listed": bool, "known_regions": [...]}` is a pure helper, used by the API and tests.

## 4. Availability — `availability.py` (new) + `/api/availability`

- `availability.snapshot(now=None) -> dict`:
  - `generated_at`;
  - `openrouter`: `{"refreshed_at", "stale": bool, "models": {model_id: {"listed": bool}}}` for every curated model, from `catalog.fetch_openrouter_models()` through a **6-hour** module cache (`_TTL_SECONDS = 6 * 3600`) guarded by a lock. If a refresh fails or returns nothing, keep the previous snapshot and set `stale: true`.
  - `backends`: for bedrock, vertex and foundry, `{label, verified, source, regions, models: {model_id: [regions]}}` from the curated data.
- `GET /api/availability` returns the snapshot. There's no background thread: the first request after the TTL expires triggers the refresh, so the data is never more than 6 hours old while the server is being used.

## 5. Frontend

- The credentials panel gets a 4th tab, **Microsoft Foundry**: resource name, region `<select>`, an auth toggle (API key / Entra access token) with aria-labels, and a hint pointing to `az account get-access-token --resource https://cognitiveservices.azure.com`.
- The Bedrock and Vertex region inputs become `<select>`s populated from `/api/catalog` (which now also returns `regions`). The judge-backend select gains Microsoft Foundry.
- Model chips show a **Foundry** chip where a route exists. For each selected `@backend` target, if the chosen region isn't listed, the chip gets a ⚠ with the tooltip and text "Not listed in {region} — available in {regions}. Switch region in the {backend} tab." Before running, a non-blocking warning line lists all mismatches. It links to the availability page.
- **"Where models run"** is a new page at `/availability` (server-rendered template shell plus JS fetching `/api/availability`), reached from the header nav. It has a filter box and backend/region selects. Columns: model, provider, OpenRouter (listed ✓/✗), Bedrock regions, Vertex regions, Foundry regions. Sorting is by clicking column headers, and "Last refreshed" / "Curated as of" lines appear with source links. A banner reads: *"Not every model is offered in every region. If a model isn't listed for your region, switch regions or backends. Curated data can lag — verify on the provider's page."*
- **Provider status** nav menu, a `<details>` dropdown with these links:
  - OpenRouter — https://status.openrouter.ai
  - AWS — https://health.aws.amazon.com/health/status
  - Google Cloud — https://status.cloud.google.com
  - Azure — https://azure.status.microsoft/en-us/status

  The footer gets matching **report-a-problem** links:
  - OpenRouter feedback (existing)
  - AWS Support — https://console.aws.amazon.com/support/home
  - Google Cloud Support — https://cloud.google.com/support-hub
  - Azure Support — https://azure.microsoft.com/en-us/support/create-ticket
- **Error popup:** when a failed cell's target backend is known, add "Check {backend} status" and "Report to {backend}" links, from a single `PROVIDER_LINKS` map in JS that the server also exposes via `/api/catalog` as `provider_links`.
- All new text reaches the DOM through `textContent`/`escapeHtml`, and every new control has a label or aria-label.

## 6. MCP

`run_comparison` accepts `@foundry` targets and a `foundry` judge backend automatically, through `gateway.BACKENDS`. A new `list_availability()` tool returns `availability.snapshot()`. Docstrings mention Foundry.

## 7. Error handling & safety

- Foundry follows the same fail-closed/fail-soft rules as the other backends: invalid creds are rejected up front by `check_run_creds`, before the rate limiter.
- No Foundry secret may appear in any API response, log line, run history entry, cell error, report, or MCP result.
- Availability fetch failures never raise into a request, and the last good snapshot stays.

## 8. Testing (no live network; time mocked for the TTL)

- `test_foundry.py`: URL; `api-key` vs Bearer header; response parsing; each error mapping; missing auth.
- `test_gateway.py`: Foundry prepare (valid key, valid token, bad resource such as `evil.com#` / uppercase / too long, unknown region, both-or-neither auth, whitespace secret); dispatch; idempotency; Bedrock/Vertex region membership.
- `test_scrub.py`: Foundry exact-value redaction; JWT pattern.
- `test_catalog.py`: every route has `regions` ⊆ the backend's region ids; `region_availability`.
- `test_availability.py`: first call fetches; a second call within 6h doesn't; after 6h it refetches; a failed refresh keeps the old data with `stale: true`; the curated backend section is correct.
- `test_app.py` / `test_mcp_server.py`: `/api/availability` shape; the catalog exposes `regions` and `provider_links`; a Foundry target plus judge flows through with mocks; a **key-leak test** passes Foundry creds with a secret embedded in a raised error and asserts the secret is absent from the JSON response, `caplog`, run history and the MCP result; the `list_availability` tool works.
- Frontend: `node --check static/app.js`; render smoke tests for `/` and `/availability`.
- The whole suite (387 today) stays green.

## Out of scope for A

Region auto-detection; live per-account model listing (would need server-held credentials); classic Azure OpenAI deployment endpoints.
