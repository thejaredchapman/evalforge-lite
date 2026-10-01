from unittest.mock import Mock, patch

import catalog
import config


def setup_function():
    catalog._cache["data"] = None
    catalog._cache["fetched_at"] = 0.0


def test_load_catalog_matches_config_providers():
    assert catalog.load_catalog() == config.load_providers()


def test_frontier_list_includes_one_model_per_provider():
    cat = catalog.load_catalog()
    frontier = catalog.frontier_models(cat)

    assert len(frontier) == len(cat)
    provider_ids = {m["provider"] for m in frontier}
    assert provider_ids == set(cat.keys())


def test_frontier_models_have_expected_fields():
    cat = catalog.load_catalog()
    frontier = catalog.frontier_models(cat)

    for model in frontier:
        assert "id" in model
        assert "name" in model
        assert "family" in model
        assert "provider" in model


def test_family_suggestions_exclude_the_selected_model():
    cat = catalog.load_catalog()
    suggestions = catalog.suggest_family(cat, "openai/gpt-5")

    ids = [m["id"] for m in suggestions]
    assert "openai/gpt-5" not in ids


def test_family_suggestions_stay_within_same_provider():
    cat = catalog.load_catalog()
    suggestions = catalog.suggest_family(cat, "anthropic/claude-opus-4.5")

    for model in suggestions:
        # OpenRouter's own self-updating "-latest" alias ids use a leading "~"
        # instead of a plain "provider/model" prefix (e.g. "~anthropic/claude-opus-latest").
        assert model["id"].lstrip("~").startswith("anthropic/")


def test_family_suggestions_for_unknown_model_returns_empty_list():
    cat = catalog.load_catalog()
    assert catalog.suggest_family(cat, "nonexistent/model") == []


def test_route_for_returns_backend_route():
    cat = catalog.load_catalog()
    route = catalog.route_for(cat, "anthropic/claude-sonnet-4.5", "bedrock")
    assert route["id"] == "{geo}.anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_route_for_missing_backend_or_model_returns_none():
    cat = catalog.load_catalog()
    assert catalog.route_for(cat, "openai/gpt-5", "bedrock") is None
    assert catalog.route_for(cat, "nonexistent/model", "vertex") is None


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


def test_every_route_is_well_formed():
    cat = catalog.load_catalog()
    regions_by_backend = catalog.load_regions()
    for provider in cat.values():
        for model in provider["models"]:
            for backend, route in (model.get("routes") or {}).items():
                assert backend in ("bedrock", "vertex", "foundry")
                assert isinstance(route["id"], str) and route["id"]
                assert set(route["price"]) == {"input_per_m", "output_per_m"}
                assert all(isinstance(v, (int, float)) and v >= 0 for v in route["price"].values())
                known_ids = {r["id"] for r in regions_by_backend[backend]["regions"]}
                assert route["regions"] and set(route["regions"]) <= known_ids


@patch("catalog.requests.get")
def test_fetch_openrouter_models_returns_id_name_and_created(mock_get):
    mock_get.return_value = Mock(status_code=200, json=lambda: {
        "data": [
            {"id": "mistralai/mistral-large", "name": "Mistral Large", "created": 1700000000},
            {"id": "openai/gpt-5", "name": "GPT-5", "created": 1750000000},
        ]
    })

    result = catalog.fetch_openrouter_models()

    assert result == [
        {"id": "mistralai/mistral-large", "name": "Mistral Large", "created": 1700000000, "pricing": None},
        {"id": "openai/gpt-5", "name": "GPT-5", "created": 1750000000, "pricing": None},
    ]
    mock_get.assert_called_once_with(catalog.OPENROUTER_MODELS_URL, timeout=10)


@patch("catalog.requests.get")
def test_fetch_openrouter_models_falls_back_to_id_when_name_missing(mock_get):
    mock_get.return_value = Mock(status_code=200, json=lambda: {
        "data": [{"id": "some/model", "created": 1700000000}]
    })

    result = catalog.fetch_openrouter_models()

    assert result == [{"id": "some/model", "name": "some/model", "created": 1700000000, "pricing": None}]


@patch("catalog.requests.get")
def test_fetch_openrouter_models_returns_empty_list_on_request_failure(mock_get):
    import requests
    mock_get.side_effect = requests.RequestException("timed out")

    assert catalog.fetch_openrouter_models() == []


@patch("catalog.requests.get")
def test_fetch_openrouter_models_caches_within_ttl(mock_get):
    mock_get.return_value = Mock(status_code=200, json=lambda: {"data": [{"id": "a/b", "name": "AB"}]})

    catalog.fetch_openrouter_models()
    catalog.fetch_openrouter_models()
    catalog.fetch_openrouter_models()

    mock_get.assert_called_once()


@patch("catalog.requests.get")
def test_fetch_openrouter_models_refetches_after_ttl_expires(mock_get):
    mock_get.return_value = Mock(status_code=200, json=lambda: {"data": [{"id": "a/b", "name": "AB"}]})

    with patch("catalog.time.time", return_value=1000.0):
        catalog.fetch_openrouter_models()
    with patch("catalog.time.time", return_value=1000.0 + catalog._CACHE_TTL_SECONDS + 1):
        catalog.fetch_openrouter_models()

    assert mock_get.call_count == 2


@patch("catalog.requests.get")
def test_fetch_openrouter_models_does_not_cache_failures(mock_get):
    import requests
    mock_get.side_effect = requests.RequestException("timed out")

    catalog.fetch_openrouter_models()
    catalog.fetch_openrouter_models()

    assert mock_get.call_count == 2


EXPECTED_TIERS = {
    "~openai/gpt-latest": "flagship", "openai/gpt-5": "flagship", "openai/gpt-5-mini": "fast",
    "openai/gpt-4o": "balanced", "openai/gpt-4o-mini": "fast",
    "~anthropic/claude-opus-latest": "flagship", "anthropic/claude-opus-4.5": "flagship",
    "anthropic/claude-sonnet-4.5": "balanced", "anthropic/claude-haiku-4.5": "fast",
    "~google/gemini-pro-latest": "flagship", "google/gemini-2.5-pro": "flagship",
    "google/gemini-3.7-flash": "balanced", "google/gemini-2.5-flash": "fast",
    "meta-llama/llama-4-maverick": "flagship", "meta-llama/llama-3.3-70b-instruct": "balanced",
    "meta-llama/llama-4-scout": "fast",
}
EXPECTED_REASONING = {
    "~openai/gpt-latest", "openai/gpt-5", "openai/gpt-5-mini", "google/gemini-2.5-pro",
    "google/gemini-2.5-flash", "google/gemini-3.7-flash", "~google/gemini-pro-latest",
}


def test_every_curated_model_has_its_expected_tier():
    cat = catalog.load_catalog()
    tiers = {m["id"]: m.get("tier") for p in cat.values() for m in p["models"]}
    assert tiers == EXPECTED_TIERS


def test_reasoning_flags():
    cat = catalog.load_catalog()
    flagged = {m["id"] for p in cat.values() for m in p["models"] if m.get("reasoning")}
    assert flagged == EXPECTED_REASONING


def test_find_model():
    cat = catalog.load_catalog()
    provider_id, model = catalog.find_model(cat, "anthropic/claude-haiku-4.5")
    assert provider_id == "anthropic" and model["name"] == "Claude Haiku 4.5"
    assert catalog.find_model(cat, "nope/nope") == (None, None)


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


@patch("catalog.requests.get")
def test_fetch_openrouter_models_keeps_pricing(mock_get):
    catalog._cache["data"] = None
    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.json.return_value = {"data": [
        {"id": "a/priced", "name": "Priced", "created": 1, "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
        {"id": "a/free-form", "name": "Odd", "created": 2, "pricing": {"prompt": "n/a"}},
        {"id": "a/none", "name": "None", "created": 3},
    ]}
    models = {m["id"]: m for m in catalog.fetch_openrouter_models()}
    catalog._cache["data"] = None
    assert models["a/priced"]["pricing"] == {"prompt": 0.000001, "completion": 0.000002}
    assert models["a/free-form"]["pricing"] is None
    assert models["a/none"]["pricing"] is None


def test_price_for_native_id_matches_bedrock_geo_template():
    cat = catalog.load_catalog()
    price = catalog.price_for_native_id(cat, "bedrock", "{geo}.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert price == {"input_per_m": 1.0, "output_per_m": 5.0}


def test_price_for_native_id_matches_foundry_plain_id():
    cat = catalog.load_catalog()
    price = catalog.price_for_native_id(cat, "foundry", "gpt-4o-mini")
    assert price == {"input_per_m": 0.15, "output_per_m": 0.6}


def test_price_for_native_id_returns_none_when_not_found():
    cat = catalog.load_catalog()
    assert catalog.price_for_native_id(cat, "bedrock", "not-a-real-model") is None


def test_price_for_native_id_returns_none_for_unknown_backend():
    cat = catalog.load_catalog()
    assert catalog.price_for_native_id(cat, "openrouter", "openai/gpt-5") is None
