"""Tests for the FastAPI application layer.

Uses FastAPI's TestClient (httpx-backed) with an injected mock pipeline so no
real database, Redis, or LLM backend is required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.models import (
    AnnotatedSchema,
    AuditEntry,
    ColumnSchema,
    ExecutionResult,
    PipelineState,
    SQLCandidate,
    TableSchema,
)

# ---------------------------------------------------------------------------
# Helpers — build minimal fixtures
# ---------------------------------------------------------------------------

def _mock_schema() -> AnnotatedSchema:
    col = ColumnSchema(name="id", type="INTEGER", is_primary_key=True)
    tbl = TableSchema(name="orders", columns=[col])
    return AnnotatedSchema(db_url_hash="test-hash", tables=[tbl], glossary={})


def _mock_execution_result(sql: str = "SELECT 1") -> ExecutionResult:
    return ExecutionResult(
        success=True,
        sql=sql,
        row_count=1,
        columns=["?column?"],
        sample_rows=[{"?column?": 1}],
    )


def _mock_state(question: str = "How many orders?") -> PipelineState:
    sql = "SELECT COUNT(*) FROM orders;"
    result = _mock_execution_result(sql)
    candidate = SQLCandidate(
        sql=sql,
        strategy="direct_cot",
        execution_result=result,
        score=0.9,
    )
    audit = AuditEntry(
        timestamp=datetime.now(UTC),
        question=question,
        final_sql=sql,
        tables_used=["orders"],
        columns_used=["orders.id"],
        model_used="mock-model",
        backend_used="MockBackend",
        correction_steps=[],
        total_latency_ms=12.5,
        success=True,
        stage_timings={
            "entity_retrieval": 1.2,
            "schema_linking": 0.4,
            "query_decomposition": 0.1,
            "candidate_generation": 0.2,
            "execution_scoring": 0.8,
        },
    )
    return PipelineState(
        question=question,
        final_sql=sql,
        best_candidate=candidate,
        candidates=[candidate],
        audit_entry=audit,
        stage_timings=audit.stage_timings,
    )


def _make_mock_pipeline(state: PipelineState | None = None) -> MagicMock:
    pipeline = MagicMock()
    pipeline.run = AsyncMock(return_value=state or _mock_state())
    pipeline._backend = MagicMock()
    pipeline._backend.generate = AsyncMock(
        return_value="This query counts all rows in the orders table."
    )
    pipeline._annotated_schema = _mock_schema()
    pipeline._load_schema = AsyncMock(return_value=_mock_schema())
    pipeline._router = MagicMock()
    pipeline._router._sglang_healthy = False
    return pipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_pipeline() -> MagicMock:
    return _make_mock_pipeline()


@pytest.fixture()
def client(mock_pipeline: MagicMock) -> TestClient:
    from app.api.main import create_app

    app = create_app(pipeline=mock_pipeline)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /query
# ---------------------------------------------------------------------------

class TestPostQuery:
    def test_returns_200_with_sql(self, client: TestClient) -> None:
        resp = client.post("/query", json={"question": "How many orders?"})
        assert resp.status_code == 200
        body = resp.json()
        assert "sql" in body
        assert body["sql"] == "SELECT COUNT(*) FROM orders;"

    def test_returns_explanation(self, client: TestClient) -> None:
        resp = client.post("/query", json={"question": "How many orders?"})
        assert resp.status_code == 200
        body = resp.json()
        assert "explanation" in body
        assert isinstance(body["explanation"], str)
        assert len(body["explanation"]) > 0

    def test_returns_execution_result(self, client: TestClient) -> None:
        resp = client.post("/query", json={"question": "How many orders?"})
        body = resp.json()
        assert body["execution_result"] is not None
        assert body["execution_result"]["success"] is True
        assert body["execution_result"]["row_count"] == 1

    def test_returns_reasoning_trace(self, client: TestClient) -> None:
        resp = client.post("/query", json={"question": "How many orders?"})
        body = resp.json()
        assert "reasoning_trace" in body
        assert "stage_timings_ms" in body["reasoning_trace"]

    def test_returns_latency_ms(self, client: TestClient) -> None:
        resp = client.post("/query", json={"question": "How many orders?"})
        body = resp.json()
        assert "latency_ms" in body
        assert isinstance(body["latency_ms"], float)

    def test_empty_question_returns_422(self, client: TestClient) -> None:
        resp = client.post("/query", json={"question": ""})
        assert resp.status_code == 422

    def test_missing_question_returns_422(self, client: TestClient) -> None:
        resp = client.post("/query", json={})
        assert resp.status_code == 422

    def test_pipeline_exception_returns_500(
        self, mock_pipeline: MagicMock
    ) -> None:
        mock_pipeline.run = AsyncMock(side_effect=RuntimeError("DB exploded"))
        from app.api.main import create_app

        app = create_app(pipeline=mock_pipeline)
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post("/query", json={"question": "test"})
        assert resp.status_code == 500
        assert "DB exploded" in resp.json()["detail"]

    def test_optional_db_url_accepted(self, client: TestClient) -> None:
        """db_url field is accepted but ignored in Phase 4."""
        resp = client.post(
            "/query",
            json={"question": "test query", "db_url": "sqlite:///test.db"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestGetHealth:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_status_is_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.json()["status"] == "ok"

    def test_has_required_fields(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert "status" in body
        assert "sglang_healthy" in body
        assert "db_connected" in body

    def test_db_connected_false_when_no_engine(self, client: TestClient) -> None:
        """Injected pipeline has no real engine — db_connected should be False."""
        body = client.get("/health").json()
        assert body["db_connected"] is False

    def test_sglang_healthy_false_by_default(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert body["sglang_healthy"] is False


# ---------------------------------------------------------------------------
# GET /schema
# ---------------------------------------------------------------------------

class TestGetSchema:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/schema")
        assert resp.status_code == 200

    def test_has_tables_field(self, client: TestClient) -> None:
        body = client.get("/schema").json()
        assert "tables" in body
        assert isinstance(body["tables"], list)

    def test_has_glossary_field(self, client: TestClient) -> None:
        body = client.get("/schema").json()
        assert "glossary" in body


# ---------------------------------------------------------------------------
# GET /audit
# ---------------------------------------------------------------------------

class TestGetAudit:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/audit")
        assert resp.status_code == 200

    def test_returns_empty_when_no_log(self, client: TestClient) -> None:
        from unittest.mock import patch

        from config import settings as _settings

        with patch.object(_settings.settings, "audit_path", "/tmp/mercer_nonexistent_audit.jsonl"):
            body = client.get("/audit").json()
        assert "entries" in body
        assert "total" in body
        assert body["entries"] == []
        assert body["total"] == 0

    def test_limit_and_offset_params_accepted(self, client: TestClient) -> None:
        resp = client.get("/audit?limit=5&offset=0")
        assert resp.status_code == 200

    def test_invalid_limit_returns_422(self, client: TestClient) -> None:
        resp = client.get("/audit?limit=0")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Auth — optional API key
# ---------------------------------------------------------------------------

class TestApiKeyAuth:
    def test_no_key_configured_allows_all(self, client: TestClient) -> None:
        """Default test env has no MERCER_API_KEY — all requests succeed."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_wrong_key_returns_403_when_configured(
        self, mock_pipeline: MagicMock
    ) -> None:
        from app.api.main import create_app
        from config.settings import settings as _settings

        original = _settings.mercer_api_key
        _settings.mercer_api_key = "secret-key"
        try:
            app = create_app(pipeline=mock_pipeline)
            with TestClient(app) as c:
                resp = c.post(
                    "/query",
                    json={"question": "test"},
                    headers={"X-API-Key": "wrong-key"},
                )
            assert resp.status_code == 403
        finally:
            _settings.mercer_api_key = original

    def test_correct_key_allows_request_when_configured(
        self, mock_pipeline: MagicMock
    ) -> None:
        from app.api.main import create_app
        from config.settings import settings as _settings

        original = _settings.mercer_api_key
        _settings.mercer_api_key = "secret-key"
        try:
            app = create_app(pipeline=mock_pipeline)
            with TestClient(app) as c:
                resp = c.post(
                    "/query",
                    json={"question": "test"},
                    headers={"X-API-Key": "secret-key"},
                )
            assert resp.status_code == 200
        finally:
            _settings.mercer_api_key = original
