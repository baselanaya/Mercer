<div align="center">

# Mercer

**Natural Language → SQL for Real-World Databases**

*Structure-first · Agentic · GPU-accelerated*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![BIRD Benchmark](https://img.shields.io/badge/BIRD-65%25%2B%20target-green.svg)](#evaluation)

</div>

---

Mercer converts plain English questions into accurate SQL — even when the underlying schema is a mess of cryptic abbreviations (`cust_seg_cd`, `e_add`, `p_spec`), missing foreign keys, legacy denormalization, and inconsistent naming. Built for mid-size production environments where schemas evolve constantly and precision matters more than approximate similarity.

```
"Show top 10 customers by total spend last quarter"

  → Stage 1  Entity & glossary retrieval
  → Stage 2  3-step schema linking (CHESS)
  → Stage 3  Query decomposition + CoT plan
  → Stage 4  3× parallel SQL candidates (async)
  → Stage 5  Execution + best-candidate selection
  → Stage 6  Taxonomy-guided error correction

SELECT c.customer_id, c.full_name, SUM(o.total_amount) AS total_spend
FROM cust_mstr c
JOIN ord_hdr o ON c.cust_id = o.cust_fk
WHERE o.ord_dt >= DATE_TRUNC('quarter', NOW() - INTERVAL '1 quarter')
  AND o.ord_dt <  DATE_TRUNC('quarter', NOW())
GROUP BY c.customer_id, c.full_name
ORDER BY total_spend DESC
LIMIT 10;
```

---

## Features

**Schema intelligence**
- 3-step CHESS-inspired schema linking: column pre-filter → table selection → final column selection
- Semantic mapping layer: business glossary, column descriptions, abbreviation expansion
- FK relationship graph for automatic join path discovery
- GPU-accelerated LSH entity matching against millions of DB values

**Agentic pipeline**
- Multi-candidate generation: 3 strategies executed in parallel (direct CoT, divide-and-conquer, plan-execute)
- Execution-based candidate selection with result consistency scoring
- Taxonomy-guided error correction (schema errors, join errors, filter errors, logic errors)
- Stepwise reasoning trace for every query

**GPU-first inference**
- SGLang backend with RadixAttention for prefix caching (shared schema context = massive speedup)
- FlashInfer CUDA kernels for inter-token latency reduction
- FP8 quantization support for RTX 4070 local development
- Model router: 7B local → 32B cloud → frontier API based on query complexity

**Production safety**
- LLM sees only schema metadata, never raw row data
- Read-only sandboxed execution with statement timeout
- Blocked DDL/DML keywords, max row limits
- Structured audit log for every query

---

## Architecture

```
mercer/
├── core/
│   ├── pipeline.py              # 6-stage orchestrator
│   ├── entity_retriever.py      # Stage 1: LSH + BM25 + glossary
│   ├── schema_linker.py         # Stage 2: 3-step CHESS linker
│   ├── query_decomposer.py      # Stage 3: subproblem decomposition + CoT
│   ├── candidate_generator.py   # Stage 4: async multi-candidate generation
│   ├── executor.py              # Stage 5: dry-run + candidate selection
│   └── corrector.py             # Stage 6: taxonomy-guided correction
│
├── kernels/                     # GPU-accelerated kernels (Triton)
│   ├── lsh_hash.py              # Batch LSH for entity matching
│   ├── schema_encode.py         # Batch schema tokenization
│   └── result_score.py          # Result consistency scoring
│
├── inference/                   # LLM serving abstraction
│   ├── sglang_backend.py        # SGLang async client
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
│   ├── api/                     # FastAPI backend + WebSocket streaming
│   └── ui/                      # React + TailwindCSS chat interface
│
├── prompts/                     # All LLM prompts, versioned
├── eval/                        # BIRD, Spider 2.0, messy-schema benchmarks
├── config/                      # mappings.yaml, inference.yaml
├── data/                        # DVDRental, Northwind, Chinook + messy variants
└── docker/                      # docker-compose.yml, Dockerfiles
```

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| LLM serving (local) | SGLang + FlashInfer + CUDA Graphs |
| Local model | Qwen2.5-Coder-7B-Instruct (FP8, RTX 4070) |
| Cloud model | Qwen2.5-Coder-32B-Instruct (A100) |
| API fallback | Claude claude-sonnet-4-6 / GPT-4o |
| GPU kernels | Triton (LSH, schema encode, result scoring) |
| DB abstraction | SQLAlchemy 2.0 |
| Schema graph | networkx |
| Entity retrieval | rank-bm25 + custom GPU LSH |
| Caching | Redis (schema) + DuckDB (query results) |
| API backend | FastAPI + uvicorn |
| Frontend | React + TailwindCSS |
| Quantization | bitsandbytes / AutoGPTQ (INT4, FP8) |

**No vector database required** for core functionality. Optional pgvector/Weaviate for supplementary glossary RAG.

---

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL (for test databases)
- NVIDIA GPU with CUDA 12.4+ (optional but recommended)

### 1. Clone

```bash
git clone https://github.com/baselanaya/mercer.git
cd mercer
```

### 2. Install

```bash
# CPU-only (API mode)
pip install -r requirements.txt

# GPU stack (local model mode)
pip install -r requirements.txt -r requirements-gpu.txt
```

### 3. Configure

```bash
cp .env.example .env
# Set ANTHROPIC_API_KEY or OPENAI_API_KEY for API mode
# Set DATABASE_URL for your target database
```

### 4. Load a test database

```bash
# PostgreSQL DVDRental (recommended for first run)
createdb mercer_test
psql mercer_test -f data/dvdrental/dvdrental.sql

# Or use Docker
docker compose -f docker/docker-compose.yml up postgres redis
```

### 5. Run

```bash
# With Docker (recommended — starts DB + Redis + SGLang + app)
docker compose -f docker/docker-compose.yml up

# Or manually
uvicorn app.api.main:app --reload --port 8000
```

Open `http://localhost:8000` and start querying.

---

## Local GPU Setup (RTX 4070)

Start the SGLang inference server before running Mercer:

```bash
# Qwen2.5-Coder-7B in FP8 — fits in 8GB VRAM
python -m sglang.launch_server \
  --model-path Qwen/Qwen2.5-Coder-7B-Instruct \
  --dtype bfloat16 \
  --quantization fp8 \
  --enable-cuda-graph \
  --enable-flashinfer \
  --mem-fraction-static 0.88 \
  --port 30000
```

Then set `INFERENCE_BACKEND=sglang` in your `.env`.

---

## Messy Schema Configuration

Mercer's differentiator. Add semantic context for your messy schema:

```yaml
# config/mappings.yaml
tables:
  cust_mstr:
    description: "Main customer master table"
    columns:
      cust_seg_cd: "Customer segment code (e.g. RETAIL, CORP, SMB)"
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

Target benchmarks:

| Benchmark | Description | Target |
|---|---|---|
| BIRD Mini-Dev (500) | Cross-domain accuracy | > 65% EX |
| Spider 2.0 (600) | Enterprise workflow SQL | > 20% EX |
| DVDRental / Northwind | Clean baseline | > 85% EX |
| Mercer Messy Suite | Custom messy-schema test | > 70% EX |

Metrics: Execution Accuracy (EX), Reward-based VES (R-VES), Soft F1.

Run the eval suite:

```bash
python scripts/benchmark.py --suite bird --split mini_dev
python scripts/benchmark.py --suite mercer_messy
```

---

## Security

- LLM receives only schema metadata + mappings — never raw row data
- All execution goes through `ReadOnlySandbox`: blocked DDL/DML, 5s timeout, 100 row limit
- 3 sample rows max exposed to LLM during correction (never full result sets)
- Structured audit log per query: question, generated SQL, execution result, correction steps
- Optional read-only DB role enforcement at connection level

---

## Research Foundation

| Paper | Contribution | Used In |
|---|---|---|
| CHESS (Talaei et al. 2024) | 3-step schema linking + LSH entity retrieval | Stage 2 |
| SQL-of-Thought (2025) | Taxonomy-guided CoT error correction | Stage 6 |
| CHASE-SQL (ICLR 2025) | Multi-path candidate generation + selection | Stage 4 |
| Arctic/ExCoT (Snowflake 2025) | SOTA open-weight SQL model benchmark | Model choice |
| Qwen2.5-Coder (Alibaba 2024) | Code-specialized base model | Local inference |
| FlashInfer (2025) | Custom CUDA attention kernels | GPU stack |
| SGLang RadixAttention | Prefix cache for shared-prompt workloads | Inference backend |

---

## Contributing

Mercer is actively developed. High-value contribution areas:

- Additional database connectors (BigQuery, Snowflake, SQL Server)
- Improved messy-schema test cases (the benchmark matters)
- Better FK graph traversal for complex join paths
- Alternative agentic correction strategies
- Data catalog integrations (Amundsen, DataHub, OpenMetadata)

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## License

MIT — see [LICENSE](LICENSE).

---

*Built for real databases — not just clean benchmarks.*
*Maximlabs · Basel Anaya*
