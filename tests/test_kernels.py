"""Tests for the GPU kernel layer — all tests run the CPU path.

We patch kernels.USE_GPU = False (and each module's local copy) before
importing the kernel modules so the factory functions always return CPU
implementations, and no torch/triton calls are made.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Force CPU-only mode before importing kernel modules.
# We patch the USE_GPU flag in the kernels package AND in each kernel module
# so that get_* factory functions return CPU implementations regardless of
# whether a GPU is present.
# ---------------------------------------------------------------------------
# Pre-patch the kernels namespace so CUDA_AVAILABLE / USE_GPU are False
import kernels as _kernels_pkg

_kernels_pkg.CUDA_AVAILABLE = False
_kernels_pkg.USE_GPU = False

import kernels.lsh_hash as _lsh_mod  # noqa: E402
import kernels.result_score as _score_mod  # noqa: E402
import kernels.schema_encode as _enc_mod  # noqa: E402

_lsh_mod.USE_GPU   = False  # type: ignore[attr-defined]
_enc_mod.USE_GPU   = False  # type: ignore[attr-defined]
_score_mod.USE_GPU = False  # type: ignore[attr-defined]

# Now import the public symbols (USE_GPU is already False in each module)
from kernels.lsh_hash import CPULSHMatcher, get_lsh_matcher  # noqa: E402
from kernels.result_score import get_result_scorer, score_consistency_cpu  # noqa: E402
from kernels.schema_encode import get_tokenizer, tokenize_corpus_cpu  # noqa: E402

# ---------------------------------------------------------------------------
# CPULSHMatcher
# ---------------------------------------------------------------------------

class TestCPULSHMatcher:
    """Tests for the sklearn-backed CPU LSH matcher."""

    _CORPUS = [
        "customer payment amount",
        "rental film inventory",
        "actor first name last name",
        "category film category join",
        "payment date timestamp",
        "film title rental duration",
        "staff member store location",
        "address city country",
        "language name code",
        "special features description",
    ]

    def test_fit_does_not_raise(self) -> None:
        m = CPULSHMatcher()
        m.fit(self._CORPUS)  # should not raise

    def test_query_returns_top_k_results(self) -> None:
        m = CPULSHMatcher()
        m.fit(self._CORPUS)
        results = m.query("rental film", top_k=3)
        assert len(results) == 3

    def test_query_returns_tuples_of_str_float(self) -> None:
        m = CPULSHMatcher()
        m.fit(self._CORPUS)
        results = m.query("actor name", top_k=2)
        for item, score in results:
            assert isinstance(item, str)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0

    def test_query_closest_match(self) -> None:
        """Query 'customer payment' should rank the payment-related corpus entry highest."""
        m = CPULSHMatcher()
        m.fit(self._CORPUS)
        results = m.query("customer payment", top_k=1)
        assert len(results) == 1
        top_item, top_score = results[0]
        # The top result should contain 'payment'
        assert "payment" in top_item.lower()

    def test_query_exact_match_scores_highest(self) -> None:
        """Querying a corpus string verbatim should return it as top-1."""
        target = "actor first name last name"
        m = CPULSHMatcher()
        m.fit(self._CORPUS)
        results = m.query(target, top_k=1)
        assert results[0][0] == target

    def test_query_before_fit_raises(self) -> None:
        m = CPULSHMatcher()
        try:
            m.query("anything")
            raise AssertionError("Expected RuntimeError")
        except RuntimeError:
            pass

    def test_query_top_k_capped_by_corpus_size(self) -> None:
        m = CPULSHMatcher()
        m.fit(["a", "b", "c"])
        results = m.query("a", top_k=10)
        assert len(results) <= 3

    def test_scores_sorted_descending(self) -> None:
        m = CPULSHMatcher()
        m.fit(self._CORPUS)
        results = m.query("film rental", top_k=5)
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_factory_returns_cpu_matcher_when_no_gpu(self) -> None:
        matcher = get_lsh_matcher()
        assert isinstance(matcher, CPULSHMatcher)


# ---------------------------------------------------------------------------
# tokenize_corpus_cpu
# ---------------------------------------------------------------------------

class TestTokenizeCorpusCPU:
    def test_basic_whitespace(self) -> None:
        result = tokenize_corpus_cpu(["hello world"])
        assert result == [["hello", "world"]]

    def test_punctuation_splitting(self) -> None:
        result = tokenize_corpus_cpu(["foo.bar,baz"])
        # Should split on '.' and ','
        for tokens in result:
            assert "foo" in tokens
            assert "bar" in tokens
            assert "baz" in tokens

    def test_mixed_case_lowercased(self) -> None:
        result = tokenize_corpus_cpu(["Hello World"])
        assert result == [["hello", "world"]]

    def test_empty_string(self) -> None:
        result = tokenize_corpus_cpu([""])
        assert result == [[]]

    def test_empty_corpus(self) -> None:
        assert tokenize_corpus_cpu([]) == []

    def test_multiple_strings(self) -> None:
        texts = ["hello world", "foo bar"]
        result = tokenize_corpus_cpu(texts)
        assert len(result) == 2
        assert result[0] == ["hello", "world"]
        assert result[1] == ["foo", "bar"]

    def test_sql_like_string(self) -> None:
        result = tokenize_corpus_cpu(["SELECT COUNT(*) FROM table_a;"])
        tokens = result[0]
        assert "select" in tokens
        assert "count" in tokens
        assert "from" in tokens

    def test_multiple_spaces_collapsed(self) -> None:
        result = tokenize_corpus_cpu(["a  b   c"])
        assert result == [["a", "b", "c"]]

    def test_factory_returns_cpu_tokenizer_when_no_gpu(self) -> None:
        tok = get_tokenizer()
        assert tok is tokenize_corpus_cpu


# ---------------------------------------------------------------------------
# score_consistency_cpu
# ---------------------------------------------------------------------------

class TestScoreConsistencyCPU:

    def _rows(self, cols: list[str]) -> list[dict[str, Any]]:
        """Helper: make a single result-row dict with the given column names."""
        return [{c: 1 for c in cols}]

    def test_empty_input(self) -> None:
        assert score_consistency_cpu([]) == []

    def test_single_result_set(self) -> None:
        result = score_consistency_cpu([self._rows(["a", "b"])])
        assert result == [1.0]

    def test_three_identical_sets_score_one(self) -> None:
        rs = self._rows(["id", "name", "value"])
        scores = score_consistency_cpu([rs, rs, rs])
        assert len(scores) == 3
        for s in scores:
            assert abs(s - 1.0) < 1e-9

    def test_three_disjoint_sets_score_zero(self) -> None:
        rs1 = self._rows(["a"])
        rs2 = self._rows(["b"])
        rs3 = self._rows(["c"])
        scores = score_consistency_cpu([rs1, rs2, rs3])
        for s in scores:
            assert abs(s - 0.0) < 1e-9

    def test_partial_overlap(self) -> None:
        rs1 = self._rows(["a", "b"])
        rs2 = self._rows(["a", "c"])
        scores = score_consistency_cpu([rs1, rs2])
        # Jaccard({a,b},{a,c}) = 1/3 ≈ 0.333
        for s in scores:
            assert abs(s - 1 / 3) < 1e-9

    def test_scores_in_range(self) -> None:
        rs1 = self._rows(["x", "y"])
        rs2 = self._rows(["y", "z"])
        rs3 = self._rows(["x", "z"])
        scores = score_consistency_cpu([rs1, rs2, rs3])
        for s in scores:
            assert 0.0 <= s <= 1.0

    def test_column_names_case_insensitive(self) -> None:
        rs1 = self._rows(["ID", "Name"])
        rs2 = self._rows(["id", "name"])
        scores = score_consistency_cpu([rs1, rs2])
        for s in scores:
            assert abs(s - 1.0) < 1e-9

    def test_multi_row_result_set(self) -> None:
        """Column names extracted from multiple rows in one result set."""
        rs = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
        scores = score_consistency_cpu([rs, rs])
        for s in scores:
            assert abs(s - 1.0) < 1e-9

    def test_empty_result_sets_treated_as_identical(self) -> None:
        scores = score_consistency_cpu([[], []])
        # Both sets have empty column vocabulary → union=0 → Jaccard=1.0
        for s in scores:
            assert abs(s - 1.0) < 1e-9

    def test_factory_returns_cpu_scorer_when_no_gpu(self) -> None:
        scorer = get_result_scorer()
        assert scorer is score_consistency_cpu

    def test_different_sets_score_lower_than_identical(self) -> None:
        identical_rs = self._rows(["a", "b", "c"])
        different_rs = self._rows(["x", "y", "z"])
        scores_identical = score_consistency_cpu([identical_rs, identical_rs, identical_rs])
        scores_different = score_consistency_cpu([identical_rs, different_rs, different_rs])
        avg_identical = sum(scores_identical) / len(scores_identical)
        avg_different = sum(scores_different) / len(scores_different)
        assert avg_identical > avg_different
