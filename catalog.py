import time

import requests

import config

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

_CACHE_TTL_SECONDS = 300
_cache = {"data": None, "fetched_at": 0.0}


def _pricing(model):
    pricing = model.get("pricing") or {}
    try:
        return {"prompt": float(pricing["prompt"]), "completion": float(pricing["completion"])}
    except (KeyError, TypeError, ValueError):
        return None


def load_catalog():
    return config.load_providers()


def load_regions():
    return config.load_regions()


def fetch_openrouter_models():
    """Fetch OpenRouter's full public model list (no API key required to list models).

    Cached for _CACHE_TTL_SECONDS — this is called once per page load per
    visitor, and repeatedly hitting OpenRouter's public endpoint on every
    reload serves no one; a short server-side cache means the real HTTP
    call happens at most once per TTL window regardless of visitor count.
    Returns an empty list on any request failure (never cached, so a
    transient failure self-heals on the next call) — this powers an
    optional autocomplete convenience, not core functionality, so it fails
    soft rather than surfacing an error.
    """
    now = time.time()
    if _cache["data"] is not None and (now - _cache["fetched_at"]) < _CACHE_TTL_SECONDS:
        return _cache["data"]

    try:
        resp = requests.get(OPENROUTER_MODELS_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return []

    models = [
        {"id": m["id"], "name": m.get("name", m["id"]), "created": m.get("created", 0), "pricing": _pricing(m)}
        for m in data.get("data", [])
    ]
    _cache["data"] = models
    _cache["fetched_at"] = now
    return models


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


def route_for(catalog_dict, model_id, backend):
    for provider in catalog_dict.values():
        for model in provider["models"]:
            if model["id"] == model_id:
                return (model.get("routes") or {}).get(backend)
    return None


def price_for_native_id(catalog_dict, backend, native_model_id):
    """Find the catalog price for a backend-native model id — what gateway.call_backend
    receives directly for a judge call (not routed through call_target, which already
    prices by catalog model id). Native ids are compared literally, including any
    unresolved "{geo}" template, since that's the same templated id the catalog route
    stores and the same one judge.py/policy.py pass straight through.
    """
    for provider in catalog_dict.values():
        for model in provider["models"]:
            route = (model.get("routes") or {}).get(backend)
            if route and route.get("id") == native_model_id:
                return route.get("price")
    return None


def find_model(catalog_dict, model_id):
    for provider_id, provider in catalog_dict.items():
        for model in provider["models"]:
            if model["id"] == model_id:
                return provider_id, model
    return None, None


def region_availability(catalog_dict, model_id, backend, region):
    route = route_for(catalog_dict, model_id, backend)
    known_regions = list((route or {}).get("regions") or [])
    return {"listed": region in known_regions, "known_regions": known_regions}
