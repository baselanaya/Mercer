"""Stratified eval of Mercer against gretelai/synthetic_text_to_sql test set.

Each entry is self-contained: sql_context has CREATE TABLE + INSERT statements,
sql has gold SQL. We spin up an in-memory SQLite per question, run Mercer,
then compare results.
"""
import asyncio, json, random, time, sys, re
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import load_dataset
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text as sa_text
from core.pipeline import MercerPipeline
from schema.cache import SchemaCache

REDIS_URL = "redis://localhost:6379/0"

# Stratified sample: questions per complexity tier
SAMPLE_PER_TIER = {
    "basic SQL":          8,
    "aggregation":        8,
    "single join":        8,
    "subqueries":         7,
    "window functions":   7,
    "multiple_joins":     6,
    "set operations":     4,
    "CTEs":               2,
}
TOTAL = sum(SAMPLE_PER_TIER.values())  # 50
SEED = 42


def _sqlite_safe_context(ctx: str) -> str:
    """Strip MySQL/Postgres-isms so SQLite can execute the context."""
    ctx = re.sub(r"AUTO_INCREMENT", "", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"ENGINE\s*=\s*\w+", "", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"DEFAULT\s+CHARSET\s*=\s*\w+", "", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"\bINT\s+UNSIGNED\b", "INTEGER", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"\bTINYINT\b", "INTEGER", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"\bDATETIME\b", "TEXT", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"\bDATE\b", "TEXT", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"\bFLOAT\b", "REAL", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"\bDOUBLE\b", "REAL", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"\bDECIMAL\([^)]+\)", "REAL", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"\bVARCHAR\([^)]+\)", "TEXT", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"\bCHAR\([^)]+\)", "TEXT", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"\bBOOLEAN\b", "INTEGER", ctx, flags=re.IGNORECASE)
    ctx = re.sub(r"COMMENT\s+'[^']*'", "", ctx, flags=re.IGNORECASE)
    return ctx


async def _setup_db(sql_context: str):
    """Create in-memory SQLite and execute the context SQL."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    safe_ctx = _sqlite_safe_context(sql_context)
    # Split on ; to execute statement by statement
    stmts = [s.strip() for s in safe_ctx.split(";") if s.strip()]
    async with engine.begin() as conn:
        for stmt in stmts:
            try:
                await conn.execute(sa_text(stmt))
            except Exception:
                pass  # skip unsupported DDL fragments
    return engine


async def _run_gold(engine, gold_sql: str):
    """Execute gold SQL and return result rows."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(sa_text(gold_sql))
            return result.fetchall()
    except Exception:
        return None


def _results_match(predicted_rows, gold_rows) -> bool:
    """Order-insensitive row comparison."""
    if predicted_rows is None or gold_rows is None:
        return False
    try:
        return sorted(str(r) for r in predicted_rows) == sorted(str(r) for r in gold_rows)
    except Exception:
        return False


async def run_eval():
    random.seed(SEED)
    print("Loading gretelai/synthetic_text_to_sql test split...")
    ds = load_dataset("gretelai/synthetic_text_to_sql", split="test")

    # Group by complexity
    by_complexity = defaultdict(list)
    for e in ds:
        by_complexity[e["sql_complexity"]].append(e)

    # Sample
    sample = []
    for tier, n in SAMPLE_PER_TIER.items():
        pool = by_complexity.get(tier, [])
        chosen = random.sample(pool, min(n, len(pool)))
        for e in chosen:
            e["_tier"] = tier
        sample.extend(chosen)
    random.shuffle(sample)

    print(f"Running {len(sample)} questions across {len(SAMPLE_PER_TIER)} complexity tiers...\n")

    results = []
    for i, entry in enumerate(sample, 1):
        tier = entry["_tier"]
        question = entry["sql_prompt"]
        gold_sql = entry["sql"]
        sql_context = entry["sql_context"]

        t0 = time.monotonic()
        engine = await _setup_db(sql_context)

        try:
            # Flush schema cache so each question gets a fresh introspection
            cache = SchemaCache(REDIS_URL, ttl_seconds=60)
            await cache.invalidate_all()
            await cache.close()

            pipeline = MercerPipeline(db_engine=engine, redis_url=REDIS_URL)
            state = await pipeline.run(question)
            latency_ms = round((time.monotonic() - t0) * 1000, 2)

            predicted_sql = state.final_sql or ""
            exec_success = bool(predicted_sql)
            correction_steps = len(state.correction_log)

            # Compare result sets
            result_match = False
            if exec_success:
                try:
                    async with engine.connect() as conn:
                        pred_result = await conn.execute(sa_text(predicted_sql))
                        predicted_rows = pred_result.fetchall()
                    gold_rows = await _run_gold(engine, gold_sql)
                    result_match = _results_match(predicted_rows, gold_rows)
                except Exception:
                    result_match = False

        except Exception as exc:
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            exec_success = False
            result_match = False
            correction_steps = 0
            predicted_sql = ""

        finally:
            await engine.dispose()

        status = "MATCH" if result_match else ("EXEC" if exec_success else "FAIL")
        print(f"[{i:2}/{len(sample)}] {status:<5} {tier:<22} {latency_ms:>7.0f}ms  {question[:55]}")

        results.append({
            "tier": tier,
            "question": question,
            "predicted_sql": predicted_sql,
            "gold_sql": gold_sql,
            "exec_success": exec_success,
            "result_match": result_match,
            "correction_steps": correction_steps,
            "latency_ms": latency_ms,
        })

    # Summary
    total = len(results)
    exec_ok = sum(1 for r in results if r["exec_success"])
    match_ok = sum(1 for r in results if r["result_match"])
    corrections = sum(r["correction_steps"] for r in results)
    avg_lat = sum(r["latency_ms"] for r in results) / total

    print(f"\n{'='*65}")
    print(f"gretelai/synthetic_text_to_sql — Stratified Eval ({total} questions)")
    print(f"{'='*65}")
    print(f"  Execution accuracy  : {exec_ok}/{total} = {exec_ok/total:.1%}")
    print(f"  Result match (exact): {match_ok}/{total} = {match_ok/total:.1%}")
    print(f"  Total corrections   : {corrections}")
    print(f"  Avg latency         : {avg_lat:.0f} ms")

    print(f"\n{'Tier':<22} {'Exec':<6} {'Match':<6} {'N'}")
    print("-" * 45)
    by_tier = defaultdict(lambda: {"exec": 0, "match": 0, "n": 0})
    for r in results:
        t = r["tier"]
        by_tier[t]["n"] += 1
        by_tier[t]["exec"] += int(r["exec_success"])
        by_tier[t]["match"] += int(r["result_match"])

    tier_order = list(SAMPLE_PER_TIER.keys())
    for tier in tier_order:
        s = by_tier[tier]
        if s["n"] == 0:
            continue
        ep = f"{s['exec']}/{s['n']}"
        mp = f"{s['match']}/{s['n']}"
        print(f"  {tier:<20} {ep:<6} {mp:<6}")


asyncio.run(run_eval())
