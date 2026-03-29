# Mercer — Claude Code Project Memory

## Project

Text-to-SQL system for messy real-world schemas. Converts natural language queries to accurate SQL using a 6-stage agentic pipeline: entity retrieval → schema linking → query decomposition → multi-candidate generation → execution + selection → taxonomy-guided correction.

See `docs/architecture.md` for the full pipeline design.
See `docs/plan.md` for the phased implementation roadmap.

---

## Stack

- **Language**: Python 3.11+
- **LLM inference**: SGLang (local) or Anthropic/OpenAI API (cloud)
- **Local model**: Qwen2.5-Coder-7B-Instruct via SGLang on RTX 4070
- **DB abstraction**: SQLAlchemy 2.0 (async)
- **API backend**: FastAPI + uvicorn
- **Frontend**: React + TailwindCSS (`app/ui/`)
- **GPU kernels**: Triton (`kernels/`)
- **Caching**: Redis (schema), DuckDB (query results)
- **Schema graph**: networkx
- **Entity retrieval**: rank-bm25 + GPU LSH

---

## Project Structure

```
core/          # 6-stage pipeline (one file per stage)
kernels/       # Triton GPU kernels
inference/     # LLM backend clients + model router
schema/        # Introspector, semantic mapper, FK graph, cache
db/            # Connectors (postgres, mysql, sqlite, duckdb), sandbox, explain
app/           # FastAPI (api/) + React (ui/)
prompts/       # All LLM prompts — versioned, never inline
eval/          # Benchmark runners + metrics
config/        # mappings.yaml, inference.yaml, settings.py (Pydantic)
data/          # Test databases
docker/        # docker-compose.yml, Dockerfiles
scripts/       # CLI tools (ingest_schema.py, benchmark.py, serve.sh)
docs/          # Architecture, plan, ADRs
```

---

## Code Rules

**Async by default.** All I/O-bound operations (DB queries, LLM calls, HTTP) use `async/await`. Use `asyncio.gather()` for parallel operations (multi-candidate generation runs all 3 strategies concurrently).

**Pydantic for all data models.** No raw dicts crossing module boundaries. Define schemas in `core/models.py`.

**Prompts live in `prompts/`.** Never inline prompt strings in pipeline code. Import from the prompts module.

**One file per pipeline stage.** `core/entity_retriever.py`, `core/schema_linker.py`, etc. The orchestrator is `core/pipeline.py`. Keep stages independently testable.

**No LangChain or LlamaIndex.** Custom pipeline only. These add abstraction that makes GPU tuning and debugging impossible.

**SQLAlchemy text() for all raw SQL.** Never use f-strings to build SQL in the application layer (only the LLM generates SQL strings).

**Error taxonomy in `core/corrector.py`.** When writing the correction stage, classify errors before retrying: schema_error, join_error, filter_error, aggregation_error, syntax_error, logic_error.

---

## Security Rules (non-negotiable)

- `db/sandbox.py` is the **only** path to DB execution. Never call `db_engine.execute()` directly from pipeline code.
- LLM prompts must never include raw row data. Pass only schema metadata, column descriptions, and at most 3 sample values from `ReadOnlySandbox.execute()`.
- Blocked keywords in sandbox: `INSERT UPDATE DELETE DROP ALTER CREATE GRANT TRUNCATE`.
- Max rows returned from sandbox: 100. Max execution time: 5 seconds.

---

## Environment Variables

```
DATABASE_URL          # Target database connection string
REDIS_URL             # Redis for schema cache
SGLANG_URL            # SGLang server (default: http://localhost:30000)
ANTHROPIC_API_KEY     # For API fallback
OPENAI_API_KEY        # For API fallback
INFERENCE_BACKEND     # "sglang" | "anthropic" | "openai"
LOG_LEVEL             # "DEBUG" | "INFO" | "WARNING"
```

Settings are loaded via Pydantic `config/settings.py`. Never hardcode keys.

---

## Dev Commands

```bash
# Start SGLang local server (RTX 4070, FP8)
bash scripts/serve.sh

# Run the app
uvicorn app.api.main:app --reload --port 8000

# Run tests
pytest tests/ -v

# Run benchmark
python scripts/benchmark.py --suite bird --split mini_dev
python scripts/benchmark.py --suite mercer_messy

# Ingest schema for a database
python scripts/ingest_schema.py --db-url $DATABASE_URL

# Full Docker stack (DB + Redis + SGLang + app)
docker compose -f docker/docker-compose.yml up
```

---

## Testing

- Unit tests: one test file per module in `tests/`
- Benchmark eval: `eval/` — BIRD Mini-Dev, Spider 2.0, Mercer Messy Suite
- Regression suite: `eval/regression_suite.py` — run before every commit
- Test databases: DVDRental, Northwind, Chinook in `data/`
- Mock LLM responses in `tests/fixtures/` for unit tests (don't hit real APIs in unit tests)

---

## Implementation Phases

When implementing, follow this order. Check `docs/plan.md` for task-level detail.

1. **Phase 0** — Scaffold + single-pass baseline (SQLAlchemy introspector, basic BM25, Claude API, dry-run execution)
2. **Phase 1** — CHESS 3-step schema linker + FK graph + Redis cache
3. **Phase 2** — Multi-candidate async generator + taxonomy corrector
4. **Phase 3** — SGLang backend + Triton GPU kernels
5. **Phase 4** — FastAPI + React UI + Docker production stack

Do not skip ahead. Each phase has a working, testable state before the next begins.

---

## Key Design Decisions

- **Vectorless core**: No embeddings or vector DB for schema navigation. BM25 + LSH + LLM reasoning. Vector RAG is opt-in for glossary only.
- **SGLang over Ollama**: RadixAttention caches the shared schema prefix across all queries — critical for Text2SQL workloads where schema context is identical per DB session.
- **Multi-candidate selection**: Generate 3 SQL candidates with different strategies, execute all, pick best. Do not generate-and-pray with one candidate.
- **Qwen2.5-Coder as local model**: Current SOTA open-weight model for SQL. SQLCoder is deprecated for this purpose.
- **Triton LSH**: GPU-accelerated locality-sensitive hashing for entity matching. CPU sklearn LSH is too slow for production value matching.
