"""WebSocket endpoint — /ws/query.

Protocol (JSON messages, one per send):
  Client → server:  {"question": "<nl question>"}
  Server → client:  {"type": "started",        "question": "..."}
                    {"type": "stage_complete",  "stage": "<name>", "latency_ms": <float>}
                    {"type": "complete",        "sql": "...", "execution_result": {...}}
                    {"type": "error",           "detail": "..."}

Since the current LLM backends do not expose token-level streaming, the
server runs the full pipeline and then replays the per-stage timing data as
sequential ``stage_complete`` messages before sending the final result.

When the pipeline is extended with streaming backends (Phase 5), replace the
``run()`` call with an async generator and push tokens in real time.
"""

from __future__ import annotations

import contextlib
from typing import Any

from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from core.logging import get_logger
from core.pipeline import MercerPipeline

logger = get_logger(__name__)

router = APIRouter()

# Ordered stage names used to replay progress messages in logical pipeline order
_STAGE_ORDER = [
    "entity_retrieval",
    "schema_linking",
    "query_decomposition",
    "candidate_generation",
    "execution_scoring",
    "correction",
]


@router.websocket("/ws/query")
async def ws_query(websocket: WebSocket) -> None:
    """Handle a single WebSocket session: receive question, stream stage events, send result."""
    await websocket.accept()
    try:
        data: dict[str, Any] = await websocket.receive_json()
        question: str = (data.get("question") or "").strip()

        if not question:
            await websocket.send_json({"type": "error", "detail": "question is required"})
            await websocket.close(code=1003)
            return

        await websocket.send_json({"type": "started", "question": question})

        pipeline: MercerPipeline = websocket.app.state.pipeline

        try:
            state = await pipeline.run(question)
        except Exception as exc:  # noqa: BLE001
            logger.error("ws_pipeline_error", question=question, error=str(exc))
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=1011)
            return

        # Replay per-stage timing as sequential progress messages
        timings = state.stage_timings
        for stage in _STAGE_ORDER:
            if stage in timings:
                await websocket.send_json(
                    {
                        "type": "stage_complete",
                        "stage": stage,
                        "latency_ms": timings[stage],
                    }
                )

        # Final result
        execution_result = None
        if state.best_candidate and state.best_candidate.execution_result:
            execution_result = state.best_candidate.execution_result.model_dump()

        await websocket.send_json(
            {
                "type": "complete",
                "sql": state.final_sql,
                "execution_result": execution_result,
                "latency_ms": (
                    state.audit_entry.total_latency_ms if state.audit_entry else 0.0
                ),
            }
        )

    except WebSocketDisconnect:
        logger.info("ws_disconnected")
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()
