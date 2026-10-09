# Warehouse DDL (P1)

Iceberg table definitions, partition specs and clustering, emitted from
`ontology/v1.toml` by the codegen in P2 rather than hand-written here.

Planned shape:

- **bronze** — one table per source, raw-shaped, partitioned by `logical_date`
- **silver** — conformed and bitemporal, partitioned by `valid_to` year,
  clustered on `issuer_key`
- **objects / links** — the ontology's serving tables

Canonical Parquet writer settings (fixed row-group size, sorted by the declared
sort key, no creation timestamps) are what make D5 hold for Parquet; getting
them right is the acceptance test for the sink swap.

Owner: Data Platform Engineer.
