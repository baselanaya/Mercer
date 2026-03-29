"""LLMBackend — protocol and default batch implementation."""

from __future__ import annotations

import asyncio
from typing import Protocol


class LLMBackend(Protocol):
    """Protocol for all LLM inference backends.

    Backends must implement `generate()`. `generate_batch()` has a default
    implementation that fans out to `generate()` via asyncio.gather — backends
    can override it if the underlying API supports true batch endpoints.
    """

    async def generate(
        self,
        prompt: str,
        system: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Send a single prompt to the LLM and return the generated text."""
        ...

    async def generate_batch(
        self,
        prompts: list[str],
        system: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> list[str]:
        """Default: concurrent fan-out over generate(). Override for native batch APIs."""
        results = await asyncio.gather(*(
            self.generate(p, system, temperature, max_tokens)
            for p in prompts
        ))
        return list(results)
