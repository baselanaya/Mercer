"""Tests for GlossaryExpander, BM25ColumnRetriever, LSHEntityMatcher,
and the EntityRetriever orchestrator.

Uses a small in-memory AnnotatedSchema (5 tables, 20 columns) that mirrors
a simplified e-commerce / rental database.
"""

from __future__ import annotations

import pytest

from core.entity_retriever import (
    BM25ColumnRetriever,
    EntityRetriever,
    GlossaryExpander,
    LSHEntityMatcher,
    _tokenize,
)
from core.models import AnnotatedSchema, ColumnSchema, TableSchema

# ---------------------------------------------------------------------------
# Schema fixture — 5 tables, 20 columns
# ---------------------------------------------------------------------------

@pytest.fixture()
def schema() -> AnnotatedSchema:
    def col(name: str, desc: str | None = None, pk: bool = False, fk: bool = False) -> ColumnSchema:
        return ColumnSchema(name=name, type="INTEGER" if "id" in name else "TEXT",
                            description=desc, is_primary_key=pk, is_foreign_key=fk)

    return AnnotatedSchema(
        db_url_hash="test",
        tables=[
            TableSchema(
                name="customer",
                description="Customer master table",
                columns=[
                    col("customer_id", "Unique customer identifier", pk=True),
                    col("first_name", "Customer first name"),
                    col("last_name", "Customer last name"),
                    col("email", "Customer email address"),
                ],
            ),
            TableSchema(
                name="payment",
                description="Payment transactions",
                columns=[
                    col("payment_id", "Payment identifier", pk=True),
                    col("customer_id", "FK to customer", fk=True),
                    col("amount", "Payment amount in USD"),
                    col("payment_date", "Date payment was made"),
                ],
            ),
            TableSchema(
                name="film",
                description="Film catalogue",
                columns=[
                    col("film_id", "Film identifier", pk=True),
                    col("title", "Film title"),
                    col("rental_duration", "Rental duration in days"),
                    col("rating", "MPAA rating"),
                ],
            ),
            TableSchema(
                name="rental",
                description="Rental transactions",
                columns=[
                    col("rental_id", "Rental identifier", pk=True),
                    col("customer_id", "FK to customer", fk=True),
                    col("film_id", "FK to film", fk=True),
                    col("rental_date", "Date of rental"),
                ],
            ),
            TableSchema(
                name="actor",
                description="Actor registry",
                columns=[
                    col("actor_id", "Actor identifier", pk=True),
                    col("first_name", "Actor first name"),
                    col("last_name", "Actor last name"),
                    col("birth_year", "Year actor was born"),
                ],
            ),
        ],
    )


@pytest.fixture()
def glossary() -> dict[str, str]:
    return {
        "revenue":        "SUM(payment.amount)",
        "top customers":  "customers ordered by SUM(payment.amount) DESC",
        "active":         "customer has at least one rental",
        "rental period":  "rental_duration in days",
    }


# ---------------------------------------------------------------------------
# _tokenize helper
# ---------------------------------------------------------------------------

def test_tokenize_lowercases() -> None:
    assert _tokenize("Hello World") == ["hello", "world"]


def test_tokenize_strips_punctuation() -> None:
    assert _tokenize("film.title,rating") == ["film", "title", "rating"]


def test_tokenize_empty_string() -> None:
    assert _tokenize("") == []


def test_tokenize_filters_empty_tokens() -> None:
    tokens = _tokenize("  a  b  ")
    assert "" not in tokens


# ---------------------------------------------------------------------------
# GlossaryExpander
# ---------------------------------------------------------------------------

class TestGlossaryExpander:
    def test_expand_known_term(self, glossary: dict[str, str]) -> None:
        expander = GlossaryExpander(glossary)
        hits = expander.expand("Show revenue by customer")
        assert "revenue" in hits
        assert hits["revenue"] == "SUM(payment.amount)"

    def test_expand_multi_word_term(self, glossary: dict[str, str]) -> None:
        expander = GlossaryExpander(glossary)
        hits = expander.expand("List top customers by spend")
        assert "top customers" in hits

    def test_expand_unknown_term_not_included(self, glossary: dict[str, str]) -> None:
        expander = GlossaryExpander(glossary)
        hits = expander.expand("How many films are there?")
        assert not hits

    def test_expand_case_insensitive(self, glossary: dict[str, str]) -> None:
        expander = GlossaryExpander(glossary)
        hits = expander.expand("Show REVENUE per region")
        assert "revenue" in hits

    def test_expand_returns_empty_dict_for_no_match(self, glossary: dict[str, str]) -> None:
        expander = GlossaryExpander(glossary)
        assert expander.expand("what is the weather today") == {}

    def test_apply_appends_expansion(self, glossary: dict[str, str]) -> None:
        expander = GlossaryExpander(glossary)
        result = expander.apply("Show revenue by customer")
        assert result.startswith("Show revenue by customer")
        assert "SUM(payment.amount)" in result

    def test_apply_no_match_returns_original(self, glossary: dict[str, str]) -> None:
        expander = GlossaryExpander(glossary)
        question = "How many actors are there?"
        assert expander.apply(question) == question

    def test_apply_multiple_expansions(self, glossary: dict[str, str]) -> None:
        expander = GlossaryExpander(glossary)
        result = expander.apply("Show revenue for active customers")
        assert "SUM(payment.amount)" in result
        assert "customer has at least one rental" in result

    def test_longer_term_matched_first(self, glossary: dict[str, str]) -> None:
        # "top customers" is longer than neither term alone — both should appear
        expander = GlossaryExpander(glossary)
        hits = expander.expand("Find top customers by revenue")
        assert "top customers" in hits
        assert "revenue" in hits


# ---------------------------------------------------------------------------
# BM25ColumnRetriever
# ---------------------------------------------------------------------------

class TestBM25ColumnRetriever:
    def test_build_index_no_exception(self, schema: AnnotatedSchema) -> None:
        retriever = BM25ColumnRetriever(schema)
        retriever.build_index()  # must not raise

    def test_search_returns_list(self, schema: AnnotatedSchema) -> None:
        retriever = BM25ColumnRetriever(schema)
        results = retriever.search("customer payment amount")
        assert isinstance(results, list)

    def test_search_returns_tuples(self, schema: AnnotatedSchema) -> None:
        retriever = BM25ColumnRetriever(schema)
        results = retriever.search("rental date")
        assert all(len(r) == 3 for r in results)

    def test_search_payment_amount_ranks_high(self, schema: AnnotatedSchema) -> None:
        retriever = BM25ColumnRetriever(schema)
        results = retriever.search("payment amount")
        tables_cols = [(t, c) for t, c, _ in results]
        assert ("payment", "amount") in tables_cols

    def test_search_customer_email_returns_customer_table(self, schema: AnnotatedSchema) -> None:
        retriever = BM25ColumnRetriever(schema)
        results = retriever.search("customer email address")
        tables = [t for t, _, _ in results]
        assert "customer" in tables

    def test_search_top_k_respected(self, schema: AnnotatedSchema) -> None:
        retriever = BM25ColumnRetriever(schema)
        results = retriever.search("id name date amount title rating", top_k=3)
        assert len(results) <= 3

    def test_search_scores_positive(self, schema: AnnotatedSchema) -> None:
        retriever = BM25ColumnRetriever(schema)
        results = retriever.search("film title rental")
        assert all(score > 0 for _, _, score in results)

    def test_search_empty_question_returns_empty(self, schema: AnnotatedSchema) -> None:
        retriever = BM25ColumnRetriever(schema)
        assert retriever.search("") == []

    def test_index_rebuilt_lazily(self, schema: AnnotatedSchema) -> None:
        retriever = BM25ColumnRetriever(schema)
        # Should not raise even without explicit build_index() call
        results = retriever.search("actor first name")
        assert isinstance(results, list)

    def test_search_actor_name_finds_actor_table(self, schema: AnnotatedSchema) -> None:
        retriever = BM25ColumnRetriever(schema)
        results = retriever.search("actor name")
        tables = [t for t, _, _ in results]
        assert "actor" in tables


# ---------------------------------------------------------------------------
# LSHEntityMatcher
# ---------------------------------------------------------------------------

class TestLSHEntityMatcher:
    def test_build_index_no_exception(self, schema: AnnotatedSchema) -> None:
        matcher = LSHEntityMatcher(schema)
        matcher.build_index()  # must not raise

    def test_match_returns_list(self, schema: AnnotatedSchema) -> None:
        matcher = LSHEntityMatcher(schema)
        results = matcher.match(["customer", "payment"])
        assert isinstance(results, list)

    def test_match_customer_token_hits_customer_table(self, schema: AnnotatedSchema) -> None:
        matcher = LSHEntityMatcher(schema)
        results = matcher.match(["customer"])
        tables = [m.table for m in results]
        assert "customer" in tables

    def test_match_returns_entity_match_objects(self, schema: AnnotatedSchema) -> None:
        from core.models import EntityMatch
        matcher = LSHEntityMatcher(schema)
        results = matcher.match(["film"])
        assert all(isinstance(r, EntityMatch) for r in results)

    def test_match_scores_between_0_and_1(self, schema: AnnotatedSchema) -> None:
        matcher = LSHEntityMatcher(schema)
        results = matcher.match(["rental", "customer", "payment"])
        assert all(0.0 <= m.score <= 1.0 for m in results)

    def test_match_no_duplicates(self, schema: AnnotatedSchema) -> None:
        matcher = LSHEntityMatcher(schema)
        results = matcher.match(["payment", "payment"])
        keys = [(m.token, m.table, m.column) for m in results]
        assert len(keys) == len(set(keys))

    def test_match_empty_tokens_returns_empty(self, schema: AnnotatedSchema) -> None:
        matcher = LSHEntityMatcher(schema)
        assert matcher.match([]) == []

    def test_match_lazy_index_build(self, schema: AnnotatedSchema) -> None:
        matcher = LSHEntityMatcher(schema)
        # Call match without explicit build_index — should not raise
        results = matcher.match(["film"])
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# EntityRetriever (orchestrator)
# ---------------------------------------------------------------------------

class TestEntityRetriever:
    def test_retrieve_returns_entity_context(
        self, schema: AnnotatedSchema, glossary: dict[str, str]
    ) -> None:
        from core.models import EntityContext
        retriever = EntityRetriever(schema, glossary)
        ctx = retriever.retrieve("Show total payment amount per customer")
        assert isinstance(ctx, EntityContext)

    def test_retrieve_preserves_original_question(
        self, schema: AnnotatedSchema, glossary: dict[str, str]
    ) -> None:
        retriever = EntityRetriever(schema, glossary)
        q = "How many films are there?"
        ctx = retriever.retrieve(q)
        assert ctx.original_question == q

    def test_retrieve_expands_glossary_terms(
        self, schema: AnnotatedSchema, glossary: dict[str, str]
    ) -> None:
        retriever = EntityRetriever(schema, glossary)
        ctx = retriever.retrieve("Show revenue by customer")
        assert "revenue" in ctx.glossary_expansions
        assert "SUM(payment.amount)" in ctx.expanded_question

    def test_retrieve_no_glossary_hit_unchanged(
        self, schema: AnnotatedSchema, glossary: dict[str, str]
    ) -> None:
        retriever = EntityRetriever(schema, glossary)
        ctx = retriever.retrieve("List all films")
        assert ctx.glossary_expansions == {}
        assert ctx.original_question == ctx.expanded_question

    def test_retrieve_entity_matches_non_empty_for_relevant_question(
        self, schema: AnnotatedSchema, glossary: dict[str, str]
    ) -> None:
        retriever = EntityRetriever(schema, glossary)
        ctx = retriever.retrieve("Show total payment amount for each customer")
        assert len(ctx.entity_matches) > 0

    def test_retrieve_entity_matches_cover_relevant_tables(
        self, schema: AnnotatedSchema, glossary: dict[str, str]
    ) -> None:
        retriever = EntityRetriever(schema, glossary)
        ctx = retriever.retrieve("Show payment amount and customer email")
        tables = {m.table for m in ctx.entity_matches}
        assert "payment" in tables or "customer" in tables

    def test_retrieve_film_query_matches_film_table(
        self, schema: AnnotatedSchema, glossary: dict[str, str]
    ) -> None:
        retriever = EntityRetriever(schema, glossary)
        ctx = retriever.retrieve("List all film titles and their rental duration")
        tables = {m.table for m in ctx.entity_matches}
        assert "film" in tables

    def test_retrieve_with_empty_glossary(self, schema: AnnotatedSchema) -> None:
        retriever = EntityRetriever(schema, glossary={})
        ctx = retriever.retrieve("Show customer emails")
        assert ctx.glossary_expansions == {}
        assert len(ctx.entity_matches) > 0

    def test_retrieve_sorted_by_score_descending(
        self, schema: AnnotatedSchema, glossary: dict[str, str]
    ) -> None:
        retriever = EntityRetriever(schema, glossary)
        ctx = retriever.retrieve("Show payment amount customer date")
        scores = [m.score for m in ctx.entity_matches]
        assert scores == sorted(scores, reverse=True)

    def test_retrieve_actor_query_matches_actor_table(
        self, schema: AnnotatedSchema, glossary: dict[str, str]
    ) -> None:
        retriever = EntityRetriever(schema, glossary)
        ctx = retriever.retrieve("List actor first and last names")
        tables = {m.table for m in ctx.entity_matches}
        assert "actor" in tables


# ---------------------------------------------------------------------------
# Sample-value LSH integration (regression: previously ColumnSchema had no
# sample_values field, so LSH always fell back to indexing column names)
# ---------------------------------------------------------------------------

def test_lsh_indexes_actual_sample_values() -> None:
    """LSHEntityMatcher must index col.sample_values when populated.

    With sample_values like ['RETAIL', 'CORP', 'SMB'] on a column named
    'cust_seg_cd', a query token 'retail' should match the column via
    its values, not via the column name (which doesn't contain 'retail').
    """
    from core.entity_retriever import LSHEntityMatcher
    from core.models import AnnotatedSchema, ColumnSchema, TableSchema

    schema = AnnotatedSchema(
        db_url_hash="test",
        tables=[
            TableSchema(
                name="customer",
                columns=[
                    ColumnSchema(
                        name="cust_seg_cd",
                        type="TEXT",
                        sample_values=["RETAIL", "CORP", "SMB"],
                    ),
                    ColumnSchema(
                        name="cust_name",
                        type="TEXT",
                        sample_values=["Alice", "Bob"],
                    ),
                ],
            ),
        ],
    )

    matcher = LSHEntityMatcher(schema)
    matcher.build_index()
    matches = matcher.match(["retail"])

    assert any(
        m.column == "cust_seg_cd" and "RETAIL" in m.matched_value.upper()
        for m in matches
    ), f"expected LSH to match 'retail' against RETAIL value; got: {matches}"


def test_lsh_falls_back_to_column_name_when_no_samples() -> None:
    """When sample_values is None (legacy path), LSH still uses col.name."""
    from core.entity_retriever import LSHEntityMatcher
    from core.models import AnnotatedSchema, ColumnSchema, TableSchema

    schema = AnnotatedSchema(
        db_url_hash="test",
        tables=[
            TableSchema(
                name="orders",
                columns=[
                    ColumnSchema(name="order_id", type="INTEGER", sample_values=None),
                ],
            ),
        ],
    )
    matcher = LSHEntityMatcher(schema)
    matcher.build_index()
    matches = matcher.match(["order"])
    assert any(m.column == "order_id" for m in matches)


def test_lsh_handles_empty_sample_values() -> None:
    """sample_values=[] (column was skipped or empty) must not crash."""
    from core.entity_retriever import LSHEntityMatcher
    from core.models import AnnotatedSchema, ColumnSchema, TableSchema

    schema = AnnotatedSchema(
        db_url_hash="test",
        tables=[
            TableSchema(
                name="t",
                columns=[
                    ColumnSchema(name="empty_col", type="TEXT", sample_values=[]),
                    ColumnSchema(name="name_col", type="TEXT", sample_values=None),
                ],
            ),
        ],
    )
    matcher = LSHEntityMatcher(schema)
    matcher.build_index()
    matches = matcher.match(["name"])
    assert any(m.column == "name_col" for m in matches)
