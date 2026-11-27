"""Eval 1 – model comparison.

Runs the same rights questions on each model and compares:
  time (measured), answer quality and data reliability (LLM-as-judge, rubric.md),
  data quality (precision / recall / F1 of the rights identified vs. the labelled rights).
Output: results/compare_models.csv (per question) + results/compare_models_summary.csv (per model).

Usage:  python evals/compare_models.py [--models m1 m2 ...] [--limit N] [--free-limit N]
"""

import argparse
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.common import is_free, merge_existing, parallel_map, print_table, run_case, setup_console, usage_totals, write_csv  # noqa: E402
from evals.dataset import IN_SCOPE  # noqa: E402
from evals.judge import CRITERIA, judge  # noqa: E402

from agent import config  # noqa: E402


def rights_metrics(predicted: list[str], expected: list[str], acceptable: list[str]) -> dict:
    """Precision: share of predicted rights that are correct (expected or acceptable).
    Recall: share of expected (core) rights that were found."""
    correct = set(expected) | set(acceptable)
    hits = [r for r in predicted if r in correct]
    precision = len(hits) / len(predicted) if predicted else 0.0
    recall = len(set(predicted) & set(expected)) / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 2), "recall": round(recall, 2), "f1": round(f1, 2)}


def evaluate(case: dict, model: str) -> dict:
    run = run_case([case["question"]], model)
    values = run["values"]
    predicted = [s["id"] for s in values.get("sources", [])]
    answer = values.get("output", "")
    row = {
        "model": model,
        "case_id": case["id"],
        "question": case["question"],
        "latency_s": run["latency"],
        **usage_totals(run["usage"]),
        "path": run["path"],
        "expected_ids": " ".join(case["expected"]),
        "predicted_ids": " ".join(predicted),
        **rights_metrics(predicted, case["expected"], case["acceptable"]),
    }
    judge_cost = 0.0
    if run["error"] or not answer:
        row["error"] = run["error"] or "empty answer"
    else:
        try:
            scores, judge_usage = judge(case["question"], answer, predicted, case["expected"])
            row.update(scores)
            judge_cost = judge_usage["cost"]
        except Exception as e:  # noqa: BLE001
            row["error"] = f"judge: {type(e).__name__}: {str(e)[:150]}"
        row.setdefault("error", "")
    row["judge_cost"] = round(judge_cost, 6)
    row["answer"] = answer
    return row


def summarize(model: str, rows: list[dict]) -> dict:
    ok = [r for r in rows if not r["error"]]

    def avg(key: str) -> float | str:
        vals = [r[key] for r in ok if isinstance(r.get(key), (int, float))]
        return round(mean(vals), 2) if vals else ""

    summary = {
        "model": model,
        "provider": config.model_info(model)["provider"],
        "questions": len(rows),
        "errors": len(rows) - len(ok),
        "avg_latency_s": avg("latency_s"),
        "quality_judge_overall": avg("judge_overall"),
        **{f"judge_{c}": avg(c) for c in CRITERIA},
        "data_quality_f1": avg("f1"),
        "precision": avg("precision"),
        "recall": avg("recall"),
        "avg_cost_per_question": round(mean(r["cost"] for r in rows), 6) if rows else 0,
        "avg_theoretical_cost": round(mean(r["theoretical_cost"] for r in rows), 6) if rows else 0,
        "judge_cost_total": round(sum(r["judge_cost"] for r in rows), 6),
    }
    return summary


def main() -> int:
    setup_console()
    parser = argparse.ArgumentParser(description="Eval: model comparison (LLM-as-judge)")
    parser.add_argument("--models", nargs="+", default=config.EVAL_MODELS)
    parser.add_argument("--limit", type=int, help="number of questions per model")
    parser.add_argument("--free-limit", type=int, default=6,
                        help="questions for free models (OpenRouter free tier has a daily request cap)")
    parser.add_argument("--merge", action="store_true",
                        help="keep other models' rows in the existing CSVs; replace only the models run now")
    args = parser.parse_args()

    print(f"Judge model (fixed): {config.JUDGE_MODEL}\n")
    all_rows, summaries = [], []
    for model in args.models:
        limit = args.free_limit if is_free(model) else args.limit
        cases = IN_SCOPE[:limit] if limit else IN_SCOPE
        print(f"▶ {model}: {len(cases)} questions...")
        rows = parallel_map(lambda case: evaluate(case, model), cases, model)
        for r in rows:
            status = f"ERROR {r['error']}" if r["error"] else f"judge={r.get('judge_overall')} f1={r['f1']}"
            print(f"   {r['case_id']:<22} {r['latency_s']:>6.1f}s  {status}")
        all_rows += rows
        summaries.append(summarize(model, rows))

    if args.merge:
        all_rows = merge_existing("compare_models.csv", all_rows)
        summaries = merge_existing("compare_models_summary.csv", summaries)
    detail = write_csv("compare_models.csv", all_rows)
    summary = write_csv("compare_models_summary.csv", summaries)
    print("\n=== Model comparison ===")
    print_table(summaries, ["model", "questions", "errors", "avg_latency_s", "quality_judge_overall",
                            "judge_reliability", "data_quality_f1", "avg_cost_per_question", "avg_theoretical_cost"])
    print(f"\nSaved: {detail}\n       {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
