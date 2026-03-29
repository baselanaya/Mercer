from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class PostgresConnector:
    """Async PostgreSQL connector via asyncpg.

    Connection string: postgresql+asyncpg://user:password@host:port/dbname
    """

    def __init__(self, url: str, pool_size: int = 5, max_overflow: int = 10) -> None:
        self._url = url
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._engine: AsyncEngine | None = None

    async def connect(self) -> None:
        self._engine = create_async_engine(
            self._url,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            pool_pre_ping=True,
        )

    async def test_connection(self) -> bool:
        engine = self.get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    def get_engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = create_async_engine(
                self._url,
                pool_size=self._pool_size,
                max_overflow=self._max_overflow,
                pool_pre_ping=True,
            )
        return self._engine
