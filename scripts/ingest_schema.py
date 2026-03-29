"""ingest_schema.py — CLI for schema introspection and annotation.

Usage:
    python scripts/ingest_schema.py --db-url postgresql+asyncpg://... [options]

Options:
    --db-url      SQLAlchemy async DB URL (required)
    --redis-url   Redis URL for schema cache (default: redis://localhost:6379)
    --mappings    Path to mappings.yaml (default: config/mappings.yaml)
    --output      Destination: 'print' or a file path to write JSON (default: print)
    --invalidate  Invalidate all cached schemas then exit (does not introspect)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging import get_logger
from schema.cache import SchemaCache
from schema.introspector import SchemaIntrospector
from schema.semantic_mapper import SemanticMapper

logger = get_logger(__name__)


def _format_schema_text(annotated_schema) -> str:  # type: ignore[no-untyped-def]
    """Return a human-readable summary of the annotated schema."""
    lines: list[str] = []

    lines.append(f"Database schema — {len(annotated_schema.tables)} table(s)")
    lines.append("=" * 60)

    for table in annotated_schema.tables:
        lines.append(f"\nTABLE: {table.name}")
        if table.description:
            lines.append(f"  Description: {table.description}")
        lines.append("  Columns:")
        for col in table.columns:
            flags: list[str] = []
            if col.is_primary_key:
                flags.append("PK")
            if col.is_foreign_key:
                flags.append("FK")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            desc_str = f" — {col.description}" if col.description else ""
            lines.append(f"    {col.name} ({col.type}){flag_str}{desc_str}")

    if annotated_schema.glossary:
        lines.append("\n" + "=" * 60)
        lines.append("Glossary:")
        for term, definition in annotated_schema.glossary.items():
            lines.append(f"  {term} = {definition}")

    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> None:
    cache = SchemaCache(redis_url=args.redis_url)

    try:
        if args.invalidate:
            count = await cache.invalidate_all()
            print(f"Invalidated {count} cached schema(s).")
            return

        engine = create_async_engine(args.db_url, echo=False)

        try:
            introspector = SchemaIntrospector()
            mapper = SemanticMapper(mappings_path=args.mappings)

            logger.info("introspecting_schema", db_url=args.db_url)
            raw_schema = await introspector.introspect(engine)
            annotated = mapper.annotate(raw_schema)
            logger.info("schema_ready", tables=len(annotated.tables))

            await cache.set(annotated.db_url_hash, annotated)
            logger.info("schema_cached", db_url_hash=annotated.db_url_hash)

            if args.output == "print":
                print(_format_schema_text(annotated))
            else:
                out_path = Path(args.output)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                schema_dict = annotated.model_dump()
                out_path.write_text(json.dumps(schema_dict, indent=2), encoding="utf-8")
                print(f"Schema written to {out_path}")
        finally:
            await engine.dispose()
    finally:
        await cache.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Introspect a database schema and store it in the Redis cache.",
    )
    parser.add_argument(
        "--db-url",
        required=False,
        help="SQLAlchemy async DB URL (e.g. postgresql+asyncpg://user:pass@host/db)",
    )
    parser.add_argument(
        "--redis-url",
        default="redis://localhost:6379",
        help="Redis URL (default: redis://localhost:6379)",
    )
    parser.add_argument(
        "--mappings",
        default="config/mappings.yaml",
        help="Path to mappings.yaml (default: config/mappings.yaml)",
    )
    parser.add_argument(
        "--output",
        default="print",
        help="'print' to stdout or a file path for JSON output (default: print)",
    )
    parser.add_argument(
        "--invalidate",
        action="store_true",
        help="Invalidate all cached schemas and exit (no introspection performed)",
    )
    args = parser.parse_args()

    if not args.invalidate and not args.db_url:
        parser.error("--db-url is required unless --invalidate is specified")

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
