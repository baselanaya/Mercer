"""Mercer FastAPI application factory.

Usage:
    # Run the server
    uvicorn app.api.main:app --reload --port 8000

    # Or use the factory to inject a custom pipeline (e.g. tests):
    from app.api.main import create_app
    app = create_app(pipeline=my_mock_pipeline)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from app.api import routes, websocket
from app.api.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from config.settings import settings
from core.logging import get_logger
from core.pipeline import MercerPipeline

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Allowed CORS origins (development)
# ---------------------------------------------------------------------------
_CORS_ORIGINS = [
    "http://localhost:3000",   # CRA / Next.js default
    "http://localhost:5173",   # Vite default
    "http://localhost:8000",   # uvicorn (same-origin dev)
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
]


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(pipeline: MercerPipeline | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        pipeline: Optional pre-built pipeline.  When provided the startup
                  lifecycle skips DB / Redis initialisation and uses the
                  injected pipeline directly.  Pass a mock here in tests.

    Returns:
        Configured FastAPI instance.
    """
    _injected = pipeline  # captured in lifespan closure

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # ---- startup ----
        if _injected is not None:
            app.state.pipeline = _injected
            app.state.engine = None
            logger.info("startup_injected_pipeline")
        else:
            from sqlalchemy.ext.asyncio import create_async_engine

            engine = create_async_engine(settings.database_url, echo=False)
            pl = MercerPipeline(
                db_engine=engine,
                redis_url=settings.redis_url,
                audit_path=settings.audit_path,
            )
            app.state.pipeline = pl
            app.state.engine = engine
            logger.info(
                "startup_complete",
                db_url=settings.database_url,
                redis_url=settings.redis_url,
                audit_path=settings.audit_path,
            )

        yield

        # ---- shutdown ----
        _shutdown_engine: object = getattr(app.state, "engine", None)
        if _shutdown_engine is not None:
            await _shutdown_engine.dispose()  # type: ignore[attr-defined]
            logger.info("shutdown_db_disposed")

    # Build app
    application = FastAPI(
        title="Mercer",
        description="Natural Language to SQL — REST + WebSocket API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Middleware — outermost first (CORS → rate-limit → logging)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RateLimitMiddleware, max_requests=10, window_seconds=60)
    application.add_middleware(RequestLoggingMiddleware)

    # Routers
    application.include_router(routes.router)
    application.include_router(websocket.router)

    # Serve React UI static files if the dist directory exists
    _ui_dist = Path(__file__).parent.parent / "ui" / "dist"
    if _ui_dist.is_dir():
        application.mount("/", StaticFiles(directory=str(_ui_dist), html=True), name="ui")

    return application


# ---------------------------------------------------------------------------
# Default app instance (used by uvicorn)
# ---------------------------------------------------------------------------
app = create_app()
