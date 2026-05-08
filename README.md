<div align="center">

![Mercer](banner.svg)

[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-D97757?style=flat-square)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/baselanaya/Mercer/ci.yml?branch=master&style=flat-square&label=CI)](https://github.com/baselanaya/Mercer/actions/workflows/ci.yml)
[![Exec Accuracy](https://img.shields.io/badge/exec_accuracy-74%25-22c55e?style=flat-square)](#evaluation)
[![llama.cpp](https://img.shields.io/badge/llama.cpp-local_GPU-D97757?style=flat-square)](https://github.com/ggerganov/llama.cpp)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)

</div>

---

Mercer converts plain English questions into accurate SQL against production schemas — including the messy ones with cryptic abbreviations (`cust_seg_cd`, `e_add`, `p_spec`), missing foreign keys, legacy denormalization, and inconsistent naming. It runs a 6-stage agentic pipeline entirely on a consumer GPU (8 GB VRAM) with no vector database required.

---

## How It Works

Each question passes through six stages before a SQL query is returned:

1. **Entity Retrieval** — BM25 + GPU-accelerated LSH matches natural language terms against actual column values and a business glossary
2. **Schema Linking** — 3-step CHESS-inspired linker: column pre-filter → table selection → final column selection
3. **Query Decomposition** — Breaks complex questions into subproblems with a chain-of-thought reasoning plan
4. **Candidate Generation** — Three SQL strategies run in parallel (direct CoT, divide-and-conquer, plan-execute)
5. **Execution + Selection** — All candidates execute against the real database; the best result is selected by consistency scoring
6. **Taxonomy Correction** — Classifies and fixes errors by type: schema errors, join errors, filter errors, aggregation errors, syntax errors, logic errors

---

## Key Design Decisions

**No vector database.** Schema navigation uses BM25 + LSH + LLM reasoning. Vector RAG is opt-in for glossary only.

**Multi-candidate selection.** Three SQL queries are generated with different strategies, all executed, and the best is picked. One-shot generation produces worse results on messy schemas.

**Local-first inference.** llama.cpp with GGUF IQ4_XS quantization + q8_0 KV cache (TurboQuant profile) runs Qwen2.5-Coder-7B fully on an RTX 4070 (8 GB). Cloud API (Anthropic/OpenAI) is an optional fallback.

**Read-only sandbox.** The LLM never sees raw row data. All execution goes through a sandboxed layer with blocked DDL/DML, 5-second timeout, and 100-row limit.

---

## Quick Start

**Prerequisites:** Python 3.11+, Redis, Node.js 18+ (for the UI)

```bash
git clone https://github.com/baselanaya/mercer.git
cd mercer

# Install Python dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
DATABASE_URL=sqlite+aiosqlite:///data/chinook/Chinook.sqlite  # or your database
INFERENCE_BACKEND=anthropic                                    # or llamacpp / openai
ANTHROPIC_API_KEY=sk-ant-...
```

Start the server:

```bash
uvicorn app.api.main:app --port 8000
```

Open `http://localhost:8000` — the API is live. For the full UI, see [Usage → UI](#ui-development-server) below.

---

## Usage

### Local GPU (llama.cpp)

Requires CUDA 12.4+ and ~5.6 GB VRAM. Tested on RTX 4070 Laptop.

```bash
# Install GPU stack
pip install -r requirements-gpu.txt

# Download the model
pip install huggingface-hub
huggingface-cli download bartowski/Qwen2.5-Coder-7B-Instruct-GGUF \
  Qwen2.5-Coder-7B-Instruct-IQ4_XS.gguf --local-dir models/

# Start the inference server (TurboQuant: IQ4_XS weights + q8_0 KV cache)
bash scripts/serve_llamacpp_turboquant.sh
```

The server starts on `http://localhost:8080` (OpenAI-compatible API). Set in `.env`:

```bash
INFERENCE_BACKEND=llamacpp
LLAMACPP_URL=http://localhost:8080
```

### Cloud API

Set the appropriate key and backend in `.env`:

```bash
# Anthropic
INFERENCE_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
INFERENCE_BACKEND=openai
OPENAI_API_KEY=sk-proj-...
```

No model download required. Start the server normally:

```bash
uvicorn app.api.main:app --port 8000
```

### API Server

```bash
# Start (production)
uvicorn app.api.main:app --port 8000

# Start (development, auto-reload)
uvicorn app.api.main:app --reload --port 8000
```

### REST API

```bash
# Run a query
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Top 5 customers by total spend"}'

# Get schema-aware suggested questions
curl http://localhost:8000/suggest

# Health check
curl http://localhost:8000/health
```

### WebSocket (Streaming)

Connect to `/ws/query` to receive pipeline progress in real time:

```
Client → {"question": "How many tracks are in each genre?"}

Server → {"type": "started",        "question": "..."}
Server → {"type": "stage_complete", "stage": "entity_retrieval",    "latency_ms": 9}
Server → {"type": "stage_complete", "stage": "schema_linking",      "latency_ms": 3700}
Server → {"type": "stage_complete", "stage": "query_decomposition", "latency_ms": 4000}
Server → {"type": "stage_complete", "stage": "candidate_generation","latency_ms": 5000}
Server → {"type": "stage_complete", "stage": "execution_scoring",   "latency_ms": 7}
Server → {"type": "stage_complete", "stage": "correction",          "latency_ms": 0}
Server → {"type": "complete",       "sql": "SELECT ...", "execution_result": {...}, "latency_ms": 12722}
```

### UI Development Server

The chat interface is a separate Vite + React app that proxies to the API backend:

```bash
cd app/ui
npm install
npm run dev        # starts on http://localhost:5173
```

The UI proxies `/api`, `/query`, `/ws`, `/suggest`, `/schema`, `/health`, and `/setup` to `localhost:8000`.

### Ingesting a Schema

Preload the schema graph and entity index for faster queries:

```bash
python scripts/ingest_schema.py --db-url $DATABASE_URL
```

This caches the full schema in Redis and pre-builds the BM25/LSH entity indices.

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy async connection string | — |
| `REDIS_URL` | Redis for schema cache | `redis://localhost:6379/0` |
| `INFERENCE_BACKEND` | `llamacpp` \| `anthropic` \| `openai` \| `ollama` | `llamacpp` |
| `LLAMACPP_URL` | llama.cpp server URL | `http://localhost:8080` |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | `INFO` |

Connection string examples:

```bash
# SQLite
DATABASE_URL=sqlite+aiosqlite:///path/to/database.db

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/mydb

# MySQL
DATABASE_URL=mysql+aiomysql://user:password@localhost:3306/mydb
```

### Messy Schema Annotations

Add semantic context for cryptic column names in `config/mappings.yaml`:

```yaml
tables:
  cust_mstr:
    description: "Main customer master table"
    columns:
      cust_seg_cd: "Customer segment code (RETAIL, CORP, SMB)"
      e_add:       "Employee address — legacy field, rarely populated"
      p_spec:      "Product specialization code"

  ord_hdr:
    description: "Order header — one row per order"
    columns:
      ord_dt:   "Order date"
      cust_fk:  "Foreign key to cust_mstr.cust_id"
      tot_amt:  "Total order amount in USD"

glossary:
  revenue:  "SUM of ord_hdr.tot_amt"
  churn:    "Customers with no orders in the past 90 days"
  segment:  "cust_mstr.cust_seg_cd"
```

---

## Evaluation

Benchmarked with **Qwen2.5-Coder-7B-Instruct-Q4_K_M** on an RTX 4070 Laptop (8 GB VRAM) via llama.cpp.

### External Benchmark

| Dataset | Questions | Execution Accuracy | Exact Match |
|---|---|---|---|
| gretelai/synthetic_text_to_sql | 50 stratified | **74.0%** | **34.0%** |

Breakdown by SQL complexity:

| Complexity | Execution | Exact Match |
|---|---|---|
| Basic SQL | 6/8 (75%) | 3/8 (38%) |
| Aggregation | 7/8 (88%) | 5/8 (63%) |
| Single join | 6/8 (75%) | 3/8 (38%) |
| Subqueries | 3/7 (43%) | 1/7 (14%) |
| Window functions | 7/7 (100%) | 3/7 (43%) |
| Multiple joins | 4/6 (67%) | 1/6 (17%) |
| Set operations | 4/4 (100%) | 1/4 (25%) |
| CTEs | 0/2 | 0/2 |

5 of 50 questions were DDL/DML (`DELETE`/`INSERT`) — blocked by the read-only sandbox and counted as failures. These are outside scope for a read-only NL→SQL pipeline.

### Live Queries (Chinook Database)

| Question | Correct | Latency |
|---|---|---|
| How many customers are there? | ✓ (59) | 7.6s |
| Top 5 artists by album count | ✓ (Iron Maiden, 21) | 13.6s |
| Employee with most invoices + revenue | ✓ (Jane Peacock, $833) | 16.8s |
| Genres for artist with most tracks | ✓ (Rock, 1297 tracks) | 22.7s |

All four queries required zero correction steps.

### Running the Eval Suite

```bash
python scripts/benchmark.py --suite regression
python scripts/benchmark.py --suite mercer_messy
python eval/gretelai_eval.py
```

---

## Architecture

```
mercer/
├── core/
│   ├── pipeline.py              # 6-stage orchestrator
│   ├── entity_retriever.py      # Stage 1: LSH + BM25 + glossary
│   ├── schema_linker.py         # Stage 2: 3-step CHESS linker
│   ├── query_decomposer.py      # Stage 3: subproblem decomposition
│   ├── candidate_generator.py   # Stage 4: async multi-candidate
│   ├── executor.py              # Stage 5: execution + selection
│   └── corrector.py             # Stage 6: taxonomy-guided correction
│
├── kernels/                     # Triton GPU kernels
│   ├── lsh_hash.py              # Batch LSH for entity matching
│   ├── schema_encode.py         # Batch schema tokenization
│   └── result_score.py          # Result consistency scoring
│
├── inference/                   # LLM backend abstraction
│   ├── llamacpp_backend.py      # llama.cpp async client
│   ├── api_backend.py           # Anthropic / OpenAI client
│   └── router.py                # Complexity-based model routing
│
├── schema/
│   ├── introspector.py          # SQLAlchemy schema introspection
│   ├── semantic_mapper.py       # Glossary + column description injection
│   ├── graph_builder.py         # FK graph (networkx)
│   └── cache.py                 # Redis schema cache
│
├── db/
│   ├── connectors/              # PostgreSQL, MySQL, SQLite, DuckDB
│   ├── sandbox.py               # Read-only execution sandbox
│   └── explain.py               # EXPLAIN / dry-run abstraction
│
├── app/
│   ├── api/                     # FastAPI + WebSocket streaming
│   └── ui/                      # React + TailwindCSS chat UI
│
├── prompts/                     # All LLM prompts, versioned
├── eval/                        # Benchmark runners
├── config/                      # mappings.yaml, inference.yaml
└── data/                        # Chinook, DVDRental, Northwind test databases
```

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| API backend | FastAPI + uvicorn |
| Frontend | React 19 + TailwindCSS v4 + Vite |
| LLM serving (local) | llama.cpp (GGUF, IQ4_XS + q8_0 KV) |
| Local model | Qwen2.5-Coder-7B-Instruct |
| API fallback | Claude claude-sonnet-4-6 / GPT-4.1 |
| GPU kernels | Triton |
| DB abstraction | SQLAlchemy 2.0 (async) |
| Schema graph | networkx |
| Entity retrieval | rank-bm25 + custom GPU LSH |
| Cache | Redis (schema) + DuckDB (audit log) |
| Databases supported | PostgreSQL, MySQL, SQLite, DuckDB |

---

## Research Foundation

| Paper | Contribution | Pipeline Stage |
|---|---|---|
| CHESS (Talaei et al. 2024) | 3-step schema linking + LSH entity retrieval | Stage 2 |
| SQL-of-Thought (2025) | Taxonomy-guided error correction | Stage 6 |
| CHASE-SQL (ICLR 2025) | Multi-path candidate generation + selection | Stage 4 |
| Qwen2.5-Coder (Alibaba 2024) | Code-specialized base model | Local inference |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). High-value areas:

- Additional database connectors (BigQuery, Snowflake, SQL Server)
- Improved messy-schema test cases
- Better FK graph traversal for complex join paths
- Data catalog integrations (Amundsen, DataHub, OpenMetadata)

---

## License

MIT — see [LICENSE](LICENSE).
