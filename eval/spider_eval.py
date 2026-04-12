"""Spider 2.0 benchmark evaluator.

Evaluates Mercer against the Spider 2.0 dataset, which focuses on
enterprise-scale, workflow-style SQL including multi-step queries,
CTEs, window functions, and cross-database joins.

NOTE: The Spider 2.0 dataset must be downloaded manually before use.
      Repository: https://github.com/xlang-ai/Spider2
      After downloading, pass the JSON file path via ``load_dataset(path)``.

Spider 2.0 JSON format (list of objects):
  {
    "instance_id": "local_1",
    "question":    "How many rows are in the table?",
    "SQL":         "SELECT COUNT(*) FROM my_table",
    "db_id":       "my_database",
    "difficulty":  "simple"
  }

Usage:
    evaluator = SpiderEvaluator()
    questions = evaluator.load_dataset("/path/to/spider2_dev.json")
    results = asyncio.run(evaluator.run(pipeline, questions))
    print(results["execution_accuracy"])
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pipeline import MercerPipeline
from eval.metrics import reward_based_ves


class SpiderEvaluator:
    """Evaluate Mercer against the Spider 2.0 Text-to-SQL benchmark.

    Spider 2.0 emphasises real-world enterprise SQL: complex JOINs, CTEs,
    window functions, and multi-step analytical queries. Target EX > 20%.

    Assumes the pipeline is already configured with an engine pointing at the
    Spider 2.0 database for the questions being evaluated.
    """

    def load_dataset(
        self,
        path: str,
        difficulty: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Load a Spider 2.0 JSON dataset file.

        Args:
            path:       Path to the Spider 2.0 dev/test JSON file.
            difficulty: Optional filter — "simple", "moderate", or "challenging".
                        Pass None to include all difficulties.
            limit:      Optional cap on the number of questions loaded.

        Returns:
            List of question dicts, each containing at minimum
            ``instance_id``, ``question``, and ``SQL``.

        Raises:
            FileNotFoundError: if ``path`` does not exist.
            ValueError:        if the file is not a JSON list.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"Spider 2.0 dataset not found at {path}.\n"
                "Clone the Spider 2.0 repository from https://github.com/xlang-ai/Spider2 "
                "and pass the path to the dev JSON file."
            )
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(
                f"Expected a JSON list in {path}; got {type(data).__name__}. "
                "Check that you are using the Spider 2.0 JSON format."
            )

        if difficulty is not None:
            data = [q for q in data if q.get("difficulty", "").lower() == difficulty.lower()]

        if limit is not None:
            data = data[:limit]

        return data

    async def run(
        self,
        pipeline: MercerPipeline,
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run every question through the pipeline and compute eval metrics.

        Metrics computed:
          - ``execution_accuracy``:  fraction of predictions that execute
            successfully and return the correct result set.
          - ``reward_based_ves``:    average Reward-based Valid Efficiency Score
            (soft_f1 with a 2× wall-time penalty).
          - ``by_difficulty``:       breakdown of EX by difficulty level.

        Args:
            pipeline:  A fully configured MercerPipeline instance.
            questions: Question dicts loaded via ``load_dataset()``.

        Returns:
            Summary dict:
              {
                "execution_accuracy": float,
                "reward_based_ves":   float,
                "total":              int,
                "passed":             int,
                "by_difficulty":      dict[str, dict],
                "per_question":       list[dict],
              }
        """
        per_question: list[dict[str, Any]] = []

        for entry in questions:
            instance_id = entry.get("instance_id", entry.get("id", "?"))
            question: str = entry["question"]
            gold_sql: str = entry.get("SQL", entry.get("query", entry.get("expected_sql", "")))
            difficulty: str = entry.get("difficulty", "unknown")

            t0 = time.monotonic()
            try:
                state = await pipeline.run(question)
                latency_ms = round((time.monotonic() - t0) * 1000, 2)

                predicted_sql = state.final_sql or (
                    state.best_candidate.sql if state.best_candidate else ""
                )
                exec_success = bool(state.final_sql)

                ves_score = 0.0
                if exec_success and gold_sql:
                    try:
                        ves_score = await reward_based_ves(
                            predicted_sql, gold_sql, pipeline._engine
                        )
                    except Exception:  # noqa: BLE001
                        ves_score = 0.0

                per_question.append({
                    "id": instance_id,
                    "question": question,
                    "difficulty": difficulty,
                    "success": exec_success,
                    "predicted_sql": predicted_sql,
                    "gold_sql": gold_sql,
                    "ves_score": ves_score,
                    "latency_ms": latency_ms,
                    "correction_steps": len(state.correction_log),
                })

            except Exception as exc:  # noqa: BLE001
                latency_ms = round((time.monotonic() - t0) * 1000, 2)
                per_question.append({
                    "id": instance_id,
                    "question": question,
                    "difficulty": difficulty,
                    "success": False,
                    "predicted_sql": None,
                    "gold_sql": gold_sql,
                    "ves_score": 0.0,
                    "error": str(exc),
                    "latency_ms": latency_ms,
                    "correction_steps": 0,
                })

        total = len(per_question)
        passed = sum(1 for r in per_question if r["success"])
        avg_ves = sum(r["ves_score"] for r in per_question) / total if total else 0.0

        # Breakdown by difficulty
        by_difficulty: dict[str, dict[str, Any]] = {}
        for r in per_question:
            d = r["difficulty"]
            if d not in by_difficulty:
                by_difficulty[d] = {"total": 0, "passed": 0}
            by_difficulty[d]["total"] += 1
            by_difficulty[d]["passed"] += int(r["success"])
        for stats in by_difficulty.values():
            t = stats["total"]
            stats["execution_accuracy"] = stats["passed"] / t if t else 0.0

        return {
            "execution_accuracy": passed / total if total else 0.0,
            "reward_based_ves": avg_ves,
            "total": total,
            "passed": passed,
            "by_difficulty": by_difficulty,
            "per_question": per_question,
        }

    def print_summary(self, results: dict[str, Any]) -> None:
        """Print a human-readable summary of evaluation results."""
        total = results["total"]
        passed = results["passed"]
        ex = results["execution_accuracy"]
        ves = results["reward_based_ves"]

        print("\nSpider 2.0 Evaluation Results")
        print("=" * 50)
        print(f"Execution Accuracy : {passed}/{total} = {ex:.1%}")
        print(f"Reward-based VES   : {ves:.3f}")

        by_diff = results.get("by_difficulty", {})
        if by_diff:
            print("\nBreakdown by difficulty:")
            for diff, stats in sorted(by_diff.items()):
                t = stats["total"]
                p = stats["passed"]
                acc = stats["execution_accuracy"]
                print(f"  {diff:<12} {p}/{t} = {acc:.1%}")

        # Show failures
        failures = [r for r in results["per_question"] if not r["success"]]
        if failures:
            print(f"\nFailed questions ({len(failures)}):")
            for r in failures[:10]:
                print(f"  [{r['id']}] {r['question'][:80]}")
                if "error" in r:
                    print(f"           Error: {r['error'][:80]}")
            if len(failures) > 10:
                print(f"  ... and {len(failures) - 10} more")
        print()
