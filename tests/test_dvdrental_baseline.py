"""End-to-end baseline validation against the DVDRental schema.

Loads data/test_queries/dvdrental_baseline.yaml and runs all 5 queries
through MercerPipeline using:
  - A mocked LLM backend that returns the expected SQL (SQLite-adapted)
  - An in-memory SQLite database seeded with the relevant DVDRental tables

SQLite adaptations vs the PostgreSQL canonical SQL in the YAML:
  - EXTRACT(YEAR FROM col) → STRFTIME('%Y', col)
  - Otherwise identical SQL structure (same JOINs, GROUP BY, HAVING, etc.)

All 5 ExecutionResults must have success=True.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis as faio
import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from core.models import AnnotatedSchema, ColumnSchema, TableSchema
from core.pipeline import MercerPipeline
from schema.cache import SchemaCache


def _fake_cache() -> SchemaCache:
    return SchemaCache._from_client(faio.FakeRedis(decode_responses=True))

# ---------------------------------------------------------------------------
# SQLite-adapted versions of the 5 canonical PostgreSQL queries
# ---------------------------------------------------------------------------

# The YAML contains PostgreSQL SQL. We provide SQLite-compatible equivalents
# with identical structure (same joins, aggregations, filters) but adapted
# syntax where necessary.

SQLITE_SQL: dict[str, str] = {
    "dvd_01": """
        SELECT f.title, COUNT(r.rental_id) AS rental_count
        FROM film f
        JOIN inventory i ON f.film_id = i.film_id
        JOIN rental r    ON i.inventory_id = r.inventory_id
        GROUP BY f.film_id, f.title
        ORDER BY rental_count DESC
        LIMIT 5;
    """,
    "dvd_02": """
        SELECT
            c.customer_id,
            c.first_name,
            c.last_name,
            SUM(p.amount) AS total_amount
        FROM customer c
        JOIN payment p ON c.customer_id = p.customer_id
        WHERE STRFTIME('%Y', p.payment_date) = '2005'
        GROUP BY c.customer_id, c.first_name, c.last_name
        ORDER BY total_amount DESC;
    """,
    "dvd_03": """
        SELECT
            a.actor_id,
            a.first_name,
            a.last_name,
            COUNT(fa.film_id) AS film_count
        FROM actor a
        JOIN film_actor fa ON a.actor_id = fa.actor_id
        GROUP BY a.actor_id, a.first_name, a.last_name
        HAVING COUNT(fa.film_id) > 30
        ORDER BY film_count DESC;
    """,
    "dvd_04": """
        SELECT c.customer_id, c.first_name, c.last_name, c.email
        FROM customer c
        LEFT JOIN rental r ON c.customer_id = r.customer_id
        WHERE r.rental_id IS NULL
        ORDER BY c.customer_id;
    """,
    "dvd_05": """
        SELECT
            cat.name AS category,
            ROUND(AVG(f.rental_duration), 2) AS avg_rental_duration_days
        FROM category cat
        JOIN film_category fc ON cat.category_id = fc.category_id
        JOIN film f           ON fc.film_id = f.film_id
        GROUP BY cat.category_id, cat.name
        ORDER BY avg_rental_duration_days DESC;
    """,
}

# ---------------------------------------------------------------------------
# SQLite DVDRental schema (tables required by the 5 queries)
# ---------------------------------------------------------------------------

_DDL = [
    """CREATE TABLE film (
        film_id         INTEGER PRIMARY KEY,
        title           TEXT    NOT NULL,
        rental_duration INTEGER NOT NULL DEFAULT 3
    )""",
    """CREATE TABLE inventory (
        inventory_id INTEGER PRIMARY KEY,
        film_id      INTEGER NOT NULL REFERENCES film(film_id)
    )""",
    """CREATE TABLE rental (
        rental_id    INTEGER PRIMARY KEY,
        inventory_id INTEGER NOT NULL REFERENCES inventory(inventory_id),
        customer_id  INTEGER NOT NULL,
        rental_date  TEXT    NOT NULL
    )""",
    """CREATE TABLE customer (
        customer_id INTEGER PRIMARY KEY,
        first_name  TEXT NOT NULL,
        last_name   TEXT NOT NULL,
        email       TEXT
    )""",
    """CREATE TABLE payment (
        payment_id   INTEGER PRIMARY KEY,
        customer_id  INTEGER NOT NULL REFERENCES customer(customer_id),
        amount       REAL    NOT NULL,
        payment_date TEXT    NOT NULL
    )""",
    """CREATE TABLE actor (
        actor_id   INTEGER PRIMARY KEY,
        first_name TEXT NOT NULL,
        last_name  TEXT NOT NULL
    )""",
    """CREATE TABLE film_actor (
        actor_id INTEGER NOT NULL REFERENCES actor(actor_id),
        film_id  INTEGER NOT NULL REFERENCES film(film_id),
        PRIMARY KEY (actor_id, film_id)
    )""",
    """CREATE TABLE category (
        category_id INTEGER PRIMARY KEY,
        name        TEXT NOT NULL
    )""",
    """CREATE TABLE film_category (
        film_id     INTEGER NOT NULL REFERENCES film(film_id),
        category_id INTEGER NOT NULL REFERENCES category(category_id),
        PRIMARY KEY (film_id, category_id)
    )""",
]

# Seed data sized to satisfy all 5 query conditions.
# dvd_01 needs ≥5 films with rentals; dvd_03 needs actors with >30 film entries;
# dvd_04 needs at least one customer with no rentals.
def _seed_rows() -> list[tuple[str, list[dict[str, Any]]]]:
    films = [{"film_id": i, "title": f"Film {i}", "rental_duration": 3 + (i % 5)}
             for i in range(1, 21)]
    inventories = [{"inventory_id": i, "film_id": ((i - 1) % 20) + 1}
                   for i in range(1, 41)]
    # Customer 1 has rentals; customer 99 has none (tests dvd_04)
    customers = [
        {"customer_id": 1, "first_name": "Alice", "last_name": "Smith", "email": "a@example.com"},
        {"customer_id": 2, "first_name": "Bob",   "last_name": "Jones", "email": "b@example.com"},
        {"customer_id": 99, "first_name": "Nora",  "last_name": "Ghost", "email": "n@example.com"},
    ]
    rentals = [{"rental_id": i, "inventory_id": ((i - 1) % 40) + 1,
                "customer_id": 1, "rental_date": "2005-06-01 10:00:00"}
               for i in range(1, 61)]
    payments = [{"payment_id": i, "customer_id": 1, "amount": round(i * 0.99, 2),
                 "payment_date": "2005-06-01 10:00:00"}
                for i in range(1, 11)]
    # One actor with >30 film entries to satisfy dvd_03's HAVING clause
    actors = [{"actor_id": i, "first_name": f"Actor{i}", "last_name": "Test"}
              for i in range(1, 6)]
    # Use real unique actor-film pairs: actor 1 needs >30 films, extend to 41
    extra_films = [{"film_id": i, "title": f"Film {i}", "rental_duration": 3}
                   for i in range(21, 42)]
    all_films = films + extra_films
    actor1_film_actors = [{"actor_id": 1, "film_id": fid} for fid in range(1, 36)]  # 35 films
    other_film_actors = [{"actor_id": a, "film_id": fid}
                         for a in range(2, 6) for fid in range(1, 6)]
    all_film_actors = actor1_film_actors + other_film_actors

    categories = [{"category_id": i, "name": f"Category{i}"} for i in range(1, 4)]
    film_categories = [{"film_id": fid, "category_id": ((fid - 1) % 3) + 1}
                       for fid in range(1, 36)]

    return [
        ("film",          all_films),
        ("inventory",     inventories),
        ("customer",      customers),
        ("rental",        rentals),
        ("payment",       payments),
        ("actor",         actors),
        ("film_actor",    all_film_actors),
        ("category",      categories),
        ("film_category", film_categories),
    ]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
async def dvdrental_engine() -> AsyncGenerator[AsyncEngine, None]:
    """In-memory SQLite DB seeded with minimal DVDRental data."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        for ddl in _DDL:
            await conn.execute(text(ddl))
        for table, rows in _seed_rows():
            if rows:
                cols = ", ".join(rows[0].keys())
                placeholders = ", ".join(f":{k}" for k in rows[0])
                await conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"), rows)
    yield engine
    await engine.dispose()


@pytest.fixture()
def dvdrental_schema() -> AnnotatedSchema:
    """Minimal AnnotatedSchema for the DVDRental tables used by the 5 queries."""
    def _tbl(name: str, cols: list[tuple[str, str, bool, bool]]) -> TableSchema:
        return TableSchema(
            name=name,
            columns=[ColumnSchema(name=c, type=t, is_primary_key=pk, is_foreign_key=fk)
                     for c, t, pk, fk in cols],
        )

    return AnnotatedSchema(
        db_url_hash="dvdrental-test",
        tables=[
            _tbl("film",         [("film_id", "INTEGER", True, False),
                                   ("title", "TEXT", False, False),
                                   ("rental_duration", "INTEGER", False, False)]),
            _tbl("inventory",    [("inventory_id", "INTEGER", True, False),
                                   ("film_id", "INTEGER", False, True)]),
            _tbl("rental",       [("rental_id", "INTEGER", True, False),
                                   ("inventory_id", "INTEGER", False, True),
                                   ("customer_id", "INTEGER", False, True),
                                   ("rental_date", "TEXT", False, False)]),
            _tbl("customer",     [("customer_id", "INTEGER", True, False),
                                   ("first_name", "TEXT", False, False),
                                   ("last_name", "TEXT", False, False),
                                   ("email", "TEXT", False, False)]),
            _tbl("payment",      [("payment_id", "INTEGER", True, False),
                                   ("customer_id", "INTEGER", False, True),
                                   ("amount", "REAL", False, False),
                                   ("payment_date", "TEXT", False, False)]),
            _tbl("actor",        [("actor_id", "INTEGER", True, False),
                                   ("first_name", "TEXT", False, False),
                                   ("last_name", "TEXT", False, False)]),
            _tbl("film_actor",   [("actor_id", "INTEGER", False, True),
                                   ("film_id", "INTEGER", False, True)]),
            _tbl("category",     [("category_id", "INTEGER", True, False),
                                   ("name", "TEXT", False, False)]),
            _tbl("film_category",[("film_id", "INTEGER", False, True),
                                   ("category_id", "INTEGER", False, True)]),
        ],
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _load_yaml() -> list[dict[str, Any]]:
    yaml_path = Path(__file__).parent.parent / "data" / "test_queries" / "dvdrental_baseline.yaml"
    data: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return list(data["queries"])


def _make_pipeline(
    engine: AsyncEngine,
    schema: AnnotatedSchema,
    expected_sql: str,
    audit_path: str,
) -> MercerPipeline:
    backend = MagicMock()
    backend._model = "mock-model"
    backend.generate = AsyncMock(return_value=expected_sql)
    backend.generate_batch = AsyncMock(return_value=[expected_sql, expected_sql, expected_sql])
    pipeline = MercerPipeline(db_engine=engine, backend=backend, audit_path=audit_path, cache=_fake_cache())
    pipeline._annotated_schema = schema
    return pipeline


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDVDRentalBaseline:
    """Run all 5 baseline queries end-to-end; all must execute successfully."""

    @pytest.mark.parametrize("query_id", list(SQLITE_SQL.keys()))
    async def test_query_executes_successfully(
        self,
        dvdrental_engine: AsyncEngine,
        dvdrental_schema: AnnotatedSchema,
        tmp_path: Path,
        query_id: str,
    ) -> None:
        audit_path = str(tmp_path / f"audit_{query_id}.jsonl")
        sql = SQLITE_SQL[query_id]
        pipeline = _make_pipeline(dvdrental_engine, dvdrental_schema, sql, audit_path)

        state = await pipeline.run(f"baseline query {query_id}")

        assert state.best_candidate is not None, f"{query_id}: no candidate produced"
        result = state.best_candidate.execution_result
        assert result is not None, f"{query_id}: execution_result is None"
        assert result.success is True, (
            f"{query_id}: execution failed — {result.error_message}"
        )

    async def test_all_five_queries_succeed(
        self,
        dvdrental_engine: AsyncEngine,
        dvdrental_schema: AnnotatedSchema,
        tmp_path: Path,
    ) -> None:
        """Single test that asserts all 5 queries succeed — used as a quick smoke test."""
        queries = _load_yaml()
        assert len(queries) == 5, "Expected exactly 5 baseline queries in YAML"

        for entry in queries:
            qid: str = entry["id"]
            sql = SQLITE_SQL[qid]
            audit_path = str(tmp_path / f"audit_{qid}.jsonl")
            pipeline = _make_pipeline(dvdrental_engine, dvdrental_schema, sql, audit_path)
            state = await pipeline.run(entry["question"])

            assert state.best_candidate is not None
            result = state.best_candidate.execution_result
            assert result is not None
            assert result.success is True, (
                f"Query {qid} failed: {result.error_message}"
            )
