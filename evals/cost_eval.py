"""Eval 2 – cost.

Runs common user tasks and reports the cost of every graph step (node) and the total,
as tokens × model pricing. For free models, the actual cost (0) is shown next to the
theoretical cost at the paid-equivalent price.
Output: results/cost_eval.csv (per node + per task totals) + results/cost_eval_summary.csv (per model).

Usage:  python evals/cost_eval.py [--models m1 m2 ...]
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.common import print_table, run_case, setup_console, usage_totals, write_csv  # noqa: E402
from evals.dataset import COMMON_TASKS  # noqa: E402

from agent import config  # noqa: E402


def main() -> int:
    setup_console()
    parser = argparse.ArgumentParser(description="Eval: cost per step and total")
    parser.add_argument("--models", nargs="+", default=config.EVAL_MODELS)
    args = parser.parse_args()

    rows, summaries = [], []
    for model in args.models:
        print(f"▶ {model}")
        model_usage = []
        errors = 0
        for task in COMMON_TASKS:
            run = run_case(task["steps"], model)
            errors += bool(run["error"])
            for u in run["usage"]:
                rows.append({
                    "model": model, "task_id": task["id"], "task": task["name"], "step": u["node"],
                    "input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"],
                    "latency_s": u["latency"], "cost": round(u["cost"], 6),
                    "theoretical_cost": round(u["theoretical_cost"], 6), "error": "",
                })
            totals = usage_totals(run["usage"])
            rows.append({
                "model": model, "task_id": task["id"], "task": task["name"], "step": "TOTAL",
                **totals, "latency_s": run["latency"], "error": run["error"],
            })
            model_usage += run["usage"]
            flag = f"  ERROR {run['error']}" if run["error"] else ""
            print(f"   {task['id']:<26} ${totals['cost']:.5f}  (theoretical ${totals['theoretical_cost']:.5f}){flag}")

        # cost by node across all tasks
        by_node = defaultdict(lambda: {"calls": 0, "cost": 0.0, "theoretical_cost": 0.0})
        for u in model_usage:
            by_node[u["node"]]["calls"] += 1
            by_node[u["node"]]["cost"] += u["cost"]
            by_node[u["node"]]["theoretical_cost"] += u["theoretical_cost"]
        print("   by node: " + ", ".join(f"{n}=${v['cost']:.5f}" for n, v in by_node.items()))

        t = usage_totals(model_usage)
        n = len(COMMON_TASKS)
        summaries.append({
            "model": model,
            "provider": config.model_info(model)["provider"],
            "price_in_per_1m": config.model_info(model)["input"],
            "price_out_per_1m": config.model_info(model)["output"],
            "tasks": n,
            "errors": errors,
            "llm_calls": len(model_usage),
            **t,
            "avg_cost_per_task": round(t["cost"] / n, 6),
            "avg_theoretical_cost_per_task": round(t["theoretical_cost"] / n, 6),
            "est_cost_per_1000_tasks": round(t["cost"] / n * 1000, 2),
            "est_theoretical_cost_per_1000_tasks": round(t["theoretical_cost"] / n * 1000, 2),
        })

    grand = {
        "model": "ALL", "tasks": sum(s["tasks"] for s in summaries),
        "llm_calls": sum(s["llm_calls"] for s in summaries),
        "cost": round(sum(s["cost"] for s in summaries), 6),
        "theoretical_cost": round(sum(s["theoretical_cost"] for s in summaries), 6),
    }
    detail = write_csv("cost_eval.csv", rows)
    summary = write_csv("cost_eval_summary.csv", summaries + [grand])
    print("\n=== Cost summary ===")
    print_table(summaries + [grand], ["model", "tasks", "llm_calls", "input_tokens", "output_tokens", "cost",
                                      "theoretical_cost", "avg_cost_per_task", "est_cost_per_1000_tasks"])
    print(f"\nTotal eval cost (actual): ${grand['cost']:.5f}")
    print(f"Saved: {detail}\n       {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
