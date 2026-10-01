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
