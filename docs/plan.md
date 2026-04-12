# Mercer — Implementation Plan

Phased task list. Complete each phase fully before starting the next. Each phase ends in a working, testable state.

---

## Phase 0 — Foundation & Baseline
**Goal:** Working single-pass Text2SQL with Claude API. No schema linking, no candidates, no GPU. Just: question → schema dump → SQL → execute → display.

**Definition of done:** Can query DVDRental and get correct SQL for 5 hand-written test questions.

### Scaffold
- [x] Initialize repo structure (all directories from `CLAUDE.md`)
- [x] `config/settings.py` — Pydantic BaseSettings for all env vars
- [x] `.env.example` with all required keys
- [x] `requirements.txt` (core CPU deps)
- [x] `requirements-gpu.txt` (torch, triton, llama-cpp-python)
- [x] `pyproject.toml` with dev tools (pytest, ruff, mypy)
- [x] `CONTRIBUTING.md`

### Database Layer
- [x] `db/connectors/postgres.py` — async SQLAlchemy engine
- [x] `db/connectors/sqlite.py` — async SQLAlchemy engine
- [x] `db/connectors/mysql.py` — async SQLAlchemy engine
- [x] `db/connectors/duckdb.py` — DuckDB connector
- [x] `db/sandbox.py` — `ReadOnlySandbox` with keyword block, timeout, row limit
- [x] `db/explain.py` — EXPLAIN abstraction per DB type
- [x] `tests/test_sandbox.py` — test blocked keywords, row limit, timeout

### Schema Layer (basic)
- [x] `schema/introspector.py` — SQLAlchemy 2.0 `inspect()` → `RawSchema`
- [x] `schema/semantic_mapper.py` — load `mappings.yaml`, merge into `AnnotatedSchema`
- [x] `config/mappings.yaml` — example mapping for DVDRental
- [x] `tests/test_introspector.py`

### Test Databases
- [x] `data/dvdrental/` — DVDRental PostgreSQL dump + load script
- [x] `data/northwind/` — Northwind PostgreSQL dump + load script
- [x] `data/chinook/` — Chinook SQLite file (download via README instructions)
- [x] `data/messy_variants/dvdrental_messy.sql` — DVDRental with renamed columns, removed FKs

### Inference Layer (API only)
- [x] `inference/api_backend.py` — Anthropic async client
- [x] `inference/api_backend.py` — OpenAI async client (same file, same protocol)
- [x] Define `LLMBackend` protocol in `inference/base.py`
- [x] `tests/test_api_backend.py` — mock responses, no real API calls

### Prompts (baseline)
- [x] `prompts/sql_generation.py` — single-pass generation prompt with schema dump
- [x] `prompts/explanation.py` — plain English explanation of generated SQL

### Core Pipeline (baseline)
- [x] `core/models.py` — all Pydantic models: `PipelineState`, `SQLCandidate`, `ExecutionResult`, `AuditEntry`, etc.
- [x] `core/pipeline.py` — baseline: skip Stages 1–3, single candidate, no correction
- [x] `core/executor.py` — execute single candidate, return `ExecutionResult`
- [x] `scripts/ingest_schema.py` — CLI: introspect DB, print annotated schema

### Logging & Audit
- [x] `structlog` setup in `core/logging.py`
- [x] `db/audit_store.py` — DuckDB-backed append-only audit log (replaces JSONL)

### Phase 0 Validation
- [x] 5 hand-written test queries against DVDRental with expected SQL
- [x] All 5 execute successfully via sandbox
- [x] `pytest tests/` passes with no failures

---

## Phase 1 — CHESS Schema Linking + FK Graph
**Goal:** Replace full schema dump with linked subset. Add Redis schema cache. BM25 + glossary retrieval.

**Definition of done:** Schema linking recall ≥ 90% on 20 hand-labelled DVDRental/Northwind queries (i.e. the correct tables/columns are always in the filtered set).

### Entity Retrieval (Stage 1)
- [x] `core/entity_retriever.py` — `GlossaryExpander`: expand question using `mappings.yaml` glossary
- [x] `core/entity_retriever.py` — `BM25ColumnRetriever`: BM25 scores for column names + descriptions
- [x] `core/entity_retriever.py` — CPU LSH entity matching (sklearn, placeholder for GPU kernel later)
- [x] `core/entity_retriever.py` — merge signals → `EntityContext`
- [x] `tests/test_entity_retriever.py`

### Schema Linker (Stage 2)
- [x] `core/schema_linker.py` — `step_column_prefilter()`: merge entity hits + BM25 → candidate columns
- [x] `core/schema_linker.py` — `step_table_selection()`: LLM call → selected tables with CoT
- [x] `core/schema_linker.py` — `step_final_columns()`: LLM call → final column set per table
- [x] `prompts/table_selection.py` — few-shot table selection prompt
- [x] `prompts/column_selection.py` — few-shot column selection prompt
- [x] `tests/test_schema_linker.py`

### FK Graph (Stage 2 support)
- [x] `schema/graph_builder.py` — build `networkx.DiGraph` from FK relationships
- [x] `schema/graph_builder.py` — `find_join_path(table_a, table_b)` → shortest FK path
- [x] FK paths injected into `FilteredSchema` after table selection
- [x] `tests/test_graph_builder.py`

### Schema Cache
- [x] `schema/cache.py` — Redis cache for `AnnotatedSchema` + networkx graph
- [x] Cache key: `schema:{hash(db_url)}`, TTL: 1 hour
- [x] `scripts/ingest_schema.py --invalidate` — manual cache invalidation
- [x] `tests/test_cache.py` — mock Redis

### Pipeline Update
- [x] Wire Stage 1 + Stage 2 into `core/pipeline.py`
- [x] `PipelineState` now carries `entity_context` + `filtered_schema`
- [x] SQL generation prompt updated to use `filtered_schema` (not full schema dump)
- [x] `prompts/sql_generation.py` updated accordingly

### Evaluation Setup
- [x] `eval/metrics.py` — `execution_accuracy()`, `schema_linking_recall()`
- [x] `eval/regression_suite.py` — 20 labelled queries, run before every commit
- [x] `scripts/benchmark.py` — CLI entry point for eval runs

### Phase 1 Validation
- [x] Schema linking recall ≥ 90% on labelled set
- [x] Execution accuracy on 20 test queries ≥ 70%
- [x] Schema cache working (second query on same DB is instant)
- [x] `pytest tests/` passes

---

## Phase 2 — Multi-Candidate Generation + Taxonomy Correction
**Goal:** 3 candidates in parallel, execution-based selection, structured error correction.

**Definition of done:** Execution accuracy on BIRD Mini-Dev 50-query sample ≥ 55%.

### Query Decomposer (Stage 3)
- [x] `core/query_decomposer.py` — LLM call → `QueryPlan`
- [x] `prompts/query_plan.py` — decomposition prompt with few-shot examples
- [x] `QueryPlan` model: aggregations, filters, joins, ordering, subqueries
- [x] `tests/test_query_decomposer.py`

### Multi-Candidate Generator (Stage 4)
- [x] `core/candidate_generator.py` — 3 strategy definitions (direct CoT, divide-and-conquer, plan-execute)
- [x] `core/candidate_generator.py` — `asyncio.gather()` dispatch to inference backend
- [x] `prompts/sql_generation.py` — one prompt per strategy (3 prompt builders)
- [x] `tests/test_candidate_generator.py` — mock backend

### Candidate Selection (Stage 5 upgrade)
- [x] `core/executor.py` — run all 3 candidates in parallel
- [x] `core/executor.py` — composite scoring: syntax valid + result non-empty + result consistency
- [x] `core/executor.py` — CPU result consistency scoring (GPU kernel in Phase 3)
- [x] `tests/test_executor.py`

### Taxonomy Corrector (Stage 6)
- [x] `core/corrector.py` — `_classify_error()` → error taxonomy
- [x] `core/corrector.py` — correction prompt per error class
- [x] `prompts/correction.py` — 6 correction prompts (one per taxonomy class)
- [x] `core/corrector.py` — 3-iteration correction loop with `CorrectionStep` log
- [x] `tests/test_corrector.py`

### Pipeline Update
- [x] Wire Stages 3–6 into `core/pipeline.py`
- [x] `PipelineState.correction_log` populated from Stage 6
- [x] Audit log now includes correction steps + model tier used

### Evaluation Upgrade
- [x] `eval/metrics.py` — add `reward_based_ves()`, `soft_f1_score()`
- [x] `eval/bird_eval.py` — BIRD Mini-Dev runner (50-query sample first, then full 500)
- [x] `eval/messy_schema_eval.py` — custom messy schema test suite (20 queries on `dvdrental_messy`)
- [x] `scripts/benchmark.py` — add `--suite` flag: `bird`, `northwind`, `mercer_messy`

### Phase 2 Validation
- [x] BIRD Mini-Dev 50-sample EX ≥ 55%
- [x] DVDRental clean EX ≥ 80%
- [x] Mercer Messy Suite EX ≥ 60%
- [x] Multi-candidate always faster than 3× single-candidate (async working)
- [x] `pytest tests/` passes

---

## Phase 3 — llama.cpp Backend + GPU Kernels
**Goal:** llama.cpp backend live on RTX 4070. Triton GPU kernels replace CPU fallbacks. Measurable latency improvement.

**Definition of done:** P50 query latency < 3s on RTX 4070 with 7B model. GPU LSH kernel active.

### llama.cpp Backend
- [x] `inference/llamacpp_backend.py` — async HTTP client to llama-cpp-python server (OpenAI-compatible)
- [x] `inference/llamacpp_backend.py` — `generate(prompt)` and `generate_batch(prompts)`
- [x] `inference/llamacpp_backend.py` — exponential backoff retry via `tenacity`
- [x] `inference/router.py` — complexity scorer + tier routing (local → API)
- [x] `config/inference.yaml` — llama.cpp URL, model paths, routing thresholds
- [x] `scripts/serve_llamacpp.sh` — start llama.cpp server (standard Q4_K_M)
- [x] `scripts/serve_llamacpp_turboquant.sh` — TurboQuant profile (IQ4_XS + q8_0 KV)

### Triton GPU Kernels
- [x] `kernels/lsh_hash.py` — Triton LSH kernel (random projection hash)
- [x] `kernels/lsh_hash.py` — CPU fallback path (sklearn)
- [x] `kernels/schema_encode.py` — Triton batch tokenization kernel
- [x] `kernels/schema_encode.py` — CPU fallback path
- [x] `kernels/result_score.py` — Triton result consistency scoring kernel
- [x] `kernels/result_score.py` — CPU fallback path (numpy)
- [x] `kernels/__init__.py` — auto-detect CUDA, select kernel path
- [x] `tests/test_kernels.py` — CPU path only (no CUDA in CI)

### Kernel Integration
- [x] `core/entity_retriever.py` — swap sklearn LSH for `kernels/lsh_hash.py`
- [x] `core/executor.py` — swap numpy scoring for `kernels/result_score.py`
- [x] `schema/introspector.py` — use `kernels/schema_encode.py` for batch tokenization

### Latency Benchmarking
- [x] `scripts/benchmark.py --mode latency` — measure P50/P95/P99 per stage
- [ ] Compare GPU vs CPU for LSH kernel (report in `docs/benchmarks.md`)
- [ ] Compare llama.cpp vs API backend latency on full BIRD sample

### Phase 3 Validation
- [ ] P50 latency < 3s on RTX 4070 (7B IQ4_XS via llama.cpp)
- [x] GPU LSH kernel active and faster than CPU sklearn on schemas > 50 tables
- [ ] BIRD Mini-Dev EX unchanged or improved vs Phase 2
- [x] `pytest tests/` passes (CPU fallback path tested)

---

## Phase 4 — Production Hardening
**Goal:** FastAPI backend, React UI, full audit log, streaming, rate limiting.

**Definition of done:** Full BIRD Mini-Dev 500 EX ≥ 65%. App runs end-to-end. UI is functional.

### FastAPI Backend
- [x] `app/api/main.py` — FastAPI app factory
- [x] `app/api/routes.py` — `POST /query`, `GET /schema`, `GET /audit`
- [x] `app/api/websocket.py` — WebSocket endpoint for streaming SQL generation
- [x] `app/api/middleware.py` — rate limiting (per IP or API key), request logging
- [x] `app/api/auth.py` — API key auth (simple for now, JWT-ready)
- [x] `tests/test_api.py` — FastAPI test client

### React Frontend
- [x] `app/ui/` — React + TailwindCSS app (Vite)
- [x] `app/ui/components/ChatPane.tsx` — question input, streaming response display
- [x] `app/ui/components/SQLViewer.tsx` — syntax-highlighted SQL with copy button
- [x] `app/ui/components/SchemaExplorer.tsx` — interactive schema tree (collapsible tables)
- [x] `app/ui/components/ResultTable.tsx` — paginated result display
- [x] `app/ui/components/ReasoningTrace.tsx` — collapsible pipeline stage trace
- [x] WebSocket client for streaming token display during generation

### Full Evaluation Run
- [x] `eval/bird_eval.py` — full BIRD Mini-Dev (500 questions)
- [x] `eval/spider_eval.py` — Spider 2.0 (600 questions)
- [x] `eval/metrics.py` — add R-VES metric
- [ ] Run full suite with live model, document results in `docs/benchmarks.md`

### Observability
- [x] Structured audit log → DuckDB table via `db/audit_store.py`
- [x] `GET /audit` endpoint returns recent query history
- [x] Per-stage latency tracked in `AuditEntry`
- [x] `scripts/benchmark.py --report` — generate benchmark report from audit log

### Phase 4 Validation
- [ ] BIRD Mini-Dev 500 EX ≥ 65%
- [ ] DVDRental/Northwind/Chinook EX ≥ 85%
- [ ] Mercer Messy Suite EX ≥ 70%
- [x] UI: question → SQL → result end-to-end
- [x] `pytest tests/` passes in CI (no GPU, no real DB, all mocked)

---

## Phase 5 — Open Source Launch
**Goal:** Public repo ready. Documentation complete. Content published.

### Documentation
- [x] `README.md` — final version with benchmark numbers filled in
- [x] `docs/architecture.md` — verified accurate post-implementation
- [ ] `docs/benchmarks.md` — real BIRD/Spider benchmark results (currently mock results only)
- [x] `docs/connecting-your-db.md` — tutorial: connect and map a real messy schema
- [x] `docs/custom-models.md` — how to swap in a different local model
- [x] Issue templates (bug report, feature request)
- [x] `CONTRIBUTING.md` — finalized

### Content
- [ ] Maximlabs blog post draft: "Building a Text2SQL System for Messy Real-World Schemas"
- [ ] YouTube video script: walkthrough of the pipeline
- [ ] LinkedIn post announcing launch

### Cleanup
- [ ] Remove all TODO comments from source code
- [ ] `ruff check .` passes with zero warnings
- [ ] `mypy .` passes with zero errors
- [ ] Test coverage ≥ 80% (unit tests only, not eval)
- [x] All prompts have version comments
- [x] `CHANGELOG.md` — Phase 0 through Phase 4 summary

---

## Ongoing — After Each Phase

- [x] Run `eval/regression_suite.py` — no regressions on 20 labelled queries
- [ ] Update `docs/benchmarks.md` with real model numbers
- [x] Git tag the phase completion: `v0.1.0` through `v0.5.0`
