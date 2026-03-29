"""Anthropic and OpenAI async backends implementing LLMBackend.

Both backends:
- Use async client libraries
- Retry 3× on rate-limit errors (exponential backoff: 1s → 2s → 4s)
- Strip <thinking>...</thinking> blocks before returning
"""

from __future__ import annotations

import re

import anthropic
import openai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import settings
from inference.base import LLMBackend

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """Remove <thinking>...</thinking> blocks (extended reasoning output)."""
    return _THINKING_RE.sub("", text).strip()


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

class AnthropicBackend(LLMBackend):
    """Async Anthropic backend using the Messages API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._model = model or settings.anthropic_model
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key if api_key is not None else settings.anthropic_api_key
        )

    async def generate(
        self,
        prompt: str,
        system: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Generate a completion using the Anthropic Messages API."""
        return await self._call(prompt, system, temperature, max_tokens)

    @retry(
        retry=retry_if_exception_type(anthropic.RateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def _call(
        self,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [b for b in response.content if isinstance(b, anthropic.types.TextBlock)]
        raw_text = text_blocks[0].text if text_blocks else ""
        return _strip_thinking(raw_text)


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

class OpenAIBackend(LLMBackend):
    """Async OpenAI backend using the Chat Completions API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._model = model or settings.openai_model
        self._client = openai.AsyncOpenAI(
            api_key=api_key if api_key is not None else settings.openai_api_key
        )

    async def generate(
        self,
        prompt: str,
        system: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Generate a completion using the OpenAI Chat Completions API."""
        return await self._call(prompt, system, temperature, max_tokens)

    @retry(
        retry=retry_if_exception_type(openai.RateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def _call(
        self,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return _strip_thinking(response.choices[0].message.content or "")
