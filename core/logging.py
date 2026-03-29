"""Structured logging setup via structlog.

- Development (LOG_LEVEL=DEBUG or interactive TTY): ColourConsoleRenderer
- Production: JSON renderer, one object per line
- Call get_logger(name) anywhere in the codebase.
"""

from __future__ import annotations

import logging
import sys

import structlog

from config.settings import settings

_configured: bool = False


def configure_logging() -> None:
    """Idempotent: safe to call multiple times."""
    global _configured
    if _configured:
        return

    level_int = getattr(logging, settings.log_level, logging.INFO)

    # Wire stdlib logging so third-party libraries respect our level
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level_int)

    is_dev = settings.log_level == "DEBUG" or sys.stderr.isatty()
    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer(colors=True)
        if is_dev
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> structlog.types.FilteringBoundLogger:
    configure_logging()
    return structlog.get_logger(name)  # type: ignore[no-any-return]
