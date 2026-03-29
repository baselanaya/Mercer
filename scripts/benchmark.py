"""benchmark.py — CLI benchmark runner.

Usage:
    # Self-contained regression run (in-memory SQLite + mock LLM, no DB needed)
    python scripts/benchmark.py --suite regression

    # Regression against a real database
    python scripts/benchmark.py --suite regression --db-url sqlite+aiosqlite:///data/dvdrental.db

    # Messy-schema suite (in-memory SQLite + mock LLM)
    python scripts/benchmark.py --suite mercer_messy

    # BIRD suite (requires manual dataset download)
    python scripts/benchmark.py --suite bird

    # Per-stage latency breakdown (20 queries, P50/P95/P99 table)
    python scripts/benchmark.py --suite regression --mode latency

Options:
    --suite        regression | bird | mercer_messy  (default: regression)
    --mode         default | latency  (default: default)
    --db-url       SQLAlchemy async DB URL (optional; omit to use in-memory mock)
    --redis-url    Redis URL for schema cache (default: redis://localhost:6379)
    --dataset-path Path to BIRD JSON file (required for --suite bird)
    --output       stdout | json  (default: stdout)
    --output-file  File path for JSON output (default: benchmark_results.json)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import create_async_engine

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pipeline import MercerPipeline

_LATENCY_RUNS = 20  # number of query runs for latency profiling

# ---------------------------------------------------------------------------
# Suite runners
# ---------------------------------------------------------------------------

async def _run_regression(db_url: str | None, redis_url: str) -> list[dict[str, Any]]:
    """Run the DVDRental baseline regression suite.

    If ``db_url`` is None, uses an in-memory SQLite DB + mock LLM
    (no external services required).
    """
    from eval import regression_suite

    if db_url is None:
        return await regression_suite.run_mock()

    # Real-DB path
    queries_path = Path(__file__).parent.parent / "data" / "test_queries" / "dvdrental_baseline.yaml"
    data: dict[str, Any] = yaml.safe_load(queries_path.read_text(encoding="utf-8"))
    queries = list(data["queries"])

    engine = create_async_engine(db_url, echo=False)
    pipeline = MercerPipeline(db_engine=engine, redis_url=redis_url)

    import time
    results: list[dict[str, Any]] = []
    for entry in queries:
        qid: str = entry["id"]
        question: str = entry["question"]
        t0 = time.monotonic()
        try:
            state = await pipeline.run(question)
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            success = bool(state.final_sql)
            results.append({
                "id": qid,
                "question": question,
                "success": success,
                "predicted_sql": state.final_sql or (
                    state.best_candidate.sql if state.best_candidate else None
                ),
                "latency_ms": latency_ms,
            })
        except Exception as exc:  # noqa: BLE001
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            results.append({
                "id": qid, "question": question, "success": False,
                "predicted_sql": None, "error": str(exc), "latency_ms": latency_ms,
            })

    await engine.dispose()
    return results


async def _run_messy(db_url: str | None, redis_url: str) -> list[dict[str, Any]]:
    """Run the messy-schema evaluation suite.

    If ``db_url`` is None, uses an in-memory SQLite DB + mock LLM.
    """
    from eval.messy_schema_eval import MessySchemaEvaluator

    evaluator = MessySchemaEvaluator()

    if db_url is None:
        return await evaluator.run_mock()

    # Real-DB path
    engine = create_async_engine(db_url, echo=False)
    pipeline = MercerPipeline(db_engine=engine, redis_url=redis_url)
    questions = evaluator.load_dataset()
    summary = await evaluator.run(pipeline, questions)
    await engine.dispose()
    return summary["per_question"]


# ---------------------------------------------------------------------------
# Latency profiling
# ---------------------------------------------------------------------------

async def _run_latency(suite: str) -> None:
    """Run ``_LATENCY_RUNS`` queries, collect per-stage timings, print percentiles."""
    import math

    from eval import regression_suite as _rsuite

    # Collect enough pipeline runs (repeat the query set to reach _LATENCY_RUNS)
    all_timings: list[dict[str, float]] = []
    engine = await _rsuite._make_mock_engine()
    queries = _rsuite._load_queries()

    run_count = 0
    while run_count < _LATENCY_RUNS:
        for entry in queries:
            if run_count >= _LATENCY_RUNS:
                break
            qid: str = entry["id"]
            sql = _rsuite._SQLITE_SQL[qid]
            pipeline = _rsuite._make_mock_pipeline(engine, sql)
            try:
                state = await pipeline.run(entry["question"])
                if state.stage_timings:
                    all_timings.append(state.stage_timings)
            except Exception:  # noqa: BLE001
                pass
            run_count += 1

    await engine.dispose()

    if not all_timings:
        print("No timing data collected.")
        return

    # Collect all stage names seen across runs
    stage_names = list(dict.fromkeys(k for t in all_timings for k in t))

    def _percentile(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = (len(sorted_vals) - 1) * p / 100.0
        lo, hi = int(math.floor(idx)), int(math.ceil(idx))
        return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)

    # Print table
    col_w = 22
    num_w = 9
    header = f"{'Stage':<{col_w}}{'P50 ms':>{num_w}}{'P95 ms':>{num_w}}{'P99 ms':>{num_w}}"
    sep = "-" * len(header)
    print(f"\nLatency breakdown ({len(all_timings)} runs, suite={suite})")
    print(sep)
    print(header)
    print(sep)
    total_p50 = total_p95 = total_p99 = 0.0
    for stage in stage_names:
        vals = [t[stage] for t in all_timings if stage in t]
        p50 = _percentile(vals, 50)
        p95 = _percentile(vals, 95)
        p99 = _percentile(vals, 99)
        total_p50 += p50
        total_p95 += p95
        total_p99 += p99
        print(f"  {stage:<{col_w - 2}}{p50:>{num_w}.2f}{p95:>{num_w}.2f}{p99:>{num_w}.2f}")
    print(sep)
    print(f"  {'TOTAL':<{col_w - 2}}{total_p50:>{num_w}.2f}{total_p95:>{num_w}.2f}{total_p99:>{num_w}.2f}")
    print()


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _print_stdout(suite: str, results: list[dict[str, Any]]) -> None:
    passed = sum(1 for r in results if r["success"])
    total = len(results)
    print(f"Suite: {suite}  ({passed}/{total} passed)")
    print("-" * 60)
    for r in results:
        status = "PASS" if r["success"] else "FAIL"
        latency = r.get("latency_ms", 0)
        print(f"  {status}  [{r['id']}]  {r['question']}  ({latency:.0f} ms)")
        if not r["success"]:
            err = r.get("error") or r.get("predicted_sql") or ""
            print(f"         {str(err)[:120]}")
    print("-" * 60)
    accuracy = passed / total if total else 0.0
    avg_ms = sum(r.get("latency_ms", 0) for r in results) / total if total else 0.0
    print(f"Accuracy: {accuracy:.1%}  Avg latency: {avg_ms:.0f} ms")


def _write_json(
    results: list[dict[str, Any]],
    suite: str,
    output_file: str,
) -> None:
    passed = sum(1 for r in results if r["success"])
    total = len(results)
    output: dict[str, Any] = {
        "suite": suite,
        "total": total,
        "passed": passed,
        "accuracy": passed / total if total else 0.0,
        "results": results,
    }
    Path(output_file).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Results written to {output_file}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _print_report(audit_path: str) -> None:
    """Read AuditStore and print aggregate metrics."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from db.audit_store import AuditStore

    store = AuditStore(audit_path)
    m = await store.aggregate()

    if m.get("total_queries", 0) == 0:
        print(f"No audit records found at: {audit_path}")
        return

    col = 26
    num = 12
    sep = "-" * (col + num * 2)

    print(f"\nAudit Report  ({audit_path})")
    print(sep)
    print(f"  {'Total queries':<{col}}{m['total_queries']:>{num}}")
    print(f"  {'Success rate':<{col}}{m['success_rate']:>{num}.1%}")
    print(f"  {'Correction rate':<{col}}{m['correction_rate']:>{num}.1%}")
    print(sep)
    print(f"  {'Latency avg (ms)':<{col}}{m['avg_latency_ms']:>{num}.1f}")
    print(f"  {'Latency P50 (ms)':<{col}}{m['p50_ms']:>{num}.1f}")
    print(f"  {'Latency P95 (ms)':<{col}}{m['p95_ms']:>{num}.1f}")
    print(f"  {'Latency P99 (ms)':<{col}}{m['p99_ms']:>{num}.1f}")

    if m.get("top_error_classes"):
        print(sep)
        print(f"  {'Top error classes':<{col}}")
        for item in m["top_error_classes"]:
            print(f"    {item['class']:<{col - 2}}{item['count']:>{num}}")

    print(sep)
    print()


async def _main(args: argparse.Namespace) -> int:
    suite: str = args.suite
    mode: str = getattr(args, "mode", "default")

    # Report mode — read AuditStore and print aggregate metrics
    if getattr(args, "report", False):
        audit_path: str = getattr(args, "audit_path", "logs/audit.duckdb")
        await _print_report(audit_path)
        return 0

    # Latency mode — instrument pipeline stages and print percentile table
    if mode == "latency":
        await _run_latency(suite)
        return 0

    if suite == "bird":
        dataset_path: str | None = getattr(args, "dataset_path", None)
        if not dataset_path:
            print(
                "Download BIRD Mini-Dev from https://bird-bench.github.io "
                "and pass --dataset-path /path/to/dev.json"
            )
            return 0
        # Real BIRD run
        from eval.bird_eval import BIRDEvaluator
        engine = create_async_engine(args.db_url, echo=False)
        pipeline = MercerPipeline(
            db_engine=engine, redis_url=args.redis_url
        )
        evaluator = BIRDEvaluator()
        questions = evaluator.load_dataset(dataset_path)
        summary = await evaluator.run(pipeline, questions)
        await engine.dispose()
        results = summary["per_question"]
        if args.output == "json":
            _write_json(results, suite, args.output_file)
        else:
            _print_stdout(suite, results)
            print(f"Reward-based VES: {summary['reward_based_ves']:.3f}")
        return 0 if summary["execution_accuracy"] >= 0.8 else 1

    if suite == "regression":
        results = await _run_regression(args.db_url, args.redis_url)
    elif suite == "mercer_messy":
        results = await _run_messy(args.db_url, args.redis_url)
    else:
        print(f"Unknown suite: {suite}")
        return 1

    if args.output == "json":
        _write_json(results, suite, args.output_file)
    else:
        _print_stdout(suite, results)

    passed = sum(1 for r in results if r["success"])
    return 0 if passed == len(results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Mercer benchmark runner")
    parser.add_argument(
        "--suite",
        choices=["regression", "bird", "mercer_messy"],
        default="regression",
        help="Benchmark suite to run (default: regression)",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help=(
            "SQLAlchemy async DB URL. "
            "Omit for regression/mercer_messy to use in-memory mock mode."
        ),
    )
    parser.add_argument(
        "--redis-url",
        default="redis://localhost:6379",
        help="Redis URL for schema cache (default: redis://localhost:6379)",
    )
    parser.add_argument(
        "--dataset-path",
        default=None,
        help="Path to BIRD JSON dataset file (required for --suite bird)",
    )
    parser.add_argument(
        "--mode",
        choices=["default", "latency"],
        default="default",
        help="Run mode: 'default' (accuracy) or 'latency' (per-stage P50/P95/P99 table)",
    )
    parser.add_argument(
        "--output",
        choices=["stdout", "json"],
        default="stdout",
        help="Output format (default: stdout)",
    )
    parser.add_argument(
        "--output-file",
        default="benchmark_results.json",
        help="File path for JSON output (default: benchmark_results.json)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print aggregate metrics from the audit store and exit",
    )
    parser.add_argument(
        "--audit-path",
        default="logs/audit.duckdb",
        help="Path to audit DuckDB file (used with --report, default: logs/audit.duckdb)",
    )
    args = parser.parse_args()

    if args.suite == "bird" and not args.db_url and not args.dataset_path:
        # No args at all for BIRD → just print instructions
        print(
            "Download BIRD Mini-Dev from https://bird-bench.github.io "
            "and pass --dataset-path /path/to/dev.json"
        )
        sys.exit(0)

    exit_code = asyncio.run(_main(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
