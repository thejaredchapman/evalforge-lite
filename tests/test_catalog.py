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


def test_route_for_returns_backend_route():
    cat = catalog.load_catalog()
    route = catalog.route_for(cat, "anthropic/claude-sonnet-4.5", "bedrock")
    assert route["id"] == "{geo}.anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_route_for_missing_backend_or_model_returns_none():
    cat = catalog.load_catalog()
    assert catalog.route_for(cat, "openai/gpt-5", "bedrock") is None
    assert catalog.route_for(cat, "nonexistent/model", "vertex") is None


def test_every_route_is_well_formed():
    cat = catalog.load_catalog()
    for provider in cat.values():
        for model in provider["models"]:
            for backend, route in (model.get("routes") or {}).items():
                assert backend in ("bedrock", "vertex")
                assert isinstance(route["id"], str) and route["id"]
                assert set(route["price"]) == {"input_per_m", "output_per_m"}
                assert all(isinstance(v, (int, float)) and v >= 0 for v in route["price"].values())
