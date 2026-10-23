# Contract: Environment variables

**Feature**: `001-local-docker-infra` | **Date**: 2026-10-23

This is the configuration interface of the local environment: the complete set of variables `docker-compose.yml` reads, and the complete set `.env.example` ships. The two sets are identical by rule (FR-006). A later feature that adds a service may add variables to both files; it may not read a variable that is absent from `.env.example`.

Consumers: Compose itself (interpolation of host ports), the two official images (credentials and names), and — later — the Producer and Worker, which read the same values to build their connection strings.

## Variable table

| Variable | Tier | Default in `.env.example` | Read by | Purpose |
|---|---|---|---|---|
| `POSTGRES_USER` | required | `aegis` | `postgres` image | Owning account for the application database; created on first start |
| `POSTGRES_PASSWORD` | required | `aegis_dev_password` | `postgres` image | Password for that account. Development-grade, localhost-only |
| `POSTGRES_DB` | required | `aegisshield` | `postgres` image | Name of the application database, created empty on first start |
| `POSTGRES_PORT` | defaulted | `5432` | Compose interpolation | Host port the database is published on (FR-003, FR-004) |
| `RABBITMQ_DEFAULT_USER` | required | `aegis` | `rabbitmq` image | Project-defined administrative account; replaces `guest` (FR-008) |
| `RABBITMQ_DEFAULT_PASS` | required | `aegis_dev_password` | `rabbitmq` image | Password for that account, also used for the management interface |
| `RABBITMQ_DEFAULT_VHOST` | required | `aegisshield` | `rabbitmq` image | Virtual host created on first start |
| `RABBITMQ_PORT` | defaulted | `5672` | Compose interpolation | Host port for the messaging endpoint (FR-002, FR-004) |
| `RABBITMQ_MANAGEMENT_PORT` | defaulted | `15672` | Compose interpolation | Host port for the web management interface (FR-002, FR-004) |

No other variable is read. No value from this table appears literally in `docker-compose.yml` (FR-005, SC-007).

## Tier semantics

**Required** — declared in the Compose file as `${VAR:?<message>}`. If the variable is unset or empty, Compose aborts before creating any container and prints the variable name together with the message, which points at `.env.example`. Nothing starts partially.

Message form: `VAR is not set - copy .env.example to .env`

**ASCII only in this message, deliberately.** The separator is a plain hyphen, not an em dash, because this string is operator-facing error text printed to a terminal. Windows consoles commonly run the cp1252 code page rather than UTF-8 — verified on the development host for this feature — where a non-ASCII character can render as mojibake or a replacement glyph. An error message is the last place to risk that, so every one of the required-tier messages stays inside ASCII. Prose in these documents may use em dashes freely; strings that reach a console may not.

**Defaulted** — declared as `${VAR:-<default>}`. Omitting it is legal and yields the default shown in the table. This is the mechanism FR-004 requires: a developer whose host already uses 5432 sets `POSTGRES_PORT=55432` in `.env` and never edits the Compose file.

## Rules

1. **Source of values.** Compose auto-loads `./.env` from the project directory for interpolation. Copying `.env.example` to `.env` is the only preparation step before the first start (FR-006).
2. **Secrecy.** `.env` is excluded from version control (already in the root `.gitignore`); `.env.example` holds only development-grade, localhost-only credentials (FR-007).
3. **Container-side ports are fixed.** Only the host side of a port mapping is interpolated. Inside `aegisshield-net`, the broker is always `rabbitmq:5672` and the database always `postgres:5432`, whatever the host publishes (FR-014).
4. **Credentials freeze at volume initialization.** `POSTGRES_*` and `RABBITMQ_DEFAULT_*` values take effect only while the corresponding volume is being created. Changing one afterwards does not re-provision the account — it causes an authentication failure until the volume is discarded with `docker compose down -v`. This must be stated in the README (edge case in the spec).
5. **No speculative variables.** A variable is added only when the Compose file reads it (Principle V).
6. **Passing style.** Credentials reach the containers through explicit `environment:` keys, not `env_file:`, so the Compose file records which image consumes which variable and no unrelated value enters a container.

## Derived values (not variables)

These are composed from the table above rather than stored separately. The services added later build them from the same `.env`:

| Value | Composition | Example with defaults |
|---|---|---|
| Broker URI (from inside the network) | `amqp://${RABBITMQ_DEFAULT_USER}:${RABBITMQ_DEFAULT_PASS}@rabbitmq:5672/${RABBITMQ_DEFAULT_VHOST}` | `amqp://aegis:aegis_dev_password@rabbitmq:5672/aegisshield` |
| Broker URI (from the host) | same, with `localhost:${RABBITMQ_PORT}` | `amqp://aegis:aegis_dev_password@localhost:5672/aegisshield` |
| Database URI (from inside the network) | `postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}` | `postgresql://aegis:aegis_dev_password@postgres:5432/aegisshield` |
| Database URI (from the host) | same, with `localhost:${POSTGRES_PORT}` | `postgresql://aegis:aegis_dev_password@localhost:5432/aegisshield` |

Note the vhost segment of the broker URI: a non-default vhost must be URL-encoded when it contains `/`. The default `aegisshield` does not, which is one reason to keep it a plain word.
