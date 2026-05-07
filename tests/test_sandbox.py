"""Tests for ReadOnlySandbox.

All tests use SQLite in-memory via aiosqlite — no PostgreSQL required.

The sandbox uses sqlglot AST validation, not keyword-grep, so the test
matrix focuses on:
  - DDL/DML rejection across statement types and dialects
  - Statement-chaining rejection ("SELECT 1; DROP TABLE x")
  - String-literal false-positive avoidance ("SELECT ... LIKE '%DROP%'")
  - Comment-injection avoidance
  - WITH ... SELECT acceptance
  - UNION acceptance
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from db.sandbox import (
    MAX_ROWS,
    SAMPLE_ROWS,
    ReadOnlySandbox,
    SecurityViolation,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Bare in-memory SQLite engine (no pre-created tables)."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    yield eng
    await eng.dispose()


@pytest.fixture
async def populated_engine() -> AsyncGenerator[AsyncEngine, None]:
    """In-memory SQLite with a 'numbers' table containing 200 rows."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE numbers (id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
        ))
        await conn.execute(
            text("INSERT INTO numbers (id, label) VALUES (:id, :label)"),
            [{"id": i, "label": f"row_{i}"} for i in range(200)],
        )
    yield eng
    await eng.dispose()


@pytest.fixture
async def schema_engine() -> AsyncGenerator[AsyncEngine, None]:
    """In-memory SQLite with a simple customer table for column tests."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE customer ("
            "  customer_id INTEGER PRIMARY KEY,"
            "  name TEXT NOT NULL,"
            "  email TEXT,"
            "  notes TEXT"
            ")"
        ))
        await conn.execute(
            text("INSERT INTO customer (customer_id, name, email, notes) "
                 "VALUES (:id, :name, :email, :notes)"),
            [
                {"id": 1, "name": "Alice", "email": "alice@example.com",
                 "notes": "please don't DROP my data"},
                {"id": 2, "name": "Bob", "email": "bob@example.com",
                 "notes": "CREATE your own design"},
            ],
        )
    yield eng
    await eng.dispose()


sandbox = ReadOnlySandbox()


# ---------------------------------------------------------------------------
# Forbidden statement-type rejection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "INSERT INTO customer (name) VALUES ('x')",
    "UPDATE customer SET name = 'x' WHERE customer_id = 1",
    "DELETE FROM customer WHERE customer_id = 1",
    "DROP TABLE customer",
    "CREATE TABLE foo (id INTEGER)",
    "ALTER TABLE customer ADD COLUMN x TEXT",
    "TRUNCATE TABLE customer",
])
async def test_ddl_dml_rejected(sql: str, engine: AsyncEngine) -> None:
    """DDL and DML statements at the top level must be rejected."""
    with pytest.raises(SecurityViolation):
        await sandbox.execute(sql, engine)


@pytest.mark.parametrize("sql", [
    "insert into customer (name) values ('x')",
    "DROP table customer",
    "Update customer Set name = 'x'",
])
async def test_case_insensitive_rejection(sql: str, engine: AsyncEngine) -> None:
    """Case variations must still be rejected — sqlglot is case-insensitive."""
    with pytest.raises(SecurityViolation):
        await sandbox.execute(sql, engine)


# ---------------------------------------------------------------------------
# Statement-chaining rejection
# ---------------------------------------------------------------------------

async def test_multi_statement_rejected(engine: AsyncEngine) -> None:
    """SQL containing more than one top-level statement must be rejected."""
    with pytest.raises(SecurityViolation, match="single statement"):
        await sandbox.execute(
            "SELECT 1; DROP TABLE customer", engine
        )


async def test_two_selects_rejected(engine: AsyncEngine) -> None:
    """Even chaining two SELECTs is rejected — one statement per call."""
    with pytest.raises(SecurityViolation, match="single statement"):
        await sandbox.execute("SELECT 1; SELECT 2", engine)


async def test_trailing_semicolon_allowed(engine: AsyncEngine) -> None:
    """A single statement with a trailing semicolon parses as one statement."""
    result = await sandbox.execute("SELECT 1;", engine)
    assert result.success


# ---------------------------------------------------------------------------
# String-literal false-positive avoidance (the original-bug regression)
# ---------------------------------------------------------------------------

async def test_blocked_keyword_in_string_literal_allowed(
    schema_engine: AsyncEngine,
) -> None:
    """A blocked keyword inside a string literal must NOT trigger rejection."""
    # The 'notes' column contains the literal "please don't DROP my data".
    # Old keyword-grep sandbox would reject this query as containing DROP.
    result = await sandbox.execute(
        "SELECT customer_id FROM customer WHERE notes LIKE '%DROP%'",
        schema_engine,
    )
    assert result.success, "AST validator must accept DROP inside a string literal"
    assert result.row_count == 1


async def test_blocked_keyword_in_column_name_allowed(
    engine: AsyncEngine,
) -> None:
    """A column or alias named like a keyword (e.g. 'create_date') is allowed."""
    result = await sandbox.execute(
        "SELECT create_date FROM nonexistent", engine
    )
    assert not result.success  # execution failure
    assert result.error_message is not None  # but not a SecurityViolation


async def test_blocked_keyword_in_alias_allowed(engine: AsyncEngine) -> None:
    result = await sandbox.execute(
        "SELECT 1 AS drop_count", engine
    )
    assert result.success


# ---------------------------------------------------------------------------
# Comment-injection avoidance
# ---------------------------------------------------------------------------

async def test_block_comment_with_ddl_inside_subquery_rejected(
    engine: AsyncEngine,
) -> None:
    """A DROP inside a subquery is still found by AST walk."""
    sql = "SELECT (DROP TABLE foo) FROM customer"
    with pytest.raises(SecurityViolation):
        await sandbox.execute(sql, engine)


async def test_dash_comment_does_not_hide_select(engine: AsyncEngine) -> None:
    """Comments are stripped at parse time; a valid SELECT remains valid."""
    result = await sandbox.execute(
        "-- this is a comment\nSELECT 1", engine
    )
    assert result.success


# ---------------------------------------------------------------------------
# WITH/CTE and UNION acceptance
# ---------------------------------------------------------------------------

async def test_cte_with_select_allowed(populated_engine: AsyncEngine) -> None:
    result = await sandbox.execute(
        "WITH t AS (SELECT id FROM numbers WHERE id < 5) "
        "SELECT * FROM t",
        populated_engine,
    )
    assert result.success
    assert result.row_count == 5


async def test_union_allowed(engine: AsyncEngine) -> None:
    result = await sandbox.execute(
        "SELECT 1 AS x UNION SELECT 2 AS x", engine
    )
    assert result.success
    assert result.row_count == 2


async def test_select_subquery_allowed(populated_engine: AsyncEngine) -> None:
    result = await sandbox.execute(
        "SELECT id FROM numbers WHERE id IN (SELECT id FROM numbers WHERE id < 3)",
        populated_engine,
    )
    assert result.success


# ---------------------------------------------------------------------------
# Plain SELECT acceptance
# ---------------------------------------------------------------------------

async def test_select_not_blocked(engine: AsyncEngine) -> None:
    """Plain SELECT is never blocked."""
    result = await sandbox.execute("SELECT 1", engine)
    assert result.success


# ---------------------------------------------------------------------------
# Row limit tests
# ---------------------------------------------------------------------------

async def test_row_limit_enforced(populated_engine: AsyncEngine) -> None:
    result = await sandbox.execute("SELECT * FROM numbers", populated_engine)
    assert result.success
    assert result.row_count == MAX_ROWS


async def test_row_count_below_limit(populated_engine: AsyncEngine) -> None:
    result = await sandbox.execute(
        "SELECT * FROM numbers WHERE id < 10", populated_engine
    )
    assert result.success
    assert result.row_count == 10


async def test_sample_rows_capped(populated_engine: AsyncEngine) -> None:
    result = await sandbox.execute("SELECT * FROM numbers", populated_engine)
    assert result.success
    assert len(result.sample_rows) <= SAMPLE_ROWS


async def test_sample_rows_small_result(schema_engine: AsyncEngine) -> None:
    result = await sandbox.execute("SELECT * FROM customer", schema_engine)
    assert result.success
    assert result.row_count == 2
    assert len(result.sample_rows) == 2


# ---------------------------------------------------------------------------
# Successful execution — column and structure tests
# ---------------------------------------------------------------------------

async def test_correct_columns_returned(schema_engine: AsyncEngine) -> None:
    result = await sandbox.execute(
        "SELECT customer_id, name, email FROM customer", schema_engine
    )
    assert result.success
    assert result.columns == ["customer_id", "name", "email"]


async def test_column_subset(schema_engine: AsyncEngine) -> None:
    result = await sandbox.execute(
        "SELECT name FROM customer", schema_engine
    )
    assert result.success
    assert result.columns == ["name"]


async def test_sample_rows_are_dicts(schema_engine: AsyncEngine) -> None:
    result = await sandbox.execute(
        "SELECT customer_id, name FROM customer", schema_engine
    )
    assert result.success
    for row in result.sample_rows:
        assert isinstance(row, dict)
        assert "customer_id" in row
        assert "name" in row


async def test_sample_row_values(schema_engine: AsyncEngine) -> None:
    result = await sandbox.execute(
        "SELECT customer_id, name FROM customer ORDER BY customer_id", schema_engine
    )
    assert result.success
    assert result.sample_rows[0]["customer_id"] == 1
    assert result.sample_rows[0]["name"] == "Alice"


async def test_execution_time_populated(schema_engine: AsyncEngine) -> None:
    result = await sandbox.execute("SELECT 1", schema_engine)
    assert result.success
    assert result.execution_time_ms >= 0.0


async def test_empty_result(schema_engine: AsyncEngine) -> None:
    result = await sandbox.execute(
        "SELECT * FROM customer WHERE customer_id = 9999", schema_engine
    )
    assert result.success
    assert result.row_count == 0
    assert result.sample_rows == []
    assert result.columns == ["customer_id", "name", "email", "notes"]


# ---------------------------------------------------------------------------
# Execution error handling
# ---------------------------------------------------------------------------

async def test_missing_table_returns_failure(engine: AsyncEngine) -> None:
    """SQL referencing a missing table parses fine, fails at exec time."""
    result = await sandbox.execute("SELECT * FROM nonexistent_table", engine)
    assert not result.success
    assert result.error_message is not None
    assert result.row_count == 0
    assert result.columns == []


async def test_unparseable_sql_raises_security_violation(engine: AsyncEngine) -> None:
    """SQL that no dialect can parse is rejected by the sandbox, not the DB.

    This is a behavior change from the old keyword-grep sandbox: rather than
    forwarding garbage to the database and reporting a syntax error, we
    refuse to execute it at all.
    """
    with pytest.raises(SecurityViolation):
        await sandbox.execute("SELEKT NOT EVEN CLOSE", engine)


async def test_security_violation_is_not_swallowed(engine: AsyncEngine) -> None:
    """SecurityViolation must propagate — not be caught by the general handler."""
    with pytest.raises(SecurityViolation):
        await sandbox.execute("DROP TABLE foo", engine)
