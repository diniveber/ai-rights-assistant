"""Central configuration: providers, models, pricing."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> Path | None:
    """Load .env from the working dir, next to the exe (frozen build), or the project root."""
    candidates = [Path.cwd() / ".env"]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / ".env")
    candidates.append(Path(__file__).resolve().parent.parent / ".env")
    for path in candidates:
        if path.is_file():
            load_dotenv(path)
            return path
    return None


ENV_FILE = _load_env()

PROVIDERS = {
    "openai": {"base_url": None, "api_key_env": "OPENAI_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"},
}

# Prices in USD per 1M tokens. Verify against the providers' pricing pages:
#   https://developers.openai.com/api/docs/pricing · https://openrouter.ai/models
# Free models have actual price 0; ref_* is the paid-equivalent price used for theoretical cost.
MODELS = {
    "gpt-5.4-nano": {"provider": "openai", "input": 0.20, "output": 1.25, "reasoning_effort": "low"},
    "gpt-5.4-mini": {"provider": "openai", "input": 0.75, "output": 4.50, "reasoning_effort": "low"},
    "nvidia/nemotron-3.5-super-vl:free": {
        "provider": "openrouter", "input": 0.0, "output": 0.0, "ref_input": 0.15, "ref_output": 0.47,
    },
    # Judge only – deliberately not one of the compared models, to avoid self-preference bias
    "gpt-5.4": {"provider": "openai", "input": 2.50, "output": 15.00, "reasoning_effort": "low"},
}

DEFAULT_MODELS = {"openai": "gpt-5.4-mini", "openrouter": "nvidia/nemotron-3.5-super-vl:free"}

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
DEFAULT_MODEL = os.getenv("RIGHTS_MODEL") or DEFAULT_MODELS.get(LLM_PROVIDER, "gpt-5.4-mini")

# Evals: models compared, and a single fixed judge model for all comparisons
EVAL_MODELS = ["gpt-5.4-nano", "gpt-5.4-mini", "nvidia/nemotron-3.5-super-vl:free"]
JUDGE_MODEL = "gpt-5.4"

MAX_DRAFT_ATTEMPTS = 2   # draft → evaluator → redraft at most once
MAX_FOLLOWUP_ROUNDS = 2  # after this many follow-up rounds, answer with what we have
MAX_FILE_CHARS = 8000


def model_info(model: str) -> dict:
    """Settings for a model; unknown models get a provider guess and zero pricing."""
    if model in MODELS:
        return MODELS[model]
    return {"provider": "openrouter" if "/" in model else LLM_PROVIDER, "input": 0.0, "output": 0.0}


def costs(model: str, input_tokens: int, output_tokens: int) -> tuple[float, float]:
    """Return (actual_cost, theoretical_cost) in USD. They differ only for free models."""
    info = model_info(model)
    actual = (input_tokens * info["input"] + output_tokens * info["output"]) / 1_000_000
    ref_in = info.get("ref_input", info["input"])
    ref_out = info.get("ref_output", info["output"])
    theoretical = (input_tokens * ref_in + output_tokens * ref_out) / 1_000_000
    return actual, theoretical
