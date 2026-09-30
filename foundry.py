import time

import requests

from errors import GatewayError, describe_request_error

HOST_TEMPLATE = "https://{resource}.services.ai.azure.com"
API_VERSION = "2024-05-01-preview"


class FoundryError(GatewayError):
    pass


def endpoint_url(resource):
    return f"{HOST_TEMPLATE.format(resource=resource)}/models/chat/completions?api-version={API_VERSION}"


def _auth_headers(creds):
    headers = {"Content-Type": "application/json"}
    if creds.get("api_key"):
        headers["api-key"] = creds["api_key"]
    elif creds.get("access_token"):
        headers["Authorization"] = f"Bearer {creds['access_token']}"
    else:
        raise FoundryError("Foundry credentials were not prepared.")
    return headers


def call_model(model_id, messages, creds, timeout=60):
    headers = _auth_headers(creds)

    start = time.monotonic()
    try:
        resp = requests.post(
            endpoint_url(creds["resource"]),
            headers=headers,
            json={"model": model_id, "messages": messages},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise FoundryError(describe_request_error(e)) from e
    except ValueError as e:
        raise FoundryError(f"Malformed JSON in Foundry response: {str(e)}") from e

    latency_ms = int((time.monotonic() - start) * 1000)

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise FoundryError(f"Unexpected Foundry response shape: {data!r}") from e

    usage = data.get("usage", {}) or {}
    return {
        "text": text,
        "latency_ms": latency_ms,
        "cost_usd": 0.0,
        "tokens": usage.get("total_tokens", 0),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }
