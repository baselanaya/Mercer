"""SchemaIntrospector — SQLAlchemy 2.0 async schema extraction.

Uses conn.run_sync() to run synchronous inspect() calls without blocking
the event loop. Works with any SQLAlchemy async engine (PostgreSQL, SQLite,
MySQL).

``build_bm25_corpus`` is a helper that batch-tokenizes every column's text
using the GPU/CPU kernel tokenizer (kernels.schema_encode.get_tokenizer).
It is used by BM25ColumnRetriever when building the schema search index.
"""

import hashlib

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from core.models import ColumnSchema, RawSchema, TableSchema
from kernels.schema_encode import get_tokenizer

_tokenizer = get_tokenizer()


class SchemaIntrospector:
    async def introspect(self, engine: AsyncEngine) -> RawSchema:
        db_url_hash = _hash_url(engine)

        async with engine.connect() as conn:
            tables = await conn.run_sync(_extract_tables)

        return RawSchema(db_url_hash=db_url_hash, tables=tables)


# ---------------------------------------------------------------------------
# Internal helpers (sync — run inside conn.run_sync)
# ---------------------------------------------------------------------------

def _extract_tables(sync_conn) -> list[TableSchema]:  # type: ignore[no-untyped-def]
    inspector = inspect(sync_conn)
    tables: list[TableSchema] = []

    for table_name in inspector.get_table_names():
        pk_cols: set[str] = set(
            inspector.get_pk_constraint(table_name).get("constrained_columns", [])
        )
        # Build a map: constrained_col -> (referred_table, referred_col)
        fk_map: dict[str, tuple[str, str]] = {}
        for fk in inspector.get_foreign_keys(table_name):
            ref_table: str = fk.get("referred_table", "") or ""
            constrained: list[str] = fk.get("constrained_columns", [])
            referred: list[str] = fk.get("referred_columns", [])
            for src_col, tgt_col in zip(constrained, referred, strict=False):
                fk_map[src_col] = (ref_table, tgt_col)

        columns: list[ColumnSchema] = []
        for col in inspector.get_columns(table_name):
            col_name: str = col["name"]
            ref = fk_map.get(col_name)
            columns.append(
                ColumnSchema(
                    name=col_name,
                    type=str(col["type"]),
                    is_primary_key=col_name in pk_cols,
                    is_foreign_key=col_name in fk_map,
                    references_table=ref[0] if ref else None,
                    references_column=ref[1] if ref else None,
                )
            )

        tables.append(TableSchema(name=table_name, columns=columns))

    return tables


def build_bm25_corpus(
    schema: RawSchema,
) -> tuple[list[tuple[str, str]], list[list[str]]]:
    """Build a BM25-ready corpus from a schema using the kernel tokenizer.

    Returns a parallel pair of lists:
      - ``index``: (table_name, column_name) for each corpus entry
      - ``tokens``: tokenized text for each entry (col name + descriptions)

    The kernel tokenizer (``kernels.schema_encode.get_tokenizer``) is used
    for consistent tokenization with the GPU encode path.
    """
    raw_texts: list[str] = []
    index: list[tuple[str, str]] = []

    for table in schema.tables:
        for col in table.columns:
            parts = [col.name]
            if col.description:
                parts.append(col.description)
            if table.description:
                parts.append(table.description)
            raw_texts.append(" ".join(parts))
            index.append((table.name, col.name))

    token_lists = _tokenizer(raw_texts) if raw_texts else []
    return index, token_lists


def _hash_url(engine: AsyncEngine) -> str:
    """Stable cache key from connection URL (credentials masked)."""
    url_str = engine.url.render_as_string(hide_password=True)
    return hashlib.sha256(url_str.encode()).hexdigest()
