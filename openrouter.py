import time

import requests

API_BASE = "https://openrouter.ai/api/v1"


class OpenRouterError(Exception):
    pass


def call_model(model_id, messages, api_key, timeout=60):
    start = time.monotonic()
    try:
        resp = requests.post(
            f"{API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model_id, "messages": messages},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise OpenRouterError(str(e)) from e
    except ValueError as e:
        raise OpenRouterError(f"Malformed JSON in OpenRouter response: {str(e)}") from e

    latency_ms = int((time.monotonic() - start) * 1000)

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise OpenRouterError(f"Unexpected OpenRouter response shape: {data!r}") from e

    usage = data.get("usage", {}) or {}
    cost_usd = usage.get("cost", 0.0)
    if not isinstance(cost_usd, (int, float)):
        cost_usd = 0.0
    tokens = usage.get("total_tokens", 0)

    return {
        "text": text,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "tokens": tokens,
    }
