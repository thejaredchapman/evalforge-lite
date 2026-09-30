import json
import os
from pathlib import Path

JUDGE_MODELS = {
    "openrouter": os.environ.get("JUDGE_MODEL", "openai/gpt-4o-mini"),
    "bedrock": os.environ.get("BEDROCK_JUDGE_MODEL", "{geo}.anthropic.claude-haiku-4-5-20251001-v1:0"),
    "vertex": os.environ.get("VERTEX_JUDGE_MODEL", "google/gemini-2.5-flash"),
    "foundry": os.environ.get("FOUNDRY_JUDGE_MODEL", "gpt-4o-mini"),
}
JUDGE_MODEL = JUDGE_MODELS["openrouter"]
MAX_MODELS = 4

_DATA_DIR = Path(__file__).parent / "data"
_PROVIDERS_PATH = _DATA_DIR / "providers.json"
_REGIONS_PATH = _DATA_DIR / "regions.json"


def load_providers():
    with open(_PROVIDERS_PATH) as f:
        return json.load(f)


def load_regions():
    with open(_REGIONS_PATH) as f:
        return json.load(f)
