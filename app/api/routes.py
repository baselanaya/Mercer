"""REST API route handlers.

Endpoints:
  POST /query   — run the NL→SQL pipeline, return SQL + explanation
  GET  /schema  — return annotated schema for the connected database
  GET  /audit   — paginated audit log
  GET  /health  — liveness + dependency health
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.auth import get_api_key
from config.settings import settings
from core.logging import get_logger
from core.models import ExecutionResult, TableSchema
from core.pipeline import MercerPipeline
from db.audit_store import AuditStore
from prompts.explanation import SYSTEM_PROMPT, build_prompt

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str = Field(min_length=1, description="Natural-language question to answer")
    db_url: str | None = Field(
        None,
        description="Optional DB URL override (reserved for Phase 5 — ignored in Phase 4)",
    )


class QueryResponse(BaseModel):
    sql: str | None
    explanation: str
    execution_result: ExecutionResult | None
    reasoning_trace: dict[str, Any]
    latency_ms: float


class SchemaResponse(BaseModel):
    tables: list[TableSchema]
    glossary: dict[str, str]


class AuditListResponse(BaseModel):
    entries: list[dict[str, Any]]
    total: int


class HealthResponse(BaseModel):
    status: str
    sglang_healthy: bool
    db_connected: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _generate_explanation(
    pipeline: MercerPipeline,
    question: str,
    sql: str,
) -> str:
    """Call the LLM backend to explain the generated SQL in plain English.

    Returns an empty string if the backend is unavailable or the call fails —
    the explanation is informational and must not block the response.
    """
    backend = pipeline._backend
    if backend is None:
        try:
            backend = await pipeline._router.get_backend_async(0.5)
        except Exception:
            return ""
    try:
        return await backend.generate(
            build_prompt(question, sql),
            system=SYSTEM_PROMPT,
            temperature=0.0,
            max_tokens=256,
        )
    except Exception:  # noqa: BLE001
        return ""


def _build_reasoning_trace(state: Any) -> dict[str, Any]:
    """Extract a human-readable reasoning trace from a PipelineState."""
    trace: dict[str, Any] = {"stage_timings_ms": state.stage_timings}

    if state.entity_context:
        trace["entity_matches"] = [
            {"token": m.token, "table": m.table, "column": m.column, "score": m.score}
            for m in state.entity_context.entity_matches[:10]
        ]
        trace["glossary_expansions"] = state.entity_context.glossary_expansions

    if state.filtered_schema:
        trace["tables_selected"] = [t.name for t in state.filtered_schema.tables]

    if state.query_plan:
        trace["query_plan"] = state.query_plan.model_dump()

    if state.candidates:
        trace["candidates"] = [
            {"strategy": c.strategy, "score": round(c.score, 4)}
            for c in state.candidates
        ]

    trace["correction_steps"] = len(state.correction_log)
    return trace


# ---------------------------------------------------------------------------
# POST /query
# ---------------------------------------------------------------------------

@router.post(
    "/query",
    response_model=QueryResponse,
    dependencies=[Depends(get_api_key)],
    summary="Translate a natural-language question to SQL and execute it",
)
async def post_query(body: QueryRequest, request: Request) -> QueryResponse:
    """Run the NL→SQL pipeline on the question and return the best SQL + result."""
    pipeline: MercerPipeline = request.app.state.pipeline

    try:
        state = await pipeline.run(body.question)
    except Exception as exc:
        logger.error("pipeline_error", question=body.question, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc

    sql = state.final_sql
    latency_ms = state.audit_entry.total_latency_ms if state.audit_entry else 0.0

    # Generate plain-English explanation (best-effort)
    explanation = ""
    if sql:
        explanation = await _generate_explanation(pipeline, body.question, sql)

    execution_result = (
        state.best_candidate.execution_result
        if state.best_candidate and state.best_candidate.execution_result
        else None
    )

    return QueryResponse(
        sql=sql,
        explanation=explanation or "No explanation available.",
        execution_result=execution_result,
        reasoning_trace=_build_reasoning_trace(state),
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# GET /schema
# ---------------------------------------------------------------------------

@router.get(
    "/schema",
    response_model=SchemaResponse,
    dependencies=[Depends(get_api_key)],
    summary="Return the annotated schema for the connected database",
)
async def get_schema(request: Request) -> SchemaResponse:
    """Return the annotated schema (tables, columns, glossary) for the connected database."""
    pipeline: MercerPipeline = request.app.state.pipeline

    # _load_schema is idempotent and cache-first
    schema = await pipeline._load_schema()
    return SchemaResponse(tables=schema.tables, glossary=schema.glossary)


# ---------------------------------------------------------------------------
# GET /audit
# ---------------------------------------------------------------------------

@router.get(
    "/audit",
    response_model=AuditListResponse,
    dependencies=[Depends(get_api_key)],
    summary="Paginated pipeline audit log",
)
async def get_audit(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AuditListResponse:
    """Return a paginated audit log of all pipeline runs, newest first."""
    store = AuditStore(settings.audit_path)
    entries, total = await store.query(limit=limit, offset=offset)
    return AuditListResponse(entries=entries, total=total)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness and dependency health check",
)
async def get_health(request: Request) -> HealthResponse:
    """Return liveness status and dependency health (DB reachability, SGLang health)."""
    engine = getattr(request.app.state, "engine", None)

    db_connected = False
    if engine is not None:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_connected = True
        except Exception:  # noqa: BLE001
            db_connected = False

    pipeline = getattr(request.app.state, "pipeline", None)
    sglang_healthy = False
    if pipeline is not None:
        router_obj = getattr(pipeline, "_router", None)
        if router_obj is not None:
            sglang_healthy = bool(getattr(router_obj, "_sglang_healthy", False))

    return HealthResponse(
        status="ok",
        sglang_healthy=sglang_healthy,
        db_connected=db_connected,
    )
