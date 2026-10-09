# ADR 0001 — Record architecture decisions

**Status:** accepted · **Date:** 2026-10-09

## Context

This project makes a handful of choices that look arbitrary from the outside
and are not: single node before cluster, bitemporality on day one, rule-based
identity resolution, stdlib before Parquet. Each will be questioned by the next
person to read the code, including us in six months.

## Decision

Architecture decisions are recorded here as short numbered documents. An ADR
states the context, the decision, and — most importantly — what we gave up.
ADRs are immutable once accepted; a reversal is a new ADR that supersedes the
old one, so the reasoning trail survives the reversal.

The CTO / Chief Architect owns the review gate on ADRs and on every PR that
touches the determinism contract.

## Consequences

A new contributor can find out *why* in one place. The cost is the discipline
of writing one when a decision is load-bearing — which is a cost worth paying
roughly a dozen times a year, not a hundred.
