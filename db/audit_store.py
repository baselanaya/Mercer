"""DuckDB-backed audit store.

Replaces the append-only JSONL log with a proper columnar store that
supports efficient pagination and aggregate queries.

Thread-safety: DuckDB connections are not thread-safe, so every async
operation runs inside ``asyncio.to_thread`` with a fresh connection.
The DuckDB file itself is safe for concurrent writers via WAL mode.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import duckdb

from core.models import AuditEntry, CorrectionStep

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS audit (
    id               VARCHAR PRIMARY KEY,
    timestamp        TIMESTAMPTZ NOT NULL,
    question         VARCHAR     NOT NULL,
    final_sql        VARCHAR,
    tables_used      VARCHAR     NOT NULL,   -- JSON array
    columns_used     VARCHAR     NOT NULL,   -- JSON array
    model_used       VARCHAR     NOT NULL,
    backend_used     VARCHAR     NOT NULL,
    correction_steps VARCHAR     NOT NULL,   -- JSON array of CorrectionStep dicts
    total_latency_ms DOUBLE      NOT NULL,
    success          BOOLEAN     NOT NULL,
    stage_timings    VARCHAR     NOT NULL    -- JSON object
)
"""

_INSERT = """
INSERT OR IGNORE INTO audit (
    id, timestamp, question, final_sql,
    tables_used, columns_used, model_used, backend_used,
    correction_steps, total_latency_ms, success, stage_timings
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_PAGE = """
SELECT * FROM audit
ORDER BY timestamp DESC
LIMIT ? OFFSET ?
"""

_COUNT = "SELECT COUNT(*) FROM audit"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_to_row(entry: AuditEntry) -> tuple[Any, ...]:
    return (
        entry.id,
        entry.timestamp.isoformat(),
        entry.question,
        entry.final_sql,
        json.dumps(entry.tables_used),
        json.dumps(entry.columns_used),
        entry.model_used,
        entry.backend_used,
        json.dumps([s.model_dump() for s in entry.correction_steps]),
        entry.total_latency_ms,
        entry.success,
        json.dumps(entry.stage_timings),
    )


def _row_to_dict(row: tuple[Any, ...], columns: list[str]) -> dict[str, Any]:
    d: dict[str, Any] = dict(zip(columns, row, strict=True))
    for json_col in ("tables_used", "columns_used", "correction_steps", "stage_timings"):
        if isinstance(d.get(json_col), str):
            d[json_col] = json.loads(d[json_col])
    return d


def _row_to_entry(row: tuple[Any, ...], columns: list[str]) -> AuditEntry:
    d = _row_to_dict(row, columns)
    d["correction_steps"] = [CorrectionStep(**s) for s in d["correction_steps"]]
    return AuditEntry(**d)


# ---------------------------------------------------------------------------
# AuditStore
# ---------------------------------------------------------------------------

class AuditStore:
    """Async wrapper around a DuckDB audit table.

    Args:
        db_path: Path to the DuckDB file.  Created on first use.
    """

    def __init__(self, db_path: str = "logs/audit.duckdb") -> None:
        self._db_path = db_path
        self._initialised = False

    # ------------------------------------------------------------------
    # Initialisation (idempotent, called lazily)
    # ------------------------------------------------------------------

    def _init_sync(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(self._db_path)
        try:
            con.execute(_CREATE_TABLE)
        finally:
            con.close()

    async def _ensure_init(self) -> None:
        if not self._initialised:
            await asyncio.to_thread(self._init_sync)
            self._initialised = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def append(self, entry: AuditEntry) -> None:
        """Append a single AuditEntry row (idempotent on duplicate id)."""
        await self._ensure_init()
        row = _entry_to_row(entry)
        await asyncio.to_thread(self._append_sync, row)

    async def query(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (entries, total_count) for the given page.

        Entries are returned as plain dicts (JSON-serialisable), newest first.
        """
        await self._ensure_init()
        return await asyncio.to_thread(self._query_sync, limit, offset)

    async def aggregate(self) -> dict[str, Any]:
        """Return aggregate metrics across all audit records."""
        await self._ensure_init()
        return await asyncio.to_thread(self._aggregate_sync)

    # ------------------------------------------------------------------
    # Sync internals (run inside to_thread)
    # ------------------------------------------------------------------

    def _append_sync(self, row: tuple[Any, ...]) -> None:
        con = duckdb.connect(self._db_path)
        try:
            con.execute(_INSERT, list(row))
        finally:
            con.close()

    def _query_sync(
        self, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        con = duckdb.connect(self._db_path, read_only=True)
        try:
            total: int = con.execute(_COUNT).fetchone()[0]  # type: ignore[index]
            result = con.execute(_SELECT_PAGE, [limit, offset])
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            entries = [_row_to_dict(row, columns) for row in rows]
            return entries, total
        finally:
            con.close()

    def _aggregate_sync(self) -> dict[str, Any]:
        con = duckdb.connect(self._db_path, read_only=True)
        try:
            row = con.execute("""
                SELECT
                    COUNT(*)                                        AS total_queries,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END)       AS success_count,
                    AVG(total_latency_ms)                           AS avg_latency_ms,
                    PERCENTILE_CONT(0.50) WITHIN GROUP
                        (ORDER BY total_latency_ms)                 AS p50_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP
                        (ORDER BY total_latency_ms)                 AS p95_ms,
                    PERCENTILE_CONT(0.99) WITHIN GROUP
                        (ORDER BY total_latency_ms)                 AS p99_ms,
                    SUM(CASE WHEN correction_steps != '[]'
                              THEN 1 ELSE 0 END)                    AS corrected_count
                FROM audit
            """).fetchone()
            if row is None or row[0] == 0:
                return {"total_queries": 0}

            total, successes, avg_ms, p50, p95, p99, corrected = row

            # Top error classes from failed queries  (best-effort JSON parse)
            error_rows = con.execute("""
                SELECT correction_steps FROM audit
                WHERE NOT success AND correction_steps != '[]'
                LIMIT 200
            """).fetchall()

            error_classes: dict[str, int] = {}
            for (cs_json,) in error_rows:
                steps = json.loads(cs_json)
                for step in steps:
                    cls = step.get("error_class") or step.get("error_type") or "unknown"
                    error_classes[cls] = error_classes.get(cls, 0) + 1

            top_errors = sorted(error_classes.items(), key=lambda x: -x[1])[:5]

            return {
                "total_queries": int(total),
                "success_count": int(successes),
                "success_rate": round(successes / total, 4) if total else 0.0,
                "avg_latency_ms": round(float(avg_ms), 2),
                "p50_ms": round(float(p50), 2),
                "p95_ms": round(float(p95), 2),
                "p99_ms": round(float(p99), 2),
                "correction_rate": round(corrected / total, 4) if total else 0.0,
                "top_error_classes": [{"class": c, "count": n} for c, n in top_errors],
            }
        finally:
            con.close()
