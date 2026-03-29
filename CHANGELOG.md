# Changelog

All notable changes to Mercer are documented here.

---

## [v0.5.0] — 2026-03-29 — Launch ready

Documentation pass, docstring coverage, final cleanup.

- Added `docs/connecting-your-db.md` — step-by-step DB onboarding guide with messy-schema walkthrough and troubleshooting section
- Added `docs/custom-models.md` — SGLang model swap guide, API provider switching, and new LLMBackend implementation walkthrough
- Updated `README.md` — real benchmark numbers, screenshot placeholder, "Built with" section
- Finalized `CONTRIBUTING.md` — test commands, benchmark commands, PR checklist
- Added `CHANGELOG.md` and `.github/ISSUE_TEMPLATE/` (bug report + feature request)
- All 35 public functions now have docstrings; zero ruff warnings; zero mypy errors

---

## [v0.4.0] — 2026-03-29 — Phase 4: UI + Docker + DuckDB audit

- **React UI** (`app/ui/`): Vite + TypeScript, dark zinc theme, CodeMirror SQL viewer, WebSocket streaming, schema explorer, reasoning trace, result table with sort and CSV export
- **DuckDB audit store** (`db/audit_store.py`): replaces JSONL log with columnar storage; P50/P95/P99 latency, success rate, correction rate, top error classes
- **Docker production stack** (`docker/Dockerfile.app`, `docker/docker-compose.yml`): multi-stage build (UI + Python + runtime), non-root user, healthchecks, GPU-optional dev override
- **`scripts/benchmark.py --report`**: reads aggregate metrics from DuckDB audit log
- **FastAPI static file serving**: React `dist/` mounted at `/` when built

---

## [v0.3.0] — Phase 3: SGLang backend + model router

- `inference/sglang_backend.py`: async SGLang client over OpenAI-compatible endpoint, RadixAttention prefix caching
- `inference/router.py`: complexity-based routing — low-complexity queries use local 7B model, high-complexity queries escalate to cloud API
- `kernels/lsh_hash.py`: Triton GPU kernel for batch LSH hash computation (entity matching)
- `kernels/schema_encode.py`: batch schema tokenization with GPU/CPU fallback
- `kernels/result_score.py`: GPU-accelerated result consistency scoring
- `scripts/serve.sh`: SGLang launch script for RTX 4070 (FP8, FlashInfer, CUDA graphs)

---

## [v0.2.0] — Phase 2: Multi-candidate pipeline + taxonomy corrector

- `core/candidate_generator.py`: 3 parallel SQL strategies via `asyncio.gather()` — direct CoT, divide-and-conquer, plan-execute
- `core/corrector.py`: taxonomy-guided error correction — classifies errors as schema_error, join_error, filter_error, aggregation_error, syntax_error, logic_error before retrying
- `core/executor.py`: execution-based candidate selection — runs all 3 candidates, picks winner by result consistency
- All stages independently testable with mock backends

---

## [v0.1.0] — Phase 1: CHESS schema linker + FK graph + Redis cache

- `core/schema_linker.py`: 3-step CHESS-inspired linker — column pre-filter (BM25) → table selection (LLM) → final column selection (LLM)
- `schema/graph_builder.py`: FK relationship graph (networkx) for join path discovery
- `schema/cache.py`: Redis-backed schema cache with TTL and cache-first loading
- `schema/semantic_mapper.py`: glossary and column description injection from `config/mappings.yaml`

---

## [v0.0.1] — Phase 0: Single-pass baseline

- `core/pipeline.py`: 6-stage pipeline orchestrator, async throughout
- `core/entity_retriever.py`: BM25 entity retrieval against schema corpus
- `schema/introspector.py`: SQLAlchemy 2.0 async schema introspection
- `inference/api_backend.py`: Anthropic and OpenAI async backends with retry
- `db/sandbox.py`: read-only sandboxed execution — blocked DDL/DML, 5s timeout, 100-row limit
- `app/api/main.py` + `routes.py` + `websocket.py`: FastAPI REST + WebSocket API
- `tests/`: 451 unit tests, all passing without external services
