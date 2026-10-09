# ADR 0004 — Identity resolution is rule-based, never probabilistic

**Status:** accepted · **Date:** 2026-10-09

## Context

Resolving "is this filer the same company as this LEI record?" is the classic
entity-resolution problem, and the classic answer is a trained matcher over
name, address and jurisdiction similarity. That approach would resolve
noticeably more issuers than exact identifier matching.

## Decision

Deterministic crosswalks on public identifiers only: LEI for issuers (GLEIF),
FIGI for instruments (OpenFIGI), CIK for filers (SEC), MIC for venues, ISIN
where public. Explicit survivorship rules — currently LEI wins over CIK, and
`issuer_key` refuses to key an issuer with neither.

Ambiguous matches go to a review queue and are **never** auto-resolved by a
model.

## Consequences

A probabilistic matcher would make the pipeline irreproducible, which
contradicts the entire point of the determinism contract: the same inputs would
resolve differently after a model retrain, and nobody could explain why two
issuers merged. A model's score is also not a provenance trail.

What we give up: coverage. Issuers without an LEI, foreign private issuers, and
historical entities that predate LEI will stay unlinked until someone resolves
them by hand or a public crosswalk appears. That is a worse product on one axis
and a trustworthy one on the axis that matters here.
