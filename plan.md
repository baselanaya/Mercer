# Mercer — Implementation Plan

Phased task list. Complete each phase fully before starting the next. Each phase ends in a working, testable state.

---

## Phase 0 — Foundation & Baseline
**Goal:** Working single-pass Text2SQL with Claude API. No schema linking, no candidates, no GPU. Just: question → schema dump → SQL → execute → display.

**Definition of done:** Can query DVDRental and get correct SQL for 5 hand-written test questions.

### Scaffold
- [ ] Initialize repo structure (all directories from `CLAUDE.md`)
- [ ] `config/settings.py` — Pydantic BaseSettings for all env vars
- [ ] `.env.example` with all required keys
- [ ] `requirements.txt` (core CPU deps)
- [ ] `requirements-gpu.txt` (torch, sglang, flashinfer, triton)
- [ ] `pyproject.toml` with dev tools (pytest, ruff, mypy)
- [ ] `CONTRIBUTING.md`
- [ ] `docker/docker-compose.yml` — PostgreSQL + Redis services only (no SGLang yet)

### Database Layer
- [ ] `db/connectors/postgres.py` — async SQLAlchemy engine
- [ ] `db/connectors/sqlite.py` — async SQLAlchemy engine
- [ ] `db/connectors/mysql.py` — async SQLAlchemy engine
- [ ] `db/connectors/duckdb.py` — DuckDB connector
- [ ] `db/sandbox.py` — `ReadOnlySandbox` with keyword block, timeout, row limit
- [ ] `db/explain.py` — EXPLAIN abstraction per DB type
- [ ] `tests/test_sandbox.py` — test blocked keywords, row limit, timeout

### Schema Layer (basic)
- [ ] `schema/introspector.py` — SQLAlchemy 2.0 `inspect()` → `RawSchema`
- [ ] `schema/semantic_mapper.py` — load `mappings.yaml`, merge into `AnnotatedSchema`
- [ ] `config/mappings.yaml` — example mapping for DVDRental
- [ ] `tests/test_introspector.py`

### Test Databases
- [ ] `data/dvdrental/` — DVDRental PostgreSQL dump + load script
- [ ] `data/northwind/` — Northwind PostgreSQL dump + load script
- [ ] `data/chinook/` — Chinook SQLite file
- [ ] `data/messy_variants/dvdrental_messy.sql` — DVDRental with renamed columns, removed FKs

### Inference Layer (API only)
- [ ] `inference/api_backend.py` — Anthropic async client
- [ ] `inference/api_backend.py` — OpenAI async client (same file, same protocol)
- [ ] Define `LLMBackend` protocol in `inference/base.py`
- [ ] `tests/test_api_backend.py` — mock responses, no real API calls

### Prompts (baseline)
- [ ] `prompts/sql_generation.py` — single-pass generation prompt with schema dump
- [ ] `prompts/explanation.py` — plain English explanation of generated SQL

### Core Pipeline (baseline)
- [ ] `core/models.py` — all Pydantic models: `PipelineState`, `SQLCandidate`, `ExecutionResult`, `AuditEntry`, etc.
- [ ] `core/pipeline.py` — baseline: skip Stages 1–3, single candidate, no correction
- [ ] `core/executor.py` — execute single candidate, return `ExecutionResult`
- [ ] `scripts/ingest_schema.py` — CLI: introspect DB, print annotated schema

### Logging & Audit
- [ ] `structlog` setup in `core/logging.py`
- [ ] `AuditEntry` written on every pipeline run (JSON, append-only file for now)

### Phase 0 Validation
- [ ] 5 hand-written test queries against DVDRental with expected SQL
- [ ] All 5 execute successfully via sandbox
- [ ] `pytest tests/` passes with no failures

---

## Phase 1 — CHESS Schema Linking + FK Graph
**Goal:** Replace full schema dump with linked subset. Add Redis schema cache. BM25 + glossary retrieval.

**Definition of done:** Schema linking recall ≥ 90% on 20 hand-labelled DVDRental/Northwind queries (i.e. the correct tables/columns are always in the filtered set).

### Entity Retrieval (Stage 1)
- [ ] `core/entity_retriever.py` — `GlossaryExpander`: expand question using `mappings.yaml` glossary
- [ ] `core/entity_retriever.py` — `BM25ColumnRetriever`: BM25 scores for column names + descriptions
- [ ] `core/entity_retriever.py` — CPU LSH entity matching (sklearn, placeholder for GPU kernel later)
- [ ] `core/entity_retriever.py` — merge signals → `EntityContext`
- [ ] `tests/test_entity_retriever.py`

### Schema Linker (Stage 2)
- [ ] `core/schema_linker.py` — `step_column_prefilter()`: merge entity hits + BM25 → candidate columns
- [ ] `core/schema_linker.py` — `step_table_selection()`: LLM call → selected tables with CoT
- [ ] `core/schema_linker.py` — `step_final_columns()`: LLM call → final column set per table
- [ ] `prompts/table_selection.py` — few-shot table selection prompt
- [ ] `prompts/column_selection.py` — few-shot column selection prompt
- [ ] `tests/test_schema_linker.py`

### FK Graph (Stage 2 support)
- [ ] `schema/graph_builder.py` — build `networkx.DiGraph` from FK relationships
- [ ] `schema/graph_builder.py` — `find_join_path(table_a, table_b)` → shortest FK path
- [ ] FK paths injected into `FilteredSchema` after table selection
- [ ] `tests/test_graph_builder.py`

### Schema Cache
- [ ] `schema/cache.py` — Redis cache for `AnnotatedSchema` + networkx graph
- [ ] Cache key: `schema:{hash(db_url)}`, TTL: 1 hour
- [ ] `scripts/ingest_schema.py --invalidate` — manual cache invalidation
- [ ] `tests/test_cache.py` — mock Redis

### Pipeline Update
- [ ] Wire Stage 1 + Stage 2 into `core/pipeline.py`
- [ ] `PipelineState` now carries `entity_context` + `filtered_schema`
- [ ] SQL generation prompt updated to use `filtered_schema` (not full schema dump)
- [ ] `prompts/sql_generation.py` updated accordingly

### Evaluation Setup
- [ ] `eval/metrics.py` — `execution_accuracy()`, `schema_linking_recall()`
- [ ] `eval/regression_suite.py` — 20 labelled queries, run before every commit
- [ ] `scripts/benchmark.py` — CLI entry point for eval runs

### Phase 1 Validation
- [ ] Schema linking recall ≥ 90% on labelled set
- [ ] Execution accuracy on 20 test queries ≥ 70%
- [ ] Schema cache working (second query on same DB is instant)
- [ ] `pytest tests/` passes

---

## Phase 2 — Multi-Candidate Generation + Taxonomy Correction
**Goal:** 3 candidates in parallel, execution-based selection, structured error correction.

**Definition of done:** Execution accuracy on BIRD Mini-Dev 50-query sample ≥ 55%.

### Query Decomposer (Stage 3)
- [ ] `core/query_decomposer.py` — LLM call → `QueryPlan`
- [ ] `prompts/query_plan.py` — decomposition prompt with few-shot examples
- [ ] `QueryPlan` model: aggregations, filters, joins, ordering, subqueries
- [ ] `tests/test_query_decomposer.py`

### Multi-Candidate Generator (Stage 4)
- [ ] `core/candidate_generator.py` — 3 strategy definitions (direct CoT, divide-and-conquer, plan-execute)
- [ ] `core/candidate_generator.py` — `asyncio.gather()` dispatch to inference backend
- [ ] `prompts/sql_generation.py` — one prompt per strategy (3 prompt builders)
- [ ] `tests/test_candidate_generator.py` — mock backend

### Candidate Selection (Stage 5 upgrade)
- [ ] `core/executor.py` — run all 3 candidates in parallel
- [ ] `core/executor.py` — composite scoring: syntax valid + result non-empty + result consistency
- [ ] `core/executor.py` — CPU result consistency scoring (GPU kernel in Phase 3)
- [ ] `tests/test_executor.py`

### Taxonomy Corrector (Stage 6)
- [ ] `core/corrector.py` — `_classify_error()` → error taxonomy
- [ ] `core/corrector.py` — correction prompt per error class
- [ ] `prompts/correction.py` — 6 correction prompts (one per taxonomy class)
- [ ] `core/corrector.py` — 3-iteration correction loop with `CorrectionStep` log
- [ ] `tests/test_corrector.py`

### Pipeline Update
- [ ] Wire Stages 3–6 into `core/pipeline.py`
- [ ] `PipelineState.correction_log` populated from Stage 6
- [ ] Audit log now includes correction steps + model tier used

### Evaluation Upgrade
- [ ] `eval/metrics.py` — add `reward_based_ves()`, `soft_f1_score()`
- [ ] `eval/bird_eval.py` — BIRD Mini-Dev runner (50-query sample first, then full 500)
- [ ] `eval/messy_schema_eval.py` — custom messy schema test suite (20 queries on `dvdrental_messy`)
- [ ] `scripts/benchmark.py` — add `--suite` flag: `bird`, `northwind`, `mercer_messy`

### Phase 2 Validation
- [ ] BIRD Mini-Dev 50-sample EX ≥ 55%
- [ ] DVDRental clean EX ≥ 80%
- [ ] Mercer Messy Suite EX ≥ 60%
- [ ] Multi-candidate always faster than 3× single-candidate (async working)
- [ ] `pytest tests/` passes

---

## Phase 3 — GPU Stack
**Goal:** SGLang backend live on RTX 4070. Triton GPU kernels replace CPU fallbacks. Measurable latency improvement.

**Definition of done:** P50 query latency < 3s on RTX 4070 with 7B model. GPU LSH kernel active.

### SGLang Backend
- [ ] `inference/sglang_backend.py` — async HTTP client to SGLang server
- [ ] `inference/sglang_backend.py` — `generate(prompt)` and `generate_batch(prompts)`
- [ ] `inference/sglang_backend.py` — exponential backoff retry via `tenacity`
- [ ] `inference/router.py` — complexity scorer + tier routing (7B → 32B → API)
- [ ] `config/inference.yaml` — SGLang URL, model paths, routing thresholds
- [ ] `docker/Dockerfile.sglang` — GPU-enabled SGLang container
- [ ] `docker/docker-compose.yml` — add SGLang service with NVIDIA runtime
- [ ] `scripts/serve.sh` — start SGLang server with RTX 4070 settings
- [ ] `tests/test_sglang_backend.py` — mock server responses

### Triton GPU Kernels
- [ ] `kernels/lsh_hash.py` — Triton LSH kernel (random projection hash)
- [ ] `kernels/lsh_hash.py` — CPU fallback path (sklearn)
- [ ] `kernels/schema_encode.py` — Triton batch tokenization kernel
- [ ] `kernels/schema_encode.py` — CPU fallback path
- [ ] `kernels/result_score.py` — Triton result consistency scoring kernel
- [ ] `kernels/result_score.py` — CPU fallback path (numpy)
- [ ] `kernels/__init__.py` — auto-detect CUDA, select kernel path
- [ ] `tests/test_kernels.py` — CPU path only (no CUDA in CI)

### Kernel Integration
- [ ] `core/entity_retriever.py` — swap sklearn LSH for `kernels/lsh_hash.py`
- [ ] `core/executor.py` — swap numpy scoring for `kernels/result_score.py`
- [ ] `schema/introspector.py` — use `kernels/schema_encode.py` for batch tokenization

### Latency Benchmarking
- [ ] `scripts/benchmark.py --mode latency` — measure P50/P95/P99 per stage
- [ ] Compare GPU vs CPU for LSH kernel (report in `docs/benchmarks.md`)
- [ ] Compare SGLang vs API backend latency

### Phase 3 Validation
- [ ] P50 latency < 3s on RTX 4070 (7B FP8 via SGLang)
- [ ] GPU LSH kernel active and faster than CPU sklearn on schemas > 50 tables
- [ ] BIRD Mini-Dev EX unchanged or improved vs Phase 2 (GPU doesn't hurt accuracy)
- [ ] `pytest tests/` passes (CPU fallback path tested)

---

## Phase 4 — Production Hardening
**Goal:** FastAPI backend, React UI, full Docker stack, auth, streaming, rate limiting.

**Definition of done:** Full BIRD Mini-Dev 500 EX ≥ 65%. App runs end-to-end in Docker. UI is functional.

### FastAPI Backend
- [ ] `app/api/main.py` — FastAPI app factory
- [ ] `app/api/routes.py` — `POST /query`, `GET /schema`, `GET /audit`
- [ ] `app/api/websocket.py` — WebSocket endpoint for streaming SQL generation
- [ ] `app/api/middleware.py` — rate limiting (per IP or API key), request logging
- [ ] `app/api/auth.py` — API key auth (simple for now, JWT-ready)
- [ ] `tests/test_api.py` — FastAPI test client

### React Frontend
- [ ] `app/ui/` — React + TailwindCSS app (Vite)
- [ ] `app/ui/components/ChatPane.tsx` — question input, streaming response display
- [ ] `app/ui/components/SQLViewer.tsx` — syntax-highlighted SQL with copy button
- [ ] `app/ui/components/SchemaExplorer.tsx` — interactive schema tree (collapsible tables)
- [ ] `app/ui/components/ResultTable.tsx` — paginated result display
- [ ] `app/ui/components/ReasoningTrace.tsx` — collapsible pipeline stage trace
- [ ] WebSocket client for streaming token display during generation

### Docker Production Stack
- [ ] `docker/Dockerfile.app` — multi-stage build for FastAPI app
- [ ] `docker/docker-compose.yml` — full stack: postgres + redis + sglang + app
- [ ] Health checks for all services
- [ ] Volume mounts for HuggingFace model cache (avoid re-download)
- [ ] `docker/docker-compose.dev.yml` — dev override (hot reload, no GPU required)

### Full Evaluation Run
- [ ] `eval/bird_eval.py` — full BIRD Mini-Dev (500 questions)
- [ ] `eval/spider_eval.py` — Spider 2.0 (600 questions)
- [ ] `eval/metrics.py` — add R-VES metric
- [ ] Run full suite, document results in `docs/benchmarks.md`

### Observability
- [ ] Structured audit log → append to DuckDB table (replace JSON file)
- [ ] `GET /audit` endpoint returns recent query history
- [ ] Per-stage latency tracked in `AuditEntry`
- [ ] `scripts/benchmark.py --report` — generate benchmark report from audit log

### Phase 4 Validation
- [ ] BIRD Mini-Dev 500 EX ≥ 65%
- [ ] DVDRental/Northwind/Chinook EX ≥ 85%
- [ ] Mercer Messy Suite EX ≥ 70%
- [ ] Full Docker stack starts with `docker compose up` — no manual steps
- [ ] UI: question → SQL → result in < 5s on RTX 4070
- [ ] `pytest tests/` passes in CI (no GPU, no real DB, all mocked)

---

## Phase 5 — Open Source Launch
**Goal:** Public repo ready. Documentation complete. Content published.

### Documentation
- [ ] `README.md` — final version with benchmark numbers filled in
- [ ] `docs/architecture.md` — this file, verified accurate post-implementation
- [ ] `docs/benchmarks.md` — benchmark results table
- [ ] `docs/connecting-your-db.md` — tutorial: connect and map a real messy schema
- [ ] `docs/custom-models.md` — how to swap in a different local model
- [ ] Issue templates (bug report, feature request)
- [ ] `CONTRIBUTING.md` — finalized

### Content
- [ ] Maximlabs blog post draft: "Building a Text2SQL System for Messy Real-World Schemas"
- [ ] YouTube video script: walkthrough of the pipeline
- [ ] LinkedIn post announcing launch

### Cleanup
- [ ] Remove all TODO comments from source code
- [ ] `ruff check .` passes with zero warnings
- [ ] `mypy .` passes with zero errors
- [ ] Test coverage ≥ 80% (unit tests only, not eval)
- [ ] All prompts have version comments
- [ ] `CHANGELOG.md` — Phase 0 through Phase 4 summary

---

## Ongoing — After Each Phase

- [ ] Run `eval/regression_suite.py` — no regressions on 20 labelled queries
- [ ] Update `docs/benchmarks.md` with new numbers
- [ ] Git tag the phase completion: `v0.1.0` through `v0.5.0`
