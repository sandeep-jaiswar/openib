# Non-goals

What this project does **not** do, permanently unless the direction changes.

## Not a trading system

- No order routing, broker or exchange connectivity, or execution of any kind.
- No portfolio management, position keeping, or P&L.
- No backtester or strategy simulation.
- No buy/sell signals, no scores presented as recommendations, no advice.

The ontology has no `Portfolio`, `Position`, `Order`, `Trade`, `Signal` or
`Strategy` object type, and `tests/test_determinism.py` asserts that it never
acquires one. `Watchlist` and `Note` exist instead, so a user can follow and
annotate issuers without the system holding positions.

What we build is the information layer: accurate, point-in-time, explainable,
fast to query. Nothing downstream of a decision. A user who then trades does so
manually, elsewhere, and that is not our concern.

Derived metrics — ratios, margins, growth, multiples — are in scope and are
described as what they are, with units and periodicity declared. The line is
between *describing* a company and *recommending* an action.

## No paid feeds, no real-time data

Free public sources only, daily batch by design. Real-time market data is a
different product with different economics and would make the pipeline
unrunnable by anyone who has not bought a feed.

Bloomberg's open-source libraries are ordinary dependencies and we use them —
memray drives the optimisation work. BLPAPI market data stays out of the daily
pipeline for a mechanical reason rather than a legal one: it needs a
Terminal/Server API seat to return anything at all, so it can never be part of
a pipeline other people can run. It ships as an adapter that is off by default
and does nothing unless the user already holds a seat.

## Licensing and redistribution: deferred, not solved

There is no licence registry and no build-time publish gate. Each source
carries a `terms_url` as an inert note field; nothing gates on it.

This costs nothing today because **we publish nothing today** — the warehouse
is built locally from sources the user fetches themselves. It starts to matter
only if this project later hosts a public mirror of *derived datasets* (not
source code). FRED and OpenFIGI are the two that would need a look first.
Keeping `terms_url` on every source means that is a day's work when it comes
up, rather than a re-architecture.

Our own code is Apache-2.0, which is one `LICENSE` file.

## No cluster, no services, until the single node actually runs out

Vectorised columnar execution on one 8-core box beats a distributed cluster at
this data volume and is far easier to make deterministic. Spark, Flink and
Kafka are documented escape hatches, not day-one dependencies. Airflow and
Superset sit behind optional compose profiles, and Airflow only ever shells out
to `ob run`.
