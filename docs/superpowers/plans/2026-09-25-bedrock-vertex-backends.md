# Bedrock & Vertex AI Backends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any catalog model run through OpenRouter, Amazon Bedrock, or Google Vertex AI using per-request user credentials, with the judge/policy backend user-selectable.

**Architecture:** A new `gateway.py` sits between the orchestration layer (`runner`, `judge`, `policy`) and three thin REST clients (`openrouter.py`, new `bedrock.py`, new `vertex.py`) that share one return shape and one exception base (`errors.GatewayError`). A model **target** is a string — `"anthropic/claude-sonnet-4.5"` (OpenRouter) or `"anthropic/claude-sonnet-4.5@bedrock"` — resolved to a backend-native id via a `routes` map in `data/providers.json`. The `api_key` string threaded through the backend becomes a `creds` dict, validated and token-minted once per run by `gateway.prepare_creds`.

**Tech Stack:** Python 3.9, `requests`, `botocore` (SigV4 signing only — not boto3), `google-auth` (service-account → token only), pytest with `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-09-25-bedrock-vertex-backends-design.md`

## Global Constraints

- Every test mocks `requests.post` (or the gateway / google-auth call it wraps) — no live network calls anywhere in the test suite. Run with `source venv/bin/activate && pytest tests/ -v`.
- No server-side cloud credentials of any kind — never read an OpenRouter key, AWS key, Bedrock API key, GCP token, or service account from env/config. Every function that can reach a model takes `creds` (or a backend's slice of it) explicitly. `config.JUDGE_MODELS` holds model **ids** only.
- Backends are exactly `("openrouter", "bedrock", "vertex")`.
- Every client returns `{"text": str, "latency_ms": int, "cost_usd": float, "tokens": int}`; Bedrock and Vertex additionally return `"input_tokens"` and `"output_tokens"` (ints) for cost estimation.
- Every client raises a subclass of `errors.GatewayError` on any failure (network, malformed JSON, unexpected shape). `openrouter.OpenRouterError` becomes such a subclass with no other behavior change.
- `policy.check_policy` **fails closed** (treat as violation) on any error, including missing/invalid judge-backend creds and unknown backends. `judge.*` degrades to `None`/"Could not parse..." rather than raising.
- User-supplied region/project values are interpolated into hostnames — they must pass the regexes in `gateway.py` before any request is made: Bedrock region `^[a-z]{2}(-[a-z]+)+-\d$`, Vertex region `^(global|[a-z]+-[a-z]+\d+)$`, Vertex project `^[a-z][a-z0-9-]{4,28}[a-z0-9]$`.
- A service account's `token_uri` is always overwritten with `https://oauth2.googleapis.com/token` before google-auth sees it.
- Installing `botocore` on Python 3.9 downgrades the venv's `urllib3` from 2.x to 1.26.x (botocore pins `urllib3<1.27` below Python 3.10). `requests` 2.32 supports this; it is expected, not a bug. `google-auth` emits a Python-3.9 end-of-life `FutureWarning` on import; also expected.
- Match surrounding code: no docstrings on simple functions, module-level `_PRIVATE` constants, same exception-mapping style as `openrouter.py`.

---

### Task 1: Shared error base and Bedrock client

**Files:**
- Create: `errors.py`
- Create: `bedrock.py`
- Modify: `openrouter.py` (import + base class of `OpenRouterError`)
- Modify: `requirements.txt`
- Test: `tests/test_bedrock.py` (new), `tests/test_openrouter.py` (append one test)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `errors.GatewayError(Exception)`
  - `openrouter.OpenRouterError(GatewayError)`
  - `bedrock.BedrockError(GatewayError)`
  - `bedrock.geo_prefix(region: str) -> str` — `"us-gov" | "us" | "eu" | "apac"`, raises `BedrockError` otherwise.
  - `bedrock.resolve_model_id(model_id: str, region: str) -> str` — replaces a literal `{geo}` with `geo_prefix(region)`; ids without `{geo}` are returned unchanged.
  - `bedrock.converse_url(model_id: str, region: str) -> str`
  - `bedrock.to_converse_body(messages: list[dict]) -> dict`
  - `bedrock.call_model(model_id: str, messages: list[dict], creds: dict, timeout=60) -> dict` where `creds` is `{"region", "api_key"}` or `{"region", "access_key_id", "secret_access_key", "session_token"?}`.

- [ ] **Step 1: Add dependencies and install**

Append to `requirements.txt` (after `requests`):

```
botocore
google-auth
```

Final `requirements.txt`:

```
flask
requests
botocore
google-auth
fpdf2
pdfplumber
pytest
```

Run: `source venv/bin/activate && pip install -r requirements.txt`
Expected: installs botocore 1.42.x and google-auth 2.50.x; pip reports urllib3 downgraded to 1.26.x (see Global Constraints).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_bedrock.py`:

```python
import json
from unittest.mock import Mock, patch

import pytest
import requests

import bedrock
from errors import GatewayError

API_KEY_CREDS = {"region": "us-east-1", "api_key": "ABSKexampleexampleexample1234"}
SIGV4_CREDS = {
    "region": "eu-west-1",
    "access_key_id": "AKIAABCDEFGHIJKLMNOP",
    "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
}


def _mock_response(json_body):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_body
    return resp


def _converse_body(text="Paris.", usage=None):
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "usage": usage or {"inputTokens": 12, "outputTokens": 3, "totalTokens": 15},
    }


def test_bedrock_error_is_a_gateway_error():
    assert issubclass(bedrock.BedrockError, GatewayError)


@pytest.mark.parametrize("region,prefix", [
    ("us-east-1", "us"), ("us-west-2", "us"), ("us-gov-west-1", "us-gov"),
    ("eu-central-1", "eu"), ("ap-northeast-1", "apac"),
])
def test_resolve_model_id_fills_geo_prefix_from_region(region, prefix):
    resolved = bedrock.resolve_model_id("{geo}.anthropic.claude-haiku-4-5-20251001-v1:0", region)
    assert resolved == f"{prefix}.anthropic.claude-haiku-4-5-20251001-v1:0"


def test_resolve_model_id_leaves_plain_ids_alone():
    assert bedrock.resolve_model_id("amazon.nova-pro-v1:0", "sa-east-1") == "amazon.nova-pro-v1:0"


def test_resolve_model_id_unknown_geography_raises():
    with pytest.raises(bedrock.BedrockError):
        bedrock.resolve_model_id("{geo}.anthropic.claude-haiku-4-5-20251001-v1:0", "sa-east-1")


def test_converse_url_percent_encodes_colon_in_model_id():
    url = bedrock.converse_url("us.anthropic.claude-haiku-4-5-20251001-v1:0", "us-east-1")
    assert url == (
        "https://bedrock-runtime.us-east-1.amazonaws.com/model/"
        "us.anthropic.claude-haiku-4-5-20251001-v1%3A0/converse"
    )


def test_to_converse_body_lifts_system_messages():
    body = bedrock.to_converse_body([
        {"role": "system", "content": "Be terse."},
        {"role": "user", "content": "hi"},
    ])
    assert body == {
        "system": [{"text": "Be terse."}],
        "messages": [{"role": "user", "content": [{"text": "hi"}]}],
    }


def test_to_converse_body_omits_system_when_absent():
    body = bedrock.to_converse_body([{"role": "user", "content": "hi"}])
    assert "system" not in body


@patch("bedrock.requests.post")
def test_call_model_returns_text_latency_tokens(mock_post):
    mock_post.return_value = _mock_response(_converse_body())

    result = bedrock.call_model("{geo}.anthropic.claude-haiku-4-5-20251001-v1:0",
                                [{"role": "user", "content": "hi"}], API_KEY_CREDS)

    assert result["text"] == "Paris."
    assert result["tokens"] == 15
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 3
    assert result["cost_usd"] == 0.0
    assert isinstance(result["latency_ms"], int)


@patch("bedrock.requests.post")
def test_call_model_uses_bearer_header_for_api_key(mock_post):
    mock_post.return_value = _mock_response(_converse_body())

    bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}], API_KEY_CREDS)

    args, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer ABSKexampleexampleexample1234"
    assert json.loads(kwargs["data"]) == {"messages": [{"role": "user", "content": [{"text": "hi"}]}]}


@patch("bedrock.requests.post")
def test_call_model_signs_with_sigv4_for_access_keys(mock_post):
    mock_post.return_value = _mock_response(_converse_body())

    bedrock.call_model("{geo}.anthropic.claude-haiku-4-5-20251001-v1:0",
                       [{"role": "user", "content": "hi"}], SIGV4_CREDS)

    args, kwargs = mock_post.call_args
    auth = kwargs["headers"]["Authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIAABCDEFGHIJKLMNOP/")
    assert "/eu-west-1/bedrock/aws4_request" in auth
    assert "X-Amz-Date" in kwargs["headers"]
    assert "X-Amz-Security-Token" not in kwargs["headers"]
    assert args[0] == (
        "https://bedrock-runtime.eu-west-1.amazonaws.com/model/"
        "eu.anthropic.claude-haiku-4-5-20251001-v1%3A0/converse"
    )
    assert isinstance(kwargs["data"], bytes)


@patch("bedrock.requests.post")
def test_call_model_includes_session_token_header_when_given(mock_post):
    mock_post.return_value = _mock_response(_converse_body())

    bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}],
                       {**SIGV4_CREDS, "session_token": "FwoGZXIvYXdzEXAMPLETOKEN"})

    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["X-Amz-Security-Token"] == "FwoGZXIvYXdzEXAMPLETOKEN"


@patch("bedrock.requests.post")
def test_call_model_skips_reasoning_blocks_to_first_text(mock_post):
    body = _converse_body()
    body["output"]["message"]["content"] = [
        {"reasoningContent": {"reasoningText": {"text": "thinking..."}}},
        {"text": "Final answer."},
    ]
    mock_post.return_value = _mock_response(body)

    result = bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}], API_KEY_CREDS)

    assert result["text"] == "Final answer."


@patch("bedrock.requests.post")
def test_call_model_raises_on_request_exception(mock_post):
    mock_post.side_effect = requests.RequestException("boom")

    with pytest.raises(bedrock.BedrockError):
        bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}], API_KEY_CREDS)


@patch("bedrock.requests.post")
def test_call_model_raises_on_malformed_json(mock_post):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.side_effect = ValueError("Expecting value")
    mock_post.return_value = resp

    with pytest.raises(bedrock.BedrockError):
        bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}], API_KEY_CREDS)


@patch("bedrock.requests.post")
def test_call_model_raises_on_unexpected_shape(mock_post):
    mock_post.return_value = _mock_response({"output": {"message": {"content": [{"image": {}}]}}})

    with pytest.raises(bedrock.BedrockError):
        bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}], API_KEY_CREDS)
```

Append to `tests/test_openrouter.py`:

```python


def test_openrouter_error_is_a_gateway_error():
    from errors import GatewayError
    assert issubclass(openrouter.OpenRouterError, GatewayError)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_bedrock.py tests/test_openrouter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bedrock'` (collection error) and `ModuleNotFoundError: No module named 'errors'`.

- [ ] **Step 4: Write `errors.py`**

```python
class GatewayError(Exception):
    pass
```

- [ ] **Step 5: Make `OpenRouterError` a `GatewayError`**

In `openrouter.py`, change the imports and class line so the top of the file reads:

```python
import time

import requests

from errors import GatewayError

API_BASE = "https://openrouter.ai/api/v1"


class OpenRouterError(GatewayError):
    pass
```

Nothing else in `openrouter.py` changes.

- [ ] **Step 6: Write `bedrock.py`**

Uses the Bedrock Converse API. For access keys, the request body is serialized **once** to bytes and those exact bytes are both signed and sent (`data=`, never `json=`), and the model id is percent-encoded (`:` → `%3A`) — otherwise the SigV4 signature won't match. This was verified during planning to produce a byte-identical URL and signature to botocore's own `bedrock-runtime` client.

```python
import json
import time
from urllib.parse import quote

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from errors import GatewayError

_GEO_PREFIXES = (("us-gov-", "us-gov"), ("us-", "us"), ("eu-", "eu"), ("ap-", "apac"))


class BedrockError(GatewayError):
    pass


def geo_prefix(region):
    for region_prefix, geo in _GEO_PREFIXES:
        if region.startswith(region_prefix):
            return geo
    raise BedrockError(f"No cross-region inference profile geography for region {region}.")


def resolve_model_id(model_id, region):
    if "{geo}" in model_id:
        return model_id.replace("{geo}", geo_prefix(region))
    return model_id


def converse_url(model_id, region):
    return f"https://bedrock-runtime.{region}.amazonaws.com/model/{quote(model_id, safe='')}/converse"


def to_converse_body(messages):
    system = [{"text": m["content"]} for m in messages if m["role"] == "system"]
    convo = [
        {"role": m["role"], "content": [{"text": m["content"]}]}
        for m in messages
        if m["role"] != "system"
    ]
    body = {"messages": convo}
    if system:
        body["system"] = system
    return body


def _auth_headers(url, body_bytes, creds):
    headers = {"Content-Type": "application/json"}
    if creds.get("api_key"):
        headers["Authorization"] = f"Bearer {creds['api_key']}"
        return headers
    aws_request = AWSRequest(method="POST", url=url, data=body_bytes, headers=headers)
    aws_creds = Credentials(creds["access_key_id"], creds["secret_access_key"], creds.get("session_token"))
    SigV4Auth(aws_creds, "bedrock", creds["region"]).add_auth(aws_request)
    return dict(aws_request.headers.items())


def _first_text(content):
    for block in content:
        if isinstance(block, dict) and "text" in block:
            return block["text"]
    raise KeyError("text")


def call_model(model_id, messages, creds, timeout=60):
    region = creds["region"]
    url = converse_url(resolve_model_id(model_id, region), region)
    body = json.dumps(to_converse_body(messages)).encode("utf-8")
    headers = _auth_headers(url, body, creds)

    start = time.monotonic()
    try:
        resp = requests.post(url, headers=headers, data=body, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise BedrockError(str(e)) from e
    except ValueError as e:
        raise BedrockError(f"Malformed JSON in Bedrock response: {str(e)}") from e

    latency_ms = int((time.monotonic() - start) * 1000)

    try:
        text = _first_text(data["output"]["message"]["content"])
    except (KeyError, IndexError, TypeError) as e:
        raise BedrockError(f"Unexpected Bedrock response shape: {data!r}") from e

    usage = data.get("usage", {}) or {}
    return {
        "text": text,
        "latency_ms": latency_ms,
        "cost_usd": 0.0,
        "tokens": usage.get("totalTokens", 0),
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
    }
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_bedrock.py tests/test_openrouter.py -v`
Expected: all PASS.

- [ ] **Step 8: Run the full suite (no regressions)**

Run: `pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add errors.py bedrock.py openrouter.py requirements.txt tests/test_bedrock.py tests/test_openrouter.py
git commit -m "feat: add Bedrock Converse client with API-key and SigV4 auth"
```

---

### Task 2: Vertex AI client

**Files:**
- Create: `vertex.py`
- Test: `tests/test_vertex.py`

**Interfaces:**
- Consumes: `errors.GatewayError` (Task 1). `google-auth` installed in Task 1.
- Produces:
  - `vertex.VertexError(GatewayError)`
  - `vertex.TOKEN_URI = "https://oauth2.googleapis.com/token"`
  - `vertex.endpoint_url(project: str, region: str) -> str` — unprefixed host for `region == "global"`.
  - `vertex.mint_token(service_account_info: dict) -> str` — raises `VertexError` with a fixed message (never the underlying exception text, which can contain key material).
  - `vertex.call_model(model_id: str, messages: list[dict], creds: dict, timeout=60) -> dict` where `creds` is `{"project", "region", "access_token"}`; raises `VertexError("Vertex credentials were not prepared.")` if `access_token` is absent.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vertex.py`:

```python
from unittest.mock import Mock, patch

import pytest
import requests

import vertex
from errors import GatewayError

CREDS = {"project": "my-project-123", "region": "us-central1", "access_token": "ya29.example-token"}


def _mock_response(json_body):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_body
    return resp


def _chat_body(text="Paris."):
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11},
    }


def test_vertex_error_is_a_gateway_error():
    assert issubclass(vertex.VertexError, GatewayError)


def test_endpoint_url_uses_regional_host():
    assert vertex.endpoint_url("my-project-123", "us-central1") == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/my-project-123"
        "/locations/us-central1/endpoints/openapi/chat/completions"
    )


def test_endpoint_url_uses_unprefixed_host_for_global():
    assert vertex.endpoint_url("my-project-123", "global") == (
        "https://aiplatform.googleapis.com/v1/projects/my-project-123"
        "/locations/global/endpoints/openapi/chat/completions"
    )


@patch("vertex.requests.post")
def test_call_model_returns_text_latency_tokens(mock_post):
    mock_post.return_value = _mock_response(_chat_body())

    result = vertex.call_model("google/gemini-2.5-flash", [{"role": "user", "content": "hi"}], CREDS)

    assert result["text"] == "Paris."
    assert result["tokens"] == 11
    assert result["input_tokens"] == 9
    assert result["output_tokens"] == 2
    assert result["cost_usd"] == 0.0


@patch("vertex.requests.post")
def test_call_model_sends_bearer_token_and_model(mock_post):
    mock_post.return_value = _mock_response(_chat_body())

    vertex.call_model("google/gemini-2.5-flash", [{"role": "user", "content": "hi"}], CREDS)

    args, kwargs = mock_post.call_args
    assert args[0] == vertex.endpoint_url("my-project-123", "us-central1")
    assert kwargs["headers"]["Authorization"] == "Bearer ya29.example-token"
    assert kwargs["json"] == {"model": "google/gemini-2.5-flash", "messages": [{"role": "user", "content": "hi"}]}


def test_call_model_without_access_token_raises():
    with pytest.raises(vertex.VertexError):
        vertex.call_model("google/gemini-2.5-flash", [{"role": "user", "content": "hi"}],
                          {"project": "my-project-123", "region": "us-central1"})


@patch("vertex.requests.post")
def test_call_model_raises_on_request_exception(mock_post):
    mock_post.side_effect = requests.RequestException("boom")

    with pytest.raises(vertex.VertexError):
        vertex.call_model("google/gemini-2.5-flash", [{"role": "user", "content": "hi"}], CREDS)


@patch("vertex.requests.post")
def test_call_model_raises_on_unexpected_shape(mock_post):
    mock_post.return_value = _mock_response({"unexpected": "shape"})

    with pytest.raises(vertex.VertexError):
        vertex.call_model("google/gemini-2.5-flash", [{"role": "user", "content": "hi"}], CREDS)


@patch("vertex.service_account.Credentials.from_service_account_info")
def test_mint_token_overrides_caller_token_uri(mock_from_info):
    sa_creds = Mock()
    sa_creds.token = "ya29.minted"
    mock_from_info.return_value = sa_creds

    token = vertex.mint_token({"type": "service_account", "token_uri": "https://evil.example/steal"})

    info_passed = mock_from_info.call_args[0][0]
    assert info_passed["token_uri"] == "https://oauth2.googleapis.com/token"
    assert mock_from_info.call_args[1]["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]
    sa_creds.refresh.assert_called_once()
    assert token == "ya29.minted"


@patch("vertex.service_account.Credentials.from_service_account_info")
def test_mint_token_wraps_auth_failures_without_leaking_detail(mock_from_info):
    mock_from_info.side_effect = ValueError("bad private key -----BEGIN PRIVATE KEY-----abc")

    with pytest.raises(vertex.VertexError) as exc_info:
        vertex.mint_token({"type": "service_account"})

    assert "PRIVATE KEY" not in str(exc_info.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_vertex.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vertex'`.

- [ ] **Step 3: Write `vertex.py`**

Uses Vertex's OpenAI-compatible chat-completions endpoint, so response parsing mirrors `openrouter.py`.

```python
import time

import google.auth.exceptions
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from errors import GatewayError

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
    # Never trust a caller-supplied token_uri: google-auth POSTs a signed JWT to it.
    info = {**service_account_info, "token_uri": TOKEN_URI}
    try:
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
        raise VertexError(str(e)) from e
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_vertex.py -v`
Expected: all PASS (a google-auth Python-3.9 `FutureWarning` in the summary is expected).

- [ ] **Step 5: Commit**

```bash
git add vertex.py tests/test_vertex.py
git commit -m "feat: add Vertex AI client with access-token and service-account auth"
```

---

### Task 3: Catalog routes and per-backend judge models

**Files:**
- Modify: `data/providers.json` (add `routes` to Anthropic, Google, and Meta models)
- Modify: `catalog.py` (append `route_for`)
- Modify: `config.py` (add `JUDGE_MODELS`, keep `JUDGE_MODEL` as alias)
- Test: `tests/test_catalog.py`, `tests/test_config.py` (append)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - Model entries may carry `"routes": {"bedrock"|"vertex": {"id": str, "price": {"input_per_m": float, "output_per_m": float}}}`. Bedrock ids may contain the literal `{geo}` template (resolved by `bedrock.resolve_model_id`).
  - `catalog.route_for(catalog_dict: dict, model_id: str, backend: str) -> dict | None`
  - `config.JUDGE_MODELS: dict[str, str]` keyed by `"openrouter" | "bedrock" | "vertex"`; env overrides `JUDGE_MODEL`, `BEDROCK_JUDGE_MODEL`, `VERTEX_JUDGE_MODEL`.
  - `config.JUDGE_MODEL == config.JUDGE_MODELS["openrouter"]` (unchanged public name).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catalog.py`:

```python


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
```

Append to `tests/test_config.py`:

```python


def test_judge_models_cover_every_backend():
    assert set(config.JUDGE_MODELS) == {"openrouter", "bedrock", "vertex"}
    assert config.JUDGE_MODEL == config.JUDGE_MODELS["openrouter"]
    assert config.JUDGE_MODELS["bedrock"].startswith("{geo}.")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_catalog.py tests/test_config.py -v`
Expected: FAIL — `AttributeError: module 'catalog' has no attribute 'route_for'` and `module 'config' has no attribute 'JUDGE_MODELS'`.

- [ ] **Step 3: Replace `data/providers.json`**

Route ids and prices are best-known values at plan time; prices only feed the *estimated* `cost_usd` for Bedrock/Vertex cells. The OpenAI provider gets no routes (not offered on Bedrock/Vertex under these ids).

```json
{
  "openai": {
    "blurb": "OpenAI builds the GPT model family and popularized the modern chat-assistant interface; broad general-purpose strength and the widest third-party tooling support.",
    "color": "#10A37F",
    "frontier": "openai/gpt-5",
    "models": [
      {"id": "openai/gpt-5", "name": "GPT-5", "family": "gpt-5"},
      {"id": "openai/gpt-5-mini", "name": "GPT-5 Mini", "family": "gpt-5"},
      {"id": "openai/gpt-4o", "name": "GPT-4o", "family": "gpt-4o"},
      {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "family": "gpt-4o"}
    ]
  },
  "anthropic": {
    "blurb": "Anthropic builds the Claude model family with a focus on reliability and steerability; strong at careful reasoning, following detailed instructions, and long-context work.",
    "color": "#D97757",
    "frontier": "anthropic/claude-opus-4.5",
    "models": [
      {"id": "anthropic/claude-opus-4.5", "name": "Claude Opus 4.5", "family": "claude-opus", "routes": {"bedrock": {"id": "{geo}.anthropic.claude-opus-4-5-20251101-v1:0", "price": {"input_per_m": 5.0, "output_per_m": 25.0}}}},
      {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5", "family": "claude-sonnet", "routes": {"bedrock": {"id": "{geo}.anthropic.claude-sonnet-4-5-20250929-v1:0", "price": {"input_per_m": 3.0, "output_per_m": 15.0}}}},
      {"id": "anthropic/claude-haiku-4.5", "name": "Claude Haiku 4.5", "family": "claude-haiku", "routes": {"bedrock": {"id": "{geo}.anthropic.claude-haiku-4-5-20251001-v1:0", "price": {"input_per_m": 1.0, "output_per_m": 5.0}}}}
    ]
  },
  "google": {
    "blurb": "Google DeepMind builds the Gemini model family with native multimodal training and very large context windows, integrated tightly with Google's own products.",
    "color": "#4285F4",
    "frontier": "google/gemini-3-pro",
    "models": [
      {"id": "google/gemini-3-pro", "name": "Gemini 3 Pro", "family": "gemini-3", "routes": {"vertex": {"id": "google/gemini-3-pro-preview", "price": {"input_per_m": 2.0, "output_per_m": 12.0}}}},
      {"id": "google/gemini-3-flash", "name": "Gemini 3 Flash", "family": "gemini-3", "routes": {"vertex": {"id": "google/gemini-3-flash-preview", "price": {"input_per_m": 0.5, "output_per_m": 3.0}}}},
      {"id": "google/gemini-2.0-flash", "name": "Gemini 2.0 Flash", "family": "gemini-2", "routes": {"vertex": {"id": "google/gemini-2.0-flash-001", "price": {"input_per_m": 0.15, "output_per_m": 0.6}}}}
    ]
  },
  "meta-llama": {
    "blurb": "Meta builds the open-weight Llama model family, widely used for self-hosting and fine-tuning where control over weights and cost matters more than using a closed API.",
    "color": "#0668E1",
    "frontier": "meta-llama/llama-4-maverick",
    "models": [
      {"id": "meta-llama/llama-4-maverick", "name": "Llama 4 Maverick", "family": "llama-4", "routes": {"bedrock": {"id": "{geo}.meta.llama4-maverick-17b-instruct-v1:0", "price": {"input_per_m": 0.24, "output_per_m": 0.97}}, "vertex": {"id": "meta/llama-4-maverick-17b-128e-instruct-maas", "price": {"input_per_m": 0.35, "output_per_m": 1.15}}}},
      {"id": "meta-llama/llama-4-scout", "name": "Llama 4 Scout", "family": "llama-4", "routes": {"bedrock": {"id": "{geo}.meta.llama4-scout-17b-instruct-v1:0", "price": {"input_per_m": 0.17, "output_per_m": 0.66}}, "vertex": {"id": "meta/llama-4-scout-17b-16e-instruct-maas", "price": {"input_per_m": 0.25, "output_per_m": 0.7}}}},
      {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "family": "llama-3", "routes": {"bedrock": {"id": "{geo}.meta.llama3-3-70b-instruct-v1:0", "price": {"input_per_m": 0.72, "output_per_m": 0.72}}, "vertex": {"id": "meta/llama-3.3-70b-instruct-maas", "price": {"input_per_m": 0.72, "output_per_m": 0.72}}}}
    ]
  }
}
```

- [ ] **Step 4: Append `route_for` to `catalog.py`**

```python


def route_for(catalog_dict, model_id, backend):
    for provider in catalog_dict.values():
        for model in provider["models"]:
            if model["id"] == model_id:
                return (model.get("routes") or {}).get(backend)
    return None
```

- [ ] **Step 5: Replace `config.py`**

```python
import json
import os
from pathlib import Path

JUDGE_MODELS = {
    "openrouter": os.environ.get("JUDGE_MODEL", "openai/gpt-4o-mini"),
    "bedrock": os.environ.get("BEDROCK_JUDGE_MODEL", "{geo}.anthropic.claude-haiku-4-5-20251001-v1:0"),
    "vertex": os.environ.get("VERTEX_JUDGE_MODEL", "google/gemini-2.5-flash"),
}
JUDGE_MODEL = JUDGE_MODELS["openrouter"]

_DATA_DIR = Path(__file__).parent / "data"
_PROVIDERS_PATH = _DATA_DIR / "providers.json"


def load_providers():
    with open(_PROVIDERS_PATH) as f:
        return json.load(f)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_catalog.py tests/test_config.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add data/providers.json catalog.py config.py tests/test_catalog.py tests/test_config.py
git commit -m "feat: add Bedrock/Vertex routes to catalog and per-backend judge models"
```

---

### Task 4: Gateway — target parsing, credential prep, dispatch

**Files:**
- Create: `gateway.py`
- Test: `tests/test_gateway.py`

**Interfaces:**
- Consumes: `errors.GatewayError`, `openrouter.call_model(model_id, messages, api_key, timeout=60)`, `bedrock.call_model(model_id, messages, creds, timeout=60)`, `vertex.call_model(...)`, `vertex.mint_token(info)`, `catalog.load_catalog()`, `catalog.route_for(catalog_dict, model_id, backend)`.
- Produces:
  - `gateway.GatewayError` (re-exported from `errors`, so callers can `except gateway.GatewayError`).
  - `gateway.BACKENDS = ("openrouter", "bedrock", "vertex")`
  - `gateway.BACKEND_LABELS = {"openrouter": "OpenRouter", "bedrock": "Bedrock", "vertex": "Vertex AI"}`
  - `gateway.parse_target(target: str) -> tuple[str, str]` — `(model_id, backend)`.
  - `gateway.prepare_creds(creds: dict | None) -> dict` — validated/minted creds; a bad backend maps to `{"error": str}`; idempotent on its own output.
  - `gateway.call_backend(backend: str, native_model_id: str, messages: list[dict], creds: dict, timeout=60) -> dict`
  - `gateway.estimate_cost(price: dict | None, input_tokens: int, output_tokens: int) -> float`
  - `gateway.call_target(target: str, messages: list[dict], creds: dict, timeout=60) -> dict`
  - Missing creds error text is exactly `f"No {BACKEND_LABELS[backend]} credentials supplied."`; missing route text is exactly `f"{model_id} is not available on {BACKEND_LABELS[backend]}."`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gateway.py`:

```python
import json
from unittest.mock import patch

import pytest

import gateway
from errors import GatewayError

MESSAGES = [{"role": "user", "content": "hi"}]
FAKE_RESULT = {"text": "ok", "latency_ms": 5, "cost_usd": 0.0, "tokens": 30,
               "input_tokens": 10, "output_tokens": 20}


@pytest.mark.parametrize("target,expected", [
    ("anthropic/claude-sonnet-4.5", ("anthropic/claude-sonnet-4.5", "openrouter")),
    ("anthropic/claude-sonnet-4.5@bedrock", ("anthropic/claude-sonnet-4.5", "bedrock")),
    ("google/gemini-3-pro@vertex", ("google/gemini-3-pro", "vertex")),
    ("google/gemini-3-pro@openrouter", ("google/gemini-3-pro", "openrouter")),
    ("some/model@unknown", ("some/model@unknown", "openrouter")),
])
def test_parse_target(target, expected):
    assert gateway.parse_target(target) == expected


@pytest.mark.parametrize("bad", ["", None, 42])
def test_parse_target_rejects_empty_or_non_string(bad):
    with pytest.raises(GatewayError):
        gateway.parse_target(bad)


def test_prepare_creds_passes_openrouter_key_and_bedrock_api_key():
    prepared = gateway.prepare_creds({
        "openrouter": "sk-or-v1-test",
        "bedrock": {"region": "us-east-1", "api_key": "ABSKexample", "junk": "dropped"},
    })
    assert prepared == {
        "openrouter": "sk-or-v1-test",
        "bedrock": {"region": "us-east-1", "api_key": "ABSKexample"},
    }


def test_prepare_creds_keeps_bedrock_access_keys_and_session_token():
    prepared = gateway.prepare_creds({"bedrock": {
        "region": "eu-west-1", "access_key_id": "AKIAEXAMPLE", "secret_access_key": "secret",
        "session_token": "tok",
    }})
    assert prepared["bedrock"] == {
        "region": "eu-west-1", "access_key_id": "AKIAEXAMPLE", "secret_access_key": "secret",
        "session_token": "tok",
    }


@pytest.mark.parametrize("region", ["x.evil.com#", "us-east-1.evil.com", "US-EAST-1", "", None])
def test_prepare_creds_rejects_bad_bedrock_region(region):
    prepared = gateway.prepare_creds({"bedrock": {"region": region, "api_key": "ABSKexample"}})
    assert prepared["bedrock"] == {"error": "Bedrock region is missing or invalid."}


def test_prepare_creds_bedrock_without_any_auth_is_an_error():
    prepared = gateway.prepare_creds({"bedrock": {"region": "us-east-1"}})
    assert "error" in prepared["bedrock"]


@pytest.mark.parametrize("project,region", [
    ("evil.com#", "us-central1"),
    ("my-project-123", "x.evil.com#"),
    ("my-project-123", "us-central1/../../x"),
])
def test_prepare_creds_rejects_bad_vertex_project_or_region(project, region):
    prepared = gateway.prepare_creds({"vertex": {"project": project, "region": region, "access_token": "ya29.x"}})
    assert "error" in prepared["vertex"]


def test_prepare_creds_accepts_vertex_global_region_with_access_token():
    prepared = gateway.prepare_creds({"vertex": {"project": "my-project-123", "region": "global",
                                                 "access_token": "ya29.x"}})
    assert prepared["vertex"] == {"project": "my-project-123", "region": "global", "access_token": "ya29.x"}


@patch("gateway.vertex.mint_token", return_value="ya29.minted")
def test_prepare_creds_mints_vertex_token_from_service_account(mock_mint):
    sa = {"type": "service_account", "client_email": "x@y.iam.gserviceaccount.com"}
    prepared = gateway.prepare_creds({"vertex": {"project": "my-project-123", "region": "us-central1",
                                                 "service_account_json": json.dumps(sa)}})
    assert prepared["vertex"] == {"project": "my-project-123", "region": "us-central1",
                                  "access_token": "ya29.minted"}
    mock_mint.assert_called_once_with(sa)


@pytest.mark.parametrize("raw", ["not json", json.dumps({"type": "authorized_user"}), json.dumps([1])])
def test_prepare_creds_rejects_bad_service_account_json(raw):
    prepared = gateway.prepare_creds({"vertex": {"project": "my-project-123", "region": "us-central1",
                                                 "service_account_json": raw}})
    assert "error" in prepared["vertex"]


@patch("gateway.vertex.mint_token")
def test_prepare_creds_records_mint_failure_as_error(mock_mint):
    import vertex
    mock_mint.side_effect = vertex.VertexError("Could not obtain a Vertex access token from the service account.")
    prepared = gateway.prepare_creds({"vertex": {"project": "my-project-123", "region": "us-central1",
                                                 "service_account_json": json.dumps({"type": "service_account"})}})
    assert prepared["vertex"] == {"error": "Could not obtain a Vertex access token from the service account."}


@patch("gateway.vertex.mint_token", return_value="ya29.minted")
def test_prepare_creds_is_idempotent(mock_mint):
    raw = {
        "openrouter": "sk-or-v1-test",
        "bedrock": {"region": "nowhere"},
        "vertex": {"project": "my-project-123", "region": "us-central1",
                   "service_account_json": json.dumps({"type": "service_account"})},
    }
    once = gateway.prepare_creds(raw)
    twice = gateway.prepare_creds(once)
    assert twice == once
    assert mock_mint.call_count == 1


def test_prepare_creds_tolerates_non_dict():
    assert gateway.prepare_creds(None) == {}


@patch("gateway.openrouter.call_model", return_value=FAKE_RESULT)
def test_call_backend_openrouter_passes_key(mock_call):
    gateway.call_backend("openrouter", "openai/gpt-5", MESSAGES, {"openrouter": "sk-or-v1-test"})
    args, kwargs = mock_call.call_args
    assert args[0] == "openai/gpt-5"
    assert kwargs["api_key"] == "sk-or-v1-test"


@patch("gateway.bedrock.call_model", return_value=FAKE_RESULT)
def test_call_backend_bedrock_passes_backend_creds(mock_call):
    bedrock_creds = {"region": "us-east-1", "api_key": "ABSKexample"}
    gateway.call_backend("bedrock", "amazon.nova-pro-v1:0", MESSAGES, {"bedrock": bedrock_creds})
    args, _ = mock_call.call_args
    assert args == ("amazon.nova-pro-v1:0", MESSAGES, bedrock_creds)


@patch("gateway.vertex.call_model", return_value=FAKE_RESULT)
def test_call_backend_vertex_passes_backend_creds(mock_call):
    vertex_creds = {"project": "my-project-123", "region": "us-central1", "access_token": "ya29.x"}
    gateway.call_backend("vertex", "google/gemini-2.5-flash", MESSAGES, {"vertex": vertex_creds})
    args, _ = mock_call.call_args
    assert args == ("google/gemini-2.5-flash", MESSAGES, vertex_creds)


def test_call_backend_missing_creds_raises_named_error():
    with pytest.raises(GatewayError, match="No Bedrock credentials supplied."):
        gateway.call_backend("bedrock", "amazon.nova-pro-v1:0", MESSAGES, {"openrouter": "sk-or-v1-test"})


def test_call_backend_surfaces_prepare_error():
    with pytest.raises(GatewayError, match="Bedrock region is missing or invalid."):
        gateway.call_backend("bedrock", "amazon.nova-pro-v1:0", MESSAGES,
                             {"bedrock": {"error": "Bedrock region is missing or invalid."}})


def test_call_backend_unknown_backend_raises():
    with pytest.raises(GatewayError):
        gateway.call_backend("azure", "x", MESSAGES, {"azure": "k"})


def test_estimate_cost():
    assert gateway.estimate_cost({"input_per_m": 3.0, "output_per_m": 15.0}, 1_000_000, 100_000) == 4.5
    assert gateway.estimate_cost(None, 1000, 1000) == 0.0


@patch("gateway.openrouter.call_model", return_value=dict(FAKE_RESULT, cost_usd=0.0042))
def test_call_target_openrouter_keeps_reported_cost(mock_call):
    result = gateway.call_target("openai/gpt-5", MESSAGES, {"openrouter": "sk-or-v1-test"})
    assert result["cost_usd"] == 0.0042
    assert mock_call.call_args[0][0] == "openai/gpt-5"


@patch("gateway.bedrock.call_model", return_value=dict(FAKE_RESULT))
def test_call_target_bedrock_resolves_route_and_prices_it(mock_call):
    result = gateway.call_target("anthropic/claude-sonnet-4.5@bedrock", MESSAGES,
                                 {"bedrock": {"region": "us-east-1", "api_key": "ABSKexample"}})
    assert mock_call.call_args[0][0] == "{geo}.anthropic.claude-sonnet-4-5-20250929-v1:0"
    # 10 input tokens * $3/M + 20 output tokens * $15/M
    assert result["cost_usd"] == pytest.approx(0.00033)


def test_call_target_model_without_route_raises():
    with pytest.raises(GatewayError, match="openai/gpt-5 is not available on Bedrock."):
        gateway.call_target("openai/gpt-5@bedrock", MESSAGES,
                            {"bedrock": {"region": "us-east-1", "api_key": "ABSKexample"}})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gateway.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway'`.

- [ ] **Step 3: Write `gateway.py`**

```python
import json
import re

import bedrock
import catalog
import openrouter
import vertex
from errors import GatewayError

BACKENDS = ("openrouter", "bedrock", "vertex")
BACKEND_LABELS = {"openrouter": "OpenRouter", "bedrock": "Bedrock", "vertex": "Vertex AI"}

_BEDROCK_REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")
_VERTEX_REGION_RE = re.compile(r"^(global|[a-z]+-[a-z]+\d+)$")
_VERTEX_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def parse_target(target):
    if not isinstance(target, str) or not target:
        raise GatewayError("Model target must be a non-empty string.")
    model_id, sep, backend = target.rpartition("@")
    if sep and model_id and backend in BACKENDS:
        return model_id, backend
    return target, "openrouter"


def _nonempty_str(value):
    return isinstance(value, str) and bool(value)


def _prepare_bedrock(raw):
    if not isinstance(raw, dict):
        raise GatewayError("Bedrock credentials must be an object.")
    region = raw.get("region")
    if not _nonempty_str(region) or not _BEDROCK_REGION_RE.match(region):
        raise GatewayError("Bedrock region is missing or invalid.")
    if _nonempty_str(raw.get("api_key")):
        return {"region": region, "api_key": raw["api_key"]}
    if _nonempty_str(raw.get("access_key_id")) and _nonempty_str(raw.get("secret_access_key")):
        prepared = {
            "region": region,
            "access_key_id": raw["access_key_id"],
            "secret_access_key": raw["secret_access_key"],
        }
        if _nonempty_str(raw.get("session_token")):
            prepared["session_token"] = raw["session_token"]
        return prepared
    raise GatewayError("Bedrock credentials need an api_key, or access_key_id and secret_access_key.")


def _prepare_vertex(raw):
    if not isinstance(raw, dict):
        raise GatewayError("Vertex credentials must be an object.")
    project = raw.get("project")
    region = raw.get("region")
    if not _nonempty_str(project) or not _VERTEX_PROJECT_RE.match(project):
        raise GatewayError("Vertex project is missing or invalid.")
    if not _nonempty_str(region) or not _VERTEX_REGION_RE.match(region):
        raise GatewayError("Vertex region is missing or invalid.")
    if _nonempty_str(raw.get("access_token")):
        return {"project": project, "region": region, "access_token": raw["access_token"]}
    if _nonempty_str(raw.get("service_account_json")):
        try:
            info = json.loads(raw["service_account_json"])
        except ValueError as e:
            raise GatewayError("service_account_json is not valid JSON.") from e
        if not isinstance(info, dict) or info.get("type") != "service_account":
            raise GatewayError("service_account_json is not a service-account key.")
        token = vertex.mint_token(info)
        return {"project": project, "region": region, "access_token": token}
    raise GatewayError("Vertex credentials need an access_token or service_account_json.")


def prepare_creds(creds):
    """Validate creds once per run and mint any tokens. Idempotent on its own output."""
    creds = creds if isinstance(creds, dict) else {}
    prepared = {}
    if _nonempty_str(creds.get("openrouter")):
        prepared["openrouter"] = creds["openrouter"]
    for backend, prepare in (("bedrock", _prepare_bedrock), ("vertex", _prepare_vertex)):
        raw = creds.get(backend)
        if raw is None:
            continue
        if isinstance(raw, dict) and "error" in raw:
            prepared[backend] = raw
            continue
        try:
            prepared[backend] = prepare(raw)
        except GatewayError as e:
            prepared[backend] = {"error": str(e)}
    return prepared


def _creds_for(backend, creds):
    backend_creds = (creds or {}).get(backend)
    if not backend_creds:
        raise GatewayError(f"No {BACKEND_LABELS[backend]} credentials supplied.")
    if isinstance(backend_creds, dict) and "error" in backend_creds:
        raise GatewayError(backend_creds["error"])
    return backend_creds


def call_backend(backend, native_model_id, messages, creds, timeout=60):
    if backend not in BACKENDS:
        raise GatewayError(f"Unknown backend: {backend}")
    backend_creds = _creds_for(backend, creds)
    if backend == "openrouter":
        return openrouter.call_model(native_model_id, messages, api_key=backend_creds, timeout=timeout)
    if backend == "bedrock":
        return bedrock.call_model(native_model_id, messages, backend_creds, timeout=timeout)
    return vertex.call_model(native_model_id, messages, backend_creds, timeout=timeout)


def estimate_cost(price, input_tokens, output_tokens):
    if not price:
        return 0.0
    return round(
        input_tokens / 1e6 * price["input_per_m"] + output_tokens / 1e6 * price["output_per_m"],
        8,
    )


def call_target(target, messages, creds, timeout=60):
    model_id, backend = parse_target(target)
    if backend == "openrouter":
        return call_backend("openrouter", model_id, messages, creds, timeout=timeout)

    route = catalog.route_for(catalog.load_catalog(), model_id, backend)
    if route is None:
        raise GatewayError(f"{model_id} is not available on {BACKEND_LABELS[backend]}.")
    result = call_backend(backend, route["id"], messages, creds, timeout=timeout)
    result["cost_usd"] = estimate_cost(
        route.get("price"), result.get("input_tokens", 0), result.get("output_tokens", 0)
    )
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gateway.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add gateway.py tests/test_gateway.py
git commit -m "feat: add gateway for backend dispatch, target parsing, and credential prep"
```

---

### Task 5: Migrate judge, policy, and runner from `api_key` to `creds`

These three change together: `runner` calls `policy.check_policy` and `judge.llm_judge` with the new keyword arguments, so splitting them would leave the suite red between tasks.

**Files:**
- Modify: `judge.py` (full replacement below)
- Modify: `policy.py` (full replacement below)
- Modify: `runner.py` (full replacement below)
- Test: `tests/test_judge.py`, `tests/test_policy.py`, `tests/test_runner.py` (full replacements below)

**Interfaces:**
- Consumes: `gateway.call_backend`, `gateway.call_target`, `gateway.prepare_creds`, `gateway.GatewayError` (Task 4); `config.JUDGE_MODELS` (Task 3).
- Produces (these replace the old `api_key` signatures; the unbuilt `app.py` consumes them — see Task 7):
  - `judge.llm_judge(response_text, rubric, creds, backend="openrouter", judge_model=None) -> {"score", "rationale"}`
  - `judge.overall_verdict(aggregate_stats, creds, backend="openrouter", judge_model=None) -> {"winner", "rationale"}`
  - `policy.check_policy(prompt, policy_text, creds, backend="openrouter", judge_model=None) -> {"violates", "clause", "reason"}`
  - `runner.run(test_cases, targets, creds, policy_text=None, judge_backend="openrouter") -> list[dict]` — result cells are keyed by the **target string**; each cell's `"model_id"` is also the target string.

- [ ] **Step 1: Replace `tests/test_judge.py`**

```python
from unittest.mock import patch

import config
import gateway
import judge


def _fake_call_backend(text):
    def _inner(backend, model_id, messages, creds, timeout=60):
        return {"text": text, "latency_ms": 5, "cost_usd": 0.0, "tokens": 10}
    return _inner


@patch("judge.gateway.call_backend")
def test_llm_judge_parses_clean_json_response(mock_call):
    mock_call.side_effect = _fake_call_backend('{"score": 4, "rationale": "Accurate and concise."}')

    result = judge.llm_judge("Paris is the capital of France.", "must be accurate", creds={"openrouter": "sk-or-v1-test"})

    assert result == {"score": 4, "rationale": "Accurate and concise."}


@patch("judge.gateway.call_backend")
def test_llm_judge_parses_json_wrapped_in_prose(mock_call):
    mock_call.side_effect = _fake_call_backend(
        'Sure, here is my evaluation:\n{"score": 5, "rationale": "Perfect."}\nHope that helps!'
    )

    result = judge.llm_judge("some response", "some rubric", creds={"openrouter": "sk-or-v1-test"})

    assert result == {"score": 5, "rationale": "Perfect."}


@patch("judge.gateway.call_backend")
def test_llm_judge_fallback_on_malformed_response(mock_call):
    mock_call.side_effect = _fake_call_backend("I refuse to answer in JSON.")

    result = judge.llm_judge("some response", "some rubric", creds={"openrouter": "sk-or-v1-test"})

    assert result["score"] is None
    assert "Could not parse" in result["rationale"]


@patch("judge.gateway.call_backend")
def test_llm_judge_passes_creds_and_model_through(mock_call):
    mock_call.side_effect = _fake_call_backend('{"score": 3, "rationale": "ok"}')
    creds = {"openrouter": "sk-or-v1-mykey"}

    judge.llm_judge("resp", "rubric", creds=creds, judge_model="anthropic/claude-haiku-4.5")

    args, _ = mock_call.call_args
    assert args[0] == "openrouter"
    assert args[1] == "anthropic/claude-haiku-4.5"
    assert args[3] is creds


@patch("judge.gateway.call_backend")
def test_llm_judge_uses_backend_default_judge_model(mock_call):
    mock_call.side_effect = _fake_call_backend('{"score": 3, "rationale": "ok"}')

    judge.llm_judge("resp", "rubric", creds={"vertex": {}}, backend="vertex")

    args, _ = mock_call.call_args
    assert args[0] == "vertex"
    assert args[1] == config.JUDGE_MODELS["vertex"]


@patch("judge.gateway.call_backend")
def test_llm_judge_degrades_on_gateway_error(mock_call):
    mock_call.side_effect = gateway.GatewayError("No Bedrock credentials supplied.")

    result = judge.llm_judge("resp", "rubric", creds={}, backend="bedrock")

    assert result["score"] is None
    assert "Could not parse" in result["rationale"]


def test_llm_judge_unknown_backend_degrades_instead_of_raising():
    result = judge.llm_judge("resp", "rubric", creds={}, backend="azure")
    assert result["score"] is None


@patch("judge.gateway.call_backend")
def test_overall_verdict_routes_to_chosen_backend(mock_call):
    mock_call.side_effect = _fake_call_backend('{"winner": "a", "rationale": "b"}')

    judge.overall_verdict({"a": {"score": 90.0}}, creds={"bedrock": {}}, backend="bedrock")

    args, _ = mock_call.call_args
    assert args[0] == "bedrock"
    assert args[1] == config.JUDGE_MODELS["bedrock"]


@patch("judge.gateway.call_backend")
def test_overall_verdict_returns_winner_and_rationale(mock_call):
    mock_call.side_effect = _fake_call_backend(
        '{"winner": "openai/gpt-5", "rationale": "Highest accuracy and cleanest formatting."}'
    )

    result = judge.overall_verdict(
        {"openai/gpt-5": {"score": 95.0, "letter": "A"}, "meta-llama/llama-3.3-70b-instruct": {"score": 70.0, "letter": "C-"}},
        creds={"openrouter": "sk-or-v1-test"},
    )

    assert result == {"winner": "openai/gpt-5", "rationale": "Highest accuracy and cleanest formatting."}


@patch("judge.gateway.call_backend")
def test_overall_verdict_fallback_on_malformed_response(mock_call):
    mock_call.side_effect = _fake_call_backend("not json at all")

    result = judge.overall_verdict({"openai/gpt-5": {"score": 90.0, "letter": "A-"}}, creds={"openrouter": "sk-or-v1-test"})

    assert result["winner"] is None
    assert "Could not parse" in result["rationale"]
```

- [ ] **Step 2: Replace `tests/test_policy.py`**

```python
import io
from unittest.mock import patch

from fpdf import FPDF

import config
import policy


def _fake_call_backend(text):
    def _inner(backend, model_id, messages, creds, timeout=60):
        return {"text": text, "latency_ms": 5, "cost_usd": 0.0, "tokens": 10}
    return _inner


def test_extracts_text_from_txt_upload():
    text = policy.extract_text("policy.txt", b"No medical advice may be requested.")
    assert text == "No medical advice may be requested."


def test_extracts_text_from_pdf_upload():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Courier", size=12)
    pdf.cell(0, 10, "No medical advice may be requested.")
    pdf_bytes = bytes(pdf.output())

    text = policy.extract_text("policy.pdf", pdf_bytes)

    assert "No medical advice" in text


@patch("policy.gateway.call_backend")
def test_allows_compliant_prompt(mock_call):
    mock_call.side_effect = _fake_call_backend('{"violates": false, "clause": "", "reason": "No policy concerns."}')

    result = policy.check_policy("What's the capital of France?", "No medical advice.", creds={"openrouter": "sk-or-v1-test"})

    assert result == {"violates": False, "clause": "", "reason": "No policy concerns."}


@patch("policy.gateway.call_backend")
def test_blocks_violating_prompt_with_clause_and_reason(mock_call):
    mock_call.side_effect = _fake_call_backend(
        '{"violates": true, "clause": "No medical advice may be requested.", "reason": "The prompt asks for a diagnosis."}'
    )

    result = policy.check_policy("Diagnose my symptoms", "No medical advice may be requested.", creds={"openrouter": "sk-or-v1-test"})

    assert result["violates"] is True
    assert result["clause"] == "No medical advice may be requested."
    assert "diagnosis" in result["reason"]


@patch("policy.gateway.call_backend")
def test_fails_closed_on_malformed_llm_response(mock_call):
    mock_call.side_effect = _fake_call_backend("not valid json")

    result = policy.check_policy("some prompt", "some policy", creds={"openrouter": "sk-or-v1-test"})

    assert result["violates"] is True
    assert result["reason"] == "Could not verify policy compliance."


@patch("policy.gateway.call_backend")
def test_fails_closed_on_llm_call_error(mock_call):
    import openrouter
    mock_call.side_effect = openrouter.OpenRouterError("network down")

    result = policy.check_policy("some prompt", "some policy", creds={"openrouter": "sk-or-v1-test"})

    assert result["violates"] is True
    assert result["reason"] == "Could not verify policy compliance."


def test_no_policy_loaded_means_no_gating():
    result = policy.check_policy("anything at all", "", creds={"openrouter": "sk-or-v1-test"})

    assert result == {"violates": False, "clause": "", "reason": ""}


def test_fails_closed_when_judge_backend_has_no_creds():
    result = policy.check_policy("some prompt", "some policy", creds={"openrouter": "sk-or-v1-test"}, backend="bedrock")

    assert result["violates"] is True
    assert result["reason"] == "Could not verify policy compliance."


def test_fails_closed_on_unknown_backend():
    result = policy.check_policy("some prompt", "some policy", creds={}, backend="azure")

    assert result["violates"] is True


@patch("policy.gateway.call_backend")
def test_routes_policy_check_to_chosen_backend(mock_call):
    mock_call.side_effect = _fake_call_backend('{"violates": false, "clause": "", "reason": "ok"}')

    policy.check_policy("p", "some policy", creds={"vertex": {}}, backend="vertex")

    args, _ = mock_call.call_args
    assert args[0] == "vertex"
    assert args[1] == config.JUDGE_MODELS["vertex"]
```

- [ ] **Step 3: Replace `tests/test_runner.py`**

```python
from unittest.mock import patch

import openrouter
import runner


def _fake_call_target(target, messages, creds, timeout=60):
    return {"text": f"response from {target}", "latency_ms": 10, "cost_usd": 0.001, "tokens": 20}


@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_fans_out_every_test_case_by_model_pair(mock_call):
    test_cases = [{"prompt": "q1"}, {"prompt": "q2"}]
    model_ids = ["openai/gpt-5", "anthropic/claude-opus-4.5"]

    results = runner.run(test_cases, model_ids, creds={"openrouter": "sk-or-v1-test"})

    assert len(results) == 2
    for row in results:
        assert set(row["cells"].keys()) == set(model_ids)
    assert mock_call.call_count == 4


@patch("runner.gateway.call_target")
def test_one_model_failure_does_not_abort_other_cells(mock_call):
    def _side_effect(target, messages, creds, timeout=60):
        if target == "broken/model":
            raise openrouter.OpenRouterError("rate limited")
        return {"text": "ok response", "latency_ms": 5, "cost_usd": 0.0, "tokens": 5}

    mock_call.side_effect = _side_effect

    results = runner.run([{"prompt": "q1"}], ["broken/model", "openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"})

    cells = results[0]["cells"]
    assert cells["broken/model"]["error"] == "rate limited"
    assert cells["openai/gpt-5"]["error"] is None
    assert cells["openai/gpt-5"]["response_text"] == "ok response"


@patch("runner.policy.check_policy")
@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_policy_blocked_case_skips_model_calls_entirely(mock_call, mock_policy):
    mock_policy.return_value = {"violates": True, "clause": "No medical advice.", "reason": "asks for diagnosis"}

    results = runner.run(
        [{"prompt": "diagnose me"}], ["openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"}, policy_text="No medical advice."
    )

    cell = results[0]["cells"]["openai/gpt-5"]
    assert cell["blocked"] is True
    assert cell["policy_clause"] == "No medical advice."
    mock_call.assert_not_called()


@patch("runner.checks.run_checks")
@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_runs_rule_checks_when_defined(mock_call, mock_checks):
    mock_checks.return_value = [{"check": {"type": "contains", "value": "x"}, "passed": True}]

    results = runner.run(
        [{"prompt": "q1", "checks": [{"type": "contains", "value": "x"}]}],
        ["openai/gpt-5"],
        creds={"openrouter": "sk-or-v1-test"},
    )

    cell = results[0]["cells"]["openai/gpt-5"]
    assert cell["checks"] == [{"check": {"type": "contains", "value": "x"}, "passed": True}]


@patch("runner.judge.llm_judge")
@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_runs_judge_when_rubric_defined(mock_call, mock_judge):
    mock_judge.return_value = {"score": 4, "rationale": "Good."}

    results = runner.run(
        [{"prompt": "q1", "rubric": "be accurate"}], ["openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"}
    )

    cell = results[0]["cells"]["openai/gpt-5"]
    assert cell["judge_score"] == 4
    assert cell["judge_rationale"] == "Good."


@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_same_model_on_two_backends_gets_two_cells(mock_call):
    targets = ["anthropic/claude-sonnet-4.5", "anthropic/claude-sonnet-4.5@bedrock"]

    results = runner.run(
        [{"prompt": "q1"}], targets,
        creds={"openrouter": "sk-or-v1-test", "bedrock": {"region": "us-east-1", "api_key": "ABSKexample"}},
    )

    cells = results[0]["cells"]
    assert set(cells.keys()) == set(targets)
    assert cells["anthropic/claude-sonnet-4.5@bedrock"]["response_text"] == "response from anthropic/claude-sonnet-4.5@bedrock"


def test_missing_backend_creds_becomes_a_cell_error_not_a_crash():
    results = runner.run([{"prompt": "q1"}], ["anthropic/claude-sonnet-4.5@bedrock"],
                         creds={"openrouter": "sk-or-v1-test"})

    cell = results[0]["cells"]["anthropic/claude-sonnet-4.5@bedrock"]
    assert cell["error"] == "No Bedrock credentials supplied."


@patch("runner.gateway.prepare_creds")
@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_prepares_creds_once_and_threads_prepared_creds(mock_call, mock_prepare):
    mock_prepare.return_value = {"openrouter": "sk-or-v1-prepared"}

    runner.run([{"prompt": "q1"}, {"prompt": "q2"}], ["openai/gpt-5", "openai/gpt-5-mini"],
               creds={"openrouter": "sk-or-v1-raw"})

    mock_prepare.assert_called_once_with({"openrouter": "sk-or-v1-raw"})
    for call in mock_call.call_args_list:
        assert call[0][2] == {"openrouter": "sk-or-v1-prepared"}


@patch("runner.judge.llm_judge", return_value={"score": 4, "rationale": "Good."})
@patch("runner.policy.check_policy", return_value={"violates": False, "clause": "", "reason": ""})
@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_judge_backend_is_passed_to_policy_and_judge(mock_call, mock_policy, mock_judge):
    runner.run([{"prompt": "q1", "rubric": "r"}], ["openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"},
               policy_text="some policy", judge_backend="vertex")

    assert mock_policy.call_args[1]["backend"] == "vertex"
    assert mock_judge.call_args[1]["backend"] == "vertex"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_judge.py tests/test_policy.py tests/test_runner.py -v`
Expected: FAIL — `AttributeError: <module 'judge'> does not have the attribute 'gateway'` (and the same for `policy` / `runner`), plus `TypeError: ... unexpected keyword argument 'creds'`.

- [ ] **Step 5: Replace `judge.py`**

The model lookup moves **inside** the `try` so an unknown backend (`KeyError`) degrades instead of raising.

```python
import json
import re

import config
import gateway

JUDGE_PROMPT_TEMPLATE = """You are an expert evaluator. Given a rubric and a model's response, score the response.

Rubric: {rubric}

Response:
{response}

Respond with ONLY a JSON object in this exact shape, no other text:
{{"score": <integer 1-5>, "rationale": "<one sentence>"}}
"""

VERDICT_PROMPT_TEMPLATE = """You are comparing the aggregate performance of several LLMs on a benchmark suite.

Per-model stats:
{stats}

Which model performed best overall? Respond with ONLY a JSON object in this exact shape, no other text:
{{"winner": "<model id>", "rationale": "<two sentences>"}}
"""


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in response: {text!r}")
    return json.loads(match.group(0))


def llm_judge(response_text, rubric, creds, backend="openrouter", judge_model=None):
    prompt = JUDGE_PROMPT_TEMPLATE.format(rubric=rubric, response=response_text)

    try:
        model = judge_model or config.JUDGE_MODELS[backend]
        result = gateway.call_backend(backend, model, [{"role": "user", "content": prompt}], creds)
        parsed = _extract_json(result["text"])
        score = int(parsed["score"])
        rationale = str(parsed["rationale"])
    except (gateway.GatewayError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"score": None, "rationale": "Could not parse judge response."}

    return {"score": score, "rationale": rationale}


def overall_verdict(aggregate_stats, creds, backend="openrouter", judge_model=None):
    stats_text = "\n".join(f"- {model_id}: {stats}" for model_id, stats in aggregate_stats.items())
    prompt = VERDICT_PROMPT_TEMPLATE.format(stats=stats_text)

    try:
        model = judge_model or config.JUDGE_MODELS[backend]
        result = gateway.call_backend(backend, model, [{"role": "user", "content": prompt}], creds)
        parsed = _extract_json(result["text"])
        winner = str(parsed["winner"])
        rationale = str(parsed["rationale"])
    except (gateway.GatewayError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"winner": None, "rationale": "Could not parse verdict response."}

    return {"winner": winner, "rationale": rationale}
```

- [ ] **Step 6: Replace `policy.py`**

Still fails closed: the model lookup, template formatting, gateway call, and parsing all sit inside the `try`, and `gateway.GatewayError` covers missing creds, prepare errors, and every client's errors.

```python
import io
import json
import re

import pdfplumber

import config
import gateway

POLICY_PROMPT_TEMPLATE = """You are a compliance checker. Given a company policy and a user's prompt, determine whether the prompt violates the policy.

Policy:
{policy}

Prompt:
{prompt}

Respond with ONLY a JSON object in this exact shape, no other text:
{{"violates": <true or false>, "clause": "<quoted or paraphrased policy clause, empty string if no violation>", "reason": "<one sentence>"}}
"""


def extract_text(filename, file_bytes):
    if filename.lower().endswith(".pdf"):
        parts = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)
    return file_bytes.decode("utf-8")


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in response: {text!r}")
    return json.loads(match.group(0))


def check_policy(prompt, policy_text, creds, backend="openrouter", judge_model=None):
    if not policy_text:
        return {"violates": False, "clause": "", "reason": ""}

    try:
        model = judge_model or config.JUDGE_MODELS[backend]
        llm_prompt = POLICY_PROMPT_TEMPLATE.format(policy=policy_text, prompt=prompt)
        result = gateway.call_backend(backend, model, [{"role": "user", "content": llm_prompt}], creds)
        parsed = _extract_json(result["text"])
        violates = bool(parsed["violates"])
        clause = str(parsed.get("clause", ""))
        reason = str(parsed.get("reason", ""))
    except (gateway.GatewayError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"violates": True, "clause": "", "reason": "Could not verify policy compliance."}

    return {"violates": violates, "clause": clause, "reason": reason}
```

- [ ] **Step 7: Replace `runner.py`**

```python
from concurrent.futures import ThreadPoolExecutor

import checks
import gateway
import judge
import policy


def _run_one_cell(test_case, target, creds, policy_text, judge_backend):
    prompt = test_case["prompt"]

    if policy_text:
        policy_result = policy.check_policy(prompt, policy_text, creds=creds, backend=judge_backend)
        if policy_result["violates"]:
            return {
                "model_id": target,
                "blocked": True,
                "policy_clause": policy_result["clause"],
                "policy_reason": policy_result["reason"],
            }

    try:
        response = gateway.call_target(target, [{"role": "user", "content": prompt}], creds)
    except gateway.GatewayError as e:
        return {"model_id": target, "blocked": False, "error": str(e)}

    check_results = []
    if test_case.get("checks"):
        check_results = checks.run_checks(test_case["checks"], response["text"])

    judge_score = None
    judge_rationale = None
    if test_case.get("rubric"):
        judge_result = judge.llm_judge(response["text"], test_case["rubric"], creds=creds, backend=judge_backend)
        judge_score = judge_result["score"]
        judge_rationale = judge_result["rationale"]

    return {
        "model_id": target,
        "blocked": False,
        "error": None,
        "response_text": response["text"],
        "latency_ms": response["latency_ms"],
        "cost_usd": response["cost_usd"],
        "tokens": response["tokens"],
        "checks": check_results,
        "judge_score": judge_score,
        "judge_rationale": judge_rationale,
    }


def run(test_cases, targets, creds, policy_text=None, judge_backend="openrouter"):
    creds = gateway.prepare_creds(creds)
    cells_by_tc = {i: {} for i in range(len(test_cases))}

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}
        for tc_index, test_case in enumerate(test_cases):
            for target in targets:
                future = pool.submit(_run_one_cell, test_case, target, creds, policy_text, judge_backend)
                futures[future] = (tc_index, target)

        for future, (tc_index, target) in futures.items():
            cells_by_tc[tc_index][target] = future.result()

    return [
        {"test_case": test_case, "cells": cells_by_tc[tc_index]}
        for tc_index, test_case in enumerate(test_cases)
    ]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_judge.py tests/test_policy.py tests/test_runner.py -v`
Expected: all PASS.

- [ ] **Step 9: Confirm no stale `api_key` call sites remain outside `openrouter.py` / `gateway.py`**

Run: `grep -n "api_key" judge.py policy.py runner.py`
Expected: no output.

- [ ] **Step 10: Run the full suite**

Run: `pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 11: Commit**

```bash
git add judge.py policy.py runner.py tests/test_judge.py tests/test_policy.py tests/test_runner.py
git commit -m "feat: route judge, policy gate, and runner through gateway with per-backend creds"
```

---

### Task 6: Credential scrubber

**Files:**
- Create: `scrub.py`
- Test: `tests/test_scrub.py`

**Interfaces:**
- Consumes: nothing from other tasks (the `creds` shape from Task 4's docs).
- Produces:
  - `scrub.REDACTED = "[REDACTED]"`
  - `scrub.secret_values(creds: dict | None) -> list[str]` — every secret string in raw or prepared creds that is ≥ 8 chars, including a service account's `private_key` in both raw and JSON-escaped form.
  - `scrub.scrub(message: str, creds: dict | None = None) -> str` — exact-value replacement (longest first), then regex patterns. `app.py` (Task 7) uses this for error responses and log lines.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scrub.py`:

```python
import json

import pytest

import scrub


@pytest.mark.parametrize("secret", [
    "sk-or-v1-abcdefgh12345678",
    "AKIAABCDEFGHIJKLMNOP",
    "ASIAABCDEFGHIJKLMNOP",
    "ABSKQmVkcm9ja0FQSUtleS1leGFtcGxlZXhhbXBsZQ==",
    "bedrock-api-key-YmVkcm9jay5hbWF6b25hd3MuY29tLz9BY3Rpb24",
    "ya29.a0AfH6SMBexample_token-value",
])
def test_scrub_redacts_known_secret_formats(secret):
    out = scrub.scrub(f"request failed using {secret} today")
    assert secret not in out
    assert "[REDACTED]" in out


def test_scrub_redacts_pem_private_key_blocks():
    pem = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\nkqhkiG9w0BAQEF\n-----END PRIVATE KEY-----"
    out = scrub.scrub(f"bad key: {pem} end")
    assert "MIIEvQIBADANBg" not in out
    assert out == "bad key: [REDACTED] end"


def test_scrub_redacts_exact_creds_values_without_a_pattern():
    creds = {"bedrock": {"region": "us-east-1", "access_key_id": "AKIAABCDEFGHIJKLMNOP",
                         "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}}
    out = scrub.scrub("sig mismatch for wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", creds)
    assert "wJalrXUtnFEMI" not in out


def test_scrub_redacts_service_account_private_key_in_either_encoding():
    key = "-----BEGIN PRIVATE KEY-----\nABCDEFGH12345678\n-----END PRIVATE KEY-----\n"
    sa_json = json.dumps({"type": "service_account", "private_key": key})
    creds = {"vertex": {"project": "p", "region": "us-central1", "service_account_json": sa_json}}
    escaped = json.dumps(key)[1:-1]
    out = scrub.scrub(f"echo: {escaped}", creds)
    assert "ABCDEFGH12345678" not in out


def test_scrub_leaves_short_or_non_secret_values_alone():
    creds = {"bedrock": {"region": "us-east-1", "api_key": "short"}}
    assert scrub.scrub("region us-east-1 key short", creds) == "region us-east-1 key short"


def test_scrub_without_creds_still_applies_patterns():
    assert scrub.scrub("nothing secret here") == "nothing secret here"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scrub.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrub'`.

- [ ] **Step 3: Write `scrub.py`**

```python
import json
import re

REDACTED = "[REDACTED]"

_PATTERNS = [
    re.compile(r"\b(sk|pk)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bABSK[A-Za-z0-9+/=]{20,}"),
    re.compile(r"\bbedrock-api-key-[A-Za-z0-9+/=._-]{20,}"),
    re.compile(r"\bya29\.[A-Za-z0-9._-]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
]

_SECRET_FIELDS = {
    "bedrock": ("api_key", "access_key_id", "secret_access_key", "session_token"),
    "vertex": ("access_token", "service_account_json"),
}

_MIN_SECRET_LEN = 8


def _service_account_secrets(raw_json):
    try:
        info = json.loads(raw_json)
    except ValueError:
        return []
    key = info.get("private_key") if isinstance(info, dict) else None
    if not isinstance(key, str):
        return []
    return [key, json.dumps(key)[1:-1]]


def secret_values(creds):
    if not isinstance(creds, dict):
        return []
    values = []
    if isinstance(creds.get("openrouter"), str):
        values.append(creds["openrouter"])
    for backend, fields in _SECRET_FIELDS.items():
        backend_creds = creds.get(backend)
        if not isinstance(backend_creds, dict):
            continue
        for field in fields:
            value = backend_creds.get(field)
            if isinstance(value, str):
                values.append(value)
                if field == "service_account_json":
                    values.extend(_service_account_secrets(value))
    return [v for v in values if len(v) >= _MIN_SECRET_LEN]


def scrub(message, creds=None):
    for value in sorted(secret_values(creds), key=len, reverse=True):
        message = message.replace(value, REDACTED)
    for pattern in _PATTERNS:
        message = pattern.sub(REDACTED, message)
    return message
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scrub.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scrub.py tests/test_scrub.py
git commit -m "feat: add credential scrubber covering AWS, Bedrock, GCP, and PEM secrets"
```

---

### Task 7: Amend the finish plan, finish spec, and CLAUDE.md for the new interfaces

`app.py` and the frontend are not built yet — they are Tasks 2–3 of `docs/superpowers/plans/2026-08-29-evalforge-lite-finish.md`. That plan still targets the old `api_key` interfaces, so it must be updated before it is executed. This task edits documents only; verification is by `grep` plus a full test run to prove nothing in code moved.

**Files:**
- Modify: `docs/superpowers/plans/2026-08-29-evalforge-lite-finish.md`
- Modify: `docs/superpowers/specs/2026-08-29-evalforge-lite-finish/design.md` (append an amendment section)
- Modify: `CLAUDE.md` (untracked in git — edit it, but only `git add` it if the user has started tracking it)

**Interfaces:**
- Consumes: every "Produces" item from Tasks 1–6.
- Produces: an executable finish plan whose `app.py` accepts `{"creds": {...}, "judge_backend": "..."}` (with legacy `{"api_key": "..."}` still accepted as `creds.openrouter`) and whose frontend offers a three-tab credentials panel, per-model backend chips, and a judge-backend select.

- [ ] **Step 1: Update the finish plan's Global Constraints**

In `docs/superpowers/plans/2026-08-29-evalforge-lite-finish.md`, replace these four bullets under `## Global Constraints`:

Old:
```
- Do not modify `config.py`, `openrouter.py`, `catalog.py`, `checks.py`, `judge.py`, `grading.py`, `policy.py`, `limiter.py`, or `runner.py` — their existing interfaces are the contract this plan builds on.
```
New:
```
- Do not modify `config.py`, `errors.py`, `openrouter.py`, `bedrock.py`, `vertex.py`, `gateway.py`, `scrub.py`, `catalog.py`, `checks.py`, `judge.py`, `grading.py`, `policy.py`, `limiter.py`, or `runner.py` — their interfaces, as updated by `docs/superpowers/plans/2026-09-25-bedrock-vertex-backends.md`, are the contract this plan builds on.
```

Old:
```
- Never read an OpenRouter API key from server env/config — `api_key` is always the caller-supplied value passed through explicitly.
```
New:
```
- Never read any provider credential (OpenRouter key, AWS keys, Bedrock API key, GCP token or service account) from server env/config — `creds` is always the caller-supplied value passed through explicitly.
```

Old:
```
- Error messages returned to the client must never contain the user's API key — scrub with `re.compile(r"\b(sk|pk)-[A-Za-z0-9_-]{8,}\b")` → `"[REDACTED]"`.
```
New:
```
- Error messages returned to the client **or written to logs** must never contain credentials — always pass them through `scrub.scrub(message, raw_creds)`. Never use `logger.exception` on the run path (the traceback text is unscrubbed).
```

Old:
```
- Validate `POST /api/run`'s JSON body explicitly (missing/malformed body, missing `api_key`/`test_cases`/`models`) and return `400` before touching any of those fields — never let a malformed request reach an unhandled exception.
```
New:
```
- Validate `POST /api/run`'s JSON body explicitly (missing/malformed body, missing `creds` (or legacy `api_key`)/`test_cases`/`models`, `judge_backend` not in `gateway.BACKENDS`) and return `400` before touching any of those fields — never let a malformed request reach an unhandled exception. If a policy is loaded and `creds` has no entry for the judge backend, return `400` **before** `limiter.check_and_record` so it doesn't cost the user a run.
```

- [ ] **Step 2: Update the finish plan's Task 2 Interfaces block**

Replace the `- Consumes:` line of Task 2 with:

```
- Consumes: `catalog.load_catalog() -> dict`, `catalog.frontier_models(dict) -> list[dict]`, `catalog.suggest_family(dict, str) -> list[dict]`, `policy.extract_text(filename, bytes) -> str`, `limiter.check_and_record(session_id, now) -> dict`, `gateway.BACKENDS`, `gateway.prepare_creds(creds) -> dict`, `runner.run(test_cases, targets, creds, policy_text=None, judge_backend="openrouter") -> list[dict]`, `grading.grade_model(judge_scores, rule_check_results, judge_rationales) -> dict`, `judge.overall_verdict(aggregate_stats, creds, backend="openrouter") -> dict`, `scrub.scrub(message, creds=None) -> str`, `report.build_pdf(run_result) -> bytes`, `report.build_csv(run_result) -> str`.
```

Delete the Produces bullet `` - `app._scrub(message: str) -> str`. `` (scrubbing now lives in `scrub.py`).

- [ ] **Step 3: Add app tests to the finish plan's Task 2 Step 1 (`tests/test_app.py`)**

Append this block to the end of the `tests/test_app.py` code block in Task 2 Step 1 (after the last existing test in that block):

```python


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_accepts_creds_and_judge_backend(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    creds = {"bedrock": {"region": "us-east-1", "api_key": "ABSKexampleexampleexample1234"}}

    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}],
        "models": ["anthropic/claude-sonnet-4.5@bedrock"],
        "creds": creds,
        "judge_backend": "bedrock",
    })

    assert resp.status_code == 200
    _, run_kwargs = mock_run.call_args
    assert run_kwargs["creds"] == {"bedrock": {"region": "us-east-1", "api_key": "ABSKexampleexampleexample1234"}}
    assert run_kwargs["judge_backend"] == "bedrock"
    _, verdict_kwargs = mock_verdict.call_args
    assert verdict_kwargs["backend"] == "bedrock"


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_legacy_api_key_becomes_openrouter_creds(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    _client().post("/api/run", json={"test_cases": [], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-test"})

    _, run_kwargs = mock_run.call_args
    assert run_kwargs["creds"] == {"openrouter": "sk-or-v1-test"}
    assert run_kwargs["judge_backend"] == "openrouter"


def test_api_run_invalid_judge_backend_returns_400():
    resp = _client().post("/api/run", json={
        "test_cases": [], "models": [], "creds": {"openrouter": "sk-or-v1-test"}, "judge_backend": "azure",
    })
    assert resp.status_code == 400
    assert "judge_backend" in resp.get_json()["error"]


def test_api_run_creds_must_be_an_object():
    resp = _client().post("/api/run", json={"test_cases": [], "models": [], "creds": "sk-or-v1-test"})
    assert resp.status_code == 400


def test_api_run_policy_without_judge_creds_returns_400_without_spending_a_run():
    client = _client()
    client.post(
        "/api/policy",
        data={"file": (io.BytesIO(b"No medical advice."), "policy.txt")},
        content_type="multipart/form-data",
    )

    resp = client.post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"],
        "creds": {"openrouter": "sk-or-v1-test"}, "judge_backend": "vertex",
    })

    assert resp.status_code == 400
    assert "Vertex AI" in resp.get_json()["error"]
    assert all(len(v) == 0 for v in limiter._attempts.values())


def test_api_run_error_response_scrubs_aws_secret_by_exact_value(caplog):
    secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    with patch("app.runner.run", side_effect=Exception(f"signature mismatch for {secret}")):
        resp = _client().post("/api/run", json={
            "test_cases": [{"prompt": "q1"}], "models": ["anthropic/claude-sonnet-4.5@bedrock"],
            "creds": {
                "openrouter": "sk-or-v1-test",
                "bedrock": {"region": "us-east-1", "access_key_id": "AKIAABCDEFGHIJKLMNOP",
                            "secret_access_key": secret},
            },
        })

    assert resp.status_code == 503
    assert secret not in resp.get_json()["error"]
    assert secret not in caplog.text
```

- [ ] **Step 4: Replace `_SECRET_RE` / `_scrub` and the run endpoint in the finish plan's Task 2 Step 3 (`app.py`)**

In the `app.py` code block of Task 2 Step 3:

(a) In the imports, replace `import catalog` with:

```python
import catalog
import gateway
```

and replace `import runner` with:

```python
import runner
import scrub
```

(b) Delete these lines entirely:

```python
_SECRET_RE = re.compile(r"\b(sk|pk)-[A-Za-z0-9_-]{8,}\b")
```

```python
def _scrub(message):
    return _SECRET_RE.sub("[REDACTED]", message)
```

(If `re` is then unused in `app.py`, also delete `import re`.)

(c) Replace the whole `_validate_run_body` function **and** the whole `api_run` function with:

```python
def _raw_creds(body):
    if "creds" in body:
        return body["creds"]
    if isinstance(body.get("api_key"), str) and body["api_key"]:
        return {"openrouter": body["api_key"]}
    return None


def _validate_run_body(body):
    if not isinstance(body, dict):
        return "Request body must be JSON."
    raw_creds = _raw_creds(body)
    if not isinstance(raw_creds, dict) or not raw_creds:
        return "Missing required field: creds (or api_key)."
    if body.get("judge_backend", "openrouter") not in gateway.BACKENDS:
        return "Invalid judge_backend."
    if not isinstance(body.get("test_cases"), list):
        return "Missing required field: test_cases."
    if not isinstance(body.get("models"), list) or not all(isinstance(m, str) for m in body["models"]):
        return "Missing required field: models."
    return None


@app.route("/api/run", methods=["POST"])
def api_run():
    session_id = _get_session_id()
    body = request.get_json(silent=True)

    error = _validate_run_body(body)
    if error:
        return _with_session_cookie(_error_response(error, 400), session_id)

    raw_creds = _raw_creds(body)
    judge_backend = body.get("judge_backend", "openrouter")
    test_cases = body["test_cases"]
    model_ids = body["models"]

    with _store_lock:
        policy_text = _policy_store.get(session_id)

    if policy_text and not raw_creds.get(judge_backend):
        label = gateway.BACKEND_LABELS[judge_backend]
        message = f"A policy is loaded, so {label} credentials are required for the judge backend."
        return _with_session_cookie(_error_response(message, 400), session_id)

    limit_result = limiter.check_and_record(session_id, time.time())
    if not limit_result["allowed"]:
        resp = jsonify({"error": "rate_limited", "reset_at": limit_result["reset_at"]})
        resp.status_code = 429
        return _with_session_cookie(resp, session_id)

    try:
        creds = gateway.prepare_creds(raw_creds)
        results = runner.run(
            test_cases, model_ids, creds=creds, policy_text=policy_text, judge_backend=judge_backend
        )

        agg_stats = _aggregate_stats(results, model_ids)
        grades = {
            model_id: grading.grade_model(
                s["judge_scores"], s["rule_check_results"], s["judge_rationales"]
            )
            for model_id, s in agg_stats.items()
        }
        stats = _cost_latency_stats(agg_stats)

        verdict = {"winner": None, "rationale": "No models were run."}
        if model_ids:
            verdict = judge.overall_verdict(
                {m: {"score": grades[m]["score"], "letter": grades[m]["letter"]} for m in model_ids},
                creds=creds,
                backend=judge_backend,
            )
    except Exception as e:
        message = scrub.scrub(str(e), raw_creds)
        logger.error("run failed: %s", message)
        return _with_session_cookie(_error_response(message, 503), session_id)

    run_result = {
        "run_id": str(uuid.uuid4()),
        "created_at": time.time(),
        "results": results,
        "grades": grades,
        "stats": stats,
        "verdict": verdict,
    }

    with _store_lock:
        history = _run_history_store.setdefault(session_id, deque(maxlen=5))
        history.append(run_result)

    return _with_session_cookie(jsonify(run_result), session_id)
```

(d) The existing test `test_api_run_missing_api_key_returns_400` still passes unchanged (the new message contains `"api_key"`), as does `test_api_run_error_response_scrubs_api_key` (the `sk-or-v1-…` regex still applies).

- [ ] **Step 5: Update the finish plan's Task 3 `index.html`**

(a) Replace the tagline line:

```html
    <p class="tagline">Compare text LLMs across providers with your own OpenRouter key.</p>
```

with:

```html
    <p class="tagline">Compare text LLMs via OpenRouter, Amazon Bedrock, or Google Vertex AI with your own credentials.</p>
```

(b) Replace the entire `<section id="api-key-section" class="card">…</section>` with:

```html
  <section id="creds-section" class="card">
    <div class="tab-row">
      <button type="button" class="tab active" data-backend="openrouter">OpenRouter</button>
      <button type="button" class="tab" data-backend="bedrock">Amazon Bedrock</button>
      <button type="button" class="tab" data-backend="vertex">Google Vertex AI</button>
    </div>

    <div class="cred-panel" data-backend="openrouter">
      <label for="api-key">OpenRouter API key</label>
      <input type="password" id="api-key" placeholder="sk-or-v1-..." autocomplete="off">
    </div>

    <div class="cred-panel" data-backend="bedrock" hidden>
      <label for="bedrock-region">AWS region</label>
      <input type="text" id="bedrock-region" placeholder="us-east-1">
      <div class="auth-toggle">
        <label><input type="radio" name="bedrock-auth" value="api_key" checked> Bedrock API key</label>
        <label><input type="radio" name="bedrock-auth" value="access_keys"> Access keys</label>
      </div>
      <div class="auth-fields" data-auth-group="bedrock" data-auth="api_key">
        <input type="password" id="bedrock-api-key" placeholder="ABSK... or bedrock-api-key-..." autocomplete="off">
      </div>
      <div class="auth-fields" data-auth-group="bedrock" data-auth="access_keys" hidden>
        <input type="password" id="bedrock-access-key-id" placeholder="Access key ID" autocomplete="off">
        <input type="password" id="bedrock-secret-access-key" placeholder="Secret access key" autocomplete="off">
        <input type="password" id="bedrock-session-token" placeholder="Session token (optional)" autocomplete="off">
      </div>
    </div>

    <div class="cred-panel" data-backend="vertex" hidden>
      <label for="vertex-project">GCP project ID</label>
      <input type="text" id="vertex-project" placeholder="my-project-123">
      <label for="vertex-region">Region</label>
      <input type="text" id="vertex-region" placeholder="us-central1 (use global for Gemini 3 preview)">
      <div class="auth-toggle">
        <label><input type="radio" name="vertex-auth" value="access_token" checked> Access token</label>
        <label><input type="radio" name="vertex-auth" value="service_account"> Service-account JSON</label>
      </div>
      <div class="auth-fields" data-auth-group="vertex" data-auth="access_token">
        <input type="password" id="vertex-access-token" placeholder="ya29... (gcloud auth print-access-token)" autocomplete="off">
      </div>
      <div class="auth-fields" data-auth-group="vertex" data-auth="service_account" hidden>
        <input type="file" id="vertex-sa-file" accept=".json,application/json">
        <span id="vertex-sa-status" class="status-text"></span>
      </div>
    </div>

    <label for="judge-backend">Judge &amp; policy backend</label>
    <select id="judge-backend">
      <option value="openrouter">OpenRouter</option>
      <option value="bedrock">Amazon Bedrock</option>
      <option value="vertex">Google Vertex AI</option>
    </select>
  </section>
```

- [ ] **Step 6: Update the finish plan's Task 3 `style.css`**

Append to the end of the `static/style.css` code block:

```css

.tab-row { display: flex; gap: 6px; margin-bottom: 12px; }
.tab {
  font-family: inherit;
  font-size: 12px;
  background: #fff;
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 12px;
  cursor: pointer;
}
.tab.active { color: var(--fg); border-color: var(--fg); }
.cred-panel input[type="text"], .cred-panel input[type="password"] { display: block; width: 100%; margin-bottom: 8px; }
.auth-toggle { display: flex; gap: 16px; margin: 4px 0 8px; font-size: 12px; }
.auth-toggle label { display: inline-flex; gap: 4px; align-items: center; margin: 0; }
select {
  font-family: inherit;
  font-size: 13px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
}
.model-option { display: inline-flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.backend-chips { display: flex; gap: 4px; }
.backend-chip {
  font-size: 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 1px 8px;
  color: var(--muted);
  cursor: pointer;
  user-select: none;
}
.backend-chip.selected { background: var(--fg); border-color: var(--fg); color: #fff; }
```

- [ ] **Step 7: Update the finish plan's Task 3 `app.js`**

(a) In `const state = { … }`, add a property after `selectedModels: new Set(),`:

```javascript
  vertexServiceAccount: null,   // service-account JSON text; lives only in this tab's memory
```

`state.selectedModels` now holds **target strings** (`"<id>"` for OpenRouter, `"<id>@bedrock"` / `"<id>@vertex"` otherwise); no code change is needed for that beyond the functions below.

(b) Replace the whole `function apiKey() { … }` with:

```javascript
const BACKEND_LABELS = { openrouter: "OpenRouter", bedrock: "Amazon Bedrock", vertex: "Google Vertex AI" };

function fieldValue(id) {
  return document.getElementById(id).value.trim();
}

function checkedValue(name) {
  return document.querySelector(`input[name="${name}"]:checked`).value;
}

function buildCreds() {
  const creds = {};
  const orKey = fieldValue("api-key");
  if (orKey) creds.openrouter = orKey;

  const bedrockRegion = fieldValue("bedrock-region");
  if (bedrockRegion) {
    if (checkedValue("bedrock-auth") === "api_key") {
      creds.bedrock = { region: bedrockRegion, api_key: fieldValue("bedrock-api-key") };
    } else {
      creds.bedrock = {
        region: bedrockRegion,
        access_key_id: fieldValue("bedrock-access-key-id"),
        secret_access_key: fieldValue("bedrock-secret-access-key"),
      };
      const sessionToken = fieldValue("bedrock-session-token");
      if (sessionToken) creds.bedrock.session_token = sessionToken;
    }
  }

  const vertexProject = fieldValue("vertex-project");
  if (vertexProject) {
    const region = fieldValue("vertex-region") || "us-central1";
    if (checkedValue("vertex-auth") === "access_token") {
      creds.vertex = { project: vertexProject, region, access_token: fieldValue("vertex-access-token") };
    } else {
      creds.vertex = { project: vertexProject, region, service_account_json: state.vertexServiceAccount || "" };
    }
  }
  return creds;
}

function targetBackend(target) {
  const at = target.lastIndexOf("@");
  const suffix = at === -1 ? "" : target.slice(at + 1);
  return BACKEND_LABELS[suffix] ? suffix : "openrouter";
}

function missingBackends(creds) {
  const needed = new Set(Array.from(state.selectedModels).map(targetBackend));
  needed.add(document.getElementById("judge-backend").value);
  return Array.from(needed).filter((backend) => !creds[backend]);
}

function setupCredsPanel() {
  const tabs = document.querySelectorAll("#creds-section .tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".cred-panel").forEach((panel) => {
        panel.hidden = panel.dataset.backend !== tab.dataset.backend;
      });
    });
  });
  ["bedrock", "vertex"].forEach((group) => {
    document.querySelectorAll(`input[name="${group}-auth"]`).forEach((radio) => {
      radio.addEventListener("change", () => {
        document.querySelectorAll(`.auth-fields[data-auth-group="${group}"]`).forEach((el) => {
          el.hidden = el.dataset.auth !== radio.value;
        });
      });
    });
  });
  document.getElementById("vertex-sa-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    state.vertexServiceAccount = file ? await file.text() : null;
    document.getElementById("vertex-sa-status").textContent = file ? "Service account loaded (kept in this tab only)." : "";
  });
}
```

(c) Replace the whole `function modelBadge(model, color) { … }` with:

```javascript
function modelBadge(model, color) {
  const wrapper = document.createElement("div");
  wrapper.className = "model-option";

  const el = document.createElement("div");
  el.className = "model-badge";
  el.textContent = model.name;
  el.style.borderColor = color;
  el.style.color = color;
  el.dataset.modelId = model.id;
  el.title = "Run via OpenRouter";
  el.addEventListener("click", () => toggleModel(model.id, el, color));
  wrapper.appendChild(el);

  const backends = Object.keys(model.routes || {});
  if (backends.length) {
    const chips = document.createElement("div");
    chips.className = "backend-chips";
    backends.forEach((backend) => {
      const chip = document.createElement("span");
      chip.className = "backend-chip";
      chip.textContent = backend === "bedrock" ? "Bedrock" : "Vertex";
      chip.title = `Also run via ${BACKEND_LABELS[backend]}`;
      chip.addEventListener("click", () => toggleBackendTarget(`${model.id}@${backend}`, chip));
      chips.appendChild(chip);
    });
    wrapper.appendChild(chips);
  }
  return wrapper;
}

function toggleBackendTarget(target, chip) {
  if (state.selectedModels.has(target)) {
    state.selectedModels.delete(target);
    chip.classList.remove("selected");
  } else {
    state.selectedModels.add(target);
    chip.classList.add("selected");
  }
}
```

(d) In `runComparison`, replace the opening validation and the `fetch` body. The function's start, through the closing `});` of the `fetch` call, becomes:

```javascript
async function runComparison() {
  const runStatus = document.getElementById("run-status");
  if (state.selectedModels.size === 0) {
    runStatus.textContent = "Pick at least one model.";
    return;
  }
  const creds = buildCreds();
  const missing = missingBackends(creds);
  if (missing.length) {
    runStatus.textContent = `Add ${missing.map((b) => BACKEND_LABELS[b]).join(" and ")} credentials first.`;
    return;
  }

  runStatus.textContent = "Running...";
  const resp = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      test_cases: state.testCases,
      models: Array.from(state.selectedModels),
      creds,
      judge_backend: document.getElementById("judge-backend").value,
    }),
  });
```

The rest of `runComparison` (429 / error / success handling) is unchanged.

(e) In the init block at the bottom of `app.js`, replace:

```javascript
loadCatalog();
addTestCase();
```

with:

```javascript
setupCredsPanel();
loadCatalog();
addTestCase();
```

- [ ] **Step 8: Update the finish plan's Task 3 manual-verification step**

Append to the paragraph in Task 3 Step 4 (the one beginning "Open `http://localhost:5060` and confirm"):

```
Then confirm the credentials card: the three tabs switch panels; the Bedrock and Vertex auth radios swap their fields; Claude, Gemini, and Llama badges show small Bedrock/Vertex chips that toggle independently of the badge; selecting a Bedrock chip without Bedrock credentials shows "Add Amazon Bedrock credentials first."; the leaderboard labels a Bedrock run as `anthropic/claude-sonnet-4.5@bedrock`; and choosing a judge backend without credentials for it is blocked client-side.
```

- [ ] **Step 9: Append an amendment section to the finish spec**

Append to `docs/superpowers/specs/2026-08-29-evalforge-lite-finish/design.md`:

```markdown

## Amendment (2026-09-25): Bedrock & Vertex AI backends

The backend now supports Amazon Bedrock and Google Vertex AI alongside OpenRouter — see
`docs/superpowers/specs/2026-09-25-bedrock-vertex-backends-design.md`. Consequences for this spec:

- `/api/run` takes `creds` (`{"openrouter"?, "bedrock"?, "vertex"?}`) and optional `judge_backend`
  (default `"openrouter"`); legacy `api_key` is still accepted as `creds.openrouter`.
- `models` entries are target strings: `"<model id>"` (OpenRouter) or `"<model id>@bedrock|vertex"`.
- If a policy is loaded and the judge backend has no creds, `/api/run` returns 400 before the
  rate limiter is charged.
- Error responses and log lines use `scrub.scrub(message, raw_creds)` instead of the single
  `sk-/pk-` regex; `logger.exception` is not used on the run path.
- The frontend's API-key card becomes a three-tab credentials card with a judge-backend select,
  and models with Bedrock/Vertex routes show per-backend chips.
```

- [ ] **Step 10: Update CLAUDE.md**

In `CLAUDE.md`:

(a) Replace the paragraph beginning "Backend modules (`config.py`, `openrouter.py`, …" with:

```markdown
Backend modules (`config.py`, `errors.py`, `openrouter.py`, `bedrock.py`, `vertex.py`,
`gateway.py`, `scrub.py`, `catalog.py`, `checks.py`, `judge.py`, `grading.py`, `policy.py`,
`limiter.py`, `runner.py`) are complete. Still to build per the finish plan
(`docs/superpowers/plans/2026-08-29-evalforge-lite-finish.md`, amended 2026-09-25 for
Bedrock/Vertex): `report.py` (PDF export), `app.py` (Flask routes), and the frontend
(`templates/index.html`, `static/style.css`, `static/app.js`).
```

(b) Replace the line "Every test mocks `openrouter.call_model` (or `requests.post`) — there must be no live network calls anywhere in the test suite." with:

```markdown
Every test mocks the network (`requests.post`, `gateway.call_backend`/`call_target`, or
google-auth's token refresh) — there must be no live network calls anywhere in the test suite.
```

(c) In `## Architecture`, add these bullets directly after the `openrouter.py` bullet:

```markdown
- **`gateway.py`** — backend dispatch. A model *target* is `"<catalog id>"` (OpenRouter) or
  `"<catalog id>@bedrock|vertex"`; `call_target()` resolves it to a native id + price via the
  model's `routes` in `providers.json`, `call_backend()` calls a native id directly (used by the
  judge/policy with `config.JUDGE_MODELS[backend]`). `prepare_creds()` validates the per-request
  `creds` dict once per run (region/project regexes guard against SSRF) and mints Vertex tokens
  from service-account JSON; it is idempotent on its own output.
- **`bedrock.py`** — Bedrock Converse API; Bedrock API key (bearer) or AWS access keys (SigV4 via
  botocore). A literal `{geo}` in a model id becomes the cross-region inference-profile prefix
  derived from the region.
- **`vertex.py`** — Vertex AI OpenAI-compatible endpoint; access token, or service-account JSON
  exchanged via google-auth with `token_uri` forced to Google's.
- **`scrub.py`** — redacts credentials from any text sent to the client or logs: exact values
  from the request's `creds` plus regexes for `sk-/pk-`, AWS key ids, Bedrock keys, `ya29.`
  tokens, and PEM private keys.
```

(d) Replace the first two bullets under `## Conventions carried through the codebase` with:

```markdown
- No server-side model credentials ever, anywhere — every function that can reach a model takes
  `creds` (or its backend's slice) as an explicit parameter.
- Security-sensitive modules (`policy.py`, `judge.py`) fail closed: catch `gateway.GatewayError`
  plus JSON/parse exceptions and return a safe default rather than propagating.
```

and replace the bullet beginning "When the future `app.py` returns errors to the client…" with:

```markdown
- When `app.py` returns errors to the client or logs them, pass the text through
  `scrub.scrub(message, raw_creds)`.
```

- [ ] **Step 11: Verify the amendments landed**

Run:
```bash
grep -c "api_key" docs/superpowers/plans/2026-08-29-evalforge-lite-finish.md
grep -n "_SECRET_RE\|def _scrub\|function apiKey\|api-key-section" docs/superpowers/plans/2026-08-29-evalforge-lite-finish.md
grep -n "gateway.prepare_creds\|scrub.scrub\|setupCredsPanel\|judge_backend" docs/superpowers/plans/2026-08-29-evalforge-lite-finish.md | head
```
Expected: the second command prints nothing; the third prints matches in Global Constraints, Task 2, and Task 3. Remaining `api_key` hits are only the legacy-compat tests/validation and the `id="api-key"` input.

- [ ] **Step 12: Run the full suite (docs-only task — nothing should move)**

Run: `pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 13: Commit**

```bash
git add docs/superpowers/plans/2026-08-29-evalforge-lite-finish.md docs/superpowers/specs/2026-08-29-evalforge-lite-finish/design.md
git commit -m "docs: amend finish plan and spec for Bedrock/Vertex backends"
```

(`CLAUDE.md` is untracked; leave it out of the commit unless the user has started tracking it.)
