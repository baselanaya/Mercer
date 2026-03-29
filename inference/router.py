"""ModelRouter — routes queries to the appropriate LLM backend by complexity.

Complexity tiers:
  score < 0.3   → low  tier  → SGLangBackend (local 7B) when healthy, else API
  score < 0.7   → mid  tier  → SGLangBackend (local 7B) when healthy, else API
  score >= 0.7  → high tier  → AnthropicBackend (always API)

SGLang health is checked once on first use of ``get_backend()``.  If the
server is unreachable at that point, the router falls back to the API
backend for all tiers until the next process start.

Complexity score components (all normalised 0–1, clamped to [0, 1]):
  word_score     = question word count / 50       (weight 0.5)
  table_score    = num_tables / 10                (weight 0.3)
  subquery_score = 1.0 if has_subqueries else 0   (weight 0.2)
"""

from __future__ import annotations

import asyncio

from config.settings import Settings
from config.settings import settings as _default_settings
from core.logging import get_logger
from inference.api_backend import AnthropicBackend, OpenAIBackend
from inference.base import LLMBackend
from inference.sglang_backend import SGLangBackend

_logger = get_logger(__name__)

_LOW_THRESHOLD: float = 0.3
_MID_THRESHOLD: float = 0.7

# Complexity score weights
_W_WORDS: float = 0.5
_W_TABLES: float = 0.3
_W_SUBQUERY: float = 0.2

# Normalisation denominators
_MAX_WORDS: int = 50
_MAX_TABLES: int = 10


class ModelRouter:
    """Routes a query to the cheapest backend that can handle its complexity."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self._cfg = cfg or _default_settings
        self._api_backend: LLMBackend | None = None
        self._sglang_backend: SGLangBackend | None = None
        self._sglang_healthy: bool | None = None  # None = not yet checked

        # Pre-initialise SGLang if configured
        if self._cfg.sglang_url:
            self._sglang_backend = SGLangBackend(self._cfg.sglang_url)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def score_complexity(
        self,
        question: str,
        num_tables: int,
        has_subqueries: bool,
    ) -> float:
        """Return a complexity score in [0.0, 1.0]."""
        word_score = min(len(question.split()) / _MAX_WORDS, 1.0)
        table_score = min(num_tables / _MAX_TABLES, 1.0)
        subquery_score = 1.0 if has_subqueries else 0.0

        raw = (
            _W_WORDS * word_score
            + _W_TABLES * table_score
            + _W_SUBQUERY * subquery_score
        )
        return min(raw, 1.0)

    def get_backend(self, complexity_score: float) -> LLMBackend:
        """Return the appropriate backend for the given complexity score.

        On first call this triggers an async health check for SGLang (run
        in the current event loop if one exists, else checked synchronously).
        Subsequent calls use the cached result.
        """
        self._ensure_sglang_health()

        if complexity_score < _LOW_THRESHOLD:
            return self._low_tier()
        if complexity_score < _MID_THRESHOLD:
            return self._mid_tier()
        return self._high_tier()

    async def get_backend_async(self, complexity_score: float) -> LLMBackend:
        """Async variant of get_backend — awaits the health check properly."""
        await self._ensure_sglang_health_async()

        if complexity_score < _LOW_THRESHOLD:
            return self._low_tier()
        if complexity_score < _MID_THRESHOLD:
            return self._mid_tier()
        return self._high_tier()

    # ------------------------------------------------------------------
    # Tier resolution
    # ------------------------------------------------------------------

    def _low_tier(self) -> LLMBackend:
        if self._sglang_healthy and self._sglang_backend is not None:
            return self._sglang_backend
        return self._get_api_backend()

    def _mid_tier(self) -> LLMBackend:
        if self._sglang_healthy and self._sglang_backend is not None:
            return self._sglang_backend
        return self._get_api_backend()

    def _high_tier(self) -> LLMBackend:
        return self._get_api_backend()

    def _get_api_backend(self) -> LLMBackend:
        """Lazy-init the API backend. Cached after first call."""
        if self._api_backend is None:
            if self._cfg.inference_backend == "openai":
                self._api_backend = OpenAIBackend()
            else:
                self._api_backend = AnthropicBackend()
        return self._api_backend

    # ------------------------------------------------------------------
    # SGLang health management
    # ------------------------------------------------------------------

    def _ensure_sglang_health(self) -> None:
        """Run the async health check synchronously if not yet done."""
        if self._sglang_healthy is not None or self._sglang_backend is None:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Inside an async context — schedule; health stays None this call,
                # caller gets API backend as safe default.
                loop.create_task(self._ensure_sglang_health_async())
                self._sglang_healthy = False  # conservative until confirmed
            else:
                self._sglang_healthy = loop.run_until_complete(
                    self._sglang_backend.health_check()
                )
        except Exception:
            self._sglang_healthy = False

        if self._sglang_healthy:
            _logger.info("SGLang backend healthy", url=self._cfg.sglang_url)
        else:
            _logger.warning(
                "SGLang backend unreachable — falling back to API",
                url=self._cfg.sglang_url,
            )

    async def _ensure_sglang_health_async(self) -> None:
        """Async health check — call from async contexts."""
        if self._sglang_healthy is not None or self._sglang_backend is None:
            return
        try:
            self._sglang_healthy = await self._sglang_backend.health_check()
        except Exception:
            self._sglang_healthy = False

        if self._sglang_healthy:
            _logger.info("SGLang backend healthy", url=self._cfg.sglang_url)
        else:
            _logger.warning(
                "SGLang backend unreachable — falling back to API",
                url=self._cfg.sglang_url,
            )
