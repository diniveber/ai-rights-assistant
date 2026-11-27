"""LLM factory (OpenAI / OpenRouter) and structured calls with token & cost tracking."""

import os
import time

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from agent import config


class ConfigError(RuntimeError):
    """Missing or invalid configuration (e.g. API key)."""


class LLMOutputError(RuntimeError):
    """The model returned output that could not be parsed into the expected schema."""


_cache: dict[str, ChatOpenAI] = {}


def get_llm(model: str) -> ChatOpenAI:
    if model in _cache:
        return _cache[model]
    info = config.model_info(model)
    provider = config.PROVIDERS.get(info["provider"])
    if provider is None:
        raise ConfigError(f"ספק לא מוכר: {info['provider']}")
    api_key = os.getenv(provider["api_key_env"])
    if not api_key:
        raise ConfigError(f"{provider['api_key_env']} חסר בקובץ .env (נדרש למודל {model})")

    kwargs = {"model": model, "api_key": api_key, "timeout": 90, "max_retries": 2}
    if provider["base_url"]:
        kwargs["base_url"] = provider["base_url"]
    if info.get("reasoning_effort"):
        kwargs["reasoning_effort"] = info["reasoning_effort"]
    _cache[model] = ChatOpenAI(**kwargs)
    return _cache[model]


def structured_call(model: str, schema: type[BaseModel], messages: list, node: str):
    """Invoke the model with a structured-output schema.

    Returns (parsed_object, usage_record) where usage_record holds tokens, cost and latency for the node.
    """
    runnable = get_llm(model).with_structured_output(schema, method="json_schema", include_raw=True)
    start = time.perf_counter()
    out = runnable.invoke(messages, config={"run_name": node, "tags": [node, model]})
    latency = time.perf_counter() - start

    parsed = out.get("parsed")
    if parsed is None:
        raise LLMOutputError(f"המודל {model} החזיר פלט לא תקין בשלב {node}: {out.get('parsing_error')}")

    usage = getattr(out["raw"], "usage_metadata", None) or {}
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    actual, theoretical = config.costs(model, input_tokens, output_tokens)
    record = {
        "node": node,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": actual,
        "theoretical_cost": theoretical,
        "latency": round(latency, 2),
    }
    return parsed, record
