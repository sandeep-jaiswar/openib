# ADR 0003 — Bitemporality on day one

**Status:** accepted · **Date:** 2026-10-09

## Context

Public financial facts change after publication. A 10-K is restated; an
economic series is revised; an LEI record is corrected. The naive load —
upsert on (issuer, concept, period) — silently replaces history and leaves no
trace that it did.

An earlier draft of this plan justified bitemporality as avoiding lookahead
bias in a backtester. The backtester has since been cut (see
[non-goals](../non-goals.md)), so that argument no longer applies and the
honest one is plainer.

## Decision

Every fact carries `valid_from`/`valid_to` (the period it is about) and
`knowledge_time` (when it became knowable, taken from the source document's
filing date). `knowledge_time` is part of the primary key, so a restatement
inserts rather than overwrites.

## Consequences

The real argument: **a 10-K restated in 2027 must not silently rewrite what
2024 looked like.** "As we knew it on date X" is what makes the information
auditable rather than merely current. Without it, two people running the same
query a year apart get different answers and neither can tell why.

This is also the hardest property to retrofit, because it changes every primary
key and every join in the warehouse. Retrofitting it in P3 would be a rewrite.

Costs we accept: every fact table is larger, every query must either specify a
knowledge date or accept "latest", and `as_of` logic has to be right or the
whole guarantee is theatre. That last one is why it has dedicated tests.
