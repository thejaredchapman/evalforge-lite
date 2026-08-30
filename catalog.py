import requests

import config

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def load_catalog():
    return config.load_providers()


def fetch_openrouter_models():
    """Fetch OpenRouter's full public model list (no API key required to list models).

    Returns an empty list on any request failure — this powers an optional
    autocomplete convenience, not core functionality, so it fails soft.
    """
    try:
        resp = requests.get(OPENROUTER_MODELS_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return []

    return [{"id": m["id"], "name": m.get("name", m["id"])} for m in data.get("data", [])]


def frontier_models(catalog_dict):
    result = []
    for provider_id, provider in catalog_dict.items():
        frontier_id = provider.get("frontier")
        if not frontier_id:
            continue
        model = next((m for m in provider["models"] if m["id"] == frontier_id), None)
        if model:
            result.append({**model, "provider": provider_id})
    return result


def suggest_family(catalog_dict, model_id):
    for provider in catalog_dict.values():
        for model in provider["models"]:
            if model["id"] == model_id:
                family = model["family"]
                return [
                    m for m in provider["models"]
                    if m["family"] == family and m["id"] != model_id
                ]
    return []
