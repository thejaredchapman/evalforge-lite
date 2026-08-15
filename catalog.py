import config


def load_catalog():
    return config.load_providers()


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
