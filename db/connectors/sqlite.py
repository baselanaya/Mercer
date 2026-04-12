from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class SQLiteConnector:
    """Async SQLite connector via aiosqlite.

    Connection string: sqlite+aiosqlite:///path/to/db.sqlite3
    In-memory:         sqlite+aiosqlite:///:memory:
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._engine: AsyncEngine | None = None

    async def connect(self) -> None:
        """Create the async SQLite engine (no pool — SQLite is single-file)."""
        self._engine = create_async_engine(self._url, echo=False)

    async def test_connection(self) -> bool:
        """Verify the SQLite file is readable with a trivial query."""
        engine = self.get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    def get_engine(self) -> AsyncEngine:
        """Return the async engine, creating it lazily if necessary."""
        if self._engine is None:
            self._engine = create_async_engine(self._url, echo=False)
        return self._engine
