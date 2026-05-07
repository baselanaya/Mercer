"""Tests for prompts.m_schema (XiYan-SQL M-Schema rendering)."""

from __future__ import annotations

import pytest

from core.models import (
    AnnotatedSchema,
    ColumnSchema,
    FilteredSchema,
    JoinPath,
    TableSchema,
)
from prompts.m_schema import (
    MAX_SAMPLE_RENDER_LEN,
    SAMPLES_PER_COLUMN,
    _render_samples,
    format_filtered_schema,
    format_full_schema,
    format_table,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def customer_table() -> TableSchema:
    return TableSchema(
        name="customer",
        description="Customer master table",
        columns=[
            ColumnSchema(
                name="cust_id",
                type="INTEGER",
                is_primary_key=True,
                sample_values=["1", "2", "3"],
            ),
            ColumnSchema(
                name="cust_seg_cd",
                type="TEXT",
                description="Customer segment code",
                sample_values=["RETAIL", "CORP", "SMB"],
            ),
            ColumnSchema(
                name="e_add",
                type="TEXT",
                description="Email — legacy",
                sample_values=["alice@x.com", "bob@x.com"],
            ),
        ],
    )


@pytest.fixture
def payment_table() -> TableSchema:
    return TableSchema(
        name="payment",
        columns=[
            ColumnSchema(
                name="pay_id",
                type="INTEGER",
                is_primary_key=True,
                sample_values=["10", "11"],
            ),
            ColumnSchema(
                name="cust_id",
                type="INTEGER",
                is_foreign_key=True,
                references_table="customer",
                references_column="cust_id",
                sample_values=["1", "2"],
            ),
            ColumnSchema(
                name="amount",
                type="NUMERIC",
                sample_values=["12.50", "100.00"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# _render_samples — inline value rendering
# ---------------------------------------------------------------------------

class TestRenderSamples:
    def test_none_returns_empty(self) -> None:
        assert _render_samples(None) == ""

    def test_empty_list_returns_empty(self) -> None:
        assert _render_samples([]) == ""

    def test_renders_quoted_csv(self) -> None:
        assert _render_samples(["a", "b"]) == '"a", "b"'

    def test_caps_at_samples_per_column(self) -> None:
        many = [str(i) for i in range(SAMPLES_PER_COLUMN * 2)]
        result = _render_samples(many)
        assert result.count(",") == SAMPLES_PER_COLUMN - 1

    def test_truncates_long_values(self) -> None:
        long = "x" * (MAX_SAMPLE_RENDER_LEN * 2)
        result = _render_samples([long])
        assert "…" in result
        # Length: 2 quotes + truncated content + ellipsis
        assert len(result) <= MAX_SAMPLE_RENDER_LEN + 4

    def test_escapes_embedded_quotes(self) -> None:
        result = _render_samples(['has "quotes" inside'])
        # The double quotes inside must be escaped so the wrapper quotes
        # remain unambiguous.
        assert r'\"quotes\"' in result


# ---------------------------------------------------------------------------
# format_table
# ---------------------------------------------------------------------------

class TestFormatTable:
    def test_header_includes_table_name(self, customer_table: TableSchema) -> None:
        out = format_table(customer_table)
        assert out.startswith("# Table: customer")

    def test_header_includes_description(self, customer_table: TableSchema) -> None:
        out = format_table(customer_table)
        assert "Customer master table" in out.splitlines()[0]

    def test_pk_is_marked(self, customer_table: TableSchema) -> None:
        out = format_table(customer_table)
        # cust_id is the PK — must have PK flag
        assert "(cust_id:INTEGER, PK," in out

    def test_fk_target_is_rendered(self, payment_table: TableSchema) -> None:
        out = format_table(payment_table)
        assert "→customer.cust_id" in out

    def test_sample_values_appear_inline(self, customer_table: TableSchema) -> None:
        out = format_table(customer_table)
        assert '"RETAIL"' in out
        assert '"CORP"' in out
        assert '"SMB"' in out

    def test_description_renders_as_trailing_comment(
        self, customer_table: TableSchema
    ) -> None:
        out = format_table(customer_table)
        # The cust_seg_cd line should end with the description as comment
        line = next(
            line for line in out.splitlines() if "cust_seg_cd" in line
        )
        assert "-- Customer segment code" in line

    def test_table_block_is_bracket_delimited(
        self, customer_table: TableSchema
    ) -> None:
        out = format_table(customer_table)
        # Body must open with [ and close with ]
        lines = out.splitlines()
        assert lines[1] == "["
        assert lines[-1] == "]"


# ---------------------------------------------------------------------------
# format_filtered_schema
# ---------------------------------------------------------------------------

class TestFormatFilteredSchema:
    def test_renders_all_tables(
        self, customer_table: TableSchema, payment_table: TableSchema
    ) -> None:
        fs = FilteredSchema(tables=[customer_table, payment_table], join_paths=[])
        out = format_filtered_schema(fs)
        assert "# Table: customer" in out
        assert "# Table: payment" in out

    def test_join_paths_section_appended(
        self, customer_table: TableSchema, payment_table: TableSchema
    ) -> None:
        fs = FilteredSchema(
            tables=[customer_table, payment_table],
            join_paths=[
                JoinPath(
                    from_table="payment",
                    from_column="cust_id",
                    to_table="customer",
                    to_column="cust_id",
                ),
            ],
        )
        out = format_filtered_schema(fs)
        assert "JOIN PATHS" in out
        assert "JOIN payment ON payment.cust_id = customer.cust_id" in out

    def test_no_join_paths_section_when_empty(
        self, customer_table: TableSchema
    ) -> None:
        fs = FilteredSchema(tables=[customer_table], join_paths=[])
        out = format_filtered_schema(fs)
        assert "JOIN PATHS" not in out


# ---------------------------------------------------------------------------
# format_full_schema
# ---------------------------------------------------------------------------

class TestFormatFullSchema:
    def test_glossary_section_appended(self, customer_table: TableSchema) -> None:
        schema = AnnotatedSchema(
            db_url_hash="h",
            tables=[customer_table],
            glossary={"revenue": "SUM(payment.amount)"},
        )
        out = format_full_schema(schema)
        assert "GLOSSARY" in out
        assert "revenue = SUM(payment.amount)" in out

    def test_no_glossary_section_when_empty(
        self, customer_table: TableSchema
    ) -> None:
        schema = AnnotatedSchema(
            db_url_hash="h", tables=[customer_table], glossary={}
        )
        out = format_full_schema(schema)
        assert "GLOSSARY" not in out


# ---------------------------------------------------------------------------
# Integration: columns with no sample_values render compactly
# ---------------------------------------------------------------------------

class TestNoSamplesGracefullyHandled:
    def test_column_without_samples_omits_sample_section(self) -> None:
        col = ColumnSchema(name="x", type="INTEGER", sample_values=None)
        table = TableSchema(name="t", columns=[col])
        out = format_table(table)
        # The tuple should contain just (name:type) — no extra commas before ).
        assert "(x:INTEGER)" in out

    def test_empty_sample_list_omits_sample_section(self) -> None:
        col = ColumnSchema(name="x", type="INTEGER", sample_values=[])
        table = TableSchema(name="t", columns=[col])
        out = format_table(table)
        assert "(x:INTEGER)" in out
