from typing import Protocol

from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine


class DBConnector(Protocol):
    async def connect(self) -> None: ...
    async def test_connection(self) -> bool: ...
    def get_engine(self) -> AsyncEngine | Engine: ...
