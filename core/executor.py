"""Stage 5 — Parallel candidate execution and scoring.

CandidateExecutor runs all SQL candidates concurrently, scores each one on
three dimensions, and returns the highest-scoring candidate for the pipeline.

Scoring rubric (total = 1.0):
  syntax_score      0.5  — 1.0 if execution succeeded, 0.0 otherwise
  empty_score       0.2  — 0.5 if result has at least one row, 0.0 otherwise
  consistency_score 0.3  — fraction of other successful results that share
                           the same column names (agreement signal)
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from core.logging import get_logger
from core.models import ExecutionResult, SQLCandidate
from db.sandbox import ReadOnlySandbox
from kernels.result_score import get_result_scorer

# Module-level scorer — CPU or GPU depending on hardware
_scorer = get_result_scorer()

logger = get_logger(__name__)

_DIRECT_COT = "direct_cot"


class CandidateExecutor:
    """Execute candidates in parallel and pick the best one."""

    def __init__(self, sandbox: ReadOnlySandbox, engine: AsyncEngine) -> None:
        self._sandbox = sandbox
        self._engine = engine

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def execute_all(
        self, candidates: list[SQLCandidate]
    ) -> list[SQLCandidate]:
        """Run all candidates through the sandbox in parallel.

        Returns a new list of SQLCandidates with execution_result populated.
        Candidates whose SQL is empty or blank are marked failed immediately
        without hitting the sandbox.
        """
        async def _run(candidate: SQLCandidate) -> SQLCandidate:
            if not candidate.sql.strip():
                result = ExecutionResult(
                    success=False,
                    sql=candidate.sql,
                    row_count=0,
                    columns=[],
                    sample_rows=[],
                    error_message="empty SQL",
                )
                return candidate.model_copy(update={"execution_result": result})
            try:
                result = await self._sandbox.execute(candidate.sql, self._engine)
            except Exception as exc:  # noqa: BLE001
                result = ExecutionResult(
                    success=False,
                    sql=candidate.sql,
                    row_count=0,
                    columns=[],
                    sample_rows=[],
                    error_message=str(exc),
                )
            return candidate.model_copy(update={"execution_result": result})

        executed: list[SQLCandidate] = list(
            await asyncio.gather(*(_run(c) for c in candidates))
        )
        return executed

    def score_candidate(
        self,
        candidate: SQLCandidate,
        all_results: list[ExecutionResult],
    ) -> float:
        """Score a candidate on syntax, result non-emptiness, and cross-candidate consistency.

        Args:
            candidate:   The candidate to score (must have execution_result set).
            all_results: execution_results of *all* candidates in this generation
                         (used to compute the consistency signal).

        Returns:
            Float score in [0.0, 1.0].
        """
        result = candidate.execution_result
        if result is None:
            return 0.0

        # Component 1 — syntax / execution success
        syntax_score = 1.0 if result.success else 0.0

        # Component 2 — result non-emptiness
        empty_score = 0.5 if result.row_count > 0 else 0.0

        # Component 3 — column-name agreement with other successful results
        consistency_score = _consistency(result, all_results)

        final = syntax_score * 0.5 + empty_score * 0.2 + consistency_score * 0.3
        logger.debug(
            "candidate_scored",
            strategy=candidate.strategy,
            syntax=syntax_score,
            empty=empty_score,
            consistency=consistency_score,
            final=round(final, 4),
        )
        return final

    async def execute_and_score(
        self, candidates: list[SQLCandidate]
    ) -> list[SQLCandidate]:
        """Execute all candidates and populate their scores. Returns scored list."""
        executed = await self.execute_all(candidates)
        all_results = [
            c.execution_result for c in executed if c.execution_result is not None
        ]
        return [
            c.model_copy(update={"score": self.score_candidate(c, all_results)})
            for c in executed
        ]

    async def select_best(
        self, candidates: list[SQLCandidate]
    ) -> SQLCandidate | None:
        """Execute, score, and return the highest-scoring candidate.

        Tie-break rule: when scores are equal, the 'direct_cot' strategy wins.

        If every candidate fails execution (all syntax_score == 0), the
        candidate with the most informative error message is returned to give
        the downstream corrector the best starting point.

        Returns None only when the input list is empty.
        """
        if not candidates:
            return None

        scored = await self.execute_and_score(candidates)
        successful = [c for c in scored if c.execution_result and c.execution_result.success]

        if not successful:
            # All failed — return best for correction (prefer direct_cot, else first)
            logger.warning(
                "all_candidates_failed",
                strategies=[c.strategy for c in scored],
            )
            return _pick_best_failed(scored)

        # Among successful: highest score, tie-break by direct_cot preference
        winner = max(successful, key=lambda c: (c.score, c.strategy == _DIRECT_COT))
        logger.info(
            "best_candidate_selected",
            strategy=winner.strategy,
            score=round(winner.score, 4),
            total_candidates=len(scored),
            successful=len(successful),
        )
        return winner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result_to_row_list(result: ExecutionResult) -> list[dict[str, Any]]:
    """Convert an ExecutionResult to a list of row dicts for the kernel scorer.

    Uses sample_rows when available; falls back to a pseudo-row built from
    the column list so the scorer can still see the column schema.
    """
    if result.sample_rows:
        return result.sample_rows
    if result.columns:
        return [{c: None for c in result.columns}]
    return []


def _consistency(
    result: ExecutionResult,
    all_results: list[ExecutionResult],
) -> float:
    """Mean Jaccard similarity of this result's column set vs all other successful results.

    Uses kernels.result_score scorer for consistency with the GPU execution path.
    """
    if not result.success:
        return 0.0

    successful = [r for r in all_results if r.success]
    if len(successful) <= 1:
        # Only one successful result (ours) — full consistency by default
        return 1.0

    our_idx = next((i for i, r in enumerate(successful) if r is result), None)
    if our_idx is None:
        return 1.0

    result_sets = [_result_to_row_list(r) for r in successful]
    scores = _scorer(result_sets)
    return scores[our_idx]


def _pick_best_failed(candidates: list[SQLCandidate]) -> SQLCandidate:
    """Among all-failed candidates, prefer direct_cot; otherwise return first."""
    for c in candidates:
        if c.strategy == _DIRECT_COT:
            return c
    return candidates[0]
