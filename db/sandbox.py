"""ReadOnlySandbox — the only permitted path to database execution.

All pipeline code must call ReadOnlySandbox.execute(). Direct engine.execute()
calls anywhere else in the codebase are a security violation.
"""

import asyncio
import re
import time

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from core.models import ExecutionResult

# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------

BLOCKED_KEYWORDS: frozenset[str] = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "CREATE", "GRANT", "TRUNCATE", "EXEC", "EXECUTE",
})

MAX_ROWS: int = 100
TIMEOUT_SECONDS: int = 5
SAMPLE_ROWS: int = 3

# Pre-compiled patterns for each blocked keyword (whole-word match)
_BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b" + kw + r"\b") for kw in BLOCKED_KEYWORDS
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SecurityViolation(Exception):
    """Raised when SQL contains a blocked keyword (DDL or DML)."""


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------

class ReadOnlySandbox:
    """Executes SQL in a read-only sandboxed environment.

    Enforces:
    - Blocked DDL/DML keyword check (raises SecurityViolation)
    - Statement timeout (PostgreSQL: SET LOCAL statement_timeout)
    - Row limit: at most MAX_ROWS rows fetched
    - Returns ExecutionResult — never raw cursor objects
    - sample_rows: first SAMPLE_ROWS rows only (for LLM context)
    """

    async def execute(
        self,
        sql: str,
        engine: AsyncEngine | Engine,
    ) -> ExecutionResult:
        """Execute *sql* in the sandbox and return an ExecutionResult (never raises on SQL errors)."""
        self._check_blocked(sql)

        if isinstance(engine, AsyncEngine):
            return await self._execute_async(sql, engine)
        else:
            return await asyncio.to_thread(self._execute_sync, sql, engine)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_blocked(self, sql: str) -> None:
        """Raise SecurityViolation if any blocked keyword is found."""
        sql_upper = sql.strip().upper()
        for pattern in _BLOCKED_PATTERNS:
            if pattern.search(sql_upper):
                keyword = pattern.pattern.strip(r"\b")
                raise SecurityViolation(
                    f"Blocked keyword '{keyword}' found in SQL. "
                    "Only read-only SELECT statements are permitted."
                )

    async def _execute_async(self, sql: str, engine: AsyncEngine) -> ExecutionResult:
        start = time.monotonic()
        try:
            async with engine.begin() as conn:
                dialect = engine.dialect.name
                if dialect == "postgresql":
                    await conn.execute(
                        text(f"SET LOCAL statement_timeout = '{TIMEOUT_SECONDS * 1000}'")
                    )
                result = await conn.execute(text(sql))
                columns = list(result.keys())
                rows = result.fetchmany(MAX_ROWS)
                row_dicts = [dict(zip(columns, row, strict=True)) for row in rows]
                elapsed = (time.monotonic() - start) * 1000
                return ExecutionResult(
                    success=True,
                    sql=sql,
                    row_count=len(row_dicts),
                    columns=columns,
                    sample_rows=row_dicts[:SAMPLE_ROWS],
                    execution_time_ms=round(elapsed, 2),
                )
        except SecurityViolation:
            raise
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ExecutionResult(
                success=False,
                sql=sql,
                row_count=0,
                columns=[],
                sample_rows=[],
                error_message=str(exc),
                execution_time_ms=round(elapsed, 2),
            )

    def _execute_sync(self, sql: str, engine: Engine) -> ExecutionResult:
        start = time.monotonic()
        try:
            with engine.begin() as conn:
                result = conn.execute(text(sql))
                columns = list(result.keys())
                rows = result.fetchmany(MAX_ROWS)
                row_dicts = [dict(zip(columns, row, strict=True)) for row in rows]
                elapsed = (time.monotonic() - start) * 1000
                return ExecutionResult(
                    success=True,
                    sql=sql,
                    row_count=len(row_dicts),
                    columns=columns,
                    sample_rows=row_dicts[:SAMPLE_ROWS],
                    execution_time_ms=round(elapsed, 2),
                )
        except SecurityViolation:
            raise
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ExecutionResult(
                success=False,
                sql=sql,
                row_count=0,
                columns=[],
                sample_rows=[],
                error_message=str(exc),
                execution_time_ms=round(elapsed, 2),
            )
