"""Tests for CHESSSchemaLinker — 3-step schema linking.

All LLM calls are mocked. The FK graph uses a real FKGraphBuilder over a
small in-memory schema so join-path logic is exercised without a live DB.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models import (
    AnnotatedSchema,
    ColumnSchema,
    EntityContext,
    EntityMatch,
    FilteredSchema,
    TableSchema,
)
from core.schema_linker import (
    CHESSSchemaLinker,
    _parse_selected_columns,
    _parse_selected_tables,
    _prune_columns,
)
from core.utils import strip_json_fences as _strip_json_fences
from schema.graph_builder import FKGraphBuilder

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _col(
    name: str,
    *,
    pk: bool = False,
    fk: bool = False,
    ref_table: str | None = None,
    ref_col: str | None = None,
    desc: str | None = None,
) -> ColumnSchema:
    return ColumnSchema(
        name=name,
        type="INTEGER" if ("id" in name or pk or fk) else "TEXT",
        description=desc,
        is_primary_key=pk,
        is_foreign_key=fk,
        references_table=ref_table,
        references_column=ref_col,
    )


@pytest.fixture()
def schema() -> AnnotatedSchema:
    """5-table schema: customer ← payment, film ← inventory ← rental, actor (isolated)."""
    return AnnotatedSchema(
        db_url_hash="test",
        glossary={"revenue": "SUM(payment.amount)"},
        tables=[
            TableSchema(name="customer", description="Customer master", columns=[
                _col("customer_id", pk=True, desc="Customer PK"),
                _col("first_name", desc="First name"),
                _col("last_name", desc="Last name"),
                _col("email", desc="Email address"),
            ]),
            TableSchema(name="payment", description="Payment transactions", columns=[
                _col("payment_id", pk=True),
                _col("customer_id", fk=True, ref_table="customer", ref_col="customer_id"),
                _col("amount", desc="Payment amount"),
                _col("payment_date", desc="Date of payment"),
            ]),
            TableSchema(name="film", description="Film catalogue", columns=[
                _col("film_id", pk=True),
                _col("title", desc="Film title"),
                _col("rental_duration", desc="Duration in days"),
            ]),
            TableSchema(name="inventory", description="Inventory items", columns=[
                _col("inventory_id", pk=True),
                _col("film_id", fk=True, ref_table="film", ref_col="film_id"),
            ]),
            TableSchema(name="actor", description="Actor registry", columns=[
                _col("actor_id", pk=True),
                _col("first_name", desc="Actor first name"),
                _col("last_name", desc="Actor last name"),
            ]),
        ],
    )


@pytest.fixture()
def fk_graph(schema: AnnotatedSchema) -> FKGraphBuilder:
    return FKGraphBuilder(schema)


@pytest.fixture()
def entity_context() -> EntityContext:
    return EntityContext(
        original_question="Show total payment amount per customer",
        expanded_question="Show total payment amount per customer (revenue = SUM(payment.amount))",
        glossary_expansions={"revenue": "SUM(payment.amount)"},
        entity_matches=[
            EntityMatch(token="payment", table="payment", column="amount", matched_value="amount", score=0.9),
            EntityMatch(token="customer", table="customer", column="customer_id", matched_value="customer_id", score=0.85),
            EntityMatch(token="payment", table="payment", column="payment_id", matched_value="payment_id", score=0.5),
        ],
    )


def _make_backend(table_response: str, column_response: str) -> MagicMock:
    """Mock backend whose generate() alternates between two fixed responses."""
    backend = MagicMock()
    backend.generate = AsyncMock(side_effect=[table_response, column_response])
    return backend


def _tbl_response(tables: list[str]) -> str:
    return json.dumps({"selected_tables": tables, "reasoning": "test"})


def _col_response(col_map: dict[str, list[str]]) -> str:
    return json.dumps({"selected_columns": col_map, "reasoning": "test"})


# ---------------------------------------------------------------------------
# _strip_json_fences
# ---------------------------------------------------------------------------

def test_strip_fences_plain_json() -> None:
    raw = '{"key": "value"}'
    assert _strip_json_fences(raw) == raw


def test_strip_fences_with_json_tag() -> None:
    raw = '```json\n{"key": "value"}\n```'
    assert _strip_json_fences(raw) == '{"key": "value"}'


def test_strip_fences_plain_backticks() -> None:
    raw = '```\n{"key": "value"}\n```'
    assert _strip_json_fences(raw) == '{"key": "value"}'


# ---------------------------------------------------------------------------
# _parse_selected_tables
# ---------------------------------------------------------------------------

def test_parse_selected_tables_valid() -> None:
    raw = '{"selected_tables": ["customer", "payment"], "reasoning": "ok"}'
    assert _parse_selected_tables(raw) == ["customer", "payment"]


def test_parse_selected_tables_invalid_json() -> None:
    assert _parse_selected_tables("not json") is None


def test_parse_selected_tables_missing_key() -> None:
    assert _parse_selected_tables('{"reasoning": "ok"}') is None


def test_parse_selected_tables_wrong_type() -> None:
    assert _parse_selected_tables('{"selected_tables": "customer"}') is None


def test_parse_selected_tables_strips_whitespace() -> None:
    raw = '{"selected_tables": [" customer ", " payment"], "reasoning": "ok"}'
    result = _parse_selected_tables(raw)
    assert result == ["customer", "payment"]


def test_parse_selected_tables_with_fences() -> None:
    raw = '```json\n{"selected_tables": ["film"], "reasoning": "ok"}\n```'
    assert _parse_selected_tables(raw) == ["film"]


# ---------------------------------------------------------------------------
# _parse_selected_columns
# ---------------------------------------------------------------------------

def test_parse_selected_columns_valid() -> None:
    raw = '{"selected_columns": {"customer": ["customer_id", "email"]}, "reasoning": "ok"}'
    assert _parse_selected_columns(raw) == {"customer": ["customer_id", "email"]}


def test_parse_selected_columns_invalid_json() -> None:
    assert _parse_selected_columns("not json") is None


def test_parse_selected_columns_missing_key() -> None:
    assert _parse_selected_columns('{"reasoning": "ok"}') is None


def test_parse_selected_columns_non_list_value() -> None:
    assert _parse_selected_columns('{"selected_columns": {"t": "col"}}') is None


# ---------------------------------------------------------------------------
# _prune_columns
# ---------------------------------------------------------------------------

def test_prune_keeps_selected_columns(schema: AnnotatedSchema) -> None:
    tables = [t for t in schema.tables if t.name == "customer"]
    col_map = {"customer": ["email"]}
    pruned = _prune_columns(tables, col_map)
    col_names = {c.name for c in pruned[0].columns}
    assert "email" in col_names


def test_prune_always_keeps_pk(schema: AnnotatedSchema) -> None:
    tables = [t for t in schema.tables if t.name == "customer"]
    col_map = {"customer": ["email"]}
    pruned = _prune_columns(tables, col_map)
    col_names = {c.name for c in pruned[0].columns}
    assert "customer_id" in col_names  # PK always retained


def test_prune_always_keeps_fk(schema: AnnotatedSchema) -> None:
    tables = [t for t in schema.tables if t.name == "payment"]
    col_map = {"payment": ["amount"]}
    pruned = _prune_columns(tables, col_map)
    col_names = {c.name for c in pruned[0].columns}
    assert "customer_id" in col_names  # FK always retained


def test_prune_table_not_in_col_map_kept_whole(schema: AnnotatedSchema) -> None:
    tables = [t for t in schema.tables if t.name in {"customer", "film"}]
    col_map = {"customer": ["email"]}
    pruned = _prune_columns(tables, col_map)
    film = next(t for t in pruned if t.name == "film")
    assert len(film.columns) == len(next(t for t in schema.tables if t.name == "film").columns)


def test_prune_empty_selection_keeps_all_columns(schema: AnnotatedSchema) -> None:
    tables = [t for t in schema.tables if t.name == "actor"]
    col_map: dict[str, list[str]] = {"actor": []}
    pruned = _prune_columns(tables, col_map)
    # actor has no PK/FK-only fallback that gives zero cols; safety keeps all
    assert len(pruned[0].columns) >= 1


# ---------------------------------------------------------------------------
# step_column_prefilter
# ---------------------------------------------------------------------------

class TestStepColumnPrefilter:
    async def test_returns_list(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        linker = CHESSSchemaLinker(MagicMock(), fk_graph)
        result = await linker.step_column_prefilter(entity_context, schema)
        assert isinstance(result, list)

    async def test_payment_and_customer_in_candidates(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        linker = CHESSSchemaLinker(MagicMock(), fk_graph)
        result = await linker.step_column_prefilter(entity_context, schema)
        table_names = [tbl.name for tbl, _, _ in result]
        assert "payment" in table_names
        assert "customer" in table_names

    async def test_sorted_by_score_descending(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        linker = CHESSSchemaLinker(MagicMock(), fk_graph)
        result = await linker.step_column_prefilter(entity_context, schema)
        scores = [s for _, _, s in result]
        assert scores == sorted(scores, reverse=True)

    async def test_no_entity_matches_returns_all_tables(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder
    ) -> None:
        ctx = EntityContext(
            original_question="q", expanded_question="q",
            glossary_expansions={}, entity_matches=[],
        )
        linker = CHESSSchemaLinker(MagicMock(), fk_graph)
        result = await linker.step_column_prefilter(ctx, schema)
        assert len(result) > 0

    async def test_result_tuples_have_three_elements(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        linker = CHESSSchemaLinker(MagicMock(), fk_graph)
        result = await linker.step_column_prefilter(entity_context, schema)
        assert all(len(r) == 3 for r in result)


# ---------------------------------------------------------------------------
# step_table_selection
# ---------------------------------------------------------------------------

class TestStepTableSelection:
    async def test_returns_selected_tables(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = MagicMock()
        backend.generate = AsyncMock(return_value=_tbl_response(["customer", "payment"]))
        linker = CHESSSchemaLinker(backend, fk_graph)
        candidates = [(t, [], 1.0) for t in schema.tables[:3]]
        result = await linker.step_table_selection(
            "Show total payment per customer", entity_context, candidates, schema
        )
        names = [t.name for t in result]
        assert "customer" in names
        assert "payment" in names

    async def test_fallback_on_invalid_json(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = MagicMock()
        backend.generate = AsyncMock(return_value="this is not json")
        linker = CHESSSchemaLinker(backend, fk_graph)
        candidates = [(t, [], float(i)) for i, t in enumerate(reversed(schema.tables))]
        result = await linker.step_table_selection(
            "q", entity_context, candidates, schema
        )
        assert len(result) <= 5
        assert all(isinstance(t, TableSchema) for t in result)

    async def test_fallback_on_unknown_table_names(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = MagicMock()
        backend.generate = AsyncMock(return_value=_tbl_response(["nonexistent_table"]))
        linker = CHESSSchemaLinker(backend, fk_graph)
        candidates = [(t, [], 1.0) for t in schema.tables[:3]]
        result = await linker.step_table_selection(
            "q", entity_context, candidates, schema
        )
        assert len(result) >= 1

    async def test_returns_full_table_schema_objects(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = MagicMock()
        backend.generate = AsyncMock(return_value=_tbl_response(["film"]))
        linker = CHESSSchemaLinker(backend, fk_graph)
        candidates = [(t, [], 1.0) for t in schema.tables]
        result = await linker.step_table_selection(
            "q", entity_context, candidates, schema
        )
        film_tbl = next((t for t in result if t.name == "film"), None)
        assert film_tbl is not None
        # Full table returned — all 3 film columns present
        assert len(film_tbl.columns) == 3


# ---------------------------------------------------------------------------
# step_final_columns
# ---------------------------------------------------------------------------

class TestStepFinalColumns:
    async def test_returns_filtered_schema(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = MagicMock()
        col_resp = _col_response({
            "customer": ["customer_id", "first_name"],
            "payment": ["customer_id", "amount"],
        })
        backend.generate = AsyncMock(return_value=col_resp)
        linker = CHESSSchemaLinker(backend, fk_graph)
        selected = [t for t in schema.tables if t.name in {"customer", "payment"}]
        result = await linker.step_final_columns("q", entity_context, selected)
        assert isinstance(result, FilteredSchema)

    async def test_pruned_columns_respected(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = MagicMock()
        col_resp = _col_response({
            "customer": ["first_name"],
            "payment": ["amount"],
        })
        backend.generate = AsyncMock(return_value=col_resp)
        linker = CHESSSchemaLinker(backend, fk_graph)
        selected = [t for t in schema.tables if t.name in {"customer", "payment"}]
        result = await linker.step_final_columns("q", entity_context, selected)
        cust = next(t for t in result.tables if t.name == "customer")
        col_names = {c.name for c in cust.columns}
        assert "first_name" in col_names
        assert "email" not in col_names  # not selected

    async def test_fk_join_paths_added(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = MagicMock()
        col_resp = _col_response({
            "customer": ["customer_id"],
            "payment": ["customer_id", "amount"],
        })
        backend.generate = AsyncMock(return_value=col_resp)
        linker = CHESSSchemaLinker(backend, fk_graph)
        selected = [t for t in schema.tables if t.name in {"customer", "payment"}]
        result = await linker.step_final_columns("q", entity_context, selected)
        assert len(result.join_paths) >= 1
        involved = {t for jp in result.join_paths for t in (jp.from_table, jp.to_table)}
        assert "customer" in involved or "payment" in involved

    async def test_fallback_on_invalid_json_keeps_all_cols(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = MagicMock()
        backend.generate = AsyncMock(return_value="not json at all")
        linker = CHESSSchemaLinker(backend, fk_graph)
        selected = [t for t in schema.tables if t.name == "customer"]
        result = await linker.step_final_columns("q", entity_context, selected)
        # Fallback: all 4 customer columns retained
        cust = result.tables[0]
        assert len(cust.columns) == 4


# ---------------------------------------------------------------------------
# link() — full orchestration
# ---------------------------------------------------------------------------

class TestLink:
    async def test_link_returns_filtered_schema(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = _make_backend(
            _tbl_response(["customer", "payment"]),
            _col_response({"customer": ["customer_id", "first_name"], "payment": ["customer_id", "amount"]}),
        )
        linker = CHESSSchemaLinker(backend, fk_graph)
        result = await linker.link(
            "Show total payment amount per customer", entity_context, schema
        )
        assert isinstance(result, FilteredSchema)

    async def test_link_selects_correct_tables(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = _make_backend(
            _tbl_response(["customer", "payment"]),
            _col_response({"customer": ["customer_id"], "payment": ["customer_id", "amount"]}),
        )
        linker = CHESSSchemaLinker(backend, fk_graph)
        result = await linker.link(
            "Show total payment amount per customer", entity_context, schema
        )
        table_names = {t.name for t in result.tables}
        assert "customer" in table_names
        assert "payment" in table_names

    async def test_link_adds_join_path_between_customer_and_payment(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = _make_backend(
            _tbl_response(["customer", "payment"]),
            _col_response({"customer": ["customer_id"], "payment": ["customer_id", "amount"]}),
        )
        linker = CHESSSchemaLinker(backend, fk_graph)
        result = await linker.link(
            "Show total payment per customer", entity_context, schema
        )
        assert len(result.join_paths) >= 1
        jp = result.join_paths[0]
        assert {jp.from_table, jp.to_table} == {"customer", "payment"}

    async def test_link_with_table_selection_fallback(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        """Bad table JSON + good column JSON — should not raise."""
        backend = _make_backend(
            "GARBAGE",  # table selection fails → fallback
            _col_response({"customer": ["customer_id"]}),
        )
        linker = CHESSSchemaLinker(backend, fk_graph)
        result = await linker.link("q", entity_context, schema)
        assert isinstance(result, FilteredSchema)
        assert len(result.tables) >= 1

    async def test_link_with_both_fallbacks(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        """Both LLM calls fail — still returns a valid FilteredSchema."""
        backend = _make_backend("GARBAGE", "ALSO GARBAGE")
        linker = CHESSSchemaLinker(backend, fk_graph)
        result = await linker.link("q", entity_context, schema)
        assert isinstance(result, FilteredSchema)
        assert len(result.tables) >= 1

    async def test_link_makes_exactly_two_llm_calls(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        backend = _make_backend(
            _tbl_response(["film"]),
            _col_response({"film": ["film_id", "title"]}),
        )
        linker = CHESSSchemaLinker(backend, fk_graph)
        await linker.link("List all film titles", entity_context, schema)
        assert backend.generate.call_count == 2

    async def test_link_isolated_table_no_join_paths(
        self, schema: AnnotatedSchema, fk_graph: FKGraphBuilder, entity_context: EntityContext
    ) -> None:
        """actor has no FK edges — result should have empty join_paths."""
        backend = _make_backend(
            _tbl_response(["actor"]),
            _col_response({"actor": ["actor_id", "first_name"]}),
        )
        linker = CHESSSchemaLinker(backend, fk_graph)
        result = await linker.link("List all actors", entity_context, schema)
        assert result.join_paths == []
