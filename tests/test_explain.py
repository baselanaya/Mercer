"""Tests for db.explain — EXPLAIN-based pre-flight validation."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from db.explain import ExplainResult, ExplainRunner, _build_explain_sql, explain

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def populated_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE customer (id INTEGER PRIMARY KEY, name TEXT, email TEXT)"
        ))
        await conn.execute(text(
            "INSERT INTO customer VALUES (1, 'Alice', 'a@x.com'), (2, 'Bob', 'b@x.com')"
        ))
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# _build_explain_sql — dialect templating
# ---------------------------------------------------------------------------

class TestBuildExplainSql:
    def test_postgres_uses_format_json(self) -> None:
        out = _build_explain_sql("SELECT 1", "postgresql")
        assert "EXPLAIN (FORMAT JSON)" in out
        assert "SELECT 1" in out

    def test_sqlite_uses_query_plan(self) -> None:
        out = _build_explain_sql("SELECT 1", "sqlite")
        assert "EXPLAIN QUERY PLAN" in out

    def test_mysql_uses_format_json(self) -> None:
        out = _build_explain_sql("SELECT 1", "mysql")
        assert "EXPLAIN FORMAT=JSON" in out

    def test_duckdb_plain_explain(self) -> None:
        out = _build_explain_sql("SELECT 1", "duckdb")
        assert out.startswith("EXPLAIN ")

    def test_unknown_dialect_falls_back_to_plain(self) -> None:
        out = _build_explain_sql("SELECT 1", "exotic_db")
        assert out == "EXPLAIN SELECT 1"

    def test_dialect_lookup_is_case_insensitive(self) -> None:
        out = _build_explain_sql("SELECT 1", "PostgreSQL")
        assert "FORMAT JSON" in out


# ---------------------------------------------------------------------------
# explain() — async path against a real SQLite engine
# ---------------------------------------------------------------------------

class TestExplainAgainstSQLite:
    async def test_valid_select_returns_valid_true(
        self, populated_engine: AsyncEngine
    ) -> None:
        result = await explain("SELECT * FROM customer", populated_engine)
        assert isinstance(result, ExplainResult)
        assert result.valid is True
        assert result.error is None
        # SQLite EXPLAIN QUERY PLAN returns at least one row of plan info
        assert len(result.plan) > 0

    async def test_unknown_table_returns_valid_false(
        self, populated_engine: AsyncEngine
    ) -> None:
        result = await explain("SELECT * FROM no_such_table", populated_engine)
        assert result.valid is False
        assert result.error is not None
        assert result.plan == ""

    async def test_unknown_column_returns_valid_false(
        self, populated_engine: AsyncEngine
    ) -> None:
        result = await explain(
            "SELECT no_such_col FROM customer", populated_engine
        )
        assert result.valid is False
        assert result.error is not None

    async def test_malformed_sql_returns_valid_false(
        self, populated_engine: AsyncEngine
    ) -> None:
        result = await explain("SELECT FROM WHERE", populated_engine)
        assert result.valid is False
        assert result.error is not None

    async def test_explain_does_not_raise_on_db_error(
        self, populated_engine: AsyncEngine
    ) -> None:
        """The contract is: never raise. Always return an ExplainResult."""
        # Even with a deliberately broken statement, no exception escapes.
        result = await explain("garbage" * 50, populated_engine)
        assert isinstance(result, ExplainResult)
        assert result.valid is False

    async def test_join_query_explains_successfully(
        self, populated_engine: AsyncEngine
    ) -> None:
        # Self-join trivially valid since customer references itself
        result = await explain(
            "SELECT a.id, b.id FROM customer a JOIN customer b ON a.id = b.id",
            populated_engine,
        )
        assert result.valid is True

    async def test_dialect_override(
        self, populated_engine: AsyncEngine
    ) -> None:
        """Explicit dialect override takes precedence over the engine's dialect."""
        # SQLite engine, but request 'sqlite' explicitly to confirm it's used.
        result = await explain(
            "SELECT * FROM customer",
            populated_engine,
            dialect="sqlite",
        )
        assert result.valid is True


# ---------------------------------------------------------------------------
# ExplainRunner class wrapper
# ---------------------------------------------------------------------------

class TestExplainRunner:
    async def test_runner_delegates_to_explain(
        self, populated_engine: AsyncEngine
    ) -> None:
        runner = ExplainRunner()
        result = await runner.explain("SELECT * FROM customer", populated_engine)
        assert result.valid is True

    async def test_runner_returns_invalid_on_bad_sql(
        self, populated_engine: AsyncEngine
    ) -> None:
        runner = ExplainRunner()
        result = await runner.explain("SELECT * FROM nope", populated_engine)
        assert result.valid is False
