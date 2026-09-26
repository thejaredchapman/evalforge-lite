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
