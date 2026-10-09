# Rust crates (P1)

Planned, not yet landed. The pinned toolchain is in `rust-toolchain.toml` so
the first crate to arrive does not also have to teach every machine about
rustup.

| Crate | Responsibility |
|---|---|
| `ob-manifest` | content-addressed landing zone and fetch manifests |
| `ob-ingest` | source connectors, rate limiting, resumable backfills |
| `ob-ontology` | ontology codegen: typed accessors, Iceberg DDL, serving schema |
| `ob-compute` | DataFusion query plans, point-in-time resolution, screener scans |
| `ob-cli` | the `ob` binary |

The Python implementation in `python/ob/` is the reference semantics. A crate
replaces a module only when it passes the same golden hashes — byte for byte,
not approximately. That is the acceptance test for every crate here.

Owner: Data Platform Engineer, with the CTO as review gate.
