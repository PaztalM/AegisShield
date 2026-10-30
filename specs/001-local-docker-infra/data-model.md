# Phase 1 Data Model: Local Docker Infrastructure

**Feature**: `001-local-docker-infra` | **Date**: 2026-10-23

This feature stores no application data — it provisions an empty broker and an empty named database. "Entities" here are therefore the declarative objects of the environment definition, taken from the Key Entities section of [spec.md](./spec.md). There is no database schema in this feature; the first table and the first migration arrive with the Worker, per constitution Principle III.

Field values and validation rules below are the authoritative source for the Compose file; variable names and their exact semantics live in [contracts/environment-variables.md](./contracts/environment-variables.md).

---

## Entity: Environment definition

The single declarative description of the local stack. One instance: `docker-compose.yml` at the repository root.

| Field | Value | Rule |
|---|---|---|
| Location | `./docker-compose.yml` | Exactly one file at the repository root (FR-001). No override file, no `include:`, no `profiles:` |
| Components | `rabbitmq`, `postgres` | Exactly two services (FR-001) |
| Networks | `aegisshield-net` (bridge) | One network, joined by both services (FR-014) |
| Volumes | `rabbitmq-data`, `postgres-data` | One named volume per component (FR-011) |
| Hard-coded values | none | Every credential, name, and host port is an interpolation (FR-005, SC-007) |

**Relationships**: contains two *Component* entities; declares two *Persistent storage volume* entities; reads the *Configuration variable set*.

**Validation rules**:
- Every `${VAR}` it interpolates appears in `.env.example`, and every `.env.example` entry is interpolated by it (FR-006).
- No image reference uses `latest` or a partial version tag (FR-013).
- It accepts a new service block that joins `aegisshield-net` and declares `depends_on` on both components without any edit to the two existing service definitions (FR-015, SC-010).

---

## Entity: Component — message broker

| Field | Value | Rule |
|---|---|---|
| Service name | `rabbitmq` | Also the internal DNS name services connect to (FR-014) |
| Image | `rabbitmq:4.2.4-management-alpine` | Full `major.minor.patch` pin; `-management` variant required for User Story 2 |
| Container hostname | fixed, e.g. `aegisshield-rabbitmq` | MUST be set. Stabilizes the Erlang node name so the Mnesia directory inside the volume survives container recreation (FR-011, scenario 3.1) |
| Published messaging port | `${RABBITMQ_PORT:-5672}` → container `5672` | Host side overridable; container side fixed (FR-002, FR-004) |
| Published management port | `${RABBITMQ_MANAGEMENT_PORT:-15672}` → container `15672` | Same rule (FR-002, FR-004) |
| Administrative account | `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` | Project-defined; replaces the stock `guest` account, which is never created (FR-008) |
| Virtual host | `RABBITMQ_DEFAULT_VHOST` | Created on first start |
| Volume mount | `rabbitmq-data` → `/var/lib/rabbitmq` | Holds durable definitions and persistent messages (FR-011, FR-020) |
| Readiness check | `rabbitmq-diagnostics -q check_port_connectivity` | Must verify the listener accepts connections, not that the process started (FR-010) |
| Readiness timing | `interval: 10s`, `timeout: 10s`, `retries: 6`, `start_period: 60s` | Authoritative values — do not leave to implementation-time discretion. Longer than the database's on every axis: an Erlang node boot plus management-plugin start commonly takes 20–40s on a first start, and `rabbitmq-diagnostics` itself starts a short-lived Erlang VM per invocation, so it needs a timeout `pg_isready` does not. A success during `start_period` marks the service healthy immediately, so the 60s window delays nothing — it only stops a slow first boot being reported as failure (FR-010, FR-019, SC-002) |
| Restart policy | `unless-stopped` | Survives a host or daemon restart without starting after a deliberate stop. Not speculative configuration (Principle V): it serves the spec's "unclean shutdown (machine sleep, forced kill)" edge case directly — a developer who closes the lid or reboots finds the environment running again. One consequence to keep in mind when testing: the policy also fires after `docker compose kill`, so a killed container comes back on its own rather than sitting exited (see tasks.md T041) |

**State transitions** (as reported by `docker compose ps`):

```text
absent ──up──> created ──> starting (healthcheck failing, within start_period)
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
              healthy                  unhealthy (retries exhausted — FR-019)
                 │
       ┌─────────┴──────────┐
       ▼                    ▼
   stop → stopped       down → absent (volume retained)
       │                        │
       └── up → starting        └── down -v → absent (volume discarded — FR-012)
```

**Validation rules**:
- Never reported healthy while the messaging port refuses connections (FR-010, SC-003).
- Signing in to the management interface as `guest` is rejected (scenario 2.4).
- Durable queues declared before a restart are present after it (scenario 3.1, FR-020).

---

## Entity: Component — relational database

| Field | Value | Rule |
|---|---|---|
| Service name | `postgres` | Also the internal DNS name (FR-014) |
| Image | `postgres:18.4-alpine` | Full `major.minor.patch` pin (FR-013) |
| Published port | `${POSTGRES_PORT:-5432}` → container `5432` | Host side overridable; container side fixed (FR-003, FR-004) |
| Owning account | `POSTGRES_USER` / `POSTGRES_PASSWORD` | Created on first start; owns the application database (FR-009) |
| Application database | `POSTGRES_DB` | Created empty on first start, no manual step and no init script (FR-009) |
| Volume mount | `postgres-data` → `/var/lib/postgresql/data` | The data directory (FR-011) |
| Readiness check | `pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"` | `-h 127.0.0.1` is required: a socket-only check passes during initialization, before the TCP listener exists (FR-010) |
| Readiness timing | `interval: 5s`, `timeout: 5s`, `retries: 5`, `start_period: 30s` | Authoritative values — do not leave to implementation-time discretion. `pg_isready` is a cheap single connection attempt, so a 5s interval costs nothing and keeps detection granularity tight for SC-002's 60s warm start. `start_period: 30s` covers first-start `initdb`, which takes 10–20s; after it elapses, 5 failed checks at 5s mark the service unhealthy within ~25s (FR-010, FR-019, SC-002) |
| Restart policy | `unless-stopped` | As above |
| Schema | none | Tables and constraints belong to versioned migrations in a later feature (Principle III) |

**State transitions**: identical to the broker's, with one addition — the transition `absent → created` on a *first-ever* start also runs initialization (create account, create database, build the data directory). Initialization happens once per volume; on later starts the existing data directory is used as-is and the `POSTGRES_*` credential variables are ignored.

**Validation rules**:
- Never reported healthy while port 5432 refuses connections (FR-010, SC-003).
- After a stop and start, previously written rows are present (scenario 3.1, SC-005).
- After `down -v` and a start, the database contains no project data (scenario 3.2, SC-006).

---

## Entity: Configuration variable set

The named settings the environment reads at start time. Exists in two forms.

| Form | Path | Committed | Role |
|---|---|---|---|
| Example | `./.env.example` | yes | Lists every variable with working development defaults; copying it is the only preparation step (FR-006) |
| Active | `./.env` | **no** — already in `.gitignore` | The developer's values; auto-loaded by Compose for interpolation (FR-007) |

**Fields**: see [contracts/environment-variables.md](./contracts/environment-variables.md) for the full table with defaults and consuming service.

**Validation rules**:
- Two tiers. Credentials and identity values are *required* — declared `${VAR:?message}`, so a missing or empty value aborts the start with the variable name and a pointer to `.env.example` (edge case: missing or incomplete configuration). Host ports are *defaulted* — declared `${VAR:-<default>}`, so omitting them is legal (FR-004).
- `.env.example` contains no value intended to be secret; all defaults are development-grade and local-only (FR-007, SC-007, and the spec's assumptions).
- Changing a credential after the corresponding volume has been initialized has no effect and will fail authentication until the volume is discarded — documented, not worked around (edge case).

---

## Entity: Persistent storage volume

Two instances, both Docker named volumes created automatically on first start.

| Instance | Mounted at | Holds | Lifecycle |
|---|---|---|---|
| `postgres-data` | `/var/lib/postgresql/data` | Data directory: the application database and its account | Survives `stop` and `down`; removed only by `down -v` (FR-011, FR-012) |
| `rabbitmq-data` | `/var/lib/rabbitmq` | Mnesia node directory: users, vhost, durable queue definitions, persistent messages | Same (FR-011, FR-020) |

**Validation rules**:
- Created with no manual preparation on a machine that has never run the environment (scenario 3.3).
- `down -v` returns the environment to a state indistinguishable from a first-ever start (FR-012, SC-006).
- The broker volume is only useful together with the fixed container hostname; without it the node name changes and the preserved Mnesia directory is ignored.

---

## Entity: Broker administrative account

One account, used both by developers signing in to the management interface and by the application services connecting later.

| Field | Source | Notes |
|---|---|---|
| Username | `RABBITMQ_DEFAULT_USER` | Required variable |
| Password | `RABBITMQ_DEFAULT_PASS` | Required variable; development-grade default in `.env.example` |
| Virtual host | `RABBITMQ_DEFAULT_VHOST` | Required variable |
| Tags | administrator | Granted by the image when the default-user variables are set |

**Validation rules**: created on first start on a fresh volume; `guest` is not created (FR-008); credentials are frozen into the volume at initialization (see the Configuration variable set caveat).

---

## Entity: Application database and owning account

| Field | Source | Notes |
|---|---|---|
| Database name | `POSTGRES_DB` | Created empty — no tables, per Principle III |
| Owner username | `POSTGRES_USER` | Superuser of this instance; owns the database |
| Owner password | `POSTGRES_PASSWORD` | Required variable; development-grade default in `.env.example` |
| Encoding | image default (`UTF8`) | Not configured here; no requirement calls for it |

**Validation rules**: both created during first-start initialization with no manual step (FR-009); frozen into the volume thereafter.

---

## Relationship summary

```text
Environment definition (docker-compose.yml)
├── reads ──────────> Configuration variable set (.env ← .env.example)
├── declares ───────> Network: aegisshield-net
│                       ├── Component: rabbitmq  (internal name "rabbitmq")
│                       └── Component: postgres  (internal name "postgres")
├── declares ───────> Persistent storage volume: rabbitmq-data ──mounted by──> rabbitmq
│                     Persistent storage volume: postgres-data ──mounted by──> postgres
└── extension point > future services join aegisshield-net and depend_on
                      both components (service_healthy) — no edit to the above

Component: rabbitmq  ──initializes on first start──> Broker administrative account
Component: postgres  ──initializes on first start──> Application database + owning account
```
