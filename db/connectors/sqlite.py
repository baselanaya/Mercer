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
        self._engine = create_async_engine(self._url, echo=False)

    async def test_connection(self) -> bool:
        engine = self.get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    def get_engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = create_async_engine(self._url, echo=False)
        return self._engine
