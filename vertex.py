import time

import google.auth.exceptions
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from errors import GatewayError, describe_request_error

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class VertexError(GatewayError):
    pass


def endpoint_url(project, region):
    if region == "global":
        host = "https://aiplatform.googleapis.com"
    else:
        host = f"https://{region}-aiplatform.googleapis.com"
    return f"{host}/v1/projects/{project}/locations/{region}/endpoints/openapi/chat/completions"


def mint_token(service_account_info):
    try:
        # Never trust a caller-supplied token_uri: google-auth POSTs a signed JWT to it.
        info = {**service_account_info, "token_uri": TOKEN_URI}
        sa_creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        sa_creds.refresh(Request())
    except (ValueError, KeyError, TypeError, google.auth.exceptions.GoogleAuthError) as e:
        raise VertexError("Could not obtain a Vertex access token from the service account.") from e
    return sa_creds.token


def call_model(model_id, messages, creds, timeout=60):
    token = creds.get("access_token")
    if not token:
        raise VertexError("Vertex credentials were not prepared.")

    start = time.monotonic()
    try:
        resp = requests.post(
            endpoint_url(creds["project"], creds["region"]),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"model": model_id, "messages": messages},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise VertexError(describe_request_error(e)) from e
    except ValueError as e:
        raise VertexError(f"Malformed JSON in Vertex response: {str(e)}") from e

    latency_ms = int((time.monotonic() - start) * 1000)

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise VertexError(f"Unexpected Vertex response shape: {data!r}") from e

    usage = data.get("usage", {}) or {}
    return {
        "text": text,
        "latency_ms": latency_ms,
        "cost_usd": 0.0,
        "tokens": usage.get("total_tokens", 0),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }
