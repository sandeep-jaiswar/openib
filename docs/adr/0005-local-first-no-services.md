# ADR 0005 — Local-first: no services in the core path

**Status:** accepted · **Date:** 2026-10-09

## Context

The reflexive architecture for this system is Airflow on Postgres, object
storage, a catalog service and a warehouse. That is five long-running services
before a single number is computed, and it means nobody can try the project
without an afternoon of setup — including us.

## Decision

The core pipeline is one CLI: `ob run`, `ob rebuild`, `ob verify`, `ob query`.
No Postgres, no Kafka, no object store, no credentials, and no network access
outside the explicit fetch step. Storage is the filesystem.

Airflow and Superset live behind optional compose profiles. The governing rule:
**Airflow only ever shells out to `ob run`.** It may not import the pipeline,
hold state about it, or split it into per-task operators.

The acceptance gate: a clean Ubuntu 24.04 VM can do
`git clone && make bootstrap && make daily` and end up with a queryable
warehouse, with no further input. This runs as a CI job on an `ubuntu-24.04`
runner so it cannot silently rot.

## Consequences

That one rule about Airflow is what makes the rest hold. Because the scheduler
only shells out, the pipeline can be tested without it, a cron entry on a
laptop reproduces CI exactly, and determinism stays reachable — scheduler
retries cannot produce partial state, because the unit of work is the whole
command.

What we give up: no per-task retries or fine-grained Airflow observability for
free, and a long backfill is one long process rather than a parallel DAG. Both
are recoverable at the CLI level (`--date`, `rebuild --since`) without
reintroducing the dependency.
