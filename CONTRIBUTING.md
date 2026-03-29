# Contributing to Mercer

## Development Setup

```bash
git clone https://github.com/baselanaya/mercer.git
cd mercer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add your ANTHROPIC_API_KEY
```

Start the test databases:

```bash
docker compose -f docker/docker-compose.yml up -d
```

## Code Rules

- **Async by default.** All I/O uses `async/await`. Use `asyncio.gather()` for concurrent operations.
- **Pydantic for all data models.** No raw dicts crossing module boundaries. Schemas go in `core/models.py`.
- **Prompts live in `prompts/`.** Never inline prompt strings in pipeline code.
- **One file per pipeline stage.** Keep stages independently testable.
- **No LangChain or LlamaIndex.** Custom pipeline only.
- **`db/sandbox.py` is the only path to DB execution.** Never call `engine.execute()` directly from pipeline code.
- **LLM prompts must never include raw row data.** Pass only schema metadata and at most 3 sample values.

## Running Tests

```bash
pytest tests/ -v
```

Tests must pass without a real database (mock all external calls). GPU kernels are tested via CPU fallback paths only.

## Before Every Commit

```bash
ruff check .
mypy .
python eval/regression_suite.py
```

## Contribution Areas

- Additional database connectors (BigQuery, Snowflake, SQL Server)
- Improved messy-schema test cases
- Better FK graph traversal for complex join paths
- Alternative agentic correction strategies
- Data catalog integrations (Amundsen, DataHub, OpenMetadata)

## Pull Request Guidelines

- Target `main`. One logical change per PR.
- Include or update tests for any new module.
- Never break the regression suite (20 labelled queries in `eval/`).
- Benchmark-sensitive changes (schema linker, corrector, candidate generator) must include accuracy numbers before and after.
- Version prompt changes: append `_v2`, `_v3` to the filename rather than editing in place.
