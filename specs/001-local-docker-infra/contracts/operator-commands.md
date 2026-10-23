# Contract: Operator commands

**Feature**: `001-local-docker-infra` | **Date**: 2026-10-23

The command-line interface of this feature. FR-017 requires the start, status, log, stop, and reset commands to be documented; this table is the authoritative list, and the root `README.md` must document exactly these. No wrapper script, Makefile, or task runner is introduced (Principle V) — plain `docker compose` is the interface.

All commands run from the repository root, which is the Compose project directory.

| Intent | Command | Exit behavior | Requirement |
|---|---|---|---|
| Prepare configuration (once) | `cp .env.example .env` | — | FR-006 |
| **Start and wait for ready** | `docker compose up -d --wait` | Zero only when both components are healthy; non-zero if either fails to become healthy | FR-010, SC-003 |
| Start in the foreground (watch logs) | `docker compose up` | Streams both components' logs; Ctrl+C stops them | FR-016 |
| **Status and health** | `docker compose ps` | Lists each component's state, health, and published host ports | FR-019, scenario 1.4 |
| **Logs, one component** | `docker compose logs -f rabbitmq` / `docker compose logs -f postgres` | Follows that component's stdout | FR-016 |
| **Stop, keeping data** | `docker compose down` | Removes containers and the network; named volumes are retained | FR-011 |
| Stop without removing containers | `docker compose stop` | Containers remain and restart faster | — |
| **Reset — discard all data** | `docker compose down -v` | Removes containers, network, **and both named volumes** | FR-012 |
| Open a database shell | `docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"` | Interactive psql inside the container; needs no host client (FR-018) | — |
| Inspect the broker | `docker compose exec rabbitmq rabbitmqctl list_queues` | Needs no host client (FR-018) | — |
| Verify no hard-coded values | `docker compose config` | Prints the resolved file with interpolations applied | SC-007 |

Bold rows are the five commands FR-017 names. The others are convenience entries; the README may list them, but must not omit the bold ones.

## Semantics that matter

**`--wait` is not optional in the documented start command.** Plain `up -d` returns as soon as containers are created, which would leave the developer guessing whether the broker accepts connections yet — exactly what SC-003 forbids.

**`down` versus `down -v` is the entire persistence contract.** `down` is safe and keeps data; `down -v` is the documented reset and is irreversible. The README must make the difference unmissable, because the two differ by two characters and one of them destroys test data.

**Repeating `up` is safe.** A second `docker compose up -d --wait` against a running environment is a no-op or a clean reconcile; it does not create duplicate components or corrupt volumes (edge case in the spec).

**A changed credential needs a reset.** Because credentials are frozen into a volume at initialization, the sequence for changing one is: edit `.env`, then `docker compose down -v`, then start again. There is no in-place path, and the README says so (edge case in the spec).

**A port conflict fails the start.** When a required host port is occupied, the start fails at container creation with an error naming the host port, within seconds and without a partial environment (SC-009). The remedy is to set the corresponding `*_PORT` variable in `.env`, not to edit the Compose file (FR-004).

## Commands this feature deliberately does not provide

- No `make up` / `make reset` or equivalent wrapper — it would add a layer over a one-line command and a host dependency on `make`, against Principle V and FR-018.
- No seeding or migration command — schema belongs to versioned migrations in a later feature (Principle III).
- No queue-declaration command — topology belongs to the services that own it (Principle II).
