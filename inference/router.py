"""ModelRouter — routes queries to the appropriate LLM backend by complexity.

Complexity tiers:
  score < 0.3   → low  tier  → local backend (llama.cpp), else API fallback
  score < 0.7   → mid  tier  → local backend (llama.cpp), else API fallback
  score >= 0.7  → high tier  → API backend (Anthropic / OpenAI)

Complexity score components (all normalised 0–1, clamped to [0, 1]):
  word_score     = question word count / 50       (weight 0.5)
  table_score    = num_tables / 10                (weight 0.3)
  subquery_score = 1.0 if has_subqueries else 0   (weight 0.2)
"""

from __future__ import annotations

from config.settings import Settings
from config.settings import settings as _default_settings
from inference.api_backend import AnthropicBackend, OpenAIBackend
from inference.base import LLMBackend
from inference.llamacpp_backend import LlamaCppBackend

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
    """Routes a query to the appropriate backend based on complexity."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self._cfg = cfg or _default_settings
        self._local: LLMBackend | None = None
        self._api: LLMBackend | None = None

        if self._cfg.inference_backend == "llamacpp":
            self._local = LlamaCppBackend(self._cfg.llamacpp_url)

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
        return min(
            _W_WORDS * word_score + _W_TABLES * table_score + _W_SUBQUERY * subquery_score,
            1.0,
        )

    def get_backend(self, complexity_score: float) -> LLMBackend:
        """Return the appropriate backend for the given complexity score."""
        if complexity_score < _MID_THRESHOLD and self._local is not None:
            return self._local
        return self._get_api_backend()

    async def get_backend_async(self, complexity_score: float) -> LLMBackend:
        """Async variant of get_backend (no-op async for interface compatibility)."""
        return self.get_backend(complexity_score)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_api_backend(self) -> LLMBackend:
        if self._api is None:
            if self._cfg.inference_backend == "llamacpp" and self._local is not None:
                # llama.cpp handles all tiers when configured
                self._api = self._local
            elif self._cfg.inference_backend == "openai":
                self._api = OpenAIBackend()
            else:
                self._api = AnthropicBackend()
        return self._api
