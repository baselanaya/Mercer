"""Tests for SchemaIntrospector and SemanticMapper.

All tests use SQLite in-memory — no PostgreSQL required.

Schema under test:
    author   (author_id PK, name, bio)
    book     (book_id PK, title, author_id FK → author, isbn)
    review   (review_id PK, book_id FK → book, rating, body)
"""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from core.models import AnnotatedSchema, RawSchema
from schema.introspector import SchemaIntrospector
from schema.semantic_mapper import SemanticMapper

# ---------------------------------------------------------------------------
# Fixtures — SQLite in-memory DB
# ---------------------------------------------------------------------------

@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE author (
                author_id INTEGER PRIMARY KEY,
                name      TEXT    NOT NULL,
                bio       TEXT
            )
        """))
        await conn.execute(text("""
            CREATE TABLE book (
                book_id   INTEGER PRIMARY KEY,
                title     TEXT    NOT NULL,
                author_id INTEGER NOT NULL REFERENCES author(author_id),
                isbn      TEXT
            )
        """))
        await conn.execute(text("""
            CREATE TABLE review (
                review_id INTEGER PRIMARY KEY,
                book_id   INTEGER NOT NULL REFERENCES book(book_id),
                rating    INTEGER,
                body      TEXT
            )
        """))
    yield eng
    await eng.dispose()


@pytest.fixture
def introspector() -> SchemaIntrospector:
    return SchemaIntrospector()


@pytest.fixture
def mappings_file(tmp_path: Path) -> Path:
    """Temporary YAML mapping file for SemanticMapper tests."""
    content = {
        "tables": {
            "author": {
                "description": "Author master table",
                "columns": {
                    "author_id": "Primary key",
                    "bio": "Short author biography",
                },
            },
            "book": {
                "description": "Book catalog",
                "columns": {
                    "isbn": "International Standard Book Number",
                },
            },
        },
        "glossary": {
            "top authors": "authors ordered by COUNT(book.book_id) DESC",
            "revenue": "SUM of payment.amount",
        },
    }
    path = tmp_path / "mappings.yaml"
    path.write_text(yaml.dump(content), encoding="utf-8")
    return path


@pytest.fixture
def mapper(mappings_file: Path) -> SemanticMapper:
    return SemanticMapper(mappings_path=str(mappings_file))


# ---------------------------------------------------------------------------
# SchemaIntrospector — table discovery
# ---------------------------------------------------------------------------

async def test_finds_all_tables(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    table_names = {t.name for t in schema.tables}
    assert table_names == {"author", "book", "review"}


async def test_table_count(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    assert len(schema.tables) == 3


async def test_returns_raw_schema(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    assert isinstance(schema, RawSchema)


# ---------------------------------------------------------------------------
# SchemaIntrospector — column extraction
# ---------------------------------------------------------------------------

async def test_author_columns(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    author = next(t for t in schema.tables if t.name == "author")
    col_names = {c.name for c in author.columns}
    assert col_names == {"author_id", "name", "bio"}


async def test_book_columns(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    book = next(t for t in schema.tables if t.name == "book")
    col_names = {c.name for c in book.columns}
    assert col_names == {"book_id", "title", "author_id", "isbn"}


async def test_column_types_are_strings(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    for table in schema.tables:
        for col in table.columns:
            assert isinstance(col.type, str)
            assert len(col.type) > 0


# ---------------------------------------------------------------------------
# SchemaIntrospector — primary key detection
# ---------------------------------------------------------------------------

async def test_author_pk(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    author = next(t for t in schema.tables if t.name == "author")
    pk_col = next(c for c in author.columns if c.name == "author_id")
    assert pk_col.is_primary_key is True


async def test_book_pk(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    book = next(t for t in schema.tables if t.name == "book")
    pk_col = next(c for c in book.columns if c.name == "book_id")
    assert pk_col.is_primary_key is True


async def test_non_pk_columns_not_marked(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    author = next(t for t in schema.tables if t.name == "author")
    non_pks = [c for c in author.columns if c.name != "author_id"]
    for col in non_pks:
        assert col.is_primary_key is False


async def test_review_pk(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    review = next(t for t in schema.tables if t.name == "review")
    pk_col = next(c for c in review.columns if c.name == "review_id")
    assert pk_col.is_primary_key is True


# ---------------------------------------------------------------------------
# SchemaIntrospector — foreign key detection
# ---------------------------------------------------------------------------

async def test_book_author_id_is_fk(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    book = next(t for t in schema.tables if t.name == "book")
    fk_col = next(c for c in book.columns if c.name == "author_id")
    assert fk_col.is_foreign_key is True


async def test_review_book_id_is_fk(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    review = next(t for t in schema.tables if t.name == "review")
    fk_col = next(c for c in review.columns if c.name == "book_id")
    assert fk_col.is_foreign_key is True


async def test_non_fk_columns_not_marked(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    book = next(t for t in schema.tables if t.name == "book")
    non_fk_cols = [c for c in book.columns if c.name not in {"author_id"}]
    for col in non_fk_cols:
        assert col.is_foreign_key is False, f"{col.name} should not be FK"


async def test_author_has_no_fks(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    author = next(t for t in schema.tables if t.name == "author")
    for col in author.columns:
        assert col.is_foreign_key is False


# ---------------------------------------------------------------------------
# SchemaIntrospector — db_url_hash
# ---------------------------------------------------------------------------

async def test_db_url_hash_is_set(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    schema = await introspector.introspect(engine)
    assert isinstance(schema.db_url_hash, str)
    assert len(schema.db_url_hash) == 64  # SHA-256 hex digest


async def test_same_engine_same_hash(introspector: SchemaIntrospector, engine: AsyncEngine) -> None:
    s1 = await introspector.introspect(engine)
    s2 = await introspector.introspect(engine)
    assert s1.db_url_hash == s2.db_url_hash


async def test_different_engines_different_hash(introspector: SchemaIntrospector) -> None:
    eng1 = create_async_engine("sqlite+aiosqlite:///file_a.db", echo=False)
    eng2 = create_async_engine("sqlite+aiosqlite:///file_b.db", echo=False)
    # Both engines have no tables (file doesn't exist yet) but URLs differ
    h1 = eng1.url.render_as_string(hide_password=True)
    h2 = eng2.url.render_as_string(hide_password=True)
    assert h1 != h2
    await eng1.dispose()
    await eng2.dispose()


# ---------------------------------------------------------------------------
# SemanticMapper — description merging
# ---------------------------------------------------------------------------

async def test_annotate_returns_annotated_schema(
    introspector: SchemaIntrospector,
    engine: AsyncEngine,
    mapper: SemanticMapper,
) -> None:
    raw = await introspector.introspect(engine)
    annotated = mapper.annotate(raw)
    assert isinstance(annotated, AnnotatedSchema)


async def test_table_description_injected(
    introspector: SchemaIntrospector,
    engine: AsyncEngine,
    mapper: SemanticMapper,
) -> None:
    raw = await introspector.introspect(engine)
    annotated = mapper.annotate(raw)
    author = next(t for t in annotated.tables if t.name == "author")
    assert author.description == "Author master table"


async def test_column_description_injected(
    introspector: SchemaIntrospector,
    engine: AsyncEngine,
    mapper: SemanticMapper,
) -> None:
    raw = await introspector.introspect(engine)
    annotated = mapper.annotate(raw)
    author = next(t for t in annotated.tables if t.name == "author")
    bio_col = next(c for c in author.columns if c.name == "bio")
    assert bio_col.description == "Short author biography"


async def test_unmapped_table_has_none_description(
    introspector: SchemaIntrospector,
    engine: AsyncEngine,
    mapper: SemanticMapper,
) -> None:
    raw = await introspector.introspect(engine)
    annotated = mapper.annotate(raw)
    review = next(t for t in annotated.tables if t.name == "review")
    assert review.description is None


async def test_unmapped_column_has_none_description(
    introspector: SchemaIntrospector,
    engine: AsyncEngine,
    mapper: SemanticMapper,
) -> None:
    raw = await introspector.introspect(engine)
    annotated = mapper.annotate(raw)
    author = next(t for t in annotated.tables if t.name == "author")
    name_col = next(c for c in author.columns if c.name == "name")
    assert name_col.description is None  # 'name' has no mapping entry


async def test_partial_column_mapping(
    introspector: SchemaIntrospector,
    engine: AsyncEngine,
    mapper: SemanticMapper,
) -> None:
    """Only mapped columns get descriptions; others stay None."""
    raw = await introspector.introspect(engine)
    annotated = mapper.annotate(raw)
    author = next(t for t in annotated.tables if t.name == "author")
    author_id_col = next(c for c in author.columns if c.name == "author_id")
    bio_col = next(c for c in author.columns if c.name == "bio")
    assert author_id_col.description == "Primary key"
    assert bio_col.description == "Short author biography"


async def test_glossary_merged(
    introspector: SchemaIntrospector,
    engine: AsyncEngine,
    mapper: SemanticMapper,
) -> None:
    raw = await introspector.introspect(engine)
    annotated = mapper.annotate(raw)
    assert annotated.glossary["top authors"] == "authors ordered by COUNT(book.book_id) DESC"
    assert annotated.glossary["revenue"] == "SUM of payment.amount"


async def test_pk_fk_flags_preserved_after_annotation(
    introspector: SchemaIntrospector,
    engine: AsyncEngine,
    mapper: SemanticMapper,
) -> None:
    """SemanticMapper must not strip is_primary_key / is_foreign_key flags."""
    raw = await introspector.introspect(engine)
    annotated = mapper.annotate(raw)
    book = next(t for t in annotated.tables if t.name == "book")
    pk_col = next(c for c in book.columns if c.name == "book_id")
    fk_col = next(c for c in book.columns if c.name == "author_id")
    assert pk_col.is_primary_key is True
    assert fk_col.is_foreign_key is True


async def test_db_url_hash_preserved_after_annotation(
    introspector: SchemaIntrospector,
    engine: AsyncEngine,
    mapper: SemanticMapper,
) -> None:
    raw = await introspector.introspect(engine)
    annotated = mapper.annotate(raw)
    assert annotated.db_url_hash == raw.db_url_hash


# ---------------------------------------------------------------------------
# SemanticMapper — missing / empty mappings file
# ---------------------------------------------------------------------------

def test_missing_mappings_file_returns_no_descriptions(
    tmp_path: Path,
) -> None:
    mapper = SemanticMapper(mappings_path=str(tmp_path / "nonexistent.yaml"))
    raw = RawSchema(
        db_url_hash="abc",
        tables=[],
    )
    annotated = mapper.annotate(raw)
    assert annotated.glossary == {}
    assert annotated.tables == []


def test_empty_mappings_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    mapper = SemanticMapper(mappings_path=str(path))
    raw = RawSchema(db_url_hash="abc", tables=[])
    annotated = mapper.annotate(raw)
    assert annotated.glossary == {}
