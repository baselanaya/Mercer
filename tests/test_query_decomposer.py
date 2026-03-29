"""Tests for QueryDecomposer — Stage 3 query decomposition."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models import ColumnSchema, FilteredSchema, JoinPath, QueryPlan, TableSchema
from core.query_decomposer import QueryDecomposer, _parse_plan, _strip_json_fences

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def simple_schema() -> FilteredSchema:
    """Two-table schema: customer + payment with one FK join path."""
    return FilteredSchema(
        tables=[
            TableSchema(
                name="customer",
                columns=[
                    ColumnSchema(name="customer_id", type="INTEGER", is_primary_key=True),
                    ColumnSchema(name="first_name", type="TEXT"),
                    ColumnSchema(name="last_name", type="TEXT"),
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


def _valid_plan_json(
    aggregations: list[str] | None = None,
    filters: list[str] | None = None,
    joins: list[str] | None = None,
    ordering: str | None = None,
    subqueries: list[str] | None = None,
    reasoning: str = "test plan",
) -> str:
    return json.dumps({
        "aggregations": aggregations or [],
        "filters": filters or [],
        "joins": joins or [],
        "ordering": ordering,
        "subqueries": subqueries or [],
        "reasoning": reasoning,
    })


def _make_decomposer(response: str) -> QueryDecomposer:
    backend = MagicMock()
    backend.generate = AsyncMock(return_value=response)
    return QueryDecomposer(backend)


# ---------------------------------------------------------------------------
# _strip_json_fences
# ---------------------------------------------------------------------------

def test_strip_fences_bare_json() -> None:
    raw = '{"key": "val"}'
    assert _strip_json_fences(raw) == raw


def test_strip_fences_json_tag() -> None:
    raw = '```json\n{"key": "val"}\n```'
    assert _strip_json_fences(raw) == '{"key": "val"}'


def test_strip_fences_plain_backticks() -> None:
    raw = '```\n{"key": "val"}\n```'
    assert _strip_json_fences(raw) == '{"key": "val"}'


# ---------------------------------------------------------------------------
# _parse_plan
# ---------------------------------------------------------------------------

def test_parse_plan_valid_full() -> None:
    raw = _valid_plan_json(
        aggregations=["SUM(amount)"],
        filters=["year = 2005"],
        joins=["customer JOIN payment ON id = id"],
        ordering="total DESC",
        subqueries=[],
        reasoning="aggregate payments per customer",
    )
    plan = _parse_plan(raw)
    assert plan is not None
    assert plan.aggregations == ["SUM(amount)"]
    assert plan.filters == ["year = 2005"]
    assert plan.joins == ["customer JOIN payment ON id = id"]
    assert plan.ordering == "total DESC"
    assert plan.subqueries == []
    assert plan.reasoning == "aggregate payments per customer"


def test_parse_plan_null_ordering() -> None:
    raw = _valid_plan_json(ordering=None)
    plan = _parse_plan(raw)
    assert plan is not None
    assert plan.ordering is None


def test_parse_plan_empty_lists() -> None:
    raw = _valid_plan_json()
    plan = _parse_plan(raw)
    assert plan is not None
    assert plan.aggregations == []
    assert plan.filters == []
    assert plan.joins == []
    assert plan.subqueries == []


def test_parse_plan_invalid_json_returns_none() -> None:
    assert _parse_plan("this is not json") is None


def test_parse_plan_empty_string_returns_none() -> None:
    assert _parse_plan("") is None


def test_parse_plan_wrong_type_for_aggregations() -> None:
    # aggregations is a string instead of list — coerces to empty list
    raw = json.dumps({
        "aggregations": "SUM(amount)",
        "filters": [],
        "joins": [],
        "ordering": None,
        "subqueries": [],
        "reasoning": "test",
    })
    plan = _parse_plan(raw)
    assert plan is not None
    assert plan.aggregations == []


def test_parse_plan_with_json_fence() -> None:
    raw = "```json\n" + _valid_plan_json(reasoning="fenced") + "\n```"
    plan = _parse_plan(raw)
    assert plan is not None
    assert plan.reasoning == "fenced"


def test_parse_plan_extra_keys_ignored() -> None:
    data = json.loads(_valid_plan_json(reasoning="ok"))
    data["unknown_key"] = "ignored"
    plan = _parse_plan(json.dumps(data))
    assert plan is not None
    assert plan.reasoning == "ok"


def test_parse_plan_missing_optional_fields_default() -> None:
    # Only 'reasoning' — all list fields should default to empty
    raw = json.dumps({"reasoning": "minimal"})
    plan = _parse_plan(raw)
    assert plan is not None
    assert plan.aggregations == []
    assert plan.filters == []
    assert plan.joins == []
    assert plan.subqueries == []
    assert plan.ordering is None
    assert plan.reasoning == "minimal"


# ---------------------------------------------------------------------------
# QueryDecomposer.decompose — happy path
# ---------------------------------------------------------------------------

async def test_decompose_returns_query_plan(simple_schema: FilteredSchema) -> None:
    response = _valid_plan_json(
        aggregations=["SUM(payment.amount) AS total"],
        joins=["customer JOIN payment ON customer.customer_id = payment.customer_id"],
        ordering="total DESC",
        reasoning="aggregate by customer",
    )
    decomposer = _make_decomposer(response)
    plan = await decomposer.decompose("Total payment per customer", simple_schema)
    assert isinstance(plan, QueryPlan)


async def test_decompose_aggregations_preserved(simple_schema: FilteredSchema) -> None:
    response = _valid_plan_json(aggregations=["SUM(payment.amount) AS total"])
    decomposer = _make_decomposer(response)
    plan = await decomposer.decompose("q", simple_schema)
    assert plan.aggregations == ["SUM(payment.amount) AS total"]


async def test_decompose_filters_preserved(simple_schema: FilteredSchema) -> None:
    response = _valid_plan_json(filters=["customer.active = true"])
    decomposer = _make_decomposer(response)
    plan = await decomposer.decompose("q", simple_schema)
    assert plan.filters == ["customer.active = true"]


async def test_decompose_joins_preserved(simple_schema: FilteredSchema) -> None:
    join = "customer JOIN payment ON customer.customer_id = payment.customer_id"
    response = _valid_plan_json(joins=[join])
    decomposer = _make_decomposer(response)
    plan = await decomposer.decompose("q", simple_schema)
    assert plan.joins == [join]


async def test_decompose_ordering_preserved(simple_schema: FilteredSchema) -> None:
    response = _valid_plan_json(ordering="total DESC")
    decomposer = _make_decomposer(response)
    plan = await decomposer.decompose("q", simple_schema)
    assert plan.ordering == "total DESC"


async def test_decompose_subqueries_preserved(simple_schema: FilteredSchema) -> None:
    response = _valid_plan_json(subqueries=["SELECT MAX(amount) FROM payment"])
    decomposer = _make_decomposer(response)
    plan = await decomposer.decompose("q", simple_schema)
    assert plan.subqueries == ["SELECT MAX(amount) FROM payment"]


async def test_decompose_reasoning_preserved(simple_schema: FilteredSchema) -> None:
    response = _valid_plan_json(reasoning="join and aggregate")
    decomposer = _make_decomposer(response)
    plan = await decomposer.decompose("q", simple_schema)
    assert plan.reasoning == "join and aggregate"


async def test_decompose_calls_backend_once(simple_schema: FilteredSchema) -> None:
    backend = MagicMock()
    backend.generate = AsyncMock(return_value=_valid_plan_json())
    decomposer = QueryDecomposer(backend)
    await decomposer.decompose("q", simple_schema)
    backend.generate.assert_called_once()


async def test_decompose_passes_temperature_zero(simple_schema: FilteredSchema) -> None:
    backend = MagicMock()
    backend.generate = AsyncMock(return_value=_valid_plan_json())
    decomposer = QueryDecomposer(backend)
    await decomposer.decompose("q", simple_schema)
    _, kwargs = backend.generate.call_args
    assert kwargs.get("temperature", backend.generate.call_args[0][2] if len(backend.generate.call_args[0]) > 2 else 0) == 0.0  # noqa: E501


# ---------------------------------------------------------------------------
# QueryDecomposer.decompose — fallback on bad JSON
# ---------------------------------------------------------------------------

async def test_decompose_fallback_on_invalid_json(simple_schema: FilteredSchema) -> None:
    decomposer = _make_decomposer("this is not json at all")
    plan = await decomposer.decompose("q", simple_schema)
    assert isinstance(plan, QueryPlan)
    assert "decomposition failed" in plan.reasoning


async def test_decompose_fallback_has_empty_lists(simple_schema: FilteredSchema) -> None:
    decomposer = _make_decomposer("not json")
    plan = await decomposer.decompose("q", simple_schema)
    assert plan.aggregations == []
    assert plan.filters == []
    assert plan.joins == []
    assert plan.subqueries == []
    assert plan.ordering is None


async def test_decompose_fallback_on_empty_response(simple_schema: FilteredSchema) -> None:
    decomposer = _make_decomposer("")
    plan = await decomposer.decompose("q", simple_schema)
    assert "decomposition failed" in plan.reasoning


async def test_decompose_fallback_on_partial_json(simple_schema: FilteredSchema) -> None:
    decomposer = _make_decomposer('{"aggregations": ["SUM(x)"')  # truncated
    plan = await decomposer.decompose("q", simple_schema)
    assert "decomposition failed" in plan.reasoning


async def test_decompose_valid_json_does_not_use_fallback_reasoning(
    simple_schema: FilteredSchema,
) -> None:
    response = _valid_plan_json(reasoning="real plan")
    decomposer = _make_decomposer(response)
    plan = await decomposer.decompose("q", simple_schema)
    assert "decomposition failed" not in plan.reasoning
    assert plan.reasoning == "real plan"
