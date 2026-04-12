"""REST API route handlers.

Endpoints:
  POST /query          — run the NL→SQL pipeline, return SQL + explanation
  GET  /schema         — return annotated schema for the connected database
  GET  /audit          — paginated audit log
  GET  /health         — liveness + dependency health
  GET  /setup/model    — return current inference backend config
  POST /setup/model    — update inference backend config + write .env
  POST /setup/ollama/start — start ollama serve in background
"""

from __future__ import annotations

import contextlib
import json
import subprocess
from pathlib import Path
from typing import Any, Literal

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
from prompts.suggestions import (
    SYSTEM_PROMPT as SUGGEST_SYSTEM,
)
from prompts.suggestions import (
    build_prompt as build_suggest_prompt,
)
from prompts.suggestions import (
    build_schema_summary,
)

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
    llamacpp_healthy: bool
    db_connected: bool


class SuggestionsResponse(BaseModel):
    questions: list[str]


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
# GET /suggest
# ---------------------------------------------------------------------------

@router.get(
    "/suggest",
    response_model=SuggestionsResponse,
    summary="Generate 3 example questions for the connected database",
)
async def get_suggestions(request: Request) -> SuggestionsResponse:
    """Generate 3 schema-aware example questions via the LLM.

    Results are cached on app state after the first call so subsequent
    requests are instant and don't consume LLM tokens.
    """
    # Return cached suggestions if already generated
    cached: list[str] | None = getattr(request.app.state, "cached_suggestions", None)
    if cached:
        return SuggestionsResponse(questions=cached)

    pipeline: MercerPipeline = request.app.state.pipeline
    fallback = [
        "How many records are in the largest table?",
        "Which rows were most recently added?",
        "Show the top 10 entries by primary key.",
    ]

    try:
        schema = await pipeline._load_schema()
        if not schema.tables:
            return SuggestionsResponse(questions=fallback)

        summary = build_schema_summary(schema.tables)
        prompt = build_suggest_prompt(summary, schema.glossary)

        backend = await pipeline._router.get_backend_async(0.2)
        raw = await backend.generate(
            prompt,
            system=SUGGEST_SYSTEM,
            temperature=0.7,
            max_tokens=256,
            is_json=True,
        )

        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) >= 1:
            questions = [str(q) for q in parsed[:3]]
        else:
            questions = fallback

    except Exception as exc:
        logger.warning("suggestions_failed", error=str(exc))
        questions = fallback

    request.app.state.cached_suggestions = questions
    return SuggestionsResponse(questions=questions)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness and dependency health check",
)
async def get_health(request: Request) -> HealthResponse:
    """Return liveness status and dependency health (DB reachability, llama.cpp health)."""
    engine = getattr(request.app.state, "engine", None)

    db_connected = False
    if engine is not None:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_connected = True
        except Exception:  # noqa: BLE001
            db_connected = False

    llamacpp_healthy = False
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is not None:
        router_obj = getattr(pipeline, "_router", None)
        if router_obj is not None:
            local = getattr(router_obj, "_local", None)
            if local is not None:
                with contextlib.suppress(Exception):
                    llamacpp_healthy = await local.health_check()

    return HealthResponse(
        status="ok",
        llamacpp_healthy=llamacpp_healthy,
        db_connected=db_connected,
    )


# ---------------------------------------------------------------------------
# GET /setup/model  —  current inference config
# POST /setup/model  —  update inference backend + write .env
# POST /setup/ollama/start  —  start ollama serve in the background
# ---------------------------------------------------------------------------

class ModelSetupRequest(BaseModel):
    backend: Literal["llamacpp", "ollama", "anthropic", "openai"]
    api_key: str = Field("", description="API key (Anthropic or OpenAI)")
    model: str = Field("", description="Model name override")
    server_url: str = Field("", description="Local server URL (llama.cpp / ollama)")


class ModelSetupResponse(BaseModel):
    backend: str
    llamacpp_url: str
    anthropic_model: str
    openai_model: str
    anthropic_key_set: bool
    openai_key_set: bool


@router.get("/setup/model", response_model=ModelSetupResponse, summary="Current inference config")
async def get_model_setup() -> ModelSetupResponse:
    """Return current inference backend settings (keys are never exposed, only whether set)."""
    return ModelSetupResponse(
        backend=settings.inference_backend,
        llamacpp_url=settings.llamacpp_url,
        anthropic_model=settings.anthropic_model,
        openai_model=settings.openai_model,
        anthropic_key_set=bool(settings.anthropic_api_key),
        openai_key_set=bool(settings.openai_api_key),
    )


def _write_env(updates: dict[str, str]) -> None:
    """Upsert key=value pairs in .env, creating the file if absent."""
    env_path = Path(".env")
    existing = env_path.read_text().splitlines() if env_path.exists() else []
    written: set[str] = set()
    new_lines: list[str] = []
    for line in existing:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            new_lines.append(line)
    for key, val in updates.items():
        if key not in written:
            new_lines.append(f"{key}={val}")
    env_path.write_text("\n".join(new_lines) + "\n")


@router.post("/setup/model", summary="Update inference backend config")
async def update_model_setup(req: ModelSetupRequest) -> dict[str, object]:
    """Persist inference config to .env and update in-memory settings.

    Changes take effect immediately for the running process.
    Restart the server for a clean reload from .env.
    """
    env_updates: dict[str, str] = {}

    if req.backend == "ollama":
        url = req.server_url or "http://localhost:11434"
        env_updates["INFERENCE_BACKEND"] = "llamacpp"
        env_updates["LLAMACPP_URL"] = url
        settings.inference_backend = "llamacpp"
        settings.llamacpp_url = url
    elif req.backend == "llamacpp":
        url = req.server_url or settings.llamacpp_url
        env_updates["INFERENCE_BACKEND"] = "llamacpp"
        env_updates["LLAMACPP_URL"] = url
        settings.inference_backend = "llamacpp"
        settings.llamacpp_url = url
    elif req.backend == "anthropic":
        env_updates["INFERENCE_BACKEND"] = "anthropic"
        settings.inference_backend = "anthropic"
        if req.api_key:
            env_updates["ANTHROPIC_API_KEY"] = req.api_key
            settings.anthropic_api_key = req.api_key
        if req.model:
            env_updates["ANTHROPIC_MODEL"] = req.model
            settings.anthropic_model = req.model
    elif req.backend == "openai":
        env_updates["INFERENCE_BACKEND"] = "openai"
        settings.inference_backend = "openai"
        if req.api_key:
            env_updates["OPENAI_API_KEY"] = req.api_key
            settings.openai_api_key = req.api_key
        if req.model:
            env_updates["OPENAI_MODEL"] = req.model
            settings.openai_model = req.model

    _write_env(env_updates)
    logger.info("model_setup_updated", backend=req.backend)
    return {"ok": True, "backend": req.backend}


async def _ollama_already_running() -> bool:
    """Return True if ollama serve is already listening on localhost:11434."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get("http://localhost:11434")
            return r.status_code < 500
    except Exception:
        return False


@router.get("/setup/ollama/status", summary="Check whether ollama serve is running")
async def get_ollama_status() -> dict[str, object]:
    """Return whether ollama serve is currently listening on port 11434."""
    running = await _ollama_already_running()
    return {"running": running}


@router.post("/setup/ollama/start", summary="Start ollama serve in background")
async def start_ollama() -> dict[str, object]:
    """Launch `ollama serve` as a detached background process.

    If ollama serve is already running on port 11434, returns immediately
    without spawning a second process. Returns immediately after spawn —
    poll GET /setup/ollama/status to confirm the server is up.
    """
    if await _ollama_already_running():
        logger.info("ollama_serve_already_running")
        return {"ok": True, "already_running": True, "message": "ollama serve is already running"}

    result = subprocess.run(["which", "ollama"], capture_output=True, text=True)  # noqa: S603, S607
    if result.returncode != 0:
        return {"ok": False, "error": "ollama not found. Install from https://ollama.ai"}

    try:
        subprocess.Popen(  # noqa: S603, S607
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("ollama_serve_started")
        return {"ok": True, "already_running": False, "message": "ollama serve started in background"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
