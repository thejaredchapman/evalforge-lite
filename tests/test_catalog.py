from unittest.mock import Mock, patch

import catalog
import config


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
        assert model["id"].startswith("anthropic/")


def test_family_suggestions_for_unknown_model_returns_empty_list():
    cat = catalog.load_catalog()
    assert catalog.suggest_family(cat, "nonexistent/model") == []


@patch("catalog.requests.get")
def test_fetch_openrouter_models_returns_id_and_name_pairs(mock_get):
    mock_get.return_value = Mock(status_code=200, json=lambda: {
        "data": [
            {"id": "mistralai/mistral-large", "name": "Mistral Large"},
            {"id": "openai/gpt-5", "name": "GPT-5"},
        ]
    })

    result = catalog.fetch_openrouter_models()

    assert result == [
        {"id": "mistralai/mistral-large", "name": "Mistral Large"},
        {"id": "openai/gpt-5", "name": "GPT-5"},
    ]
    mock_get.assert_called_once_with(catalog.OPENROUTER_MODELS_URL, timeout=10)


@patch("catalog.requests.get")
def test_fetch_openrouter_models_falls_back_to_id_when_name_missing(mock_get):
    mock_get.return_value = Mock(status_code=200, json=lambda: {
        "data": [{"id": "some/model"}]
    })

    result = catalog.fetch_openrouter_models()

    assert result == [{"id": "some/model", "name": "some/model"}]


@patch("catalog.requests.get")
def test_fetch_openrouter_models_returns_empty_list_on_request_failure(mock_get):
    import requests
    mock_get.side_effect = requests.RequestException("timed out")

    assert catalog.fetch_openrouter_models() == []
