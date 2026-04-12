# Mercer — Claude Code Project Instructions

## Project

Text-to-SQL system for messy real-world schemas. Converts natural language queries to accurate SQL using a 6-stage agentic pipeline: entity retrieval → schema linking → query decomposition → multi-candidate generation → execution + selection → taxonomy-guided correction.

See [`docs/architecture.md`](docs/architecture.md) for the full pipeline design.
See [`docs/plan.md`](docs/plan.md) for the phased implementation roadmap.

---

## Stack

- **Language**: Python 3.11+
- **LLM inference**: llama.cpp (local, GGUF) or Anthropic/OpenAI API (cloud)
- **Local model**: Qwen2.5-Coder-7B-Instruct-IQ4_XS.gguf via llama-cpp-python on RTX 4070
- **DB abstraction**: SQLAlchemy 2.0 (async)
- **API backend**: FastAPI + uvicorn
- **Frontend**: React 19 + TailwindCSS v4 + Vite (`app/ui/`) — NOT Next.js, no "use client" directives
- **GPU kernels**: Triton (`kernels/`)
- **Caching**: Redis (schema), DuckDB (audit log)
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
scripts/       # CLI tools (ingest_schema.py, benchmark.py, serve_llamacpp*.sh)
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
LLAMACPP_URL          # llama.cpp server (default: http://localhost:8080)
ANTHROPIC_API_KEY     # For API fallback
OPENAI_API_KEY        # For API fallback
INFERENCE_BACKEND     # "llamacpp" | "anthropic" | "openai"
LOG_LEVEL             # "DEBUG" | "INFO" | "WARNING"
```

Settings are loaded via Pydantic `config/settings.py`. Never hardcode keys.

---

## Dev Commands

```bash
# Start llama.cpp server (TurboQuant: IQ4_XS + q8_0 KV cache)
bash scripts/serve_llamacpp_turboquant.sh

# Start the API server
uvicorn app.api.main:app --reload --port 8000

# Start the UI dev server (separate terminal)
cd app/ui && npm run dev

# Run tests
pytest tests/ -v

# Run benchmark
python scripts/benchmark.py --suite mercer_messy
python eval/gretelai_eval.py

# Ingest schema
python scripts/ingest_schema.py --db-url $DATABASE_URL
```

---

## Testing

- Unit tests: one test file per module in `tests/`
- Benchmark eval: `eval/` — gretelai/synthetic_text_to_sql, Mercer Messy Suite
- Regression suite: `eval/regression_suite.py` — run before every commit
- Test databases: DVDRental, Northwind, Chinook in `data/`
- Mock LLM responses in `tests/fixtures/` for unit tests (don't hit real APIs in unit tests)

---

## Key Design Decisions

- **Vectorless core**: No embeddings or vector DB for schema navigation. BM25 + LSH + LLM reasoning. Vector RAG is opt-in for glossary only.
- **llama.cpp over Ollama**: GGUF format with IQ4_XS quantization + q8_0 KV cache (TurboQuant profile). Native CUDA via llama-cpp-python, OpenAI-compatible API.
- **Multi-candidate selection**: Generate 3 SQL candidates with different strategies, execute all, pick best. Do not generate-and-pray with one candidate.
- **Qwen2.5-Coder as local model**: Current SOTA open-weight model for SQL.
- **Triton LSH**: GPU-accelerated locality-sensitive hashing for entity matching. CPU sklearn LSH is too slow for production value matching.
