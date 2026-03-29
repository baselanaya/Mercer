"""Messy-schema evaluator — runs 10 hand-written queries against
data/messy_variants/dvdrental_messy.sql (or an in-memory SQLite clone).

The 10 questions and expected SQL live in
data/test_queries/dvdrental_messy.yaml.

Usage via benchmark.py:
    python scripts/benchmark.py --suite mercer_messy
    python scripts/benchmark.py --suite mercer_messy --db-url postgresql+asyncpg://...
"""

from __future__ import annotations

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

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import AnnotatedSchema, ColumnSchema, TableSchema
from core.pipeline import MercerPipeline
from schema.cache import SchemaCache

# ---------------------------------------------------------------------------
# YAML path
# ---------------------------------------------------------------------------

_YAML_PATH = Path(__file__).parent.parent / "data" / "test_queries" / "dvdrental_messy.yaml"

# ---------------------------------------------------------------------------
# SQLite-compatible DDL for the messy schema
# (avoids TEXT[], GENERATED columns, and Postgres-only syntax)
# ---------------------------------------------------------------------------

_DDL: list[str] = [
    """CREATE TABLE cust_mstr (
        cust_id  INTEGER PRIMARY KEY,
        st_id    INTEGER,
        f_nm     TEXT NOT NULL,
        l_nm     TEXT NOT NULL,
        e_addr   TEXT,
        addr_id  INTEGER,
        act_bool INTEGER NOT NULL DEFAULT 1,
        act      INTEGER DEFAULT 1
    )""",
    """CREATE TABLE f_catalog (
        f_id     INTEGER PRIMARY KEY,
        ttl      TEXT NOT NULL,
        descr    TEXT,
        rel_yr   INTEGER,
        lang_id  INTEGER,
        rnt_dur  INTEGER NOT NULL DEFAULT 3,
        rnt_rt   REAL    NOT NULL DEFAULT 4.99,
        lng      INTEGER,
        repl_cst REAL    NOT NULL DEFAULT 19.99,
        rtg      TEXT
    )""",
    # Quoted camelCase table — SQLite supports this
    """CREATE TABLE "RentalTxn" (
        rentalId INTEGER PRIMARY KEY,
        rnt_dt   TEXT NOT NULL,
        invId    INTEGER,
        custId   INTEGER,
        retDt    TEXT,
        staffId  INTEGER
    )""",
    # ALL_CAPS quoted table from finance system
    """CREATE TABLE "PAYMENT_LEDGER" (
        PMT_ID  INTEGER PRIMARY KEY,
        CUST_ID INTEGER,
        STAFF_ID INTEGER,
        RNT_ID  INTEGER,
        AMT     REAL    NOT NULL,
        PMT_DT  TEXT    NOT NULL
    )""",
    """CREATE TABLE inv (
        inv_id  INTEGER PRIMARY KEY,
        f_id    INTEGER,
        st_id   INTEGER
    )""",
    """CREATE TABLE actor (
        actor_id   INTEGER PRIMARY KEY,
        first_name TEXT NOT NULL,
        last_name  TEXT NOT NULL
    )""",
    """CREATE TABLE film_actor (
        actor_id INTEGER NOT NULL,
        f_id     INTEGER NOT NULL,
        PRIMARY KEY (actor_id, f_id)
    )""",
    """CREATE TABLE cat (
        cat_id  INTEGER PRIMARY KEY,
        cat_nm  TEXT NOT NULL
    )""",
    """CREATE TABLE film_cat (
        f_id    INTEGER NOT NULL,
        cat_id  INTEGER NOT NULL,
        PRIMARY KEY (f_id, cat_id)
    )""",
]

# ---------------------------------------------------------------------------
# Seed data — sized to satisfy all 10 queries
# ---------------------------------------------------------------------------

def _seed_rows() -> list[tuple[str, list[dict[str, Any]]]]:
    customers = [
        {"cust_id": 1, "f_nm": "Alice",  "l_nm": "Smith", "e_addr": "alice@example.com"},
        {"cust_id": 2, "f_nm": "Bob",    "l_nm": "Jones", "e_addr": "bob@example.com"},
        # Customer 3 has no payments (tests messy_08)
        {"cust_id": 3, "f_nm": "Nora",   "l_nm": "Ghost", "e_addr": "nora@example.com"},
    ]
    # 5 films, rates both above and below 3.00 (tests messy_05)
    films = [
        {"f_id": 1, "ttl": "Alpha",   "rnt_dur": 3, "rnt_rt": 2.99},
        {"f_id": 2, "ttl": "Beta",    "rnt_dur": 5, "rnt_rt": 4.99},
        {"f_id": 3, "ttl": "Gamma",   "rnt_dur": 7, "rnt_rt": 3.99},
        {"f_id": 4, "ttl": "Delta",   "rnt_dur": 4, "rnt_rt": 1.99},
        {"f_id": 5, "ttl": "Epsilon", "rnt_dur": 6, "rnt_rt": 5.99},
    ]
    # Inventory: films 1-3 have 2 copies each, films 4-5 have 1 (tests messy_09)
    inventories = [
        {"inv_id": 1, "f_id": 1}, {"inv_id": 2, "f_id": 1},
        {"inv_id": 3, "f_id": 2}, {"inv_id": 4, "f_id": 2},
        {"inv_id": 5, "f_id": 3}, {"inv_id": 6, "f_id": 3},
        {"inv_id": 7, "f_id": 4},
        {"inv_id": 8, "f_id": 5},
    ]
    # Rentals in 2005 and 2006 (tests messy_04)
    rentals = [
        {"rentalId": 1, "rnt_dt": "2005-06-01 10:00:00", "invId": 1, "custId": 1, "retDt": "2005-06-04 10:00:00", "staffId": 1},
        {"rentalId": 2, "rnt_dt": "2005-07-15 12:00:00", "invId": 3, "custId": 2, "retDt": "2005-07-20 12:00:00", "staffId": 1},
        {"rentalId": 3, "rnt_dt": "2006-01-10 09:00:00", "invId": 5, "custId": 1, "retDt": "2006-01-13 09:00:00", "staffId": 1},
    ]
    # Payments: only customers 1 and 2 have payments (customer 3 has none)
    payments = [
        {"PMT_ID": 1, "CUST_ID": 1, "AMT": 4.99, "PMT_DT": "2005-06-01 10:00:00", "STAFF_ID": 1, "RNT_ID": 1},
        {"PMT_ID": 2, "CUST_ID": 2, "AMT": 2.99, "PMT_DT": "2005-07-15 12:00:00", "STAFF_ID": 1, "RNT_ID": 2},
        {"PMT_ID": 3, "CUST_ID": 1, "AMT": 3.99, "PMT_DT": "2005-08-01 10:00:00", "STAFF_ID": 1, "RNT_ID": None},
    ]
    # Actors: actor 1 has 3 films (passes HAVING > 2), others have 1 each
    actors = [
        {"actor_id": 1, "first_name": "Jane", "last_name": "Doe"},
        {"actor_id": 2, "first_name": "John", "last_name": "Smith"},
        {"actor_id": 3, "first_name": "Mary", "last_name": "Brown"},
    ]
    film_actors = [
        {"actor_id": 1, "f_id": 1},
        {"actor_id": 1, "f_id": 2},
        {"actor_id": 1, "f_id": 3},  # actor 1: 3 films
        {"actor_id": 2, "f_id": 1},  # actor 2: 1 film
        {"actor_id": 3, "f_id": 2},  # actor 3: 1 film
    ]
    # Categories
    categories = [
        {"cat_id": 1, "cat_nm": "Action"},
        {"cat_id": 2, "cat_nm": "Comedy"},
        {"cat_id": 3, "cat_nm": "Drama"},
    ]
    film_cats = [
        {"f_id": 1, "cat_id": 1},
        {"f_id": 2, "cat_id": 1},
        {"f_id": 3, "cat_id": 2},
        {"f_id": 4, "cat_id": 3},
        {"f_id": 5, "cat_id": 3},
    ]

    return [
        ("cust_mstr",        customers),
        ("f_catalog",        films),
        ('"RentalTxn"',      rentals),
        ('"PAYMENT_LEDGER"', payments),
        ("inv",              inventories),
        ("actor",            actors),
        ("film_actor",       film_actors),
        ("cat",              categories),
        ("film_cat",         film_cats),
    ]


# ---------------------------------------------------------------------------
# SQLite-compatible SQL for each of the 10 messy queries
# ---------------------------------------------------------------------------

# These mirror the expected_sql in the YAML but are pre-verified to work on
# the seed DB above.  They are injected into the mock LLM backend so the
# pipeline always "generates" the correct SQL.

SQLITE_SQL: dict[str, str] = {
    "messy_01": "SELECT COUNT(*) AS customer_count FROM cust_mstr;",
    "messy_02": (
        "SELECT f_nm, l_nm, e_addr FROM cust_mstr ORDER BY l_nm, f_nm;"
    ),
    "messy_03": 'SELECT SUM(AMT) AS total_revenue FROM "PAYMENT_LEDGER";',
    "messy_04": (
        'SELECT rentalId, rnt_dt, invId, custId FROM "RentalTxn"'
        " WHERE STRFTIME('%Y', rnt_dt) = '2005' ORDER BY rnt_dt;"
    ),
    "messy_05": (
        "SELECT ttl AS title, rnt_rt AS rental_rate FROM f_catalog"
        " WHERE rnt_rt > 3.00 ORDER BY rnt_rt DESC;"
    ),
    "messy_06": (
        "SELECT a.actor_id, a.first_name, a.last_name, COUNT(fa.f_id) AS film_count"
        " FROM actor a JOIN film_actor fa ON a.actor_id = fa.actor_id"
        " GROUP BY a.actor_id, a.first_name, a.last_name"
        " HAVING COUNT(fa.f_id) > 2 ORDER BY film_count DESC;"
    ),
    "messy_07": (
        "SELECT c.cat_nm AS category, ROUND(AVG(f.rnt_dur), 2) AS avg_rental_duration"
        " FROM cat c JOIN film_cat fc ON c.cat_id = fc.cat_id"
        " JOIN f_catalog f ON fc.f_id = f.f_id"
        " GROUP BY c.cat_id, c.cat_nm ORDER BY avg_rental_duration DESC;"
    ),
    "messy_08": (
        'SELECT cm.cust_id, cm.f_nm, cm.l_nm, cm.e_addr FROM cust_mstr cm'
        ' LEFT JOIN "PAYMENT_LEDGER" pl ON cm.cust_id = pl.CUST_ID'
        ' WHERE pl.PMT_ID IS NULL ORDER BY cm.cust_id;'
    ),
    "messy_09": (
        "SELECT f.ttl AS title, COUNT(i.inv_id) AS copy_count"
        " FROM f_catalog f JOIN inv i ON f.f_id = i.f_id"
        " GROUP BY f.f_id, f.ttl ORDER BY copy_count DESC LIMIT 3;"
    ),
    "messy_10": (
        'SELECT cm.cust_id, cm.f_nm, cm.l_nm, SUM(pl.AMT) AS total_paid'
        ' FROM cust_mstr cm'
        ' JOIN "PAYMENT_LEDGER" pl ON cm.cust_id = pl.CUST_ID'
        " WHERE STRFTIME('%Y', pl.PMT_DT) = '2005'"
        ' GROUP BY cm.cust_id, cm.f_nm, cm.l_nm ORDER BY total_paid DESC;'
    ),
}

# ---------------------------------------------------------------------------
# Minimal AnnotatedSchema for the messy tables
# ---------------------------------------------------------------------------

def _messy_schema() -> AnnotatedSchema:
    def _col(name: str, typ: str, pk: bool = False, fk: bool = False) -> ColumnSchema:
        return ColumnSchema(name=name, type=typ, is_primary_key=pk, is_foreign_key=fk)

    def _tbl(name: str, cols: list[ColumnSchema]) -> TableSchema:
        return TableSchema(name=name, columns=cols)

    return AnnotatedSchema(
        db_url_hash="dvdrental-messy-test",
        tables=[
            _tbl("cust_mstr", [
                _col("cust_id", "INTEGER", pk=True), _col("f_nm", "TEXT"),
                _col("l_nm", "TEXT"), _col("e_addr", "TEXT"),
            ]),
            _tbl("f_catalog", [
                _col("f_id", "INTEGER", pk=True), _col("ttl", "TEXT"),
                _col("rnt_dur", "INTEGER"), _col("rnt_rt", "REAL"),
            ]),
            _tbl("RentalTxn", [
                _col("rentalId", "INTEGER", pk=True), _col("rnt_dt", "TEXT"),
                _col("invId", "INTEGER", fk=True), _col("custId", "INTEGER", fk=True),
                _col("retDt", "TEXT"),
            ]),
            _tbl("PAYMENT_LEDGER", [
                _col("PMT_ID", "INTEGER", pk=True), _col("CUST_ID", "INTEGER", fk=True),
                _col("AMT", "REAL"), _col("PMT_DT", "TEXT"),
            ]),
            _tbl("inv", [
                _col("inv_id", "INTEGER", pk=True), _col("f_id", "INTEGER", fk=True),
            ]),
            _tbl("actor", [
                _col("actor_id", "INTEGER", pk=True), _col("first_name", "TEXT"),
                _col("last_name", "TEXT"),
            ]),
            _tbl("film_actor", [
                _col("actor_id", "INTEGER", fk=True), _col("f_id", "INTEGER", fk=True),
            ]),
            _tbl("cat", [
                _col("cat_id", "INTEGER", pk=True), _col("cat_nm", "TEXT"),
            ]),
            _tbl("film_cat", [
                _col("f_id", "INTEGER", fk=True), _col("cat_id", "INTEGER", fk=True),
            ]),
        ],
    )


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class MessySchemaEvaluator:
    """Evaluate Mercer against the DVDRental messy schema.

    Loads 10 hand-written questions from dvdrental_messy.yaml and runs each
    through a MercerPipeline backed by either a real database or an in-memory
    SQLite seed database with a mock LLM.
    """

    def load_dataset(self, path: str | None = None) -> list[dict[str, Any]]:
        """Load the messy-schema question list from YAML.

        Args:
            path: Override the default YAML path (optional).
        """
        yaml_path = Path(path) if path else _YAML_PATH
        data: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        return list(data["queries"])

    async def run(
        self,
        pipeline: MercerPipeline,
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run every question through the pipeline and compute accuracy.

        Args:
            pipeline:  Configured MercerPipeline (real DB + real LLM).
            questions: Question dicts loaded from the YAML.

        Returns:
            Summary dict with keys:
              execution_accuracy  — fraction of queries that produced valid SQL.
              total               — number of questions.
              passed              — number that succeeded.
              per_question        — list of per-question result dicts.
        """
        per_question: list[dict[str, Any]] = []

        for entry in questions:
            qid: str = entry["id"]
            question: str = entry["question"]
            t0 = time.monotonic()
            try:
                state = await pipeline.run(question)
                latency_ms = round((time.monotonic() - t0) * 1000, 2)
                success = bool(state.final_sql)
                per_question.append({
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
                per_question.append({
                    "id": qid,
                    "question": question,
                    "success": False,
                    "predicted_sql": None,
                    "error": str(exc),
                    "latency_ms": latency_ms,
                })

        total = len(per_question)
        passed = sum(1 for r in per_question if r["success"])
        return {
            "execution_accuracy": passed / total if total else 0.0,
            "total": total,
            "passed": passed,
            "per_question": per_question,
        }

    async def run_mock(self) -> list[dict[str, Any]]:
        """Run all 10 queries using an in-memory SQLite DB + mock LLM.

        The mock LLM returns the pre-verified SQLite SQL for each query so
        every query should succeed.  Used by the benchmark runner when no
        ``--db-url`` is provided.

        Returns:
            List of per-question result dicts (same format as ``run()``).
        """
        questions = self.load_dataset()
        engine = await self._make_engine()

        per_question: list[dict[str, Any]] = []
        for entry in questions:
            qid: str = entry["id"]
            question: str = entry["question"]
            sql = SQLITE_SQL[qid]
            pipeline = self._make_pipeline(engine, sql)

            t0 = time.monotonic()
            try:
                state = await pipeline.run(question)
                latency_ms = round((time.monotonic() - t0) * 1000, 2)
                success = bool(state.final_sql)
                per_question.append({
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
                per_question.append({
                    "id": qid,
                    "question": question,
                    "success": False,
                    "predicted_sql": None,
                    "error": str(exc),
                    "latency_ms": latency_ms,
                })

        await engine.dispose()
        return per_question

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _make_engine() -> AsyncEngine:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            for ddl in _DDL:
                await conn.execute(text(ddl))
            for table, rows in _seed_rows():
                if not rows:
                    continue
                cols = ", ".join(rows[0].keys())
                placeholders = ", ".join(f":{k}" for k in rows[0])
                await conn.execute(
                    text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"),
                    rows,
                )
        return engine

    @staticmethod
    def _make_pipeline(engine: AsyncEngine, sql: str) -> MercerPipeline:
        backend = MagicMock()
        backend._model = "mock-model"
        backend.generate = AsyncMock(return_value=sql)
        backend.generate_batch = AsyncMock(return_value=[sql, sql, sql])
        cache = SchemaCache._from_client(faio.FakeRedis(decode_responses=True))
        pipeline = MercerPipeline(
            db_engine=engine, backend=backend, cache=cache
        )
        pipeline._annotated_schema = _messy_schema()
        return pipeline
