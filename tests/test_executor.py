"""Tests for CandidateExecutor — Stage 5 parallel execution and scoring."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from core.executor import CandidateExecutor, _consistency, _pick_best_failed
from core.models import ExecutionResult, SQLCandidate
from db.sandbox import ReadOnlySandbox

# ---------------------------------------------------------------------------
# SQLite engine fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
async def sqlite_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL, status TEXT)"
        ))
        await conn.execute(text(
            "INSERT INTO orders VALUES (1, 100.0, 'paid'), (2, 200.0, 'paid'), (3, 50.0, 'pending')"
        ))
    yield engine
    await engine.dispose()


@pytest.fixture()
def executor(sqlite_engine: AsyncEngine) -> CandidateExecutor:
    return CandidateExecutor(ReadOnlySandbox(), sqlite_engine)


# ---------------------------------------------------------------------------
# Candidate helpers
# ---------------------------------------------------------------------------

def _candidate(sql: str, strategy: str = "direct_cot") -> SQLCandidate:
    return SQLCandidate(sql=sql, strategy=strategy)


def _result(
    *,
    success: bool,
    columns: list[str] | None = None,
    row_count: int = 0,
) -> ExecutionResult:
    return ExecutionResult(
        success=success,
        sql="SELECT 1",
        row_count=row_count,
        columns=columns or [],
        sample_rows=[],
        error_message=None if success else "syntax error",
    )


# ---------------------------------------------------------------------------
# execute_all
# ---------------------------------------------------------------------------

async def test_execute_all_populates_results(
    executor: CandidateExecutor,
) -> None:
    candidates = [_candidate("SELECT id FROM orders")]
    results = await executor.execute_all(candidates)
    assert results[0].execution_result is not None


async def test_execute_all_valid_sql_succeeds(
    executor: CandidateExecutor,
) -> None:
    candidates = [_candidate("SELECT id FROM orders")]
    results = await executor.execute_all(candidates)
    assert results[0].execution_result is not None
    assert results[0].execution_result.success is True


async def test_execute_all_invalid_sql_fails(
    executor: CandidateExecutor,
) -> None:
    candidates = [_candidate("NOT VALID SQL AT ALL")]
    results = await executor.execute_all(candidates)
    assert results[0].execution_result is not None
    assert results[0].execution_result.success is False


async def test_execute_all_empty_sql_fails(
    executor: CandidateExecutor,
) -> None:
    candidates = [_candidate("")]
    results = await executor.execute_all(candidates)
    assert results[0].execution_result is not None
    assert results[0].execution_result.success is False
    assert results[0].execution_result.error_message == "empty SQL"


async def test_execute_all_parallel_three(
    executor: CandidateExecutor,
) -> None:
    candidates = [
        _candidate("SELECT id FROM orders", "direct_cot"),
        _candidate("SELECT amount FROM orders", "divide_conquer"),
        _candidate("SELECT status FROM orders", "plan_execute"),
    ]
    results = await executor.execute_all(candidates)
    assert len(results) == 3
    assert all(r.execution_result is not None for r in results)


async def test_execute_all_preserves_strategy(
    executor: CandidateExecutor,
) -> None:
    candidates = [
        _candidate("SELECT id FROM orders", "divide_conquer"),
    ]
    results = await executor.execute_all(candidates)
    assert results[0].strategy == "divide_conquer"


# ---------------------------------------------------------------------------
# score_candidate
# ---------------------------------------------------------------------------

def test_score_failed_candidate_is_zero(executor: CandidateExecutor) -> None:
    c = SQLCandidate(sql="bad", strategy="s", execution_result=_result(success=False))
    score = executor.score_candidate(c, [c.execution_result])  # type: ignore[list-item]
    assert score == 0.0


def test_score_success_empty_result(executor: CandidateExecutor) -> None:
    c = SQLCandidate(
        sql="s", strategy="s",
        execution_result=_result(success=True, columns=["id"], row_count=0),
    )
    score = executor.score_candidate(c, [c.execution_result])  # type: ignore[list-item]
    # syntax=0.5, empty=0.0, consistency=1.0*0.3=0.3 → 0.8
    assert abs(score - 0.8) < 1e-9


def test_score_success_non_empty(executor: CandidateExecutor) -> None:
    r = _result(success=True, columns=["id"], row_count=5)
    c = SQLCandidate(sql="s", strategy="s", execution_result=r)
    score = executor.score_candidate(c, [r])
    # syntax=0.5, empty=0.2*0.5=0.1 (wait: 0.5*0.5+0.5*0.2+1.0*0.3 = 0.25+0.1+0.3 = 0.65)
    # Rubric: syntax_score*0.5 + empty_score*0.2 + consistency_score*0.3
    # syntax_score=1.0 → 0.5; empty_score=0.5 → 0.5*0.2=0.1; consistency=1.0 → 0.3 → total=0.9
    assert abs(score - 0.9) < 1e-9


def test_score_valid_non_empty_beats_valid_empty(executor: CandidateExecutor) -> None:
    r_full = _result(success=True, columns=["id"], row_count=3)
    r_empty = _result(success=True, columns=["id"], row_count=0)
    c_full = SQLCandidate(sql="s", strategy="s", execution_result=r_full)
    c_empty = SQLCandidate(sql="s", strategy="s", execution_result=r_empty)
    all_results = [r_full, r_empty]
    assert executor.score_candidate(c_full, all_results) > executor.score_candidate(c_empty, all_results)


def test_score_valid_beats_invalid(executor: CandidateExecutor) -> None:
    r_ok = _result(success=True, columns=["id"], row_count=1)
    r_fail = _result(success=False)
    c_ok = SQLCandidate(sql="s", strategy="s", execution_result=r_ok)
    c_fail = SQLCandidate(sql="s", strategy="s", execution_result=r_fail)
    all_results = [r_ok, r_fail]
    assert executor.score_candidate(c_ok, all_results) > executor.score_candidate(c_fail, all_results)


def test_score_consistency_higher_when_columns_agree(executor: CandidateExecutor) -> None:
    r1 = _result(success=True, columns=["id", "name"], row_count=1)
    r2 = _result(success=True, columns=["id", "name"], row_count=1)   # agrees
    r3 = _result(success=True, columns=["amount"], row_count=1)        # disagrees
    c1 = SQLCandidate(sql="s", strategy="s", execution_result=r1)
    c3 = SQLCandidate(sql="s", strategy="s", execution_result=r3)
    all_results = [r1, r2, r3]
    assert executor.score_candidate(c1, all_results) > executor.score_candidate(c3, all_results)


def test_score_none_execution_result_is_zero(executor: CandidateExecutor) -> None:
    c = SQLCandidate(sql="s", strategy="s")
    assert executor.score_candidate(c, []) == 0.0


# ---------------------------------------------------------------------------
# select_best / execute_and_score
# ---------------------------------------------------------------------------

async def test_select_best_returns_valid_candidate(
    executor: CandidateExecutor,
) -> None:
    candidates = [
        _candidate("SELECT id FROM orders", "direct_cot"),
        _candidate("NOT VALID SQL", "divide_conquer"),
    ]
    best = await executor.select_best(candidates)
    assert best is not None
    assert best.strategy == "direct_cot"
    assert best.execution_result is not None
    assert best.execution_result.success is True


async def test_select_best_returns_none_for_empty_list(
    executor: CandidateExecutor,
) -> None:
    assert await executor.select_best([]) is None


async def test_select_best_valid_non_empty_beats_valid_empty(
    executor: CandidateExecutor,
) -> None:
    candidates = [
        # Will succeed with rows
        _candidate("SELECT id FROM orders", "divide_conquer"),
        # Will succeed but return empty
        _candidate("SELECT id FROM orders WHERE id = 9999", "plan_execute"),
    ]
    best = await executor.select_best(candidates)
    assert best is not None
    assert best.strategy == "divide_conquer"


async def test_select_best_all_failed_returns_direct_cot(
    executor: CandidateExecutor,
) -> None:
    candidates = [
        _candidate("BAD SQL 1", "divide_conquer"),
        _candidate("BAD SQL 2", "direct_cot"),
        _candidate("BAD SQL 3", "plan_execute"),
    ]
    best = await executor.select_best(candidates)
    assert best is not None
    assert best.strategy == "direct_cot"


async def test_select_best_all_failed_fallback_to_first_if_no_direct_cot(
    executor: CandidateExecutor,
) -> None:
    candidates = [
        _candidate("BAD SQL 1", "divide_conquer"),
        _candidate("BAD SQL 2", "plan_execute"),
    ]
    best = await executor.select_best(candidates)
    assert best is not None
    assert best.strategy == "divide_conquer"


async def test_execute_and_score_populates_scores(
    executor: CandidateExecutor,
) -> None:
    candidates = [
        _candidate("SELECT id FROM orders", "direct_cot"),
        _candidate("NOT VALID", "divide_conquer"),
    ]
    scored = await executor.execute_and_score(candidates)
    assert len(scored) == 2
    valid = next(c for c in scored if c.strategy == "direct_cot")
    invalid = next(c for c in scored if c.strategy == "divide_conquer")
    assert valid.score > invalid.score


# ---------------------------------------------------------------------------
# _consistency helper
# ---------------------------------------------------------------------------

def test_consistency_only_successful_result_is_full() -> None:
    r = _result(success=True, columns=["a", "b"])
    assert _consistency(r, [r]) == 1.0


def test_consistency_all_agree() -> None:
    r1 = _result(success=True, columns=["a"])
    r2 = _result(success=True, columns=["a"])
    assert _consistency(r1, [r1, r2]) == 1.0


def test_consistency_no_agreement() -> None:
    r1 = _result(success=True, columns=["a"])
    r2 = _result(success=True, columns=["b"])
    assert _consistency(r1, [r1, r2]) == 0.0


def test_consistency_failed_result_is_zero() -> None:
    r = _result(success=False)
    assert _consistency(r, [r]) == 0.0


def test_consistency_partial_agreement() -> None:
    r1 = _result(success=True, columns=["a"])
    r2 = _result(success=True, columns=["a"])
    r3 = _result(success=True, columns=["b"])
    # r1 agrees with r2 but not r3 → 1/2
    assert abs(_consistency(r1, [r1, r2, r3]) - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# _pick_best_failed helper
# ---------------------------------------------------------------------------

def test_pick_best_failed_prefers_direct_cot() -> None:
    candidates = [
        SQLCandidate(sql="s", strategy="plan_execute"),
        SQLCandidate(sql="s", strategy="direct_cot"),
        SQLCandidate(sql="s", strategy="divide_conquer"),
    ]
    assert _pick_best_failed(candidates).strategy == "direct_cot"


def test_pick_best_failed_returns_first_when_no_direct_cot() -> None:
    candidates = [
        SQLCandidate(sql="s", strategy="plan_execute"),
        SQLCandidate(sql="s", strategy="divide_conquer"),
    ]
    assert _pick_best_failed(candidates).strategy == "plan_execute"
