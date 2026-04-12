"""Regression suite — runs dvdrental_baseline.yaml through MercerPipeline.

Usage (from repo root):
    python eval/regression_suite.py --db-url sqlite+aiosqlite:///data/dvdrental.db

The pipeline must be pre-configured with a real DB and LLM backend.  For CI /
unit-test usage see tests/test_dvdrental_baseline.py which mocks the LLM.

run_mock() provides a self-contained demo that uses an in-memory SQLite DB
and a mock LLM — no external services required.  Used by benchmark.py when
no --db-url is given.

Exit codes:
    0 — all queries at or above threshold
    1 — below threshold or execution error
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis as faio
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import AnnotatedSchema, ColumnSchema, TableSchema
from core.pipeline import MercerPipeline
from schema.cache import SchemaCache

_THRESHOLD = 0.8
_YAML_PATH = Path(__file__).parent.parent / "data" / "test_queries" / "dvdrental_baseline.yaml"

# ---------------------------------------------------------------------------
# In-memory SQLite mock runner (no external DB or Redis required)
# ---------------------------------------------------------------------------

_DDL: list[str] = [
    "CREATE TABLE film (film_id INTEGER PRIMARY KEY, title TEXT NOT NULL, rental_duration INTEGER NOT NULL DEFAULT 3)",
    "CREATE TABLE inventory (inventory_id INTEGER PRIMARY KEY, film_id INTEGER NOT NULL)",
    "CREATE TABLE rental (rental_id INTEGER PRIMARY KEY, inventory_id INTEGER NOT NULL, customer_id INTEGER NOT NULL, rental_date TEXT NOT NULL)",
    "CREATE TABLE customer (customer_id INTEGER PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL, email TEXT)",
    "CREATE TABLE payment (payment_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, amount REAL NOT NULL, payment_date TEXT NOT NULL)",
    "CREATE TABLE actor (actor_id INTEGER PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL)",
    "CREATE TABLE film_actor (actor_id INTEGER NOT NULL, film_id INTEGER NOT NULL, PRIMARY KEY (actor_id, film_id))",
    "CREATE TABLE category (category_id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE film_category (film_id INTEGER NOT NULL, category_id INTEGER NOT NULL, PRIMARY KEY (film_id, category_id))",
]

# SQLite-adapted SQL for each of the 5 baseline queries
_SQLITE_SQL: dict[str, str] = {
    "dvd_01": (
        "SELECT f.title, COUNT(r.rental_id) AS rental_count"
        " FROM film f"
        " JOIN inventory i ON f.film_id = i.film_id"
        " JOIN rental r ON i.inventory_id = r.inventory_id"
        " GROUP BY f.film_id, f.title"
        " ORDER BY rental_count DESC LIMIT 5;"
    ),
    "dvd_02": (
        "SELECT c.customer_id, c.first_name, c.last_name, SUM(p.amount) AS total_amount"
        " FROM customer c JOIN payment p ON c.customer_id = p.customer_id"
        " WHERE STRFTIME('%Y', p.payment_date) = '2005'"
        " GROUP BY c.customer_id, c.first_name, c.last_name"
        " ORDER BY total_amount DESC;"
    ),
    "dvd_03": (
        "SELECT a.actor_id, a.first_name, a.last_name, COUNT(fa.film_id) AS film_count"
        " FROM actor a JOIN film_actor fa ON a.actor_id = fa.actor_id"
        " GROUP BY a.actor_id, a.first_name, a.last_name"
        " HAVING COUNT(fa.film_id) > 30 ORDER BY film_count DESC;"
    ),
    "dvd_04": (
        "SELECT c.customer_id, c.first_name, c.last_name, c.email"
        " FROM customer c LEFT JOIN rental r ON c.customer_id = r.customer_id"
        " WHERE r.rental_id IS NULL ORDER BY c.customer_id;"
    ),
    "dvd_05": (
        "SELECT cat.name AS category, ROUND(AVG(f.rental_duration), 2) AS avg_rental_duration_days"
        " FROM category cat"
        " JOIN film_category fc ON cat.category_id = fc.category_id"
        " JOIN film f ON fc.film_id = f.film_id"
        " GROUP BY cat.category_id, cat.name ORDER BY avg_rental_duration_days DESC;"
    ),
}


def _seed_rows() -> list[tuple[str, list[dict[str, Any]]]]:
    films = [{"film_id": i, "title": f"Film {i}", "rental_duration": 3 + (i % 5)}
             for i in range(1, 21)]
    extra_films = [{"film_id": i, "title": f"Film {i}", "rental_duration": 3}
                   for i in range(21, 42)]
    all_films = films + extra_films

    inventories = [{"inventory_id": i, "film_id": ((i - 1) % 20) + 1}
                   for i in range(1, 41)]
    customers = [
        {"customer_id": 1, "first_name": "Alice", "last_name": "Smith", "email": "a@x.com"},
        {"customer_id": 2, "first_name": "Bob",   "last_name": "Jones", "email": "b@x.com"},
        {"customer_id": 99, "first_name": "Nora", "last_name": "Ghost", "email": "n@x.com"},
    ]
    rentals = [{"rental_id": i, "inventory_id": ((i - 1) % 40) + 1,
                "customer_id": 1, "rental_date": "2005-06-01 10:00:00"}
               for i in range(1, 61)]
    payments = [{"payment_id": i, "customer_id": 1, "amount": round(i * 0.99, 2),
                 "payment_date": "2005-06-01 10:00:00"}
                for i in range(1, 11)]
    actors = [{"actor_id": i, "first_name": f"Actor{i}", "last_name": "Test"}
              for i in range(1, 6)]
    actor1_film_actors = [{"actor_id": 1, "film_id": fid} for fid in range(1, 36)]
    other_film_actors  = [{"actor_id": a, "film_id": fid}
                          for a in range(2, 6) for fid in range(1, 6)]
    all_film_actors = actor1_film_actors + other_film_actors

    categories    = [{"category_id": i, "name": f"Category{i}"} for i in range(1, 4)]
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


def _minimal_schema() -> AnnotatedSchema:
    def _col(name: str, typ: str, pk: bool = False, fk: bool = False) -> ColumnSchema:
        return ColumnSchema(name=name, type=typ, is_primary_key=pk, is_foreign_key=fk)

    def _tbl(name: str, cols: list[ColumnSchema]) -> TableSchema:
        return TableSchema(name=name, columns=cols)

    return AnnotatedSchema(
        db_url_hash="dvdrental-regression-mock",
        tables=[
            _tbl("film",          [_col("film_id", "INTEGER", pk=True), _col("title", "TEXT"), _col("rental_duration", "INTEGER")]),
            _tbl("inventory",     [_col("inventory_id", "INTEGER", pk=True), _col("film_id", "INTEGER", fk=True)]),
            _tbl("rental",        [_col("rental_id", "INTEGER", pk=True), _col("inventory_id", "INTEGER", fk=True), _col("customer_id", "INTEGER", fk=True), _col("rental_date", "TEXT")]),
            _tbl("customer",      [_col("customer_id", "INTEGER", pk=True), _col("first_name", "TEXT"), _col("last_name", "TEXT"), _col("email", "TEXT")]),
            _tbl("payment",       [_col("payment_id", "INTEGER", pk=True), _col("customer_id", "INTEGER", fk=True), _col("amount", "REAL"), _col("payment_date", "TEXT")]),
            _tbl("actor",         [_col("actor_id", "INTEGER", pk=True), _col("first_name", "TEXT"), _col("last_name", "TEXT")]),
            _tbl("film_actor",    [_col("actor_id", "INTEGER", fk=True), _col("film_id", "INTEGER", fk=True)]),
            _tbl("category",      [_col("category_id", "INTEGER", pk=True), _col("name", "TEXT")]),
            _tbl("film_category", [_col("film_id", "INTEGER", fk=True), _col("category_id", "INTEGER", fk=True)]),
        ],
    )


async def _make_mock_engine() -> AsyncEngine:
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
                await conn.execute(
                    text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"),
                    rows,
                )
    return engine


def _make_mock_pipeline(engine: AsyncEngine, sql: str) -> MercerPipeline:
    backend = MagicMock()
    backend._model = "mock-model"
    backend.generate = AsyncMock(return_value=sql)
    backend.generate_batch = AsyncMock(return_value=[sql, sql, sql])
    cache = SchemaCache._from_client(faio.FakeRedis(decode_responses=True))
    pipeline = MercerPipeline(db_engine=engine, backend=backend, cache=cache)
    pipeline._annotated_schema = _minimal_schema()
    return pipeline


async def run_mock() -> list[dict[str, Any]]:
    """Run all 5 baseline queries with an in-memory SQLite DB + mock LLM.

    Returns a list of per-query result dicts:
      {"id", "question", "success", "predicted_sql", "latency_ms"}
    """
    queries = _load_queries()
    engine = await _make_mock_engine()
    results: list[dict[str, Any]] = []

    for entry in queries:
        qid: str  = entry["id"]
        question: str = entry["question"]
        sql = _SQLITE_SQL[qid]
        pipeline = _make_mock_pipeline(engine, sql)

        t0 = time.monotonic()
        try:
            state = await pipeline.run(question)
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            success = bool(state.final_sql)
            results.append({
                "id": qid,
                "question": question,
                "success": success,
                "predicted_sql": state.final_sql or (
                    state.best_candidate.sql if state.best_candidate else None
                ),
                "latency_ms": latency_ms,
            })
        except Exception as exc:  # noqa: BLE001
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            results.append({
                "id": qid,
                "question": question,
                "success": False,
                "predicted_sql": None,
                "error": str(exc),
                "latency_ms": latency_ms,
            })

    await engine.dispose()
    return results


def _load_queries() -> list[dict[str, Any]]:
    data: dict[str, Any] = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
    return list(data["queries"])


async def _run_suite(db_url: str, redis_url: str) -> int:
    """Run every query in the YAML through the pipeline.

    Returns exit code: 0 if accuracy >= threshold, 1 otherwise.
    """
    queries = _load_queries()
    engine = create_async_engine(db_url, echo=False)
    pipeline = MercerPipeline(db_engine=engine, redis_url=redis_url)

    passed = 0
    failed = 0

    print(f"Running {len(queries)} regression queries (threshold={_THRESHOLD:.0%})")
    print("-" * 60)

    for entry in queries:
        qid: str = entry["id"]
        question: str = entry["question"]

        try:
            state = await pipeline.run(question)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL [{qid}]  ERROR: {exc}")
            failed += 1
            continue

        success = bool(state.final_sql)
        predicted_sql = state.final_sql or (
            state.best_candidate.sql if state.best_candidate else "<no SQL>"
        )
        status = "PASS" if success else "FAIL"

        print(f"  {status} [{qid}]  {question}")
        if not success:
            print(f"         SQL: {predicted_sql[:120]}")
        failed += not success
        passed += success

    print("-" * 60)
    total = passed + failed
    accuracy = passed / total if total else 0.0
    print(f"Accuracy: {passed}/{total} = {accuracy:.1%}  (threshold={_THRESHOLD:.0%})")

    await engine.dispose()

    if accuracy < _THRESHOLD:
        print(f"REGRESSION: accuracy {accuracy:.1%} below threshold {_THRESHOLD:.0%}")
        return 1
    return 0


def main() -> None:
    """CLI entry-point: parse args and run the regression suite against a live database."""
    parser = argparse.ArgumentParser(description="Run Mercer regression suite")
    parser.add_argument("--db-url", required=True, help="SQLAlchemy async DB URL")
    parser.add_argument(
        "--redis-url",
        default="redis://localhost:6379",
        help="Redis URL for schema cache (default: redis://localhost:6379)",
    )
    args = parser.parse_args()
    exit_code = asyncio.run(_run_suite(args.db_url, args.redis_url))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
