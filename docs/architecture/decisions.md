# Decision log

One row per decision. Revisit a row when its "revisit when" condition happens.

| ID | Date | Decision | Alternatives | Why | Trade-off | Revisit when |
|---|---|---|---|---|---|---|
| 001 | 2026-11-11 | Separate repo `arcaence-online` as the base project | Keep inside `arcaence-labs` | Later layers (evals, security, governance, AWS) build on one codebase | Early proof commits stay in `arcaence-labs` | Never expected |
| 002 | 2026-11-11 | RAG is a fixed workflow, not an agent | Agentic retrieval loop | Predictable, testable, cheaper; agents only where they earn it (the desk) | Less flexible on odd questions | Golden set shows retrieval misses a loop would fix |
| 003 | 2026-11-11 | Postgres with pgvector in Supabase | Dedicated vector database | One store for vectors, metadata filters, customer tables and row-level security | Less tuning headroom at large scale | Corpus grows past what one Postgres handles well |
| 004 | 2026-11-11 | Index every document with a `status`; filter at retrieval | Index approved documents only | Tests can run with the filter on and off to show which control catches which trap | Bad chunks sit in the database, so the filter must be tested | Never expected |
| 005 | 2026-11-11 | Local embeddings with fastembed | Hosted embedding API; sentence-transformers | No per-call cost, runs offline, no PyTorch install | Smaller model, lower quality ceiling | Retrieval recall is the bottleneck |
| 006 | 2026-11-11 | Stable semantic clause IDs via a registry | Cite raw section numbers | Numbers shift between v2 and v3 (downgrades is 3.6 then 3.7) | Registry must be maintained | Never expected |
| 007 | 2026-11-11 | Supabase session pooler connection | Direct connection | Direct is IPv6 only on the free plan | Pooler has its own limits | Moving to a paid plan or AWS |
| 008 | 2026-11-11 | Golden set and traps written before code | Write tests after the pipeline | Prevents grading our own homework | Some questions will need revising | Phase 3 expands the set |