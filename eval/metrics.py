"""Evaluation metrics for the Mercer Text-to-SQL pipeline.

execution_accuracy    — compare predicted vs gold SQL by executing both and
                        checking result-set equality.
schema_linking_recall — fraction of gold tables/columns present in a
                        FilteredSchema.
soft_f1_score         — order-insensitive F1 on sets of result rows.
reward_based_ves      — execute both queries, score with soft_f1, penalise
                        when predicted is >2× slower than gold.
"""

from __future__ import annotations

import time

from sqlalchemy.ext.asyncio import AsyncEngine

from core.models import FilteredSchema
from db.sandbox import ReadOnlySandbox


async def execution_accuracy(
    results: list[tuple[str, str, AsyncEngine]],
) -> float:
    """Execute (predicted_sql, gold_sql) pairs and return the exact-match fraction.

    A pair is counted as correct when both queries succeed and their result sets
    are identical (same rows in the same order, case-insensitive column names).

    Args:
        results: List of (predicted_sql, gold_sql, engine) triples.

    Returns:
        Float in [0, 1]. Empty list → 1.0 (vacuously perfect).
    """
    if not results:
        return 1.0

    sandbox = ReadOnlySandbox()
    correct = 0

    for predicted_sql, gold_sql, engine in results:
        pred_result = await sandbox.execute(predicted_sql, engine)
        gold_result = await sandbox.execute(gold_sql, engine)

        if not pred_result.success or not gold_result.success:
            continue

        if _result_sets_equal(pred_result.sample_rows, gold_result.sample_rows):
            correct += 1

    return correct / len(results)


def schema_linking_recall(
    predicted: FilteredSchema,
    gold_tables: list[str],
    gold_columns: list[str],
) -> float:
    """Fraction of gold tables + columns present in the predicted FilteredSchema.

    Tables are matched by name (case-insensitive).
    Columns are matched by "table.column" pairs (case-insensitive) OR bare
    column name when the gold list contains unqualified names.

    Args:
        predicted:    FilteredSchema produced by the schema linker.
        gold_tables:  List of table names that the gold SQL touches.
        gold_columns: List of "table.column" or bare "column" names needed.

    Returns:
        Float in [0, 1]. Empty gold sets → 1.0.
    """
    total = len(gold_tables) + len(gold_columns)
    if total == 0:
        return 1.0

    pred_table_names = {t.name.lower() for t in predicted.tables}
    pred_col_pairs: set[str] = set()
    pred_col_bare: set[str] = set()
    for t in predicted.tables:
        for c in t.columns:
            pred_col_pairs.add(f"{t.name.lower()}.{c.name.lower()}")
            pred_col_bare.add(c.name.lower())

    hits = 0
    for tbl in gold_tables:
        if tbl.lower() in pred_table_names:
            hits += 1

    for col in gold_columns:
        col_lower = col.lower()
        if col_lower in pred_col_pairs or col_lower in pred_col_bare:
            hits += 1

    return hits / total


def soft_f1_score(
    predicted_rows: list[dict[str, object]],
    gold_rows: list[dict[str, object]],
) -> float:
    """Compute F1 on result row sets (order-insensitive, value-level).

    Rows are normalised (lowercase keys, stringified values) and matched as
    a multiset.  Duplicate rows count separately.

    Args:
        predicted_rows: Rows returned by the predicted SQL query.
        gold_rows:      Rows returned by the gold SQL query.

    Returns:
        Float in [0, 1].  Both empty → 1.0.  One empty → 0.0.

    Note:
        The sandbox returns at most ``SAMPLE_ROWS`` (3) rows in
        ``ExecutionResult.sample_rows``.  When result sets are larger than 3
        rows this metric is an approximation.  Pass the full row lists when
        available for exact scoring.
    """
    if not predicted_rows and not gold_rows:
        return 1.0
    if not predicted_rows or not gold_rows:
        return 0.0

    pred_norm = [_normalise_row(r) for r in predicted_rows]
    gold_norm = [_normalise_row(r) for r in gold_rows]

    # Multiset intersection: consume each gold row at most once
    gold_remaining = list(gold_norm)
    matched = 0
    for row in pred_norm:
        if row in gold_remaining:
            gold_remaining.remove(row)
            matched += 1

    precision = matched / len(pred_norm)
    recall = matched / len(gold_norm)

    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


async def reward_based_ves(
    predicted_sql: str,
    gold_sql: str,
    engine: AsyncEngine,
) -> float:
    """Execute both queries, score with soft_f1, penalise slow predictions.

    The Reward-based Valid Efficiency Score (VES) is:
      - 0.0  if either query fails to execute.
      - soft_f1_score(predicted_rows, gold_rows) normally.
      - score × 0.5  if the predicted query takes >2× the gold query's wall time.

    Args:
        predicted_sql: The SQL generated by the pipeline.
        gold_sql:      The reference (gold) SQL.
        engine:        Async SQLAlchemy engine for execution.

    Returns:
        Float in [0, 1].
    """
    sandbox = ReadOnlySandbox()

    t0 = time.monotonic()
    pred_result = await sandbox.execute(predicted_sql, engine)
    pred_time = time.monotonic() - t0

    t1 = time.monotonic()
    gold_result = await sandbox.execute(gold_sql, engine)
    gold_time = time.monotonic() - t1

    if not pred_result.success or not gold_result.success:
        return 0.0

    score = soft_f1_score(pred_result.sample_rows, gold_result.sample_rows)

    # Efficiency penalty: >2× slower than gold
    if gold_time > 0 and pred_time > 2.0 * gold_time:
        score *= 0.5

    return score


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_row(row: dict[str, object]) -> dict[str, str]:
    """Normalise a result row: lowercase keys, stringify values."""
    return {k.lower(): str(v) for k, v in row.items()}


def _result_sets_equal(
    a: list[dict[str, object]],
    b: list[dict[str, object]],
) -> bool:
    """Return True if both row lists are equal after normalisation."""
    if len(a) != len(b):
        return False
    return [_normalise_row(r) for r in a] == [_normalise_row(r) for r in b]
