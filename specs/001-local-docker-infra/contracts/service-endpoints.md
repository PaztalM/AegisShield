# Contract: Service endpoints and internal names

**Feature**: `001-local-docker-infra` | **Date**: 2026-10-23

The addresses this environment exposes. Two audiences: a developer on the host, and services running inside the environment. Both are part of the contract, because FR-014 requires each component to be reachable from the host at a published port and from inside by a stable name.

## From the host

| Endpoint | Protocol | Address | Credentials | Requirement |
|---|---|---|---|---|
| Broker — messaging | AMQP 0-9-1 | `localhost:${RABBITMQ_PORT:-5672}` | `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS`, vhost `RABBITMQ_DEFAULT_VHOST` | FR-002 |
| Broker — management | HTTP | `http://localhost:${RABBITMQ_MANAGEMENT_PORT:-15672}` | same account | FR-002, User Story 2 |
| Database | PostgreSQL wire protocol | `localhost:${POSTGRES_PORT:-5432}` | `POSTGRES_USER` / `POSTGRES_PASSWORD`, database `POSTGRES_DB` | FR-003 |

Three endpoints, all reachable using only values read from `.env.example` — no undocumented value is needed (SC-004).

Each host port is overridable through the variable shown; the Compose file is never edited to relocate one (FR-004).

## From inside the environment

Services on `aegisshield-net` resolve each other by Compose service name. These addresses are fixed and do not change when a host port is overridden:

| Target | Address | Note |
|---|---|---|
| Broker — messaging | `rabbitmq:5672` | Container-side port, never interpolated |
| Broker — management | `rabbitmq:15672` | Available but not normally used by services |
| Database | `postgres:5432` | Container-side port, never interpolated |

**Rule for later features**: the Producer and the Worker connect by these internal names, never through `localhost` or a published host port (FR-014). A service that connects to `localhost:5672` from inside a container is reaching its own container, not the broker.

## Extension contract for application services

What a later feature must do to join this environment, and what it may rely on (FR-015, SC-010):

```yaml
# Shape only — the owning feature writes the real block.
services:
  producer:
    build: ./producer
    depends_on:
      rabbitmq:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      RABBITMQ_HOST: rabbitmq
      # ...credentials from the same .env variables
    networks:
      - aegisshield-net
    restart: unless-stopped
```

Guarantees this feature provides to such a block:

1. `aegisshield-net` exists and both components are on it.
2. Both components declare a healthcheck, so `condition: service_healthy` is meaningful — the dependent service starts only once the broker and the database actually accept connections (FR-010, FR-015).
3. The internal names and ports in the table above are stable.
4. The variables in [environment-variables.md](./environment-variables.md) are available for interpolation.

What the block must **not** require: any change to the `rabbitmq` or `postgres` service definitions (SC-010). Adding a service is additive.

What it must still do for itself, per constitution Principle IV: retry its connections rather than exiting permanently. `service_healthy` orders startup, but it is not a substitute for retry — a dependency can drop at any time after startup.

## Readiness, as observed

| Component | Check | Passes only when |
|---|---|---|
| `rabbitmq` | `rabbitmq-diagnostics -q check_port_connectivity` | Every published listener accepts a TCP connection |
| `postgres` | `pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"` | The server accepts TCP connections on loopback for that user and database |

A component failing its check appears as `unhealthy` in `docker compose ps` and is never reported healthy (FR-019), and `docker compose up -d --wait` exits non-zero rather than claiming success (SC-003).
