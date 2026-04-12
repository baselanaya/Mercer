"""Tests for TaxonomyCorrector — Stage 6 taxonomy-guided error correction."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from core.corrector import TaxonomyCorrector
from core.models import (
    ColumnSchema,
    CorrectionStep,
    ExecutionResult,
    FilteredSchema,
    SQLCandidate,
    TableSchema,
)
from core.utils import strip_fences as _strip_fences
from db.sandbox import ReadOnlySandbox

# ---------------------------------------------------------------------------
# SQLite fixture
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
            "INSERT INTO orders VALUES (1, 100.0, 'paid'), (2, 200.0, 'paid')"
        ))
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _schema() -> FilteredSchema:
    return FilteredSchema(
        tables=[
            TableSchema(
                name="orders",
                columns=[
                    ColumnSchema(name="id", type="INTEGER", is_primary_key=True),
                    ColumnSchema(name="amount", type="REAL"),
                    ColumnSchema(name="status", type="TEXT"),
                ],
            )
        ],
        join_paths=[],
    )


def _failed_candidate(
    sql: str = "SELECT nonexistent_col FROM orders",
    error: str = "no such column: nonexistent_col",
) -> SQLCandidate:
    return SQLCandidate(
        sql=sql,
        strategy="direct_cot",
        execution_result=ExecutionResult(
            success=False,
            sql=sql,
            row_count=0,
            columns=[],
            sample_rows=[],
            error_message=error,
        ),
    )


def _make_backend(return_values: list[str]) -> MagicMock:
    """Backend whose generate() returns values in sequence."""
    backend = MagicMock()
    backend._model = "mock-model"
    backend.generate = AsyncMock(side_effect=return_values)
    return backend


def _make_corrector(
    backend: MagicMock,
    engine: AsyncEngine,
) -> TaxonomyCorrector:
    return TaxonomyCorrector(
        llm_backend=backend,
        sandbox=ReadOnlySandbox(),
        engine=engine,
    )


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------

class TestClassifyError:
    def _corrector(self) -> TaxonomyCorrector:
        backend = MagicMock()
        engine: AsyncEngine = MagicMock()
        return TaxonomyCorrector(llm_backend=backend, sandbox=ReadOnlySandbox(), engine=engine)

    def test_schema_error_does_not_exist(self) -> None:
        c = self._corrector()
        assert c.classify_error('relation "foo" does not exist', "") == "schema_error"

    def test_schema_error_no_such_column(self) -> None:
        c = self._corrector()
        assert c.classify_error("no such column: foo", "") == "schema_error"

    def test_schema_error_no_such_table(self) -> None:
        c = self._corrector()
        assert c.classify_error("no such table: bar", "") == "schema_error"

    def test_syntax_error(self) -> None:
        c = self._corrector()
        assert c.classify_error("syntax error near 'FROM'", "") == "syntax_error"

    def test_parse_error(self) -> None:
        c = self._corrector()
        assert c.classify_error("parse error at line 1", "") == "syntax_error"

    def test_join_error(self) -> None:
        c = self._corrector()
        assert c.classify_error("invalid use of join expression", "") == "join_error"

    def test_foreign_key_error(self) -> None:
        c = self._corrector()
        assert c.classify_error("foreign key constraint violation", "") == "join_error"

    def test_aggregation_error_group_by(self) -> None:
        c = self._corrector()
        assert c.classify_error("column must appear in GROUP BY clause", "") == "aggregation_error"

    def test_aggregation_error_aggregate(self) -> None:
        c = self._corrector()
        assert c.classify_error("not in aggregate function or GROUP BY", "") == "aggregation_error"

    def test_filter_error_no_rows(self) -> None:
        c = self._corrector()
        assert c.classify_error("no rows returned by subquery", "") == "filter_error"

    def test_filter_error_empty_result(self) -> None:
        c = self._corrector()
        assert c.classify_error("empty result set", "") == "filter_error"

    def test_logic_error_default(self) -> None:
        c = self._corrector()
        assert c.classify_error("something completely unexpected happened", "") == "logic_error"

    def test_logic_error_unknown_message(self) -> None:
        c = self._corrector()
        assert c.classify_error("", "") == "logic_error"

    def test_sql_parameter_not_used_in_classification(self) -> None:
        """classify_error accepts sql param but doesn't use it — verify no crash."""
        c = self._corrector()
        assert c.classify_error("syntax error", "SELECT * FROM t") == "syntax_error"


# ---------------------------------------------------------------------------
# _strip_fences helper
# ---------------------------------------------------------------------------

def test_strip_fences_bare_sql() -> None:
    assert _strip_fences("SELECT 1") == "SELECT 1"


def test_strip_fences_sql_block() -> None:
    assert _strip_fences("```sql\nSELECT 1\n```") == "SELECT 1"


def test_strip_fences_plain_block() -> None:
    assert _strip_fences("```\nSELECT 1\n```") == "SELECT 1"


# ---------------------------------------------------------------------------
# correct() — success on first attempt
# ---------------------------------------------------------------------------

async def test_correct_succeeds_first_attempt(sqlite_engine: AsyncEngine) -> None:
    good_sql = "SELECT id FROM orders"
    backend = _make_backend([good_sql])
    corrector = _make_corrector(backend, sqlite_engine)

    result_sql, log = await corrector.correct(
        failed_candidate=_failed_candidate(),
        question="get order ids",
        filtered_schema=_schema(),
    )

    assert result_sql == good_sql
    assert len(log) == 1
    assert log[0].success is True
    assert log[0].iteration == 1


# ---------------------------------------------------------------------------
# correct() — success on second attempt
# ---------------------------------------------------------------------------

async def test_correct_succeeds_on_second_attempt(sqlite_engine: AsyncEngine) -> None:
    bad_sql = "SELECT still_bad FROM orders"
    good_sql = "SELECT amount FROM orders"
    backend = _make_backend([bad_sql, good_sql])
    corrector = _make_corrector(backend, sqlite_engine)

    result_sql, log = await corrector.correct(
        failed_candidate=_failed_candidate(),
        question="get amounts",
        filtered_schema=_schema(),
    )

    assert result_sql == good_sql
    assert len(log) == 2
    assert log[0].success is False
    assert log[1].success is True
    assert log[1].iteration == 2


# ---------------------------------------------------------------------------
# correct() — max_iterations respected
# ---------------------------------------------------------------------------

async def test_correct_exhausts_max_iterations(sqlite_engine: AsyncEngine) -> None:
    always_bad = "SELECT nonexistent FROM orders"
    backend = _make_backend([always_bad, always_bad, always_bad])
    corrector = _make_corrector(backend, sqlite_engine)

    result_sql, log = await corrector.correct(
        failed_candidate=_failed_candidate(),
        question="fail forever",
        filtered_schema=_schema(),
        max_iterations=3,
    )

    assert result_sql is None
    assert len(log) == 3
    assert all(step.success is False for step in log)


async def test_correct_respects_custom_max_iterations(sqlite_engine: AsyncEngine) -> None:
    always_bad = "SELECT nonexistent FROM orders"
    backend = _make_backend([always_bad, always_bad])
    corrector = _make_corrector(backend, sqlite_engine)

    _, log = await corrector.correct(
        failed_candidate=_failed_candidate(),
        question="fail forever",
        filtered_schema=_schema(),
        max_iterations=2,
    )

    assert len(log) == 2
    assert backend.generate.call_count == 2


# ---------------------------------------------------------------------------
# correct() — CorrectionStep fields
# ---------------------------------------------------------------------------

async def test_correction_step_has_correct_fields(sqlite_engine: AsyncEngine) -> None:
    good_sql = "SELECT id FROM orders"
    original_sql = "SELECT nonexistent_col FROM orders"
    backend = _make_backend([good_sql])
    corrector = _make_corrector(backend, sqlite_engine)

    _, log = await corrector.correct(
        failed_candidate=_failed_candidate(sql=original_sql, error="no such column: nonexistent_col"),
        question="get ids",
        filtered_schema=_schema(),
    )

    step: CorrectionStep = log[0]
    assert step.iteration == 1
    assert step.error_class == "schema_error"
    assert step.original_sql == original_sql
    assert step.corrected_sql == good_sql
    assert step.success is True


# ---------------------------------------------------------------------------
# correct() — candidate with no execution_result
# ---------------------------------------------------------------------------

async def test_correct_handles_missing_execution_result(sqlite_engine: AsyncEngine) -> None:
    """Candidate without execution_result should still attempt correction."""
    good_sql = "SELECT id FROM orders"
    backend = _make_backend([good_sql])
    corrector = _make_corrector(backend, sqlite_engine)

    bare_candidate = SQLCandidate(sql="SELECT bad FROM orders", strategy="direct_cot")

    result_sql, log = await corrector.correct(
        failed_candidate=bare_candidate,
        question="get ids",
        filtered_schema=_schema(),
    )

    assert result_sql == good_sql
    assert len(log) == 1
    assert log[0].success is True


# ---------------------------------------------------------------------------
# correct() — fenced SQL from LLM is stripped
# ---------------------------------------------------------------------------

async def test_correct_strips_fences_from_llm_output(sqlite_engine: AsyncEngine) -> None:
    fenced = "```sql\nSELECT id FROM orders\n```"
    backend = _make_backend([fenced])
    corrector = _make_corrector(backend, sqlite_engine)

    result_sql, log = await corrector.correct(
        failed_candidate=_failed_candidate(),
        question="get ids",
        filtered_schema=_schema(),
    )

    assert result_sql == "SELECT id FROM orders"
    assert log[0].corrected_sql == "SELECT id FROM orders"
    assert log[0].success is True


# ---------------------------------------------------------------------------
# correct() — error class propagates to step
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("error_msg,expected_class", [
    ("syntax error near SELECT", "syntax_error"),
    ("no such column: foo",      "schema_error"),
    ("invalid join expression",  "join_error"),
    ("GROUP BY required",        "aggregation_error"),
    ("no rows returned",         "filter_error"),
    ("unexpected behavior",      "logic_error"),
])
async def test_error_class_propagates_to_step(
    sqlite_engine: AsyncEngine,
    error_msg: str,
    expected_class: str,
) -> None:
    good_sql = "SELECT id FROM orders"
    backend = _make_backend([good_sql])
    corrector = _make_corrector(backend, sqlite_engine)

    _, log = await corrector.correct(
        failed_candidate=_failed_candidate(error=error_msg),
        question="get ids",
        filtered_schema=_schema(),
    )

    assert log[0].error_class == expected_class
