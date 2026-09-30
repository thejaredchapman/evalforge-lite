import config


def test_judge_model_has_a_default():
    assert isinstance(config.JUDGE_MODEL, str)
    assert "/" in config.JUDGE_MODEL


def test_load_providers_returns_dict_of_providers():
    providers = config.load_providers()
    assert isinstance(providers, dict)
    assert "openai" in providers
    assert "anthropic" in providers


def test_each_provider_has_required_fields():
    providers = config.load_providers()
    for provider_id, provider in providers.items():
        assert "blurb" in provider
        assert "color" in provider
        assert "frontier" in provider
        assert "models" in provider
        assert isinstance(provider["models"], list)
        assert len(provider["models"]) > 0
        for model in provider["models"]:
            assert "id" in model
            assert "name" in model
            assert "family" in model


def test_judge_models_cover_every_backend():
    assert set(config.JUDGE_MODELS) == {"openrouter", "bedrock", "vertex", "foundry"}
    assert config.JUDGE_MODEL == config.JUDGE_MODELS["openrouter"]
    assert config.JUDGE_MODELS["bedrock"].startswith("{geo}.")


def test_judge_models_cover_foundry():
    assert config.JUDGE_MODELS["foundry"] == "gpt-4o-mini"


def test_max_models_is_four():
    assert config.MAX_MODELS == 4


def test_load_regions_returns_dict_with_expected_backends():
    regions = config.load_regions()
    assert set(regions) == {"bedrock", "vertex", "foundry"}
