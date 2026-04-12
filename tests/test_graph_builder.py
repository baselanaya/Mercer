"""Tests for FKGraphBuilder.

Schema under test — chain A→B→C→D, isolated node E:

    A.b_id  → B.b_id
    B.c_id  → C.c_id
    C.d_id  → D.d_id
    E       (no FK edges)
"""

from __future__ import annotations

import pytest

from core.models import ColumnSchema, JoinPath, RawSchema, TableSchema
from schema.graph_builder import FKGraphBuilder

# ---------------------------------------------------------------------------
# Schema fixture
# ---------------------------------------------------------------------------

def _col(
    name: str,
    *,
    pk: bool = False,
    fk: bool = False,
    ref_table: str | None = None,
    ref_col: str | None = None,
) -> ColumnSchema:
    return ColumnSchema(
        name=name,
        type="INTEGER",
        is_primary_key=pk,
        is_foreign_key=fk,
        references_table=ref_table,
        references_column=ref_col,
    )


@pytest.fixture()
def chain_schema() -> RawSchema:
    """A→B→C→D chain with E isolated."""
    return RawSchema(
        db_url_hash="test",
        tables=[
            TableSchema(name="A", columns=[
                _col("a_id", pk=True),
                _col("b_id", fk=True, ref_table="B", ref_col="b_id"),
            ]),
            TableSchema(name="B", columns=[
                _col("b_id", pk=True),
                _col("c_id", fk=True, ref_table="C", ref_col="c_id"),
            ]),
            TableSchema(name="C", columns=[
                _col("c_id", pk=True),
                _col("d_id", fk=True, ref_table="D", ref_col="d_id"),
            ]),
            TableSchema(name="D", columns=[
                _col("d_id", pk=True),
            ]),
            TableSchema(name="E", columns=[
                _col("e_id", pk=True),
            ]),
        ],
    )


@pytest.fixture()
def builder(chain_schema: RawSchema) -> FKGraphBuilder:
    return FKGraphBuilder(chain_schema)


# ---------------------------------------------------------------------------
# find_join_path
# ---------------------------------------------------------------------------

class TestFindJoinPath:
    def test_direct_hop_a_to_b(self, builder: FKGraphBuilder) -> None:
        path = builder.find_join_path("A", "B")
        assert path is not None
        assert len(path) == 1
        assert path[0].from_table == "A"
        assert path[0].to_table == "B"
        assert path[0].from_column == "b_id"
        assert path[0].to_column == "b_id"

    def test_two_hop_path_a_to_c(self, builder: FKGraphBuilder) -> None:
        path = builder.find_join_path("A", "C")
        assert path is not None
        assert len(path) == 2
        tables = [(jp.from_table, jp.to_table) for jp in path]
        assert tables == [("A", "B"), ("B", "C")]

    def test_three_hop_path_a_to_d(self, builder: FKGraphBuilder) -> None:
        path = builder.find_join_path("A", "D")
        assert path is not None
        assert len(path) == 3
        assert path[0].from_table == "A"
        assert path[-1].to_table == "D"

    def test_path_in_reverse_direction(self, builder: FKGraphBuilder) -> None:
        # FK is A→B, but asking B→A must still work (undirected search)
        path = builder.find_join_path("B", "A")
        assert path is not None
        assert len(path) == 1
        assert {path[0].from_table, path[0].to_table} == {"A", "B"}

    def test_disconnected_returns_none(self, builder: FKGraphBuilder) -> None:
        assert builder.find_join_path("A", "E") is None

    def test_same_table_returns_empty_list(self, builder: FKGraphBuilder) -> None:
        assert builder.find_join_path("A", "A") == []

    def test_unknown_table_returns_none(self, builder: FKGraphBuilder) -> None:
        assert builder.find_join_path("A", "Z") is None

    def test_returns_join_path_objects(self, builder: FKGraphBuilder) -> None:
        path = builder.find_join_path("A", "C")
        assert path is not None
        assert all(isinstance(jp, JoinPath) for jp in path)

    def test_column_attributes_populated(self, builder: FKGraphBuilder) -> None:
        path = builder.find_join_path("B", "C")
        assert path is not None
        jp = path[0]
        assert jp.from_column == "c_id"
        assert jp.to_column == "c_id"

    def test_d_to_c_reverse_columns_consistent(self, builder: FKGraphBuilder) -> None:
        # Reverse of C→D edge: from D to C via the FK declared on C
        path = builder.find_join_path("D", "C")
        assert path is not None
        assert len(path) == 1
        jp = path[0]
        assert {jp.from_table, jp.to_table} == {"C", "D"}
        assert jp.from_column == jp.to_column == "d_id"


# ---------------------------------------------------------------------------
# find_all_paths
# ---------------------------------------------------------------------------

class TestFindAllPaths:
    def test_three_tables_in_chain(self, builder: FKGraphBuilder) -> None:
        paths = builder.find_all_paths(["A", "C", "D"])
        assert len(paths) >= 2
        involved_tables = {t for jp in paths for t in (jp.from_table, jp.to_table)}
        assert "A" in involved_tables
        assert "C" in involved_tables
        assert "D" in involved_tables

    def test_two_tables_returns_one_join(self, builder: FKGraphBuilder) -> None:
        paths = builder.find_all_paths(["A", "B"])
        assert len(paths) == 1

    def test_single_table_returns_empty(self, builder: FKGraphBuilder) -> None:
        assert builder.find_all_paths(["A"]) == []

    def test_empty_list_returns_empty(self, builder: FKGraphBuilder) -> None:
        assert builder.find_all_paths([]) == []

    def test_no_duplicates_in_result(self, builder: FKGraphBuilder) -> None:
        paths = builder.find_all_paths(["A", "B", "C", "D"])
        keys = [(jp.from_table, jp.from_column, jp.to_table, jp.to_column) for jp in paths]
        assert len(keys) == len(set(keys))

    def test_all_tables_connected(self, builder: FKGraphBuilder) -> None:
        paths = builder.find_all_paths(["A", "B", "C", "D"])
        # A connected chain of 4 tables needs exactly 3 joins
        assert len(paths) == 3

    def test_disconnected_table_ignored(self, builder: FKGraphBuilder) -> None:
        # E has no FK edges; asking A + E should not raise
        paths = builder.find_all_paths(["A", "B", "E"])
        # A→B is reachable; E is isolated — at least one join returned
        assert len(paths) >= 1

    def test_duplicate_input_tables_deduplicated(self, builder: FKGraphBuilder) -> None:
        paths_once = builder.find_all_paths(["A", "B"])
        paths_dup = builder.find_all_paths(["A", "A", "B", "B"])
        assert len(paths_once) == len(paths_dup)

    def test_returns_join_path_objects(self, builder: FKGraphBuilder) -> None:
        paths = builder.find_all_paths(["A", "C"])
        assert all(isinstance(jp, JoinPath) for jp in paths)


# ---------------------------------------------------------------------------
# get_neighbors
# ---------------------------------------------------------------------------

class TestGetNeighbors:
    def test_a_has_b_as_neighbor(self, builder: FKGraphBuilder) -> None:
        assert "B" in builder.get_neighbors("A")

    def test_b_has_a_and_c_as_neighbors(self, builder: FKGraphBuilder) -> None:
        neighbors = set(builder.get_neighbors("B"))
        assert "A" in neighbors
        assert "C" in neighbors

    def test_e_has_no_neighbors(self, builder: FKGraphBuilder) -> None:
        assert builder.get_neighbors("E") == []

    def test_unknown_table_returns_empty(self, builder: FKGraphBuilder) -> None:
        assert builder.get_neighbors("Z") == []

    def test_d_neighbor_is_c(self, builder: FKGraphBuilder) -> None:
        assert "C" in builder.get_neighbors("D")

    def test_returns_list(self, builder: FKGraphBuilder) -> None:
        assert isinstance(builder.get_neighbors("A"), list)


# ---------------------------------------------------------------------------
# Graph construction edge cases
# ---------------------------------------------------------------------------

class TestGraphConstruction:
    def test_all_nodes_present(self, builder: FKGraphBuilder) -> None:
        nodes = set(builder._graph.nodes)
        assert {"A", "B", "C", "D", "E"}.issubset(nodes)

    def test_edge_count(self, builder: FKGraphBuilder) -> None:
        # A→B, B→C, C→D = 3 directed edges
        assert builder._graph.number_of_edges() == 3

    def test_isolated_node_has_no_edges(self, builder: FKGraphBuilder) -> None:
        assert builder._graph.degree("E") == 0

    def test_schema_with_no_fks_builds_empty_graph(self) -> None:
        schema = RawSchema(
            db_url_hash="x",
            tables=[
                TableSchema(name="foo", columns=[_col("id", pk=True)]),
                TableSchema(name="bar", columns=[_col("id", pk=True)]),
            ],
        )
        g = FKGraphBuilder(schema)
        assert g._graph.number_of_edges() == 0
        assert g.find_join_path("foo", "bar") is None

    def test_empty_schema_builds_without_error(self) -> None:
        schema = RawSchema(db_url_hash="empty", tables=[])
        g = FKGraphBuilder(schema)
        assert g._graph.number_of_nodes() == 0
