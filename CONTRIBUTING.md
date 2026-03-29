# Contributing to Mercer

## Development Setup

```bash
git clone https://github.com/baselanaya/mercer.git
cd mercer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add your ANTHROPIC_API_KEY and DATABASE_URL
```

Start the test databases (optional — unit tests use in-memory SQLite):

```bash
docker compose -f docker/docker-compose.yml up -d postgres redis
```

---

## Running Tests

```bash
# All unit tests (no external services required)
.venv/bin/pytest tests/ -v

# Single test file
.venv/bin/pytest tests/test_pipeline.py -v

# With coverage
.venv/bin/pytest tests/ --cov=. --cov-report=term-missing
```

Tests must pass without a real database — all external dependencies are mocked. GPU kernels are tested via CPU fallback paths.

---

## Running the Benchmark Suite

```bash
# Regression suite (5 queries, DVDRental, quick smoke test)
.venv/bin/python scripts/benchmark.py --suite regression

# Messy schema suite (10 queries, abbreviated column names)
.venv/bin/python scripts/benchmark.py --suite mercer_messy

# BIRD Mini-Dev (requires PostgreSQL with BIRD data loaded)
.venv/bin/python scripts/benchmark.py --suite bird --db-url "$DATABASE_URL"

# Print aggregate metrics from the audit log
.venv/bin/python scripts/benchmark.py --report
```

---

## Code Rules

- **Async by default.** All I/O uses `async/await`. Use `asyncio.gather()` for concurrent operations.
- **Pydantic for all data models.** No raw dicts crossing module boundaries. Define schemas in `core/models.py`.
- **Prompts live in `prompts/`.** Never inline prompt strings in pipeline code. Import from the prompts module.
- **One file per pipeline stage.** Keep stages independently testable.
- **No LangChain or LlamaIndex.** Custom pipeline only.
- **`db/sandbox.py` is the only path to DB execution.** Never call `engine.execute()` directly from pipeline code.
- **LLM prompts must never include raw row data.** Pass only schema metadata and at most 3 sample values.
- **Every public function must have a docstring** (one line is fine for simple helpers).

---

## PR Checklist

Before opening a pull request, run all of the following and ensure zero failures:

```bash
# 1. Lint — zero warnings
.venv/bin/ruff check .

# 2. Type checking — zero errors
.venv/bin/mypy .

# 3. Unit tests — all pass
.venv/bin/pytest tests/ -v

# 4. Regression suite — 5/5 pass
.venv/bin/python scripts/benchmark.py --suite regression
```

Additionally:

- [ ] New modules have a corresponding `tests/test_<module>.py`
- [ ] New public functions have a docstring
- [ ] Pipeline-affecting changes include accuracy numbers before and after
- [ ] Prompt changes create a new versioned file (`_v2`, `_v3`) rather than editing in place
- [ ] No new `# type: ignore` without a comment explaining why
- [ ] `CHANGELOG.md` updated with a one-line entry under the appropriate version

---

## Contribution Areas

High-value areas where contributions are especially welcome:

- **Database connectors** — BigQuery, Snowflake, SQL Server, Databricks
- **Messy-schema test cases** — more real-world messy schemas for the benchmark suite
- **FK graph traversal** — better join path discovery for complex multi-hop joins
- **Correction strategies** — alternative taxonomy-guided correction approaches
- **Data catalog integrations** — Amundsen, DataHub, OpenMetadata
- **Streaming inference** — token-level streaming from SGLang to the WebSocket endpoint

---

## Commit Style

Use conventional commit prefixes:

- `feat:` — new feature or pipeline stage capability
- `fix:` — bug fix
- `perf:` — performance improvement (latency, accuracy)
- `test:` — test additions or fixes
- `docs:` — documentation only
- `refactor:` — internal restructure with no behavior change
- `chore:` — dependency updates, build config, CI

Example: `feat: add Cohere backend with native batch generation`
