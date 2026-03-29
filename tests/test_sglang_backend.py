"""Tests for SGLangBackend and ModelRouter SGLang integration.

All tests mock httpx.AsyncClient so no real server is required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inference.sglang_backend import SGLangBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completion_response(content: str) -> MagicMock:
    """Build a mock httpx.Response that looks like an OAI chat completion."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
    }
    return mock_resp


def _make_health_response(status_code: int = 200) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    return mock_resp


# ---------------------------------------------------------------------------
# SGLangBackend.generate
# ---------------------------------------------------------------------------

class TestSGLangBackendGenerate:

    @pytest.mark.asyncio
    async def test_generate_returns_content(self) -> None:
        backend = SGLangBackend("http://localhost:30000")
        expected = "SELECT COUNT(*) FROM customers;"
        with patch.object(backend._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_completion_response(expected)
            result = await backend.generate("count customers", "You are SQL.")
        assert result == expected

    @pytest.mark.asyncio
    async def test_generate_sends_system_message(self) -> None:
        backend = SGLangBackend("http://localhost:30000")
        with patch.object(backend._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_completion_response("ok")
            await backend.generate("question", "my system prompt")

        call_kwargs: dict[str, Any] = dict(mock_post.call_args.kwargs)
        messages = call_kwargs["json"]["messages"]
        assert messages[0] == {"role": "system", "content": "my system prompt"}
        assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_generate_sends_correct_url(self) -> None:
        backend = SGLangBackend("http://myserver:9000")
        with patch.object(backend._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_completion_response("ok")
            await backend.generate("q", "s")

        url_arg = mock_post.call_args.args[0]
        assert url_arg == "http://myserver:9000/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_generate_passes_temperature_and_max_tokens(self) -> None:
        backend = SGLangBackend("http://localhost:30000")
        with patch.object(backend._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_completion_response("x")
            await backend.generate("q", "s", temperature=0.5, max_tokens=512)

        payload = mock_post.call_args.kwargs["json"]
        assert payload["temperature"] == 0.5
        assert payload["max_tokens"] == 512

    @pytest.mark.asyncio
    async def test_generate_strips_trailing_slash_from_base_url(self) -> None:
        backend = SGLangBackend("http://localhost:30000/")
        with patch.object(backend._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_completion_response("ok")
            await backend.generate("q", "s")

        url_arg = mock_post.call_args.args[0]
        assert "//v1" not in url_arg
        assert url_arg.endswith("/v1/chat/completions")


# ---------------------------------------------------------------------------
# SGLangBackend.health_check
# ---------------------------------------------------------------------------

class TestSGLangBackendHealthCheck:

    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_200(self) -> None:
        backend = SGLangBackend("http://localhost:30000")
        with patch.object(backend._client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _make_health_response(200)
            assert await backend.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_503(self) -> None:
        backend = SGLangBackend("http://localhost:30000")
        with patch.object(backend._client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _make_health_response(503)
            assert await backend.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_connection_error(self) -> None:
        backend = SGLangBackend("http://localhost:30000")
        with patch.object(
            backend._client, "get", new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            assert await backend.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_hits_correct_url(self) -> None:
        backend = SGLangBackend("http://myserver:9000")
        with patch.object(backend._client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _make_health_response(200)
            await backend.health_check()

        url_arg = mock_get.call_args.args[0]
        assert url_arg == "http://myserver:9000/health"


# ---------------------------------------------------------------------------
# SGLangBackend.generate_batch
# ---------------------------------------------------------------------------

class TestSGLangBackendGenerateBatch:

    @pytest.mark.asyncio
    async def test_generate_batch_returns_all_results(self) -> None:
        backend = SGLangBackend("http://localhost:30000")
        responses = ["SQL1", "SQL2", "SQL3"]
        call_count = 0

        async def fake_generate(prompt: str, system: str, temperature: float = 0.0, max_tokens: int = 1024) -> str:
            nonlocal call_count
            result = responses[call_count]
            call_count += 1
            return result

        with patch.object(backend, "generate", side_effect=fake_generate):
            results = await backend.generate_batch(
                ["q1", "q2", "q3"], system="sys"
            )

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_generate_batch_empty_input(self) -> None:
        backend = SGLangBackend("http://localhost:30000")
        results = await backend.generate_batch([], system="sys")
        assert results == []


# ---------------------------------------------------------------------------
# ModelRouter falls back to API when SGLang is unhealthy
# ---------------------------------------------------------------------------

class TestModelRouterFallback:

    @pytest.mark.asyncio
    async def test_router_falls_back_to_api_when_sglang_unhealthy(self) -> None:
        from config.settings import Settings
        from inference.api_backend import AnthropicBackend
        from inference.router import ModelRouter

        cfg = Settings(
            sglang_url="http://localhost:30000",
            inference_backend="anthropic",
            anthropic_api_key="test-key",
        )
        router = ModelRouter(cfg)
        assert router._sglang_backend is not None

        # Simulate health_check failing
        with patch.object(
            router._sglang_backend,
            "health_check",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await router._ensure_sglang_health_async()

        assert router._sglang_healthy is False
        backend = router.get_backend(0.1)
        assert isinstance(backend, AnthropicBackend)

    @pytest.mark.asyncio
    async def test_router_uses_sglang_when_healthy(self) -> None:
        from config.settings import Settings
        from inference.router import ModelRouter

        cfg = Settings(
            sglang_url="http://localhost:30000",
            inference_backend="anthropic",
            anthropic_api_key="test-key",
        )
        router = ModelRouter(cfg)

        with patch.object(
            router._sglang_backend,
            "health_check",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await router._ensure_sglang_health_async()

        assert router._sglang_healthy is True
        backend = router.get_backend(0.1)
        assert isinstance(backend, SGLangBackend)

    @pytest.mark.asyncio
    async def test_router_high_complexity_always_api(self) -> None:
        from config.settings import Settings
        from inference.api_backend import AnthropicBackend
        from inference.router import ModelRouter

        cfg = Settings(
            sglang_url="http://localhost:30000",
            inference_backend="anthropic",
            anthropic_api_key="test-key",
        )
        router = ModelRouter(cfg)

        # Even when SGLang is healthy, score >= 0.7 → API
        with patch.object(
            router._sglang_backend,
            "health_check",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await router._ensure_sglang_health_async()

        backend = router.get_backend(0.9)
        assert isinstance(backend, AnthropicBackend)

    @pytest.mark.asyncio
    async def test_router_no_sglang_url_all_api(self) -> None:
        from config.settings import Settings
        from inference.api_backend import AnthropicBackend
        from inference.router import ModelRouter

        cfg = Settings(
            sglang_url="",
            inference_backend="anthropic",
            anthropic_api_key="test-key",
        )
        router = ModelRouter(cfg)
        assert router._sglang_backend is None

        for score in [0.1, 0.5, 0.9]:
            assert isinstance(router.get_backend(score), AnthropicBackend)

    def test_router_health_not_checked_until_get_backend(self) -> None:
        from config.settings import Settings
        from inference.router import ModelRouter

        cfg = Settings(sglang_url="http://localhost:30000")
        router = ModelRouter(cfg)
        # _sglang_healthy starts as None (not yet probed)
        assert router._sglang_healthy is None
