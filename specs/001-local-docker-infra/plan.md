# Implementation Plan: Local Docker Infrastructure

**Branch**: `001-local-docker-infra` (spec directory; work happens on `dev`) | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-local-docker-infra/spec.md`

## Summary

Deliver the two infrastructure components every later AegisShield feature depends on — a RabbitMQ broker and a PostgreSQL database — as a single root `docker-compose.yml` that a developer starts with one command, plus a committed `.env.example` and README instructions.

Technical approach: one Compose file at the repository root declaring two services on one explicit user-defined bridge network, two named volumes, and a readiness healthcheck per service that proves the component accepts TCP connections rather than merely that the container exists. Every credential, database name, vhost, and published host port comes from environment variables interpolated from `.env`; secret-bearing variables use Compose's required-variable syntax (`${VAR:?message}`) so a missing value fails the start with a message naming the variable, while host ports use defaulted syntax (`${VAR:-5672}`) so they are overridable without editing the file. Images are pinned to full `major.minor.patch` tags verified to exist in the registry. No scripts, wrappers, Makefiles, or custom entrypoints are introduced — the documented interface is plain `docker compose` commands (`up -d --wait`, `ps`, `logs`, `down`, `down -v`), per constitution Principle V.

## Technical Context

**Language/Version**: None. This feature ships declarative YAML, a dotenv file, and Markdown. No application code, so no Python in this feature (Python 3 arrives with the Producer and Worker features).

**Primary Dependencies**: Docker Engine and Docker Compose v2+ on the host (prerequisite, not shipped). Images: `rabbitmq:4.2.4-management-alpine` and `postgres:18.4-alpine` — both tags verified present in the registry on 2026-10-23.

**Storage**: Two Docker named volumes — one for the PostgreSQL data directory (`/var/lib/postgresql/data`), one for the RabbitMQ Mnesia directory (`/var/lib/rabbitmq`).

**Testing**: Manual and scripted verification through the container tooling and standard clients, per `quickstart.md`. No test framework is added here; the automated integration test the constitution requires for the Producer → RabbitMQ → Worker → PostgreSQL path belongs to the feature that introduces those services and will run against this same Compose file.

**Target Platform**: Developer workstations (Linux, macOS, Windows with WSL2) running Docker Desktop or Docker Engine. Verified host for this plan: Windows 10 Pro, Docker 29.9.1, Docker Compose v5.6.0.

**Project Type**: Local infrastructure / development environment definition.

**Performance Goals**: Start-to-healthy under 5 minutes on a cold machine including image pulls (SC-001); under 60 seconds once images are cached (SC-002). Throughput and latency targets are out of scope here, per the constitution's Technology Stack section and the spec's assumptions.

**Constraints**: No host-installed dependency beyond Docker and Compose (FR-018, Principle IV). No `latest` or floating tags (FR-013). No secrets committed and no values hard-coded in the Compose file (FR-005, FR-007). RabbitMQ's stock `guest` account must be unreachable (FR-008). The file must accept the Producer and Worker later without restructuring (FR-015).

**Scale/Scope**: One instance of each component, one machine, one developer. Two services, two volumes, one network, roughly ten environment variables.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Applies here | Assessment |
|---|---|---|
| **I. Explicit Service Boundaries** | Partially — no application service added | PASS. This feature adds no new service to the system; it provisions the two infrastructure dependencies the constitution already names. No shared package and no cross-service import is created, because no code is shipped. The Compose file is shaped so Producer and Worker drop in later as their own directories with their own Dockerfiles (FR-015). |
| **II. Message-Driven Communication via RabbitMQ** | Partially | PASS. The broker is provisioned with durable-queue support intact (FR-020); a fixed container `hostname` keeps the Mnesia node name stable so durable definitions survive container recreation. No exchange, queue, or binding is declared here — topology belongs to the services that own it. Nothing in this feature introduces an HTTP/RPC path or a database-as-channel path between services. |
| **III. PostgreSQL as the System of Record** | Partially | PASS. PostgreSQL is the only datastore introduced; no cache or second store is added. No schema is created here, so no migration is owed yet — the database is created empty and named, and the first migration arrives with the Worker feature. Credentials and connection settings come from environment variables only, never hard-coded. |
| **IV. Docker Compose Runs Everything** | Fully — this is the principle this feature implements | PASS. Single root `docker-compose.yml`, started by `docker compose up`. No host dependency beyond Docker and Compose. Configuration through environment variables with a committed `.env.example`; `.env` is already git-ignored. Healthchecks gate startup, and `depends_on: service_healthy` is available to the services added later. Both images pinned to explicit `major.minor.patch` tags. |
| **V. No Premature Abstraction** | Fully | PASS. No wrapper script, Makefile, helper CLI, env-templating layer, Compose `profiles`, override file, or `include:` is introduced. One file, read directly; the documented interface is the raw `docker compose` subcommands. Healthchecks use tools already inside each official image rather than a custom check script. No speculative variable is added — every variable in `.env.example` is read by the Compose file. |
| **VI. Explain the Work in Plain Language** | Fully | PASS. `LEARNING-LOG.md` exists at the repository root and carries an entry covering this feature: what the constitution, spec, plan, and task list each are, why planning precedes code, every decision in `research.md` restated in plain language with its rejected alternatives, what does not yet exist, and a glossary. The accepted Alpine-collation risk is recorded there with its revisit condition, not left implicit. Task T044 keeps the log current once implementation lands. |

**Gate result: PASS, no violations. Complexity Tracking stays empty.**

### Design-time rules this plan commits to (derived from the table above)

1. No second Compose file, no override file, no `profiles:`, no `include:` — one `docker-compose.yml` (Principle IV, FR-001).
2. No shell script and no custom image build in this feature. If a step cannot be expressed in Compose plus official-image environment variables, it is out of scope rather than scripted around (Principle V).
3. No RabbitMQ `definitions.json` import and no PostgreSQL `init.sql` — topology and schema belong to their owning features (Principles II and III, and the spec's assumptions).
4. Every `.env.example` entry must be referenced by `docker-compose.yml`, and every `docker-compose.yml` interpolation must appear in `.env.example` (FR-005, FR-006).

### Post-design re-check (after Phase 1)

Re-evaluated against the design recorded in `research.md`, `data-model.md`, and `contracts/`: still **PASS**, no violations and nothing added to Complexity Tracking. Two design choices were examined specifically because they could have become abstractions and were kept minimal:

- **Readiness checks** are single built-in commands (`rabbitmq-diagnostics check_port_connectivity`, `pg_isready -h 127.0.0.1`), not a custom health script — Principle V holds, and FR-010's "actually accepts connections" is satisfied because both check the TCP listener.
- **Missing-configuration detection** uses Compose's own `${VAR:?message}` syntax rather than a preflight validation script — the edge case is covered by the tool, so no new layer appears.

One deliberate deviation from the spec's literal wording, which is a tightening rather than a violation: `.env.example` ships a non-blank development password, so copying it yields a working environment as FR-006 requires, while `${VAR:?}` guards still catch an empty or truncated `.env`. The spec's Assumptions section explicitly accepts development-grade default credentials in the committed example.

## Project Structure

### Documentation (this feature)

```text
specs/001-local-docker-infra/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── environment-variables.md
│   ├── service-endpoints.md
│   └── operator-commands.md
├── checklists/
│   └── requirements.md  # Pre-existing spec quality checklist
├── spec.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
docker-compose.yml       # NEW — environment definition: two services, one network, two volumes
.env.example             # NEW — every variable the Compose file reads, with development defaults
.env                     # NOT COMMITTED — the developer's active config; already in .gitignore
README.md                # NEW — start/status/logs/stop/reset commands, endpoints, credential source
LEARNING-LOG.md          # EXISTS — plain-language record of the work; updated per Principle VI
.gitignore               # EXISTS — already ignores .env; no change expected
```

**Structure Decision**: Flat repository root. This feature creates no `src/` or `tests/` tree because it ships no code; the per-service directories the constitution requires (`producer/`, `worker/`, each with its own `Dockerfile` and dependency manifest) are created by their own features and will reference this same root Compose file. Documentation lives in the root `README.md`, which is where the spec's final assumption places it and where a new contributor looks first (FR-017).

## Complexity Tracking

> No Constitution Check violations. This feature introduces no abstraction, no extra project, and no deviation, so this table is intentionally empty.
