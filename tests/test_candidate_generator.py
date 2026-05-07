"""Tests for CandidateGenerator — Stage 4 multi-candidate SQL generation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.candidate_generator import STRATEGIES, CandidateGenerator
from core.models import (
    ColumnSchema,
    FilteredSchema,
    JoinPath,
    QueryPlan,
    SQLCandidate,
    TableSchema,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def filtered_schema() -> FilteredSchema:
    return FilteredSchema(
        tables=[
            TableSchema(
                name="customer",
                columns=[
                    ColumnSchema(name="customer_id", type="INTEGER", is_primary_key=True),
                    ColumnSchema(name="first_name", type="TEXT"),
                ],
            ),
            TableSchema(
                name="payment",
                columns=[
                    ColumnSchema(name="payment_id", type="INTEGER", is_primary_key=True),
                    ColumnSchema(
                        name="customer_id",
                        type="INTEGER",
                        is_foreign_key=True,
                        references_table="customer",
                        references_column="customer_id",
                    ),
                    ColumnSchema(name="amount", type="NUMERIC"),
                ],
            ),
        ],
        join_paths=[
            JoinPath(
                from_table="payment",
                from_column="customer_id",
                to_table="customer",
                to_column="customer_id",
            )
        ],
    )


@pytest.fixture()
def query_plan() -> QueryPlan:
    return QueryPlan(
        aggregations=["SUM(payment.amount) AS total"],
        filters=[],
        joins=["customer JOIN payment ON customer.customer_id = payment.customer_id"],
        ordering="total DESC",
        subqueries=[],
        reasoning="aggregate payments per customer",
    )


def _make_generator(responses: list[str]) -> CandidateGenerator:
    backend = MagicMock()
    backend.generate_batch = AsyncMock(return_value=responses)
    return CandidateGenerator(backend)


_THREE_SQL = ["SELECT 1;", "SELECT 2;", "SELECT 3;"]

# ---------------------------------------------------------------------------
# STRATEGIES constant
# ---------------------------------------------------------------------------

def test_strategies_has_three_entries() -> None:
    assert len(STRATEGIES) == 3


def test_strategy_names() -> None:
    names = [str(s["name"]) for s in STRATEGIES]
    assert "direct_cot" in names
    assert "divide_conquer" in names
    assert "plan_execute" in names


def test_strategy_temperatures() -> None:
    temps = {s["name"]: s["temperature"] for s in STRATEGIES}
    assert temps["direct_cot"] == 0.0
    assert temps["divide_conquer"] == 0.2
    assert temps["plan_execute"] == 0.3


def test_strategy_builders_are_callable() -> None:
    for strat in STRATEGIES:
        assert callable(strat["builder"])


# ---------------------------------------------------------------------------
# generate_candidates — count and types
# ---------------------------------------------------------------------------

async def test_returns_three_candidates(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    gen = _make_generator(_THREE_SQL)
    candidates = await gen.generate_candidates("q", filtered_schema, query_plan)
    assert len(candidates) == 3


async def test_candidates_are_sql_candidate_instances(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    gen = _make_generator(_THREE_SQL)
    candidates = await gen.generate_candidates("q", filtered_schema, query_plan)
    assert all(isinstance(c, SQLCandidate) for c in candidates)


# ---------------------------------------------------------------------------
# Strategy names preserved in output
# ---------------------------------------------------------------------------

async def test_strategy_names_in_candidates(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    gen = _make_generator(_THREE_SQL)
    candidates = await gen.generate_candidates("q", filtered_schema, query_plan)
    names = {c.strategy for c in candidates}
    assert "direct_cot" in names
    assert "divide_conquer" in names
    assert "plan_execute" in names


async def test_candidate_order_matches_strategies(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    gen = _make_generator(_THREE_SQL)
    candidates = await gen.generate_candidates("q", filtered_schema, query_plan)
    expected_order = [str(s["name"]) for s in STRATEGIES]
    assert [c.strategy for c in candidates] == expected_order


# ---------------------------------------------------------------------------
# SQL content preserved
# ---------------------------------------------------------------------------

async def test_sql_content_from_responses(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    gen = _make_generator(_THREE_SQL)
    candidates = await gen.generate_candidates("q", filtered_schema, query_plan)
    sqls = [c.sql for c in candidates]
    assert sqls == _THREE_SQL


async def test_markdown_fences_stripped(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    fenced = ["```sql\nSELECT 1;\n```", "```\nSELECT 2;\n```", "SELECT 3;"]
    gen = _make_generator(fenced)
    candidates = await gen.generate_candidates("q", filtered_schema, query_plan)
    assert candidates[0].sql == "SELECT 1;"
    assert candidates[1].sql == "SELECT 2;"
    assert candidates[2].sql == "SELECT 3;"


# ---------------------------------------------------------------------------
# Batch dispatch — generate_batch called once with all prompts
# ---------------------------------------------------------------------------

async def test_generate_batch_called_once(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    backend = MagicMock()
    backend.generate_batch = AsyncMock(return_value=_THREE_SQL)
    gen = CandidateGenerator(backend)
    await gen.generate_candidates("q", filtered_schema, query_plan)
    backend.generate_batch.assert_called_once()


async def test_generate_batch_receives_three_prompts(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    backend = MagicMock()
    backend.generate_batch = AsyncMock(return_value=_THREE_SQL)
    gen = CandidateGenerator(backend)
    await gen.generate_candidates("q", filtered_schema, query_plan)
    call_kwargs = backend.generate_batch.call_args
    prompts = call_kwargs.kwargs.get("prompts") or call_kwargs.args[0]
    assert len(prompts) == 3


async def test_generate_batch_not_called_sequentially(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    """generate() must NOT be called — only generate_batch()."""
    backend = MagicMock()
    backend.generate = AsyncMock(return_value="SELECT 0;")
    backend.generate_batch = AsyncMock(return_value=_THREE_SQL)
    gen = CandidateGenerator(backend)
    await gen.generate_candidates("q", filtered_schema, query_plan)
    backend.generate.assert_not_called()
    backend.generate_batch.assert_called_once()


async def test_each_strategy_has_distinct_prompt(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    backend = MagicMock()
    backend.generate_batch = AsyncMock(return_value=_THREE_SQL)
    gen = CandidateGenerator(backend)
    await gen.generate_candidates("q", filtered_schema, query_plan)
    call_kwargs = backend.generate_batch.call_args
    prompts = call_kwargs.kwargs.get("prompts") or call_kwargs.args[0]
    # All three prompts must be distinct
    assert len(set(prompts)) == 3


# ---------------------------------------------------------------------------
# Fallback on empty / failed responses
# ---------------------------------------------------------------------------

async def test_empty_response_gets_negative_score(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    gen = _make_generator(["SELECT 1;", "", "SELECT 3;"])
    candidates = await gen.generate_candidates("q", filtered_schema, query_plan)
    empty = next(c for c in candidates if c.sql == "")
    assert empty.score == -1.0


async def test_non_empty_responses_default_score_zero(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    gen = _make_generator(_THREE_SQL)
    candidates = await gen.generate_candidates("q", filtered_schema, query_plan)
    for c in candidates:
        assert c.score == 0.0  # score=0 until execution


async def test_batch_exception_returns_three_empty_candidates(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    backend = MagicMock()
    backend.generate_batch = AsyncMock(side_effect=RuntimeError("backend down"))
    gen = CandidateGenerator(backend)
    candidates = await gen.generate_candidates("q", filtered_schema, query_plan)
    assert len(candidates) == 3
    assert all(c.sql == "" for c in candidates)
    assert all(c.score == -1.0 for c in candidates)


async def test_all_empty_responses_all_negative_scores(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    gen = _make_generator(["", "", ""])
    candidates = await gen.generate_candidates("q", filtered_schema, query_plan)
    assert all(c.score == -1.0 for c in candidates)


# ---------------------------------------------------------------------------
# Per-strategy temperature dispatch (CHASE-SQL diversity contract)
# ---------------------------------------------------------------------------

async def test_per_strategy_temperatures_are_passed_to_backend(
    filtered_schema: FilteredSchema, query_plan: QueryPlan
) -> None:
    """Each strategy's declared temperature must reach the backend.

    Regression test: previously the dispatch site used a single median value
    for all three strategies, which collapsed candidate diversity.
    """
    backend = MagicMock()
    backend.generate_batch = AsyncMock(return_value=_THREE_SQL)
    gen = CandidateGenerator(backend)

    await gen.generate_candidates("q", filtered_schema, query_plan)

    backend.generate_batch.assert_awaited_once()
    kwargs = backend.generate_batch.await_args.kwargs
    temps = kwargs["temperature"]

    # Must be a list — not a single float
    assert isinstance(temps, list), "temperature must be a per-strategy list"
    # And it must match the STRATEGIES table exactly, in declared order
    expected = [s["temperature"] for s in STRATEGIES]
    assert temps == expected
