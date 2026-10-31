# Implementation Plan: Transaction Event Pipeline

**Branch**: `002-transaction-event-pipeline` | **Date**: 2026-10-31 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-transaction-event-pipeline/spec.md`

## Summary

Add the two application services the system was always going to need: a **Producer** that generates synthetic transaction events and publishes them to the existing broker, and a **Worker** that consumes each event, evaluates two explicit fraud rules, and persists exactly one decision per event to the existing database.

Technical approach: two small Python services, each in its own directory with its own `Dockerfile` and pinned `requirements.txt`, using `pika` and `psycopg` directly with no wrapper layers. Correctness rests on three mechanisms rather than on careful coding: the Worker acknowledges a message only after its database transaction commits, the event identifier is the table's primary key so a duplicate delivery cannot produce a second row, and unparseable messages are rejected into a dead-letter queue where they remain inspectable. Both services retry their dependencies forever instead of exiting, which is the Principle IV debt feature 001 recorded as deferred. Velocity is computed from the database rather than from memory, so a restart cannot change a verdict.

## Technical Context

**Language/Version**: Python **3.14.10**, from `python:3.14.10-slim`, pinned identically in both services' Dockerfiles as the constitution requires.

**Primary Dependencies**: `pika==1.4.4` (AMQP 0-9-1 client), `psycopg[binary]==3.3.6` (PostgreSQL driver), `pytest==9.2.0` (test runner only, not in either service image). All three verified to install on `python:3.14-slim` with no compiler present.

**Storage**: PostgreSQL 18.4, the instance feature 001 already provides. Two tables: `fraud_decisions` and `schema_migrations`. No second datastore.

**Testing**: `pytest`, executed inside a container so nothing is required on the host. Unit tests for the two rule functions (pure, no I/O); one integration test exercising the real broker and real database with neither replaced.

**Target Platform**: Linux containers under Docker Compose, on a developer machine running Windows, macOS or Linux. No host-installed runtime.

**Project Type**: Multi-service backend. Two long-running worker-style processes with no HTTP surface, plus one on-demand test runner.

**Performance Goals**: ≥50 events/second sustained for 5 minutes (SC-004); 95th-percentile creation-to-stored under 2 seconds (SC-003); first stored decision within 60 seconds of a cold start (SC-001).

**Constraints**: Acknowledge only after commit (FR-017). Exactly one decision per event, enforced by a database constraint rather than application logic (FR-016). No host-installed dependencies (FR-026). **No change to feature 001's `rabbitmq` or `postgres` service definitions** beyond the new services declaring dependency on them (FR-023) — a property feature 001 verified in advance in T039.

**Scale/Scope**: One developer machine. One instance of each service by default. One event type, two fraud rules, one decision table. Deliberately thin.

No unresolved unknowns: every version above was established by querying the registry and installing the packages, not from memory. See [research.md](./research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Applies | Assessment |
|---|---|---|
| **I. Explicit Service Boundaries** | Fully | **PASS.** `producer/` and `worker/` each have their own `Dockerfile` and `requirements.txt`. Neither imports from the other; the event format lives in `contracts/transaction-event.md` and the two services each parse it independently. The two services are the ones the constitution itself names as initial. A third Compose entry, `tests`, is a test runner rather than a deployable service — see Complexity Tracking. |
| **II. Message-Driven Communication via RabbitMQ** | Fully | **PASS.** The broker is the only channel; neither service calls the other and neither reads the other's data. The queue is declared `durable` and messages are published with `delivery_mode=2` (persistent) plus publisher confirms. The Worker acknowledges only after commit. Unparseable messages are rejected with `requeue=false` into a dead-letter queue, never dropped. Idempotency is enforced by a primary key on the event identifier. Payloads are JSON carrying an event ID and a timestamp. |
| **III. PostgreSQL as the System of Record** | Fully | **PASS.** PostgreSQL remains the only datastore — notably, the velocity rule reads history from it rather than introducing a cache, which would have required an amendment. Schema arrives as numbered SQL files applied automatically; no manual edits. The uniqueness that idempotency depends on is a database constraint, not an application check. All connection settings and credentials come from environment variables. |
| **IV. Docker Compose Runs Everything** | Fully | **PASS, and this is where the deferred debt is paid.** Both services join the single existing `docker-compose.yml` and start with the same command. Nothing new is required on the host. Configuration comes from environment variables with `.env.example` updated. Both services **retry** the broker and the database instead of crashing — the requirement feature 001 logged as deliberately deferred because it had no application service to apply it to. `depends_on: condition: service_healthy` gates startup, and each new service gets its own healthcheck so `up -d --wait` waits for the whole pipeline. The Python base image is pinned to a full patch version. |
| **V. No Premature Abstraction** | Fully | **PASS, and it constrained several choices.** `pika` and `psycopg` are used directly, with no client wrapper, no repository layer, and no ORM. The two fraud rules are two plain functions, **not** a rule registry or plugin system — Principle V requires three concrete cases before abstracting, and there are two. Migrations are numbered `.sql` files plus a short runner rather than Alembic. Retry is a small loop rather than a retry library. Health reporting is a heartbeat file rather than an embedded HTTP server. Each rejected alternative is recorded with its reason in research.md. |
| **VI. Explain the Work in Plain Language** | Fully | **PASS.** `LEARNING-LOG.md` is updated for this plan in the same change, per the workflow rule that this applies to documentation-only work. The accepted risks below are recorded there together with the conditions that should trigger revisiting them. |

**Technology Stack & Constraints**: Python 3 for both services, exact version pinned identically (3.14.10). RabbitMQ as broker, PostgreSQL as database, Compose as orchestration — all unchanged. Each service declares pinned dependencies serving a present requirement. Logs go to stdout/stderr and every event-related line carries the event ID. Performance targets are stated as numbers in the spec's SC-003 and SC-004 rather than assumed.

**Development Workflow & Quality Gates**: This feature follows specify → plan → tasks → implement, with this Constitution Check completed before implementation. Fraud rules get unit tests covering flagged, non-flagged, and boundary cases. The full Producer → RabbitMQ → Worker → PostgreSQL path gets an integration test against real services with no mocking. The message contract and the schema arrive in the same change as the code that depends on them.

### Accepted risks

Recorded here and in `LEARNING-LOG.md`, each with the condition that should trigger a revisit — not left implicit.

1. **Queue arguments are immutable in RabbitMQ.** Declaring an existing queue with different arguments fails with `PRECONDITION_FAILED`. The dead-letter configuration must therefore be correct the first time the queue is created; changing it later requires deleting the queue or `docker compose down -v`. *Revisit when:* the topology needs to change, at which point the migration path must be written down rather than improvised.
2. **A single synchronous Worker must reach 50 events/second.** That is a 20 ms budget per message for one `SELECT` plus one `INSERT` against a local database. Plausible, and the main risk to SC-004. *Revisit when:* measurement shows a single Worker falls short. The fix is a larger prefetch with batched commits, or several Workers — which the database constraint already makes safe — **not** relaxing the criterion.
3. **Velocity counts only decided transactions.** Events still in flight are not yet in the table, so the count can undercount slightly. It is deterministic and identical across restarts and across Workers, which is what FR-012 actually requires. *Revisit when:* the throughput target rises enough that in-flight events become a large fraction of a window, or a rule needs exact real-time counting.
4. **`pika`'s blocking connection services heartbeats on the calling thread.** A database stall longer than the heartbeat timeout drops the AMQP connection. Mitigated by `prefetch=1`, a heartbeat comfortably longer than the worst expected database operation, and the reconnect loop FR-021 requires anyway. *Revisit when:* reconnect churn appears in the logs under normal load.

### Post-design re-check (after Phase 1)

Re-evaluated against the design actually produced in `research.md`, `data-model.md`, `contracts/` and `quickstart.md`. All six principles still pass, and the design tightened three of them rather than straining any:

- **Principle II got stronger, not weaker.** The ack-after-commit rule is now a fixed six-step order written into data-model.md, with the explicit observation that no ordering of those steps loses a transaction. Idempotency moved from "the Worker checks first" to a primary key plus `ON CONFLICT DO NOTHING`, which is enforcement rather than diligence.
- **Principle III is satisfied in the one place it was at risk.** The velocity rule wanted a cache; using PostgreSQL for it keeps the single-datastore rule intact with no amendment.
- **Principle V survived four separate temptations**, each recorded with its rejection in research.md: an ORM, a rule registry, a retry library, and an HTTP health endpoint. The two rules remain two functions, which is correct until there is a third.

Two things the design surfaced that were not visible when the gate was first evaluated:

1. **`/docker-entrypoint-initdb.d` is unusable here**, and for a reason worth recording: it would require editing the `postgres` service definition, which FR-023 forbids, *and* it only runs on a fresh data directory, so it would appear to work on a new clone and silently do nothing on any existing volume. The second failure mode is the dangerous one. Migrations therefore run from the Worker, which is also the only database writer, so there is no race to coordinate.
2. **The new services must use the internal ports 5672 and 5432**, not `RABBITMQ_PORT` / `POSTGRES_PORT`. Those publish to the host and a developer may relocate them — feature 001's T036 proved that is a real scenario. A service inside the network that used the host-side port would break the moment someone resolved a port conflict. This is written into contracts/environment-variables.md as a rule rather than left as a detail.

The single Complexity Tracking entry below is unchanged by the design work.

## Project Structure

### Documentation (this feature)

```text
specs/002-transaction-event-pipeline/
├── plan.md              # This file
├── spec.md              # The feature specification
├── research.md          # Phase 0 output: every decision and what was rejected
├── data-model.md        # Phase 1 output: tables, columns, constraints, indexes
├── quickstart.md        # Phase 1 output: how to validate the feature works
├── contracts/           # Phase 1 output
│   ├── transaction-event.md     # The JSON message contract
│   ├── queue-topology.md        # Queue and dead-letter names, arguments, durability
│   ├── fraud-rules.md           # The two rules, thresholds, boundary behaviour
│   └── environment-variables.md # Every new variable and its consumer
├── checklists/
│   └── requirements.md  # Spec quality checklist (already complete)
└── tasks.md             # Phase 2 output — created by /speckit-tasks, not here
```

### Source Code (repository root)

```text
producer/
├── Dockerfile               # python:3.14.10-slim
├── requirements.txt         # pika pinned
└── producer.py              # generate, publish, retry, heartbeat

worker/
├── Dockerfile               # python:3.14.10-slim, same version as producer
├── requirements.txt         # pika and psycopg pinned
├── worker.py                # consume, decide, store, ack, retry, heartbeat
├── rules.py                 # the two rule functions, pure and no I/O
├── migrate.py               # apply numbered SQL files under an advisory lock
└── migrations/
    └── 001_create_fraud_decisions.sql

tests/
├── Dockerfile               # python:3.14.10-slim
├── requirements.txt         # pytest, pika, psycopg pinned
├── unit/
│   └── test_rules.py        # flagged, non-flagged and boundary per rule
└── integration/
    └── test_pipeline.py     # real broker, real database, no stand-ins

docker-compose.yml           # EXISTS - gains producer, worker, tests
.env.example                 # EXISTS - gains the new variables
README.md                    # EXISTS - gains operating instructions for the pipeline
```

**Structure Decision**: Three top-level service directories rather than a shared `src/` tree, because Principle I requires each service to be independently buildable with its own dependency manifest and forbids them importing from one another. There is deliberately **no shared package** for the event format: the contract is a document, and each service parses the JSON on its own terms. That duplication is the point — it is what keeps the two services independently deployable, and it is cheaper than the hidden coupling a shared library creates.

`rules.py` sits inside `worker/` rather than anywhere shared, because only the Worker evaluates rules. It is a separate file purely so the rule functions can be imported by the unit tests without starting a broker connection.

Migrations live in `worker/` because the Worker is the only service that touches the database, which also removes any race over who applies them.

## Complexity Tracking

> Filled because the design breaks one rule feature 001 set for itself.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| A third Compose entry, `tests`, carrying `profiles: ["test"]` — feature 001's `docker-compose.yml` header states "no profiles" as a design rule | FR-032 requires an integration test against the real broker and real database, and FR-026 forbids requiring anything on the host — so the test must run in a container. A plain service would run on every `docker compose up`, which is wrong for a one-shot test runner. `profiles:` is the mechanism Compose provides for exactly this, and the need is concrete and present rather than speculative. The header comment is updated in the same change so the file does not contradict itself. | **Baking `pytest` into the Worker image and running `docker compose exec worker pytest`** — avoids the profile, but puts test-only dependencies into a runtime image, which cuts against the constitution's requirement that each service's pinned dependencies serve a present requirement. **A second Compose file for tests** — breaks feature 001's stronger "exactly one Compose file" rule and splits the environment definition in two. **Running `pytest` on the host** — directly violates FR-026. |

No other entries. In particular, no abstraction is introduced: there is no rule registry, no repository layer, no ORM, no base class, no configuration framework, and no retry library. Those were all considered and rejected in research.md on Principle V grounds.
