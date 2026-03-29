"""Tests for SchemaCache using fakeredis (no real Redis required)."""

from __future__ import annotations

import fakeredis.aioredis as faio
import pytest

from core.models import AnnotatedSchema, ColumnSchema, TableSchema
from schema.cache import SchemaCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_schema(db_url_hash: str = "abc123") -> AnnotatedSchema:
    """Minimal but realistic AnnotatedSchema for round-trip tests."""
    return AnnotatedSchema(
        db_url_hash=db_url_hash,
        tables=[
            TableSchema(
                name="customer",
                description="Customer master",
                columns=[
                    ColumnSchema(
                        name="customer_id",
                        type="INTEGER",
                        is_primary_key=True,
                        description="PK",
                    ),
                    ColumnSchema(
                        name="email",
                        type="VARCHAR",
                        description="Customer email address",
                    ),
                ],
            ),
            TableSchema(
                name="payment",
                columns=[
                    ColumnSchema(
                        name="payment_id",
                        type="INTEGER",
                        is_primary_key=True,
                    ),
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
        glossary={"revenue": "total payment amounts"},
    )


@pytest.fixture()
async def cache() -> SchemaCache:
    client = faio.FakeRedis(decode_responses=True)
    return SchemaCache._from_client(client, ttl_seconds=120)


# ---------------------------------------------------------------------------
# get / set round-trip
# ---------------------------------------------------------------------------

async def test_get_returns_none_when_empty(cache: SchemaCache) -> None:
    result = await cache.get("no_such_hash")
    assert result is None


async def test_set_then_get_returns_schema(cache: SchemaCache) -> None:
    schema = _make_schema()
    await cache.set(schema.db_url_hash, schema)
    result = await cache.get(schema.db_url_hash)
    assert result is not None
    assert result.db_url_hash == schema.db_url_hash


async def test_round_trip_preserves_table_count(cache: SchemaCache) -> None:
    schema = _make_schema()
    await cache.set(schema.db_url_hash, schema)
    result = await cache.get(schema.db_url_hash)
    assert result is not None
    assert len(result.tables) == len(schema.tables)


async def test_round_trip_preserves_column_names(cache: SchemaCache) -> None:
    schema = _make_schema()
    await cache.set(schema.db_url_hash, schema)
    result = await cache.get(schema.db_url_hash)
    assert result is not None
    orig_cols = [c.name for t in schema.tables for c in t.columns]
    cached_cols = [c.name for t in result.tables for c in t.columns]
    assert cached_cols == orig_cols


async def test_round_trip_preserves_pk_fk_flags(cache: SchemaCache) -> None:
    schema = _make_schema()
    await cache.set(schema.db_url_hash, schema)
    result = await cache.get(schema.db_url_hash)
    assert result is not None
    payment = next(t for t in result.tables if t.name == "payment")
    fk_col = next(c for c in payment.columns if c.name == "customer_id")
    assert fk_col.is_foreign_key is True
    assert fk_col.references_table == "customer"
    assert fk_col.references_column == "customer_id"


async def test_round_trip_preserves_column_description(cache: SchemaCache) -> None:
    schema = _make_schema()
    await cache.set(schema.db_url_hash, schema)
    result = await cache.get(schema.db_url_hash)
    assert result is not None
    customer = next(t for t in result.tables if t.name == "customer")
    email_col = next(c for c in customer.columns if c.name == "email")
    assert email_col.description == "Customer email address"


async def test_round_trip_preserves_glossary(cache: SchemaCache) -> None:
    schema = _make_schema()
    await cache.set(schema.db_url_hash, schema)
    result = await cache.get(schema.db_url_hash)
    assert result is not None
    assert result.glossary == {"revenue": "total payment amounts"}


async def test_round_trip_preserves_table_description(cache: SchemaCache) -> None:
    schema = _make_schema()
    await cache.set(schema.db_url_hash, schema)
    result = await cache.get(schema.db_url_hash)
    assert result is not None
    customer = next(t for t in result.tables if t.name == "customer")
    assert customer.description == "Customer master"


# ---------------------------------------------------------------------------
# TTL
# ---------------------------------------------------------------------------

async def test_ttl_is_set_after_store(cache: SchemaCache) -> None:
    schema = _make_schema()
    await cache.set(schema.db_url_hash, schema)
    ttl = await cache._client.ttl(f"mercer:schema:{schema.db_url_hash}")
    # TTL should be positive and ≤ configured value (120 s)
    assert 0 < ttl <= 120


async def test_custom_ttl_is_respected() -> None:
    client = faio.FakeRedis(decode_responses=True)
    short_cache = SchemaCache._from_client(client, ttl_seconds=42)
    schema = _make_schema("ttl_test")
    await short_cache.set(schema.db_url_hash, schema)
    ttl = await client.ttl("mercer:schema:ttl_test")
    assert 0 < ttl <= 42


# ---------------------------------------------------------------------------
# invalidate (single key)
# ---------------------------------------------------------------------------

async def test_invalidate_removes_key(cache: SchemaCache) -> None:
    schema = _make_schema()
    await cache.set(schema.db_url_hash, schema)
    assert await cache.get(schema.db_url_hash) is not None

    await cache.invalidate(schema.db_url_hash)
    assert await cache.get(schema.db_url_hash) is None


async def test_invalidate_nonexistent_key_does_not_raise(cache: SchemaCache) -> None:
    await cache.invalidate("ghost_hash")  # must not raise


# ---------------------------------------------------------------------------
# invalidate_all
# ---------------------------------------------------------------------------

async def test_invalidate_all_removes_all_keys(cache: SchemaCache) -> None:
    for i in range(3):
        await cache.set(f"hash_{i}", _make_schema(f"hash_{i}"))

    count = await cache.invalidate_all()
    assert count == 3
    for i in range(3):
        assert await cache.get(f"hash_{i}") is None


async def test_invalidate_all_returns_zero_when_empty(cache: SchemaCache) -> None:
    count = await cache.invalidate_all()
    assert count == 0


async def test_invalidate_all_does_not_remove_unrelated_keys(cache: SchemaCache) -> None:
    # Seed a key outside the mercer:schema: namespace
    await cache._client.set("other:namespace:key", "value")

    await cache.set("my_schema", _make_schema("my_schema"))
    await cache.invalidate_all()

    # Unrelated key should still be there
    assert await cache._client.get("other:namespace:key") == "value"


# ---------------------------------------------------------------------------
# Overwrite behaviour
# ---------------------------------------------------------------------------

async def test_set_overwrites_existing_entry(cache: SchemaCache) -> None:
    schema_v1 = _make_schema("shared_hash")
    schema_v2 = AnnotatedSchema(
        db_url_hash="shared_hash",
        tables=[
            TableSchema(
                name="orders",
                columns=[ColumnSchema(name="order_id", type="INTEGER", is_primary_key=True)],
            )
        ],
    )
    await cache.set("shared_hash", schema_v1)
    await cache.set("shared_hash", schema_v2)

    result = await cache.get("shared_hash")
    assert result is not None
    assert result.tables[0].name == "orders"
