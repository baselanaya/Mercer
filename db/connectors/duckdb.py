"""DuckDB connector.

DuckDB has no true async SQLAlchemy driver. This connector wraps the
synchronous duckdb-engine in asyncio.to_thread so it fits the async
pipeline without blocking the event loop.

get_engine() returns a sync SQLAlchemy Engine. ReadOnlySandbox detects
this and routes execution through asyncio.to_thread automatically.
"""

import asyncio
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


class DuckDBConnector:
    """DuckDB connector using duckdb-engine (sync) wrapped in run_in_executor.

    Connection string: duckdb:///path/to/db.duckdb
    In-memory:         duckdb:///:memory:
    """

    def __init__(self, url: str, **kwargs: Any) -> None:
        self._url = url
        self._kwargs = kwargs
        self._engine: Engine | None = None

    async def connect(self) -> None:
        await asyncio.to_thread(self._create_engine)

    def _create_engine(self) -> None:
        self._engine = create_engine(self._url, **self._kwargs)

    async def test_connection(self) -> bool:
        engine = self.get_engine()
        def _test() -> bool:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        return await asyncio.to_thread(_test)

    def get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine(self._url, **self._kwargs)
        return self._engine
