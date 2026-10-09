# Contributing

## The only rule that is really a rule

**If your change moves a golden hash, say so in the PR and explain why the new
bytes are the correct ones.**

`tests/golden/` holds the SHA-256 of every output table for a fixed logical
date. A change there means the pipeline now produces different bytes for the
same inputs. Sometimes that is right — you fixed an extraction bug, or added a
field. Sometimes it means something ambient leaked into a transform. The PR has
to say which.

Re-record with `make golden` and read the diff before committing it.

## Before you open a PR

```bash
make test       # the determinism contract, stdlib only
make daily      # hermetic run + the golden-hash gate
make lint       # ruff, if installed
```

CI runs the same three plus a clean-Ubuntu bootstrap and a cross-runner hash
comparison.

## Things that will be sent back

- **A float where a decimal belongs.** The canonical encoder refuses floats on
  purpose. Money and quantities are `Decimal`.
- **Network access inside a transform.** Transforms read the landing zone.
  `warehouse.py` is statically checked for forbidden imports.
- **Reading the clock, the environment or the hostname inside a transform.**
  The logical date is injected as an argument.
- **An output table without an explicit sort key.** Dict and filesystem
  iteration order are not stable; declare the order.
- **Probabilistic entity matching.** See
  [ADR 0004](docs/adr/0004-rule-based-identity-resolution.md). Ambiguous
  matches belong in a review queue.
- **Anything downstream of a decision** — orders, positions, P&L, signals,
  recommendations. See [docs/non-goals.md](docs/non-goals.md).

## Adding a data source

Add one TOML file to `sources/`. The filename must match the `id`. Mark it
`requires_credential = true` if it needs a key, and keep it out of the default
profile — the daily run has to work for someone who has not signed up for
anything.

A source only needs a transform when it should reach the warehouse; until then
it lands raw and the run receipt records that nothing consumed it.

## Architecture decisions

If a choice is load-bearing and the next reader will question it, write an ADR
in `docs/adr/`. State what you gave up, not just what you chose. ADRs are
immutable once accepted — a reversal is a new ADR that supersedes the old one.

## Commits

Conventional-ish prefixes (`feat:`, `fix:`, `docs:`, `chore:`) and a body that
explains *why*. The code already says what.
