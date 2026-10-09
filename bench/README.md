# Benchmarks (P1)

The performance targets from the build plan, to be wired as CI regression gates
on an 8-core / 32 GB Ubuntu box. These are gates, not aspirations: a PR that
regresses one fails.

| Operation | Target |
|---|---|
| Daily incremental run | < 10 min wall clock |
| Cold full rebuild, all history | < 2 h |
| Ontology point query (issuer + all linked objects) | p95 < 50 ms |
| Issuer profile assembly (20y history, all links) | p95 < 200 ms |
| Screener scan (full equity universe, 20y fundamentals, 10 predicates) | p95 < 1 s |
| API cold start | < 2 s |

**These numbers are gates against the Parquet/Arrow/DataFusion stack, not
against the P0 JSONL sink.** A full-universe screener scan over JSONL is
nowhere near a 1 s p95, and nobody should quote these against the current
implementation — see [ADR 0006](../docs/adr/0006-jsonl-sink-before-parquet.md).

Profiling: Bloomberg memray for Python memory, criterion for Rust, flamegraph
for both.

Owner: Data Quality Engineer (the gates) with the Data Platform Engineer (the
performance).
