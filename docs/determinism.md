# The determinism contract

Six rules. They are the reason this project exists in the shape it does, and
each one is a test in `tests/test_determinism.py` rather than an aspiration in
a document.

The thing we are protecting is this: **re-running any past date must produce
the same bytes, and asking "what did 2024 look like?" must give 2024's answer,
not today's.** A financial information product that cannot do this is a
snapshot, not a record.

## D1 — Raw immutability

Every fetch writes content-addressed bytes into `data/raw/<ab>/<sha256>` plus a
manifest in `data/manifests/<date>/<source>.json` recording the URL, the
SHA-256, the byte count and the source version.

Transforms read manifests. **Transforms never touch the network.** This is
enforced statically: `tests/test_determinism.py` parses `warehouse.py` and
fails if it imports `urllib`, `socket`, `os`, `time` or `random`, because a
runtime test can never prove the absence of a network call.

The landing zone is append-only by construction — a filename *is* its hash, so
a document that has been fetched before cannot be overwritten with different
bytes. `load_blob` re-hashes on read and refuses a mismatch, so tampering
surfaces as a build failure rather than as quietly wrong numbers.

## D2 — Bitemporality

Every fact carries two time axes:

| Axis | Meaning |
|---|---|
| `valid_from` / `valid_to` | the period the fact is *about* |
| `knowledge_time` | when the fact became *knowable* |

`knowledge_time` comes from the source document — for an SEC fact, the `filed`
date of the accession that reported it. It is never the wall clock.

This is what makes a restatement non-destructive. The fixture contains a real
example: FY2024 revenue was first reported as `391035000000` in a 10-K filed
2024-11-01, then restated to `390912000000` in a 10-K/A filed 2026-02-17. Both
rows are retained, so:

```console
$ ob query --as-of 2025-06-30 --concept Revenues
cik:0000320193  Revenues  2023-10-01..2024-09-28  391035000000 USD  (knew 2024-11-01, 0000320193-24-000081)

$ ob query --as-of 2026-10-09 --concept Revenues
cik:0000320193  Revenues  2023-10-01..2024-09-28  390912000000 USD  (knew 2026-02-17, 0000320193-26-000014)
```

Both answers are correct. The first is what anyone could have known in June
2025; the second is what we know now. A system that stores only the current
value destroys the first answer permanently and cannot tell you that it did.

This is the one property that is genuinely painful to retrofit — it changes
every primary key — which is why it lands on day one and not in P3.

## D3 — Pinned inputs

Each run writes a receipt to `data/runs/<date>.json` pinning the git SHA, the
ontology version, every source version, and the SHA-256 of every landed blob
and every output table. The receipt is the answer to "where did this number
come from", before anyone has to ask.

## D4 — No ambient nondeterminism

Inside a transform there is no wall clock, no environment, no hostname, no
locale and no unseeded RNG. The logical date is injected as an argument. The
single permitted clock read is at the CLI boundary, where `--date` defaults to
today.

Two consequences worth stating plainly:

- **`fetched_at` is provenance, not data.** It is recorded in the manifest and
  nothing downstream may read it. There is a test that runs the pipeline twice
  with `fetched_at` values five years apart and asserts the warehouse hashes
  are identical.
- **Money and quantities are fixed-point decimal, never binary float.** The
  canonical encoder *refuses* to serialise a float — `canonical.dumps({"v":
  0.1 + 0.2})` raises. Values arrive as `Decimal` and are written as their
  exact decimal string.

Every output table declares an explicit total sort order, because dict
iteration, filesystem order and set order are all unstable across runs and
versions.

## D5 — Byte-reproducible outputs

Re-running any past date reproduces an identical SHA-256 per table. Golden
hashes live in `tests/golden/` and are checked by `ob verify` locally and by CI
on every push. A drifting hash is a build failure, not a conversation.

CI additionally runs the same date on two different runner images and asserts
the hashes match. If something ambient leaks into a transform, that job is how
we find out, rather than discovering it a year later.

## D6 — Full lineage

Every published fact carries the `provenance_sha256` of the raw document it was
extracted from, so any number traces back to bytes we still hold. A test
asserts that every fact's provenance hash corresponds to a blob actually in
the landing zone.

---

## What is deliberately *not* promised yet

Honesty about the current state, so nobody over-reads the contract:

- **Parquet/Iceberg canonical writer settings.** D5 is currently enforced over
  canonical JSONL, not Parquet. The byte-level guarantee lives in
  `canonical.write_table`, so swapping the sink is a sink change — but the
  fixed row-group size, sorted-by-construction and no-creation-timestamp
  settings that make *Parquet* byte-reproducible are P1 work. See
  [ADR 0006](adr/0006-jsonl-sink-before-parquet.md).
- **Dependency-lock digest in the receipt.** `pyproject.toml` has no runtime
  dependencies yet, so there is nothing to pin. When the lakehouse extras
  become required, the lock digest joins the receipt.
- **Rate-limited, resumable fetching.** The P0 fetcher is a single
  `urllib.urlopen` per endpoint with no retry, backoff or per-source rate
  limit. Fine for a smoke test, not fine for the SEC's 10 req/s limit or for
  the GLEIF golden copy. P1.
