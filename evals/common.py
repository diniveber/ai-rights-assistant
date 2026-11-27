"""Shared helpers for the eval scripts: run cases through the graph, parallelism, CSV output."""

import csv
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config  # noqa: E402  (loads .env)

# Keep eval traces apart from interactive runs in LangSmith
os.environ["LANGSMITH_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "ai-rights-assistant") + "-evals"

from langchain_core.messages import HumanMessage  # noqa: E402

from agent.graph import build_graph, run_turn  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"
REFUSAL_DECISIONS = {"out_of_scope", "fraud", "injection"}


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")


def is_free(model: str) -> bool:
    info = config.model_info(model)
    return info["input"] == 0 and info["output"] == 0


def to_payload(step) -> dict:
    return {"command": "chat", "messages": [HumanMessage(step)]} if isinstance(step, str) else dict(step)


def run_case(steps: list, model: str) -> dict:
    """Run one case (one or more user steps) in a fresh conversation. HITL requests are auto-approved."""
    app = build_graph()
    thread_id = f"eval-{uuid.uuid4()}"
    usage: list[dict] = []
    path: list[str] = []
    values: dict = {}
    start = time.perf_counter()
    try:
        for step in steps:
            path = []
            values, step_usage = run_turn(app, thread_id, to_payload(step), model,
                                          on_node=path.append, approve=lambda _req: True)
            usage += step_usage
        error = ""
    except Exception as e:  # noqa: BLE001 – record the failure and keep evaluating
        error = f"{type(e).__name__}: {str(e)[:200]}"
    return {
        "values": values,
        "usage": usage,
        "latency": round(time.perf_counter() - start, 2),
        "path": " > ".join(dict.fromkeys(path)),  # unique, ordered
        "error": error,
    }


def usage_totals(usage: list[dict]) -> dict:
    return {
        "input_tokens": sum(u["input_tokens"] for u in usage),
        "output_tokens": sum(u["output_tokens"] for u in usage),
        "cost": round(sum(u["cost"] for u in usage), 6),
        "theoretical_cost": round(sum(u["theoretical_cost"] for u in usage), 6),
    }


def parallel_map(fn, items: list, model: str) -> list:
    """Run fn over items; serial for free models (rate limits), 4 workers otherwise. Keeps order."""
    workers = 1 if is_free(model) else 4
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


def write_csv(name: str, rows: list[dict]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel shows Hebrew correctly
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def merge_existing(name: str, rows: list[dict]) -> list[dict]:
    """Keep the rows of other models already in results/<name>; replace only the models in `rows`.
    Lets one model be re-run (e.g. a free model after its daily cap resets) without losing the others."""
    path = RESULTS_DIR / name
    if not path.is_file():
        return rows
    new_models = {r["model"] for r in rows}
    with path.open(newline="", encoding="utf-8-sig") as f:
        kept = [r for r in csv.DictReader(f) if r["model"] not in new_models]
    order = {m: i for i, m in enumerate(config.EVAL_MODELS)}
    return sorted(kept + rows, key=lambda r: order.get(r["model"], len(order)))


def print_table(rows: list[dict], columns: list[str]) -> None:
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    print("  ".join("-" * widths[c] for c in columns))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in columns))
