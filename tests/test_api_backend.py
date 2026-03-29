"""Tests for AnthropicBackend, OpenAIBackend, and ModelRouter.

All tests use mocked SDK clients — no real API calls.
Tenacity's async sleep is patched to keep tests instant.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import openai
import pytest

from inference.api_backend import AnthropicBackend, OpenAIBackend, _strip_thinking
from inference.router import ModelRouter

# ---------------------------------------------------------------------------
# Helpers — build SDK rate-limit errors without real HTTP responses
# ---------------------------------------------------------------------------

def _anthropic_rate_limit() -> anthropic.RateLimitError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code=429, request=request)
    return anthropic.RateLimitError(
        message="rate limit exceeded", response=response, body=None
    )


def _openai_rate_limit() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return openai.RateLimitError(
        message="rate limit exceeded", response=response, body=None
    )


def _anthropic_response(text: str) -> MagicMock:
    """Minimal mock of anthropic.types.Message with one text block."""
    msg = MagicMock()
    msg.content = [anthropic.types.TextBlock(text=text, type="text")]
    return msg


def _openai_response(text: str) -> MagicMock:
    """Minimal mock of openai.types.chat.ChatCompletion."""
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = text
    return completion


# ---------------------------------------------------------------------------
# _strip_thinking — unit tests
# ---------------------------------------------------------------------------

def test_strip_thinking_removes_block() -> None:
    text = "<thinking>internal reasoning here</thinking>SELECT 1"
    assert _strip_thinking(text) == "SELECT 1"


def test_strip_thinking_multiline() -> None:
    text = "<thinking>\nline 1\nline 2\n</thinking>\nSELECT 2"
    assert _strip_thinking(text) == "SELECT 2"


def test_strip_thinking_no_block() -> None:
    text = "SELECT * FROM film"
    assert _strip_thinking(text) == "SELECT * FROM film"


def test_strip_thinking_multiple_blocks() -> None:
    text = "<thinking>first</thinking>A<thinking>second</thinking>B"
    assert _strip_thinking(text) == "AB"


# ---------------------------------------------------------------------------
# AnthropicBackend.generate — basic behaviour
# ---------------------------------------------------------------------------

async def test_anthropic_generate_returns_string() -> None:
    backend = AnthropicBackend(api_key="test-key")
    backend._client.messages.create = AsyncMock(
        return_value=_anthropic_response("SELECT 1")
    )
    result = await backend.generate("list films", "You are SQL expert", 0.0, 256)
    assert result == "SELECT 1"


async def test_anthropic_generate_calls_create_with_correct_model() -> None:
    backend = AnthropicBackend(api_key="test-key", model="claude-test")
    mock_create = AsyncMock(return_value=_anthropic_response("ok"))
    backend._client.messages.create = mock_create
    await backend.generate("q", "sys", 0.0, 128)
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "claude-test"


async def test_anthropic_generate_passes_temperature() -> None:
    backend = AnthropicBackend(api_key="test-key")
    mock_create = AsyncMock(return_value=_anthropic_response("ok"))
    backend._client.messages.create = mock_create
    await backend.generate("q", "sys", temperature=0.7, max_tokens=512)
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["temperature"] == 0.7
    assert call_kwargs["max_tokens"] == 512


async def test_anthropic_generate_strips_thinking_tags() -> None:
    backend = AnthropicBackend(api_key="test-key")
    backend._client.messages.create = AsyncMock(
        return_value=_anthropic_response(
            "<thinking>Step 1: identify tables</thinking>SELECT film_id FROM film"
        )
    )
    result = await backend.generate("q", "sys")
    assert result == "SELECT film_id FROM film"
    assert "<thinking>" not in result


# ---------------------------------------------------------------------------
# AnthropicBackend.generate — retry on rate limit
# ---------------------------------------------------------------------------

async def test_anthropic_retry_fires_on_rate_limit() -> None:
    backend = AnthropicBackend(api_key="test-key")
    backend._client.messages.create = AsyncMock(
        side_effect=[_anthropic_rate_limit(), _anthropic_response("SELECT 1")]
    )
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await backend.generate("q", "sys")
    assert result == "SELECT 1"
    assert backend._client.messages.create.call_count == 2


async def test_anthropic_retry_reraises_after_max_attempts() -> None:
    backend = AnthropicBackend(api_key="test-key")
    backend._client.messages.create = AsyncMock(
        side_effect=[
            _anthropic_rate_limit(),
            _anthropic_rate_limit(),
            _anthropic_rate_limit(),
        ]
    )
    with patch("asyncio.sleep", new_callable=AsyncMock), pytest.raises(anthropic.RateLimitError):
        await backend.generate("q", "sys")
    assert backend._client.messages.create.call_count == 3


async def test_anthropic_no_retry_on_non_rate_limit_error() -> None:
    """Non-rate-limit errors should propagate immediately without retry."""
    backend = AnthropicBackend(api_key="test-key")
    backend._client.messages.create = AsyncMock(
        side_effect=anthropic.APIConnectionError(request=MagicMock())
    )
    with pytest.raises(anthropic.APIConnectionError):
        await backend.generate("q", "sys")
    assert backend._client.messages.create.call_count == 1


# ---------------------------------------------------------------------------
# AnthropicBackend.generate_batch
# ---------------------------------------------------------------------------

async def test_anthropic_generate_batch_correct_length() -> None:
    backend = AnthropicBackend(api_key="test-key")
    backend._client.messages.create = AsyncMock(
        side_effect=[
            _anthropic_response("SQL 1"),
            _anthropic_response("SQL 2"),
            _anthropic_response("SQL 3"),
        ]
    )
    results = await backend.generate_batch(["p1", "p2", "p3"], "sys")
    assert len(results) == 3


async def test_anthropic_generate_batch_results_match() -> None:
    backend = AnthropicBackend(api_key="test-key")
    expected = ["SELECT 1", "SELECT 2", "SELECT 3"]
    backend._client.messages.create = AsyncMock(
        side_effect=[_anthropic_response(t) for t in expected]
    )
    results = await backend.generate_batch(["p1", "p2", "p3"], "sys")
    assert set(results) == set(expected)


async def test_anthropic_generate_batch_empty_input() -> None:
    backend = AnthropicBackend(api_key="test-key")
    backend._client.messages.create = AsyncMock()
    results = await backend.generate_batch([], "sys")
    assert results == []
    backend._client.messages.create.assert_not_called()


# ---------------------------------------------------------------------------
# OpenAIBackend.generate — basic behaviour
# ---------------------------------------------------------------------------

async def test_openai_generate_returns_string() -> None:
    backend = OpenAIBackend(api_key="test-key")
    backend._client.chat.completions.create = AsyncMock(
        return_value=_openai_response("SELECT 1")
    )
    result = await backend.generate("list films", "You are SQL expert", 0.0, 256)
    assert result == "SELECT 1"


async def test_openai_generate_calls_create_with_correct_model() -> None:
    backend = OpenAIBackend(api_key="test-key", model="gpt-test")
    mock_create = AsyncMock(return_value=_openai_response("ok"))
    backend._client.chat.completions.create = mock_create
    await backend.generate("q", "sys", 0.0, 128)
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-test"


async def test_openai_generate_passes_system_message() -> None:
    backend = OpenAIBackend(api_key="test-key")
    mock_create = AsyncMock(return_value=_openai_response("ok"))
    backend._client.chat.completions.create = mock_create
    await backend.generate("user prompt", "system content")
    messages = mock_create.call_args.kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "system content"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "user prompt"


async def test_openai_generate_strips_thinking_tags() -> None:
    backend = OpenAIBackend(api_key="test-key")
    backend._client.chat.completions.create = AsyncMock(
        return_value=_openai_response(
            "<thinking>reasoning</thinking>SELECT * FROM orders"
        )
    )
    result = await backend.generate("q", "sys")
    assert result == "SELECT * FROM orders"


# ---------------------------------------------------------------------------
# OpenAIBackend.generate — retry on rate limit
# ---------------------------------------------------------------------------

async def test_openai_retry_fires_on_rate_limit() -> None:
    backend = OpenAIBackend(api_key="test-key")
    backend._client.chat.completions.create = AsyncMock(
        side_effect=[_openai_rate_limit(), _openai_response("SELECT 1")]
    )
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await backend.generate("q", "sys")
    assert result == "SELECT 1"
    assert backend._client.chat.completions.create.call_count == 2


async def test_openai_retry_reraises_after_max_attempts() -> None:
    backend = OpenAIBackend(api_key="test-key")
    backend._client.chat.completions.create = AsyncMock(
        side_effect=[_openai_rate_limit()] * 3
    )
    with patch("asyncio.sleep", new_callable=AsyncMock), pytest.raises(openai.RateLimitError):
        await backend.generate("q", "sys")
    assert backend._client.chat.completions.create.call_count == 3


# ---------------------------------------------------------------------------
# OpenAIBackend.generate_batch
# ---------------------------------------------------------------------------

async def test_openai_generate_batch_correct_length() -> None:
    backend = OpenAIBackend(api_key="test-key")
    backend._client.chat.completions.create = AsyncMock(
        side_effect=[
            _openai_response("SQL A"),
            _openai_response("SQL B"),
        ]
    )
    results = await backend.generate_batch(["p1", "p2"], "sys")
    assert len(results) == 2


async def test_openai_generate_batch_results_match() -> None:
    backend = OpenAIBackend(api_key="test-key")
    expected = ["SELECT a", "SELECT b", "SELECT c"]
    backend._client.chat.completions.create = AsyncMock(
        side_effect=[_openai_response(t) for t in expected]
    )
    results = await backend.generate_batch(["p1", "p2", "p3"], "sys")
    assert set(results) == set(expected)


# ---------------------------------------------------------------------------
# ModelRouter — complexity scoring
# ---------------------------------------------------------------------------

def test_score_complexity_short_simple() -> None:
    router = ModelRouter()
    score = router.score_complexity("list customers", num_tables=1, has_subqueries=False)
    assert 0.0 <= score < 0.3


def test_score_complexity_long_query() -> None:
    router = ModelRouter()
    long_q = " ".join(["word"] * 60)  # 60 words > 50 word threshold
    score = router.score_complexity(long_q, num_tables=1, has_subqueries=False)
    assert score > 0.3


def test_score_complexity_many_tables_bumps_score() -> None:
    router = ModelRouter()
    low = router.score_complexity("simple query", num_tables=1, has_subqueries=False)
    high = router.score_complexity("simple query", num_tables=8, has_subqueries=False)
    assert high > low


def test_score_complexity_subquery_bumps_score() -> None:
    router = ModelRouter()
    without = router.score_complexity("q", num_tables=2, has_subqueries=False)
    with_sub = router.score_complexity("q", num_tables=2, has_subqueries=True)
    assert with_sub > without


def test_score_complexity_clamped_at_one() -> None:
    router = ModelRouter()
    score = router.score_complexity(
        " ".join(["word"] * 200), num_tables=20, has_subqueries=True
    )
    assert score == 1.0


def test_score_complexity_returns_float() -> None:
    router = ModelRouter()
    score = router.score_complexity("q", 3, False)
    assert isinstance(score, float)


# ---------------------------------------------------------------------------
# ModelRouter — backend selection
# ---------------------------------------------------------------------------

def test_router_returns_backend_for_low_complexity() -> None:
    router = ModelRouter()
    backend = router.get_backend(0.1)
    # Duck-type check: must have generate and generate_batch
    assert hasattr(backend, "generate")
    assert hasattr(backend, "generate_batch")


def test_router_returns_backend_for_high_complexity() -> None:
    router = ModelRouter()
    backend = router.get_backend(0.9)
    assert hasattr(backend, "generate")


def test_router_caches_api_backend() -> None:
    """Calling get_backend multiple times returns the same instance."""
    router = ModelRouter()
    b1 = router.get_backend(0.1)
    b2 = router.get_backend(0.8)
    assert b1 is b2  # same cached instance


def test_router_uses_openai_when_configured() -> None:
    from config.settings import Settings
    cfg = Settings(inference_backend="openai", openai_api_key="k")
    router = ModelRouter(cfg=cfg)
    backend = router.get_backend(0.5)
    assert isinstance(backend, OpenAIBackend)


def test_router_uses_anthropic_when_configured() -> None:
    from config.settings import Settings
    cfg = Settings(inference_backend="anthropic", anthropic_api_key="k")
    router = ModelRouter(cfg=cfg)
    backend = router.get_backend(0.5)
    assert isinstance(backend, AnthropicBackend)
