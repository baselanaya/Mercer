"""Tests for config.settings — environment-driven Settings."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


def test_default_local_model_path_points_at_arctic() -> None:
    """The shipped default LOCAL_MODEL_PATH points at the recommended SOTA model.

    This pin guards against accidental regressions to a non-SQL-tuned
    baseline. If you legitimately want to change the default, also update
    docs/custom-models.md and config/inference.yaml.
    """
    with patch.dict(os.environ, {}, clear=True):
        # Force a fresh Settings instance with no env overrides.
        from config.settings import Settings
        s = Settings(_env_file=None)
        assert "Arctic-Text2SQL-R1-7B" in s.local_model_path
        assert s.local_model_path.endswith(".gguf")


def test_local_model_path_can_be_overridden_via_env() -> None:
    custom = "/tmp/my-custom-model.gguf"
    with patch.dict(os.environ, {"LOCAL_MODEL_PATH": custom}, clear=True):
        from config.settings import Settings
        s = Settings(_env_file=None)
        assert s.local_model_path == custom


def test_anthropic_default_model_is_current() -> None:
    """The Anthropic default tracks the current Opus snapshot."""
    with patch.dict(os.environ, {}, clear=True):
        from config.settings import Settings
        s = Settings(_env_file=None)
        # Doesn't have to be exactly opus-4-7 forever, but should at least
        # be opus-4 family or newer; this guards against silently shipping
        # an obsolete default.
        assert s.anthropic_model.startswith("claude-")
        assert "opus-4" in s.anthropic_model or "opus-5" in s.anthropic_model


def test_inference_backend_default_is_llamacpp() -> None:
    with patch.dict(os.environ, {}, clear=True):
        from config.settings import Settings
        s = Settings(_env_file=None)
        assert s.inference_backend == "llamacpp"


@pytest.mark.parametrize("backend", ["llamacpp", "anthropic", "openai"])
def test_inference_backend_accepts_known_values(backend: str) -> None:
    with patch.dict(os.environ, {"INFERENCE_BACKEND": backend}, clear=True):
        from config.settings import Settings
        s = Settings(_env_file=None)
        assert s.inference_backend == backend
