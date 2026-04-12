"""Tests for ReadOnlySandbox.

All tests use SQLite in-memory via aiosqlite — no PostgreSQL required.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from db.sandbox import (
    BLOCKED_KEYWORDS,
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
            "  email TEXT"
            ")"
        ))
        await conn.execute(
            text("INSERT INTO customer (customer_id, name, email) VALUES (:id, :name, :email)"),
            [
                {"id": 1, "name": "Alice", "email": "alice@example.com"},
                {"id": 2, "name": "Bob",   "email": "bob@example.com"},
            ],
        )
    yield eng
    await eng.dispose()


sandbox = ReadOnlySandbox()


# ---------------------------------------------------------------------------
# Blocked keyword tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("keyword", sorted(BLOCKED_KEYWORDS))
async def test_blocked_keyword_raises(keyword: str, engine: AsyncEngine) -> None:
    """Every blocked keyword must raise SecurityViolation."""
    # Build a statement that contains the keyword as a standalone token
    sql = f"{keyword} INTO foo VALUES (1)"
    with pytest.raises(SecurityViolation, match=keyword):
        await sandbox.execute(sql, engine)


@pytest.mark.parametrize("keyword", sorted(BLOCKED_KEYWORDS))
async def test_blocked_keyword_lowercase(keyword: str, engine: AsyncEngine) -> None:
    """Keyword check is case-insensitive."""
    sql = f"{keyword.lower()} foo"
    with pytest.raises(SecurityViolation):
        await sandbox.execute(sql, engine)


@pytest.mark.parametrize("keyword", sorted(BLOCKED_KEYWORDS))
async def test_blocked_keyword_mixed_case(keyword: str, engine: AsyncEngine) -> None:
    """Mixed-case keywords are caught."""
    mixed = keyword[0].upper() + keyword[1:].lower()
    sql = f"{mixed} foo"
    with pytest.raises(SecurityViolation):
        await sandbox.execute(sql, engine)


async def test_keyword_inside_identifier_not_blocked(engine: AsyncEngine) -> None:
    """'create_date' should not trigger the CREATE block."""
    # create_date contains 'create' but as part of an identifier (word boundary safe)
    # We just check that the sandbox doesn't raise SecurityViolation;
    # the query itself may fail on missing table, but that's an execution error.
    result = await sandbox.execute(
        "SELECT create_date FROM nonexistent_table", engine
    )
    # SecurityViolation was NOT raised — we get a normal execution failure
    assert not result.success
    assert result.error_message is not None


async def test_select_not_blocked(engine: AsyncEngine) -> None:
    """Plain SELECT is never blocked."""
    result = await sandbox.execute("SELECT 1", engine)
    assert result.success


# ---------------------------------------------------------------------------
# Row limit tests
# ---------------------------------------------------------------------------

async def test_row_limit_enforced(populated_engine: AsyncEngine) -> None:
    """Fetching from a 200-row table must return at most MAX_ROWS rows."""
    result = await sandbox.execute("SELECT * FROM numbers", populated_engine)
    assert result.success
    assert result.row_count == MAX_ROWS


async def test_row_count_below_limit(populated_engine: AsyncEngine) -> None:
    """When actual rows < MAX_ROWS, all rows are returned."""
    result = await sandbox.execute(
        "SELECT * FROM numbers WHERE id < 10", populated_engine
    )
    assert result.success
    assert result.row_count == 10


async def test_sample_rows_capped(populated_engine: AsyncEngine) -> None:
    """sample_rows must contain at most SAMPLE_ROWS entries regardless of row_count."""
    result = await sandbox.execute("SELECT * FROM numbers", populated_engine)
    assert result.success
    assert len(result.sample_rows) <= SAMPLE_ROWS


async def test_sample_rows_small_result(schema_engine: AsyncEngine) -> None:
    """When row_count < SAMPLE_ROWS, sample_rows == all rows."""
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
    assert result.columns == ["customer_id", "name", "email"]


# ---------------------------------------------------------------------------
# Execution error handling
# ---------------------------------------------------------------------------

async def test_bad_sql_returns_failure(engine: AsyncEngine) -> None:
    """Malformed SQL returns ExecutionResult with success=False, not an exception."""
    result = await sandbox.execute("SELECT * FROM nonexistent_table", engine)
    assert not result.success
    assert result.error_message is not None
    assert result.row_count == 0
    assert result.columns == []


async def test_syntax_error_returns_failure(engine: AsyncEngine) -> None:
    result = await sandbox.execute("SELEKT 1", engine)
    assert not result.success
    assert result.error_message is not None


async def test_security_violation_is_not_swallowed(engine: AsyncEngine) -> None:
    """SecurityViolation must propagate — not be caught by the general handler."""
    with pytest.raises(SecurityViolation):
        await sandbox.execute("DROP TABLE foo", engine)
