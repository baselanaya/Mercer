"""Tests for MercerPipeline — Phase 0 baseline.

Uses an in-memory SQLite database (StaticPool) and a mock LLM backend so the
pipeline can run end-to-end without external services.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis as faio
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from core.models import AnnotatedSchema, ColumnSchema, PipelineState, TableSchema
from core.pipeline import MercerPipeline
from db.audit_store import AuditStore
from schema.cache import SchemaCache


def _fake_cache(ttl: int = 3600) -> SchemaCache:
    """Return a SchemaCache backed by an in-memory FakeRedis (no real Redis needed)."""
    return SchemaCache._from_client(faio.FakeRedis(decode_responses=True), ttl_seconds=ttl)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
async def sqlite_engine() -> AsyncGenerator[AsyncEngine, None]:
    """In-memory SQLite engine shared via StaticPool.

    StaticPool ensures all connections (including those opened inside
    `engine.begin()`) share the same underlying SQLite connection and therefore
    see the same in-memory tables.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE table_a (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        ))
        await conn.execute(text(
            "CREATE TABLE table_b (id INTEGER PRIMARY KEY, value REAL)"
        ))
        await conn.execute(text("INSERT INTO table_a VALUES (1, 'alpha'), (2, 'beta')"))
        await conn.execute(text("INSERT INTO table_b VALUES (1, 3.14)"))
    yield engine
    await engine.dispose()


@pytest.fixture()
def mock_backend() -> MagicMock:
    """LLM backend that always returns a fixed COUNT query."""
    backend = MagicMock()
    backend._model = "mock-model"
    _sql = "SELECT COUNT(*) AS row_count FROM table_a;"
    backend.generate = AsyncMock(return_value=_sql)
    backend.generate_batch = AsyncMock(return_value=[_sql, _sql, _sql])
    return backend


@pytest.fixture()
def fixed_schema() -> AnnotatedSchema:
    """Minimal annotated schema matching the SQLite fixture above."""
    return AnnotatedSchema(
        db_url_hash="test-hash",
        tables=[
            TableSchema(
                name="table_a",
                columns=[
                    ColumnSchema(name="id", type="INTEGER", is_primary_key=True),
                    ColumnSchema(name="name", type="TEXT"),
                ],
            ),
            TableSchema(
                name="table_b",
                columns=[
                    ColumnSchema(name="id", type="INTEGER", is_primary_key=True),
                    ColumnSchema(name="value", type="REAL"),
                ],
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline(
    engine: AsyncEngine,
    backend: MagicMock,
    schema: AnnotatedSchema,
    audit_store: AuditStore,
) -> MercerPipeline:
    """Build a pipeline with the schema pre-cached to skip actual introspection."""
    pipeline = MercerPipeline(
        db_engine=engine,
        backend=backend,
        audit_store=audit_store,
        cache=_fake_cache(),
    )
    # Pre-populate the session schema cache so introspection is skipped
    pipeline._annotated_schema = schema
    return pipeline


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipelineRun:
    async def test_final_sql_is_set_on_success(
        self,
        sqlite_engine: AsyncEngine,
        mock_backend: MagicMock,
        fixed_schema: AnnotatedSchema,
        tmp_path: Path,
    ) -> None:
        store = AuditStore(str(tmp_path / "audit.duckdb"))
        pipeline = _make_pipeline(sqlite_engine, mock_backend, fixed_schema, store)
        state: PipelineState = await pipeline.run("how many rows are in table_a?")

        assert state.final_sql is not None
        assert "table_a" in state.final_sql.lower()

    async def test_execution_result_success(
        self,
        sqlite_engine: AsyncEngine,
        mock_backend: MagicMock,
        fixed_schema: AnnotatedSchema,
        tmp_path: Path,
    ) -> None:
        store = AuditStore(str(tmp_path / "audit.duckdb"))
        pipeline = _make_pipeline(sqlite_engine, mock_backend, fixed_schema, store)
        state: PipelineState = await pipeline.run("how many rows are in table_a?")

        assert state.best_candidate is not None
        assert state.best_candidate.execution_result is not None
        assert state.best_candidate.execution_result.success is True

    async def test_execution_result_contains_rows(
        self,
        sqlite_engine: AsyncEngine,
        mock_backend: MagicMock,
        fixed_schema: AnnotatedSchema,
        tmp_path: Path,
    ) -> None:
        store = AuditStore(str(tmp_path / "audit.duckdb"))
        pipeline = _make_pipeline(sqlite_engine, mock_backend, fixed_schema, store)
        state: PipelineState = await pipeline.run("how many rows are in table_a?")

        assert state.best_candidate is not None
        result = state.best_candidate.execution_result
        assert result is not None
        assert result.row_count == 1  # COUNT returns one result row
        assert result.sample_rows[0]["row_count"] == 2  # two rows inserted in fixture

    async def test_audit_entry_written_to_store(
        self,
        sqlite_engine: AsyncEngine,
        mock_backend: MagicMock,
        fixed_schema: AnnotatedSchema,
        tmp_path: Path,
    ) -> None:
        store = AuditStore(str(tmp_path / "audit.duckdb"))
        pipeline = _make_pipeline(sqlite_engine, mock_backend, fixed_schema, store)
        await pipeline.run("how many rows are in table_a?")

        entries, total = await store.query(limit=10, offset=0)
        assert total == 1
        assert entries[0]["success"] is True
        assert entries[0]["question"] == "how many rows are in table_a?"
        assert entries[0]["model_used"] == "mock-model"

    async def test_audit_entry_in_state(
        self,
        sqlite_engine: AsyncEngine,
        mock_backend: MagicMock,
        fixed_schema: AnnotatedSchema,
        tmp_path: Path,
    ) -> None:
        store = AuditStore(str(tmp_path / "audit.duckdb"))
        pipeline = _make_pipeline(sqlite_engine, mock_backend, fixed_schema, store)
        state: PipelineState = await pipeline.run("how many rows are in table_a?")

        assert state.audit_entry is not None
        assert state.audit_entry.total_latency_ms > 0

    async def test_failed_sql_sets_final_sql_none(
        self,
        sqlite_engine: AsyncEngine,
        fixed_schema: AnnotatedSchema,
        tmp_path: Path,
    ) -> None:
        """When the LLM returns invalid SQL, final_sql should be None."""
        bad_backend = MagicMock()
        bad_backend._model = "mock-model"
        _bad_sql = "NOT VALID SQL ;;; ???"
        bad_backend.generate = AsyncMock(return_value=_bad_sql)
        bad_backend.generate_batch = AsyncMock(return_value=[_bad_sql, _bad_sql, _bad_sql])

        store = AuditStore(str(tmp_path / "audit.duckdb"))
        pipeline = _make_pipeline(sqlite_engine, bad_backend, fixed_schema, store)
        state: PipelineState = await pipeline.run("break everything")

        assert state.final_sql is None
        assert state.best_candidate is not None
        assert state.best_candidate.execution_result is not None
        assert state.best_candidate.execution_result.success is False

    async def test_fence_stripping(
        self,
        sqlite_engine: AsyncEngine,
        fixed_schema: AnnotatedSchema,
        tmp_path: Path,
    ) -> None:
        """LLM output wrapped in ```sql ... ``` fences must still execute."""
        fenced_backend = MagicMock()
        fenced_backend._model = "mock-model"
        _fenced_sql = "```sql\nSELECT COUNT(*) AS row_count FROM table_a;\n```"
        fenced_backend.generate = AsyncMock(return_value=_fenced_sql)
        fenced_backend.generate_batch = AsyncMock(return_value=[_fenced_sql, _fenced_sql, _fenced_sql])

        store = AuditStore(str(tmp_path / "audit.duckdb"))
        pipeline = _make_pipeline(sqlite_engine, fenced_backend, fixed_schema, store)
        state: PipelineState = await pipeline.run("how many rows?")

        assert state.final_sql is not None
        assert state.best_candidate is not None
        assert state.best_candidate.execution_result is not None
        assert state.best_candidate.execution_result.success is True

    async def test_multiple_runs_append_audit(
        self,
        sqlite_engine: AsyncEngine,
        mock_backend: MagicMock,
        fixed_schema: AnnotatedSchema,
        tmp_path: Path,
    ) -> None:
        """Each pipeline run appends one row to the audit store."""
        store = AuditStore(str(tmp_path / "audit.duckdb"))
        pipeline = _make_pipeline(sqlite_engine, mock_backend, fixed_schema, store)
        await pipeline.run("first question")
        await pipeline.run("second question")

        entries, total = await store.query(limit=10, offset=0)
        assert total == 2
        questions = [e["question"] for e in entries]
        assert "first question" in questions
        assert "second question" in questions

    async def test_schema_cached_after_first_run(
        self,
        sqlite_engine: AsyncEngine,
        mock_backend: MagicMock,
        tmp_path: Path,
    ) -> None:
        """_annotated_schema is populated after the first run (lazy load path)."""
        # Do NOT pre-populate schema — let the pipeline introspect for real
        pipeline = MercerPipeline(
            db_engine=sqlite_engine,
            backend=mock_backend,
            audit_store=AuditStore(str(tmp_path / "audit.duckdb")),
            cache=_fake_cache(),
        )
        assert pipeline._annotated_schema is None

        await pipeline.run("any question")

        assert pipeline._annotated_schema is not None
        assert len(pipeline._annotated_schema.tables) >= 1
