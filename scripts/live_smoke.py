"""Live smoke test: one tiny real call per cloud backend.

Unit tests mock every provider; this script makes real, billable calls
(fractions of a cent each) to confirm Bedrock and Vertex work end to end.
Credentials come from environment variables and are never printed.

Bedrock (either an API key or an access key pair):
    BEDROCK_REGION=us-east-1
    AWS_BEARER_TOKEN_BEDROCK=...                  # Bedrock API key, or:
    AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... [AWS_SESSION_TOKEN=...]

Vertex:
    VERTEX_PROJECT=my-gcp-project
    VERTEX_REGION=us-central1
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

Usage:
    python scripts/live_smoke.py                       # every backend with creds set
    python scripts/live_smoke.py bedrock               # just one
    python scripts/live_smoke.py --model anthropic/claude-sonnet-4.5@bedrock
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gateway  # noqa: E402
from errors import GatewayError  # noqa: E402

DEFAULT_TARGETS = {
    "bedrock": "anthropic/claude-haiku-4.5@bedrock",
    "vertex": "google/gemini-2.5-flash@vertex",
}
PROMPT = [{"role": "user", "content": "Reply with exactly the word OK."}]


def bedrock_creds():
    region = os.getenv("BEDROCK_REGION")
    if not region:
        return None
    if os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
        return {"region": region, "api_key": os.environ["AWS_BEARER_TOKEN_BEDROCK"]}
    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        creds = {
            "region": region,
            "access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
            "secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
        }
        if os.getenv("AWS_SESSION_TOKEN"):
            creds["session_token"] = os.environ["AWS_SESSION_TOKEN"]
        return creds
    return None


def vertex_creds():
    project, region = os.getenv("VERTEX_PROJECT"), os.getenv("VERTEX_REGION")
    key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not (project and region and key_path):
        return None
    return {"project": project, "region": region,
            "service_account_json": Path(key_path).read_text()}


def run(target, creds):
    start = time.monotonic()
    try:
        result = gateway.call_target(target, PROMPT, creds, timeout=60)
    except GatewayError as e:
        print(f"FAIL  {target}: {e}")
        return False
    elapsed = time.monotonic() - start
    text = (result.get("text") or "").strip().replace("\n", " ")[:60]
    print(f"PASS  {target}: {elapsed:.2f}s, {result.get('input_tokens', 0)} in / "
          f"{result.get('output_tokens', 0)} out tokens, ${result.get('cost_usd', 0):.6f}, reply: {text!r}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("backends", nargs="*", help="bedrock and/or vertex (default: both)")
    parser.add_argument("--model", help="explicit target, e.g. anthropic/claude-sonnet-4.5@bedrock")
    args = parser.parse_args()
    unknown = [b for b in args.backends if b not in DEFAULT_TARGETS]
    if unknown:
        parser.error(f"unknown backend(s): {', '.join(unknown)}; choose from bedrock, vertex")

    creds = {"bedrock": bedrock_creds(), "vertex": vertex_creds()}
    if args.model:
        targets = [args.model]
    else:
        targets = [DEFAULT_TARGETS[b] for b in (args.backends or DEFAULT_TARGETS)]

    ok = True
    for target in targets:
        backend = target.rpartition("@")[2]
        if not creds.get(backend):
            print(f"SKIP  {target}: no {backend} credentials in the environment (see script docstring)")
            continue
        ok = run(target, {k: v for k, v in creds.items() if v}) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
