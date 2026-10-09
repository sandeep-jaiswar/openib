# ADR 0006 — Canonical JSONL as the P0 sink, Parquet/Iceberg in P1

**Status:** accepted · **Date:** 2026-10-09 · **Supersede when:** the lakehouse sink lands

## Context

The target architecture is Iceberg tables of Parquet files with canonical
writer settings. But the property that actually has to be designed in on day
one is the *determinism contract*, not the file format — and pyarrow,
pyiceberg and duckdb are a package index away, which the acceptance gate for
ADR 0005 explicitly does not assume.

## Decision

P0 writes canonical sorted JSONL through a single function,
`canonical.write_table`, which owns the sort, the encoding and the hash. The
core pipeline therefore has **zero runtime dependencies** and runs on a box
with nothing installed but Python 3.11+.

Parquet/Iceberg is the P1 sink, and it is a replacement of
`canonical.write_table` — not a change to the contract above it.

## Consequences

The determinism guarantees (D4, D5) are expressed once, in one function, and
tested against a real pipeline run from the first commit. The golden-hash
harness has something real to hash before the lakehouse exists, so the
regression gate is live from day one rather than arriving with P1.

What this is **not**: JSONL is not fast, not columnar, and not compressed. It
will not meet the performance targets in the plan — a full-universe screener
scan over JSONL is nowhere near a 1 s p95. Those targets are P1/P2 gates
against the Parquet sink and should not be quoted against this one.

The Data Platform Engineer owns the swap. The acceptance test for it is that
the golden hashes change exactly once, in a reviewed commit, and then never
again.
