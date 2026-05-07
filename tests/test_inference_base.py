"""Tests for inference.base helper functions."""

from __future__ import annotations

import pytest

from inference.base import _expand_temperatures


class TestExpandTemperatures:
    """_expand_temperatures normalizes scalar/list temperature into per-prompt list."""

    def test_scalar_broadcasts_to_n(self) -> None:
        assert _expand_temperatures(0.5, 3) == [0.5, 0.5, 0.5]

    def test_list_pass_through_when_lengths_match(self) -> None:
        assert _expand_temperatures([0.0, 0.2, 0.7], 3) == [0.0, 0.2, 0.7]

    def test_int_is_coerced_to_float(self) -> None:
        result = _expand_temperatures(1, 2)
        assert result == [1.0, 1.0]
        assert all(isinstance(x, float) for x in result)

    def test_list_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="length"):
            _expand_temperatures([0.0, 0.5], 3)

    def test_zero_prompts(self) -> None:
        assert _expand_temperatures(0.0, 0) == []
        assert _expand_temperatures([], 0) == []
