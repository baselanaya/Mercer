---
name: Feature request
about: Suggest an improvement or new capability for Mercer
title: "[FEAT] "
labels: enhancement
assignees: ''
---

## Summary

One or two sentences describing the feature.

## Motivation

Why is this useful? Which use case does it address? Is there a workaround today?

## Proposed approach

How would you implement this? If you have a specific design in mind, describe it here.

## Which pipeline stage does this affect?

- [ ] Stage 1 — Entity retrieval (`core/entity_retriever.py`)
- [ ] Stage 2 — Schema linking (`core/schema_linker.py`)
- [ ] Stage 3 — Query decomposition (`core/query_decomposer.py`)
- [ ] Stage 4 — Candidate generation (`core/candidate_generator.py`)
- [ ] Stage 5 — Execution + selection (`core/executor.py`)
- [ ] Stage 6 — Error correction (`core/corrector.py`)
- [ ] Inference backend (`inference/`)
- [ ] Schema / mappings (`schema/`, `config/`)
- [ ] API / UI (`app/`)
- [ ] Benchmarking / eval (`eval/`, `scripts/`)
- [ ] Other

## Benchmark impact

Would this change affect benchmark accuracy? If so, which suite(s)?

- [ ] BIRD Mini-Dev
- [ ] Spider 2.0
- [ ] DVDRental / Northwind (regression)
- [ ] Mercer Messy Suite
- [ ] Not benchmark-sensitive

## Alternatives considered

Any alternative approaches you considered and why you ruled them out.

## Additional context

Links to papers, prior art, or related issues.
