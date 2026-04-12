---
name: Bug report
about: Report a bug or incorrect behavior in Mercer
title: "[BUG] "
labels: bug
assignees: ''
---

## Describe the bug

A clear description of what is wrong and what you expected to happen.

## Steps to reproduce

1. Question asked: `"..."`
2. Database type: PostgreSQL / MySQL / SQLite / DuckDB
3. Inference backend: `llamacpp` / `anthropic` / `openai`
4. Command or request: `...`

## Actual behavior

Paste the full response, error message, or generated SQL here.

```
<paste here>
```

## Expected behavior

What should have happened instead.

## Reasoning trace

If this is a wrong SQL issue, paste the `reasoning_trace` from the `/query` response:

```json
<paste reasoning_trace here>
```

## Environment

- OS: [e.g. Ubuntu 22.04]
- Python version: [e.g. 3.11.8]
- Mercer version / git hash: [e.g. v0.4.0 / abc1234]
- GPU: [e.g. RTX 4070 / none]
- llama-cpp-python version (if using local model): [e.g. 0.3.4]

## Relevant schema

If the bug is schema-related, paste the relevant portion of your `config/mappings.yaml`:

```yaml
<paste here>
```

## Additional context

Any other context that might help diagnose the issue.
