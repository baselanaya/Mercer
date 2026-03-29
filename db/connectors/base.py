from typing import Protocol

from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine


class DBConnector(Protocol):
    """Protocol satisfied by all database connector implementations."""

    async def connect(self) -> None:
        """Initialise the connection pool / engine."""
        ...

    async def test_connection(self) -> bool:
        """Return True if the database is reachable, False otherwise."""
        ...

    def get_engine(self) -> AsyncEngine | Engine:
        """Return the underlying SQLAlchemy engine (async or sync)."""
        ...
