"""SGLang async backend — calls the OpenAI-compatible endpoint SGLang exposes.

SGLang serves Qwen2.5-Coder-7B-Instruct locally and exposes a
``/v1/chat/completions`` endpoint that matches the OpenAI Chat API.

Retries on transient HTTP/connection failures with exponential backoff
(3 attempts, 1s–8s window).
"""

from __future__ import annotations

import asyncio

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from core.logging import get_logger
from inference.base import LLMBackend

_logger = get_logger(__name__)


class SGLangBackend(LLMBackend):
    """Async inference backend for a locally-running SGLang server.

    SGLang exposes an OpenAI-compatible ``/v1/chat/completions`` endpoint,
    so the request payload is identical to what ``OpenAIBackend`` sends.
    """

    def __init__(self, base_url: str = "http://localhost:30000") -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120.0)

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        system: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        return await self._call(prompt, system, temperature, max_tokens)

    async def generate_batch(
        self,
        prompts: list[str],
        system: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> list[str]:
        """Fan out to generate() concurrently — SGLang queues requests internally."""
        results = await asyncio.gather(*(
            self.generate(p, system, temperature, max_tokens)
            for p in prompts
        ))
        return list(results)

    # ------------------------------------------------------------------
    # Health probe
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Return True if the SGLang server is reachable and healthy."""
        try:
            resp = await self._client.get(f"{self._base_url}/health")
            return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _call(
        self,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = await self._client.post(
            f"{self._base_url}/v1/chat/completions",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["choices"][0]["message"]["content"])
