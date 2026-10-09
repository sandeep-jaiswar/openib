# ADR 0002 — Single node, columnar, before any cluster

**Status:** accepted · **Date:** 2026-10-09

## Context

"Investment bank data platform" invites a reflexive reach for Spark, Kafka and
a cluster. The actual data volume here is the SEC full-text corpus, the GLEIF
golden copy, and a few thousand economic series — tens of gigabytes of
structured facts, not petabytes.

## Decision

Single node first, deliberately. Apache Arrow in memory, Apache Parquet on
disk, Apache Iceberg for table semantics, DataFusion embedded and DuckDB for
interactive work. Target box: 8 cores, 32 GB, Ubuntu 24.04. Must still complete
on 16 GB — slower, byte-identical output.

Spark, Flink and Kafka are documented escape hatches, reachable if a workload
genuinely outgrows one machine.

## Consequences

Vectorised columnar execution on one box is faster than a small cluster at this
volume, because there is no shuffle and no serialisation across the wire. It is
also *far* easier to make deterministic: no scheduler nondeterminism, no
partition-count-dependent output, no speculative execution writing a different
file.

What we give up: a workload that genuinely needs 100 cores will need a rewrite
of the compute layer rather than a config change. We accept that, and ADR 0002
is where we will look when it happens.
