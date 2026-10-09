# Optional compose profiles (P2)

Nothing here is needed to run the pipeline. The core path is `ob run` with no
services at all ([ADR 0005](../docs/adr/0005-local-first-no-services.md)).

Planned:

- `docker compose --profile ui up` — Superset and Marquez
- `docker compose --profile scheduler up` — Airflow 3.x on LocalExecutor

**The governing rule: Airflow only ever shells out to `ob run`.** It does not
import the pipeline, hold state about it, or split it into per-task operators.
That is what keeps the scheduler genuinely optional and determinism reachable —
a cron entry on a laptop reproduces CI exactly, because the unit of work is the
whole command.

Owner: SRE / Platform Engineer.
