# Mercer — Architecture

## Overview

Mercer is a 6-stage agentic Text-to-SQL pipeline. Each stage is a discrete, independently testable module in `core/`. The orchestrator (`core/pipeline.py`) wires them together and manages state across stages.

The pipeline is designed around three principles:

1. **Structure before semantics.** Schema linking happens before any SQL is generated. The LLM never sees the full schema dump — only the filtered subset relevant to the query.
2. **Multiple candidates, not multiple retries.** Three SQL strategies run in parallel. Selection is execution-based, not LLM self-judgment.
3. **Taxonomy-guided correction, not blind retry.** Errors are classified before correction so the fix targets the actual problem.

---

## Full Pipeline

```
User NL Query
     │
     ▼
┌──────────────────────────────────────────────┐
│ STAGE 1 — Entity & Context Retrieval         │
│                                              │
│  Input : raw NL question                     │
│  Output: EntityContext (matched values,      │
│          expanded question, glossary hits)   │
│                                              │
│  1a. Glossary expansion                      │
│      "revenue" → "SUM of ord_hdr.tot_amt"   │
│      "churn"   → "no orders in 90 days"     │
│                                              │
│  1b. GPU LSH entity matching                 │
│      Find DB values matching NL entities     │
│      e.g. "RETAIL" → cust_mstr.cust_seg_cd  │
│                                              │
│  1c. BM25 keyword retrieval                  │
│      Score column names vs question tokens   │
└───────────────────────┬──────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ STAGE 2 — Schema Linking (3-step CHESS)      │
│                                              │
│  Input : EntityContext + full Schema         │
│  Output: FilteredSchema (tables + columns)   │
│                                              │
│  2a. Column pre-filter (all tables)          │
│      Merge entity hits + BM25 scores         │
│      Produce candidate column set            │
│                                              │
│  2b. Table selection                         │
│      LLM selects tables from candidates      │
│      with CoT reasoning                      │
│                                              │
│  2c. Final column selection (per table)      │
│      LLM prunes to only needed columns       │
│      FK paths added from graph builder       │
└───────────────────────┬──────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ STAGE 3 — Query Decomposition                │
│                                              │
│  Input : NL question + FilteredSchema        │
│  Output: QueryPlan (subproblems + CoT steps) │
│                                              │
│  Breaks complex queries into clauses:        │
│  - Identify aggregation intent               │
│  - Identify filter conditions                │
│  - Identify join paths required              │
│  - Identify ordering / limiting              │
│  - Identify subquery needs (CTEs, nested)    │
│                                              │
│  Output is a structured plan, not SQL yet.   │
└───────────────────────┬──────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ STAGE 4 — Multi-Candidate SQL Generation     │
│                                              │
│  Input : QueryPlan + FilteredSchema          │
│  Output: List[SQLCandidate] (N=3)            │
│                                              │
│  Three strategies run in parallel (async):   │
│                                              │
│  Strategy A — Direct CoT (temp=0.0)          │
│    Single-pass CoT, most conservative        │
│                                              │
│  Strategy B — Divide & Conquer (temp=0.2)    │
│    Subquery-per-clause then merge            │
│                                              │
│  Strategy C — Plan & Execute (temp=0.3)      │
│    Follows QueryPlan step by step            │
│                                              │
│  All three run via SGLang async batch.       │
│  Wall time ≈ single generation time.         │
└───────────────────────┬──────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ STAGE 5 — Execution & Candidate Selection    │
│                                              │
│  Input : List[SQLCandidate]                  │
│  Output: SQLCandidate (best)                 │
│                                              │
│  For each candidate:                         │
│  - Dry-run via ReadOnlySandbox               │
│  - Score: syntax valid (0/1) +               │
│           result non-empty +                 │
│           result consistency across          │
│           candidates (GPU batch scoring)     │
│                                              │
│  Select candidate with highest composite     │
│  score. Tie-break: Strategy A wins.          │
│                                              │
│  If no candidate passes dry-run → Stage 6   │
└───────────────────────┬──────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ STAGE 6 — Taxonomy-Guided Error Correction   │
│                                              │
│  Input : failed SQLCandidate + error msg     │
│  Output: corrected SQL (or give_up signal)   │
│                                              │
│  Error taxonomy:                             │
│  schema_error     → re-run schema linking    │
│  join_error       → re-examine FK graph      │
│  filter_error     → re-check entity values   │
│  aggregation_error→ re-decompose subproblem  │
│  syntax_error     → structural fix only      │
│  logic_error      → re-read question intent  │
│                                              │
│  Max 3 correction iterations.                │
│  Each iteration re-executes in sandbox.      │
│  Correction trace appended to audit log.     │
└───────────────────────┬──────────────────────┘
                        │
                        ▼
               Final SQL + Explanation
               + Reasoning trace
               + Audit log entry
```

---

## Module Reference

### `core/pipeline.py`

The orchestrator. Holds a `PipelineState` dataclass that accumulates output from each stage. Calls stages in order, handles stage failures, routes to correction when needed.

```python
@dataclass
class PipelineState:
    question:        str
    entity_context:  Optional[EntityContext]   = None
    filtered_schema: Optional[FilteredSchema]  = None
    query_plan:      Optional[QueryPlan]        = None
    candidates:      List[SQLCandidate]         = field(default_factory=list)
    best_candidate:  Optional[SQLCandidate]     = None
    final_sql:       Optional[str]              = None
    correction_log:  List[CorrectionStep]       = field(default_factory=list)
    audit_entry:     Optional[AuditEntry]       = None
```

### `core/entity_retriever.py`

**Stage 1.** Combines three retrieval signals:

- `GlossaryExpander`: loads `config/mappings.yaml`, expands known abbreviations and business terms in the question before any retrieval
- `GPULSHMatcher`: wraps `kernels/lsh_hash.py`, matches NL tokens against column values at scale
- `BM25ColumnRetriever`: wraps `rank-bm25`, scores column names and descriptions against the question

Output: `EntityContext` with matched column-value pairs and expanded question string.

### `core/schema_linker.py`

**Stage 2.** 3-step CHESS implementation.

- `step_column_prefilter()`: merges LSH + BM25 signals, returns scored column candidates
- `step_table_selection()`: LLM call with `prompts/table_selection.py`, returns selected tables with CoT reasoning
- `step_final_columns()`: LLM call with `prompts/column_selection.py`, prunes to final column set per table

FK paths between selected tables are added automatically from the graph built by `schema/graph_builder.py`.

### `core/query_decomposer.py`

**Stage 3.** Single LLM call with `prompts/query_plan.py`. Returns a structured `QueryPlan` with typed fields (aggregations, filters, joins, ordering, subqueries). Not SQL — a plan that Stage 4 strategies consume.

### `core/candidate_generator.py`

**Stage 4.** Three async tasks dispatched to `inference/sglang_backend.py` (or `inference/api_backend.py`) via `asyncio.gather()`. Each strategy uses its own prompt from `prompts/sql_generation.py`. Returns `List[SQLCandidate]` with metadata (strategy name, generation confidence, raw prompt).

### `core/executor.py`

**Stage 5.** Runs each candidate through `db/sandbox.py`. Scores results. Selects best. If no candidate executes successfully, returns the best candidate's error to Stage 6.

### `core/corrector.py`

**Stage 6.** Classifies the error using `_classify_error()`, looks up the taxonomy hint, generates a targeted correction prompt, re-executes. Appends each attempt to `PipelineState.correction_log`. Returns after first successful execution or after 3 failed attempts.

---

## Schema Layer

### `schema/introspector.py`

Uses SQLAlchemy 2.0 `inspect()` to extract tables, columns, types, primary keys, foreign keys, indexes, and check constraints. Produces a `RawSchema` object.

### `schema/semantic_mapper.py`

Loads `config/mappings.yaml` and merges user-defined descriptions into `RawSchema`. Falls back to column DB comments where mappings are absent. Produces an `AnnotatedSchema`.

### `schema/graph_builder.py`

Builds a directed `networkx.DiGraph` from FK relationships. Used by Stage 2 to find join paths between selected tables. `find_join_path(table_a, table_b)` returns the shortest FK path.

### `schema/cache.py`

Serializes `AnnotatedSchema` + networkx graph to Redis with a TTL (default 1 hour). Cache key is `schema:{hash(db_url)}`. Invalidated manually via `scripts/ingest_schema.py --invalidate`.

---

## Inference Layer

### `inference/router.py`

Routes each query to a model tier based on a complexity score (question length, number of tables in filtered schema, presence of subquery signals in the query plan).

```
complexity < 0.3  →  local_7b   (Qwen2.5-Coder-7B-Instruct via SGLang)
complexity < 0.7  →  local_32b  (Qwen2.5-Coder-32B-Instruct via SGLang)
complexity ≥ 0.7  →  api        (claude-sonnet-4-6 or gpt-4o)
```

### `inference/sglang_backend.py`

Async HTTP client to the SGLang server. Implements `generate(prompt)` and `generate_batch(prompts)`. Handles retries with exponential backoff via `tenacity`.

### `inference/api_backend.py`

Async clients for Anthropic and OpenAI APIs. Same interface as SGLang backend — both implement the `LLMBackend` protocol.

---

## GPU Kernel Layer

All Triton kernels in `kernels/`. CPU fallback implementations exist for all kernels — used in test environments and when CUDA is unavailable.

### `kernels/lsh_hash.py`

Triton kernel: batch random-projection LSH hashing. Takes a matrix of tokenized column values, returns hash buckets. Used by `core/entity_retriever.py` to match NL tokens against DB values.

CPU fallback: `sklearn.neighbors.LSHForest`

### `kernels/schema_encode.py`

Triton kernel: batch tokenize schema descriptions for BM25 indexing. Runs schema ingestion 4–6× faster than CPU on large schemas (300+ tables).

CPU fallback: plain Python tokenizer loop.

### `kernels/result_score.py`

Triton kernel: batch compute result consistency scores across candidate result sets. Computes overlap between result column vectors from all 3 candidates to detect agreement.

CPU fallback: numpy pairwise comparison.

---

## Database Layer

### `db/sandbox.py` — `ReadOnlySandbox`

The only permitted path to DB execution. Enforces:
- Blocked keyword check (DDL + DML)
- Statement timeout (5s, Postgres: `SET statement_timeout`)
- Row limit (100 rows max)
- Returns `ExecutionResult` — never raw cursor objects

### `db/explain.py`

Wraps database-specific EXPLAIN / dry-run syntax. PostgreSQL: `EXPLAIN (FORMAT JSON)`. MySQL: `EXPLAIN FORMAT=JSON`. SQLite: `EXPLAIN QUERY PLAN`. DuckDB: `EXPLAIN`. Returns a normalized `ExplainResult`.

### `db/connectors/`

One file per DB. Each implements the `DBConnector` protocol: `connect()`, `test_connection()`, `get_engine()`. All return SQLAlchemy 2.0 async engines.

---

## Prompt Design

All prompts live in `prompts/`. No inline prompt strings in pipeline code.

Each prompt file exports:
- A `build_prompt(**kwargs) -> str` function
- A `SYSTEM_PROMPT: str` constant
- A `FEW_SHOT_EXAMPLES: list[dict]` constant

Prompt files: `table_selection.py`, `column_selection.py`, `query_plan.py`, `sql_generation.py`, `correction.py`, `explanation.py`.

Version prompts by appending `_v2`, `_v3` to the filename when making breaking changes. Never edit a prompt in place without benchmarking the change.

---

## Data Flow — State Object

```
question (str)
    │
    ├── entity_context
    │     ├── glossary_expansions: dict[str, str]
    │     ├── entity_matches: list[EntityMatch]  # (token, table, column, value)
    │     └── expanded_question: str
    │
    ├── filtered_schema
    │     ├── tables: list[TableSchema]
    │     │     ├── name, description
    │     │     └── columns: list[ColumnSchema]  # (name, type, description)
    │     └── join_paths: list[JoinPath]
    │
    ├── query_plan
    │     ├── aggregations: list[str]
    │     ├── filters: list[str]
    │     ├── joins: list[str]
    │     ├── ordering: Optional[str]
    │     └── subqueries: list[str]
    │
    ├── candidates: list[SQLCandidate]
    │     ├── sql: str
    │     ├── strategy: str
    │     ├── execution_result: Optional[ExecutionResult]
    │     └── score: float
    │
    ├── best_candidate: SQLCandidate
    │
    ├── final_sql: str
    │
    └── audit_entry
          ├── question, final_sql, timestamp
          ├── tables_used, columns_used
          ├── model_used, backend_used
          └── correction_steps: list[CorrectionStep]
```

---

## Configuration

`config/settings.py` — Pydantic `BaseSettings`. All values from environment variables. No hardcoded credentials anywhere in the codebase.

`config/mappings.yaml` — Per-database semantic mappings. Loaded at schema ingestion time and merged into `AnnotatedSchema`.

`config/inference.yaml` — SGLang server URL, model paths, quantization settings, complexity routing thresholds.

---

## SGLang Server

Mercer relies on SGLang's RadixAttention for prefix caching. In Text2SQL, the schema context (often 2–8K tokens) is identical across all queries for the same database session. RadixAttention caches this shared prefix in GPU memory, reducing effective prompt processing to near-zero for subsequent queries.

Start command for RTX 4070 (FP8, 8GB VRAM):

```bash
python -m sglang.launch_server \
  --model-path Qwen/Qwen2.5-Coder-7B-Instruct \
  --dtype bfloat16 \
  --quantization fp8 \
  --enable-cuda-graph \
  --enable-flashinfer \
  --mem-fraction-static 0.88 \
  --context-length 16384 \
  --port 30000
```

Multi-candidate generation (Stage 4) sends 3 prompts via `generate_batch()`. SGLang batches them on the server, so wall time ≈ single generation latency.

---

## Audit & Logging

Every pipeline run produces an `AuditEntry` written to the audit log (structured JSON via `structlog`). Fields: question, final SQL, tables used, columns used, model tier used, correction steps taken, total latency, user ID (if authenticated).

The audit log is append-only. Never delete entries. Use it for debugging, regression detection, and eventually for building a few-shot example corpus from successful queries.
