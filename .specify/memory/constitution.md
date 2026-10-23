

# AegisShield Constitution

Real-Time Fraud Detection System.

## Core Principles

### I. Explicit Service Boundaries

The system is composed of independently deployable services. The initial services are:

- **Producer** (Python): ingests or generates transaction events and publishes them to RabbitMQ.
- **Worker** (Python): consumes transaction events, evaluates them for fraud, and persists
  results to PostgreSQL.

Rules:

- Each service MUST live in its own directory with its own `Dockerfile` and dependency manifest.
- Services MUST NOT import code from one another. Shared message formats are documented as a
  contract (e.g., a JSON schema or a documented example payload), not as a shared package.
- A new service MUST be justified in the feature plan by a concrete need (independent scaling,
  isolation, or a distinct responsibility) that cannot be met by an existing service.

Rationale: clear ownership keeps services replaceable and testable in isolation, while the ban
on shared packages prevents hidden coupling.

### II. Message-Driven Communication via RabbitMQ

- RabbitMQ is the ONLY channel for communication between Producer and Worker. Services MUST NOT
  call each other directly (no HTTP/RPC between them) and MUST NOT communicate through the
  database.
- Queues carrying transaction events MUST be durable and messages MUST be published as
  persistent.
- The Worker MUST acknowledge a message only after its result has been committed to PostgreSQL.
  Failed messages MUST be rejected or dead-lettered, never silently dropped.
- Message processing MUST be idempotent: redelivery of the same event (identified by a unique
  event/transaction ID) MUST NOT produce duplicate records or duplicate fraud decisions.
- Every message payload MUST be JSON and MUST include an event ID and a timestamp.

Rationale: at-least-once delivery is the realistic guarantee of a broker; durability, late
acknowledgement, and idempotency together prevent lost or double-counted transactions.

### III. PostgreSQL as the System of Record

- PostgreSQL is the single persistent datastore. Adding another datastore (cache, document store,
  etc.) requires a constitution amendment.
- Schema changes MUST be applied through versioned SQL migration files checked into the
  repository; manual schema edits against a running database are prohibited.
- Uniqueness required for idempotency (Principle II) MUST be enforced by database constraints,
  not only by application logic.
- Credentials and connection settings MUST come from environment variables, never hard-coded.

Rationale: one source of truth with enforced constraints keeps fraud decisions auditable and
consistent.

### IV. Docker Compose Runs Everything

- All components — Producer, Worker, RabbitMQ, PostgreSQL — MUST be defined in a single
  `docker-compose.yml` and start with `docker compose up`.
- No component may require host-installed dependencies beyond Docker and Docker Compose.
- Service configuration MUST be supplied through environment variables (with a committed
  `.env.example`); secrets MUST NOT be committed.
- Services MUST tolerate dependency startup order: they MUST retry connections to RabbitMQ and
  PostgreSQL instead of crashing permanently, and Compose healthchecks SHOULD gate startup.
- Third-party images MUST be pinned to explicit version tags (no `latest`).

Rationale: a one-command, reproducible environment makes local development, testing, and demos
identical.

### V. No Premature Abstraction

- Write the direct, concrete solution first. Use client libraries (e.g., the RabbitMQ and
  PostgreSQL drivers) directly rather than wrapping them in custom layers.
- An abstraction (base class, interface, plugin system, repository layer, generic framework,
  configuration DSL) MUST NOT be introduced until at least three concrete cases need it, or a
  current requirement demonstrably cannot be met without it.
- No interface or abstract base class with only one implementation.
- No speculative configuration options, extension points, or features "for later".
- Any abstraction that is introduced MUST be justified in the plan's Complexity Tracking section.

Rationale: abstractions are cheapest to add once real duplication exists and most expensive to
remove once they are wrong.

### VI. Explain the Work in Plain Language

This project is a learning project. Working software is only half the deliverable; the other half
is the maintainer understanding why it works the way it does.

- A single running log MUST be kept at `LEARNING-LOG.md` in the repository root.
- After any meaningful unit of work — a ratified constitution change, a new spec, a plan, a task
  list, an implemented feature, or any significant technical decision — that file MUST be updated
  (or created, if absent) in the same change.
- Each entry MUST cover, in plain language: **what** was done, **why** it was done, **what
  alternatives were rejected and why**, and **what state the project is now in**.
- Entries MUST assume no prior knowledge. Every term is defined at first use, including terms an
  experienced engineer would consider obvious. "Trivial" is not a reason to omit an explanation;
  it is a reason the explanation will be short.
- Entries MUST state plainly what does NOT yet exist or work, so planning output is never mistaken
  for a running system.
- The log MUST record accepted risks and trade-offs together with the condition under which they
  should be revisited, rather than leaving them implicit in the design documents.
- The log is a teaching document, not a changelog. Git history already records what changed; this
  file records the reasoning a future reader cannot reconstruct from a diff.
- An entry that its intended reader cannot follow is a defect in the entry and MUST be rewritten
  on request.

Rationale: the reasoning behind a decision is the most valuable and most perishable artifact in a
project. It is absent from the code, absent from the diff, and gone from memory within weeks.
Recording it in plain language is what makes the difference between maintaining a system and
merely possessing it — and between engineering a system and having prompted one into existence.

## Technology Stack & Constraints

- **Language**: Python 3 for all application services. The exact minor version is pinned once in
  each service's `Dockerfile` and kept identical across services.
- **Message broker**: RabbitMQ.
- **Database**: PostgreSQL.
- **Runtime/orchestration**: Docker Compose (local and test environments).
- **Dependencies**: each service declares pinned dependencies in its own manifest. New
  dependencies MUST serve a present requirement (Principle V).
- **Logging**: services MUST log to stdout/stderr; each processed event's log lines MUST include
  its event ID so a transaction can be traced from Producer through Worker.
- **Performance**: "real-time" targets (throughput, end-to-end latency) MUST be stated as
  measurable numbers in each relevant feature spec; they are not assumed globally.

Changing any item in this section (language, broker, database, orchestration) requires a
constitution amendment.

## Development Workflow & Quality Gates

- Every feature follows the Spec Kit flow: specify → plan → tasks → implement. The plan MUST
  include a Constitution Check against Principles I–VI before implementation begins.
- No unit of work is complete until `LEARNING-LOG.md` has been updated for it (Principle VI). This
  applies to documentation-only work, including specs, plans, and task lists.
- Fraud-detection rules MUST have unit tests covering both flagged and non-flagged cases.
- The Producer → RabbitMQ → Worker → PostgreSQL path MUST have at least one integration test that
  runs against the real services in Docker Compose (no mocking of the broker or database in that
  test).
- Changes to a message contract or database schema MUST update the contract documentation or
  migration in the same change.
- Code review MUST verify compliance with this constitution, with particular attention to
  unjustified abstractions (Principle V).

## Governance

- This constitution supersedes other project practices and conventions. Where they conflict,
  this document wins.
- Amendments are made by editing this file through a reviewed change that states the reason,
  the version bump, and any migration impact on existing services.
- Versioning follows semantic versioning:
  - MAJOR: removal or backward-incompatible redefinition of a principle or stack constraint.
  - MINOR: a new principle or section, or materially expanded guidance.
  - PATCH: clarifications, wording, and typo fixes.
- Compliance is reviewed at every plan's Constitution Check and in every code review. Deviations
  MUST be recorded with justification in the plan's Complexity Tracking section, or the change
  is rejected.

**Version**: 1.1.0 | **Ratified**: 2026-10-23 | **Last Amended**: 2026-10-23

**Amendment history**:

- **1.1.0** (2026-10-23) — Added Principle VI (Explain the Work in Plain Language) and the
  corresponding workflow gate, requiring `LEARNING-LOG.md` to be updated with every unit of work.
  MINOR bump: a new principle was added, no existing principle was changed or removed. Migration
  impact: none on existing services (there are none yet); the Constitution Check table in every
  plan now carries a sixth row.
