# openib — Open Investment Bank

An open-source platform that pulls free public financial data every day,
resolves it into a Palantir-style ontology, and serves it fast and
reproducibly — so that a person can *understand* a company, a market, or an
economy.

It is an **information product**. There is no execution, no broker
connectivity, no portfolio, no P&L and no signals. What you do with the
information happens elsewhere. See [docs/non-goals.md](docs/non-goals.md).

> **Status: P0 scaffold.** The determinism contract, the ontology declaration,
> the source registry, the CLI and the golden-hash gate are real and tested
> end to end. The Iceberg/Parquet sink, the live source connectors beyond a
> smoke test, and the serving API are P1–P2. What is and is not promised yet is
> stated explicitly at the bottom of
> [docs/determinism.md](docs/determinism.md) — please read that before quoting
> any performance number.

## Quickstart

On a clean Ubuntu 24.04 box:

```bash
git clone https://github.com/sandeep-jaiswar/openib.git
cd openib
make bootstrap      # apt + rustup + uv. Idempotent. Root only for the apt step.
make daily          # hermetic run over vendored fixtures, then the determinism gate
```

That is the whole setup. No Postgres, no Kafka, no object store, no
credentials, no Docker. Storage is `./data`, and `make reset` is a clean slate.

Then look at something:

```bash
make query AS_OF=2025-06-30     # the warehouse as it was knowable in June 2025
make query AS_OF=2026-10-09     # the warehouse as it is knowable today
make ontology                   # object types, link types, identity anchors
make sources                    # the source registry
make test                       # the determinism contract, as 22 tests
```

To fetch from the live public sources instead of the fixtures:

```bash
make daily-full                 # SEC, GLEIF, OpenFIGI, Treasury, ECB
```

## Why fixtures in the default run?

`make daily` runs against two vendored documents in
`tests/fixtures/sec-companyfacts/` rather than the network. That is deliberate,
and it is what makes the rest of the project possible:

- the acceptance gate ("a clean VM, no further input") is **hermetic** — it
  cannot fail because the SEC is slow or because you are on a train;
- the golden-hash determinism gate needs a byte-stable input to hash;
- and the fixtures use the *real* SEC `companyfacts` schema, so the same
  transform code serves the fixture and `data.sec.gov`.

The fixtures include a restatement — FY2024 revenue reported one way in 2024
and restated in 2026 — because that is the case the whole architecture exists
to handle correctly.

## The one idea worth understanding

Every fact has two time axes: the period it is **about**, and when it became
**knowable**. So:

```console
$ ob query --as-of 2025-06-30 --concept Revenues
cik:0000320193  Revenues  2023-10-01..2024-09-28  391035000000 USD  (knew 2024-11-01, 0000320193-24-000081)

$ ob query --as-of 2026-10-09 --concept Revenues
cik:0000320193  Revenues  2023-10-01..2024-09-28  390912000000 USD  (knew 2026-02-17, 0000320193-26-000014)
```

Same company, same fiscal year, two different revenue figures — and both are
correct. The first is what anyone could have known in June 2025. The second is
what we know now, after the 10-K/A.

A system that stores only the current value destroys the first answer
permanently, and cannot tell you that it did. That is the difference between
information that is *auditable* and information that is merely *current*, and
it is why bitemporality is in the first commit rather than in P3. The full
reasoning is [ADR 0003](docs/adr/0003-bitemporality-on-day-one.md).

## The determinism contract

Six rules, each enforced by tests rather than asserted in prose:

| | Rule | Enforced by |
|---|---|---|
| **D1** | Raw immutability — content-addressed bytes, transforms never touch the network | static import check on the transform module; blob re-hashed on read |
| **D2** | Bitemporality — `valid_from`/`valid_to` plus `knowledge_time` from the source document | restatement test over the fixture |
| **D3** | Pinned inputs — git SHA, ontology version, source versions, every blob hash | run receipt in `data/runs/<date>.json` |
| **D4** | No ambient nondeterminism — no clock, env, locale or RNG in a transform; decimals not floats | encoder *refuses* floats; two runs with `fetched_at` five years apart must agree |
| **D5** | Byte-reproducible outputs | golden hashes in `tests/golden/`, checked in CI on two runner images |
| **D6** | Full lineage — every fact carries the hash of the document it came from | every `provenance_sha256` must resolve to a landed blob |

Read [docs/determinism.md](docs/determinism.md) for what each one actually
means, and for the list of things the contract does **not** promise yet.

## Architecture

Single node, deliberately — vectorised columnar execution on one 8-core box
beats a cluster at this data volume and is far easier to make deterministic
([ADR 0002](docs/adr/0002-single-node-columnar-first.md)).

| Layer | Choice | Status |
|---|---|---|
| Raw landing | content-addressed bytes + fetch manifest | **live** |
| Canonical sink | sorted canonical JSONL via one writer | **live** (P0) |
| Table format | Apache Iceberg, filesystem + SQLite catalog | P1 |
| File format | Apache Parquet, canonical writer settings | P1 |
| Memory / transport | Apache Arrow, Arrow Flight SQL | P2 |
| Query engine | Apache DataFusion (embedded) + DuckDB | P2 |
| Orchestration | Apache Airflow 3.x — optional, shells out to `ob run` | P2 |
| Dashboards | Apache Superset, Apache ECharts | P3 |
| Lineage | OpenLineage + Marquez | P2 |
| Profiling | Bloomberg memray, criterion, flamegraph | P1 |

The P0 sink is JSONL and not Parquet on purpose: it keeps the core pipeline at
**zero runtime dependencies**, so the clean-VM gate holds, and it puts the
byte-level guarantee in one function that P1 replaces without touching the
contract above it ([ADR 0006](docs/adr/0006-jsonl-sink-before-parquet.md)).

```
Makefile          bootstrap, daily, verify, test
scripts/          bootstrap-ubuntu.sh
ontology/         the ontology declaration (v1.toml)
sources/          declarative source registry, one TOML per source
python/ob/        the pipeline: canonical, fetch, warehouse, ontology, cli
crates/           Rust compute crates (P1)
warehouse/        Iceberg DDL and partition specs (P1)
tests/golden/     committed determinism hashes
tests/fixtures/   vendored documents for the hermetic run
docs/adr/         architecture decision records
bench/            benchmark suite wired to CI gates (P1)
compose/          optional ui / scheduler profiles (P2)
```

## The ontology

Object types, link types and properties — with units, currency and periodicity
— are declared once in [`ontology/v1.toml`](ontology/v1.toml). P0 validates and
serves that declaration; code generation (typed accessors, Iceberg DDL and the
serving schema emitted from the same file) is P2.

Identity is anchored on public identifiers — LEI, FIGI, CIK, MIC, ISIN — and
resolution is **rule-based, never probabilistic**. A trained matcher would
resolve more issuers and make the pipeline irreproducible; ambiguous matches go
to a review queue instead
([ADR 0004](docs/adr/0004-rule-based-identity-resolution.md)).

## Data sources

Free and public, all of them: SEC EDGAR, GLEIF LEI, OpenFIGI, FRED, US Treasury
FiscalData, ECB Data Portal. Each is a TOML file in `sources/`, so adding one is
a reviewable diff rather than a patch to the ingest engine.

FRED needs a free API key, so it is marked `requires_credential` and is skipped
unless you pass `--allow-credentialed`. The default daily run must work for
someone who has not signed up for anything.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: if your change moves
a golden hash, say so in the PR and explain why the new bytes are the correct
ones.

## Licence

Apache-2.0 — see [LICENSE](LICENSE). That covers this source code and says
nothing about the terms of the data you fetch with it. Each source records a
`terms_url`, and the redistribution question is deliberately deferred rather
than solved — see [non-goals](docs/non-goals.md).
