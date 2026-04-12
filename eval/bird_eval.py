"""BIRD benchmark evaluator.

Evaluates Mercer against the BIRD Mini-Dev dataset.

NOTE: The BIRD dataset must be downloaded manually before use.
      Download instructions: https://bird-bench.github.io
      After downloading, pass the JSON file path via ``load_dataset(path)``.

BIRD JSON format (list of objects):
  {
    "question_id": 1,
    "question":    "How many singers are there?",
    "SQL":         "SELECT count(*) FROM singer",
    "db_id":       "concert_singer",
    ...
  }

Usage:
    evaluator = BIRDEvaluator()
    questions = evaluator.load_dataset("/path/to/dev.json")
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


class BIRDEvaluator:
    """Evaluate Mercer against the BIRD Text-to-SQL benchmark.

    Assumes the pipeline is already configured with an engine pointing at the
    BIRD database (or a target database containing the relevant tables).
    """

    def load_dataset(self, path: str) -> list[dict[str, Any]]:
        """Load a BIRD JSON dataset file.

        Args:
            path: Path to the BIRD dev.json (or train/test) file.

        Returns:
            List of question dicts, each containing at minimum
            ``question_id``, ``question``, and ``SQL``.

        Raises:
            FileNotFoundError: if ``path`` does not exist.
            ValueError:        if the file is not a JSON list.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"BIRD dataset not found at {path}.\n"
                "Download BIRD Mini-Dev from https://bird-bench.github.io "
                "and pass the path via --dataset-path."
            )
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(
                f"Expected a JSON list in {path}; got {type(data).__name__}. "
                "Check that you are using the correct BIRD JSON format."
            )
        return data

    async def run(
        self,
        pipeline: MercerPipeline,
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run every question through the pipeline and compute eval metrics.

        Metrics computed:
          - ``execution_accuracy``: fraction of predictions that execute
            successfully and return the correct result set.
          - ``reward_based_ves``: average Reward-based Valid Efficiency Score
            (soft_f1 with a 2× wall-time penalty).

        Args:
            pipeline:  A fully configured MercerPipeline instance (with the
                       BIRD target DB connected).
            questions: Question dicts loaded via ``load_dataset()``.

        Returns:
            Summary dict:
              {
                "execution_accuracy": float,
                "reward_based_ves":   float,
                "total":              int,
                "passed":             int,
                "per_question":       list[dict],
              }
        """
        per_question: list[dict[str, Any]] = []

        for entry in questions:
            qid = entry.get("question_id", entry.get("id", "?"))
            question: str = entry["question"]
            gold_sql: str = entry.get("SQL", entry.get("expected_sql", ""))

            t0 = time.monotonic()
            try:
                state = await pipeline.run(question)
                latency_ms = round((time.monotonic() - t0) * 1000, 2)

                predicted_sql = state.final_sql or (
                    state.best_candidate.sql if state.best_candidate else ""
                )
                exec_success = bool(state.final_sql)

                # VES requires both queries and the engine
                ves_score = 0.0
                if exec_success and gold_sql:
                    try:
                        ves_score = await reward_based_ves(
                            predicted_sql, gold_sql, pipeline._engine
                        )
                    except Exception:  # noqa: BLE001
                        ves_score = 0.0

                per_question.append({
                    "id": qid,
                    "question": question,
                    "success": exec_success,
                    "predicted_sql": predicted_sql,
                    "gold_sql": gold_sql,
                    "ves_score": ves_score,
                    "latency_ms": latency_ms,
                })

            except Exception as exc:  # noqa: BLE001
                latency_ms = round((time.monotonic() - t0) * 1000, 2)
                per_question.append({
                    "id": qid,
                    "question": question,
                    "success": False,
                    "predicted_sql": None,
                    "gold_sql": gold_sql,
                    "ves_score": 0.0,
                    "error": str(exc),
                    "latency_ms": latency_ms,
                })

        total = len(per_question)
        passed = sum(1 for r in per_question if r["success"])
        avg_ves = (
            sum(r["ves_score"] for r in per_question) / total if total else 0.0
        )

        return {
            "execution_accuracy": passed / total if total else 0.0,
            "reward_based_ves": avg_ves,
            "total": total,
            "passed": passed,
            "per_question": per_question,
        }
