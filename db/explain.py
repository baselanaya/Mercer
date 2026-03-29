"""ExplainRunner — database-specific EXPLAIN / dry-run abstraction."""


from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine


class ExplainResult(BaseModel):
    valid: bool
    plan: str
    error: str | None = None


# EXPLAIN SQL templates per dialect
_EXPLAIN_TEMPLATES: dict[str, str] = {
    "postgresql": "EXPLAIN (FORMAT JSON) {sql}",
    "sqlite":     "EXPLAIN QUERY PLAN {sql}",
    "mysql":      "EXPLAIN FORMAT=JSON {sql}",
    "duckdb":     "EXPLAIN {sql}",
}


class ExplainRunner:
    async def explain(
        self,
        sql: str,
        engine: AsyncEngine | Engine,
        dialect: str,
    ) -> ExplainResult:
        """Run EXPLAIN on *sql* using the dialect-appropriate template."""
        template = _EXPLAIN_TEMPLATES.get(dialect.lower(), "EXPLAIN {sql}")
        explain_sql = template.format(sql=sql)

        if isinstance(engine, AsyncEngine):
            return await self._explain_async(explain_sql)
        else:
            import asyncio
            return await asyncio.to_thread(self._explain_sync, explain_sql, engine)

    async def _explain_async(self, explain_sql: str) -> ExplainResult:
        # engine not stored — caller passes engine into explain()
        # this overload is reached only via explain() which has the engine
        raise NotImplementedError("Call explain() instead.")

    def _explain_sync(self, explain_sql: str, engine: Engine) -> ExplainResult:
        try:
            with engine.connect() as conn:
                result = conn.execute(text(explain_sql))
                rows = result.fetchall()
                plan = "\n".join(str(row) for row in rows)
            return ExplainResult(valid=True, plan=plan)
        except Exception as exc:
            return ExplainResult(valid=False, plan="", error=str(exc))


class _AsyncExplainRunner(ExplainRunner):
    """Internal helper that holds the engine reference for async path."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def _explain_async(self, explain_sql: str) -> ExplainResult:
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(text(explain_sql))
                rows = result.fetchall()
                plan = "\n".join(str(row) for row in rows)
            return ExplainResult(valid=True, plan=plan)
        except Exception as exc:
            return ExplainResult(valid=False, plan="", error=str(exc))


# Re-export a patched explain() that handles async engine correctly
async def explain(
    sql: str,
    engine: AsyncEngine | Engine,
    dialect: str,
) -> ExplainResult:
    """Convenience function — wraps ExplainRunner with correct async dispatch."""
    template = _EXPLAIN_TEMPLATES.get(dialect.lower(), "EXPLAIN {sql}")
    explain_sql = template.format(sql=sql)

    if isinstance(engine, AsyncEngine):
        async_runner = _AsyncExplainRunner(engine)
        return await async_runner._explain_async(explain_sql)
    else:
        import asyncio
        sync_runner = ExplainRunner()
        return await asyncio.to_thread(sync_runner._explain_sync, explain_sql, engine)
