# Phase 0 Research: Local Docker Infrastructure

**Feature**: `001-local-docker-infra` | **Date**: 2026-10-23

The Technical Context in [plan.md](./plan.md) contains no `NEEDS CLARIFICATION` markers. Everything it states is resolved below: image versions were verified against the live registry, and each remaining decision traces to a functional requirement, a success criterion, or an edge case in [spec.md](./spec.md).

Verification environment: Windows 10 Pro, Docker 29.9.1, Docker Compose v5.6.0.

---

## 1. Image versions and pinning

**Decision**: `rabbitmq:4.2.4-management-alpine` and `postgres:18.4-alpine`, both pinned to the full `major.minor.patch` tag.

**Rationale**: FR-013 forbids floating tags. A `4.2` or `18` tag is still floating across patch releases, so only a three-part tag actually pins the image. Both tags were confirmed to exist by `docker manifest inspect` on 2026-10-23, which also established the ceiling of each line — `rabbitmq:4.2.5-management-alpine` does not exist, so 4.2.4 is the current head of the 4.2 line:

| Tag probed | Present |
|---|---|
| `rabbitmq:4.2.4-management-alpine` | yes (**chosen**) |
| `rabbitmq:4.2.5-management-alpine` | no |
| `rabbitmq:4.3.0-management-alpine` | yes |
| `rabbitmq:4.1.8-management-alpine` | yes |
| `postgres:18.4-alpine` | yes (**chosen**) |
| `postgres:18.3-alpine` | yes |
| `postgres:17.6-alpine` | yes |

The `-management` variant is required by User Story 2: the management plugin must be enabled without a custom image or a plugin-enable step. RabbitMQ 4.2 was chosen over 4.3.0 because 4.3.0 is the first release of a new minor line, and nothing in this feature needs anything from it; 4.2.4 has had patch releases land on it.

**Alternatives considered**:
- *`latest` or `4-management`* — rejected outright by FR-013.
- *Two-part pins (`4.2-management-alpine`, `18-alpine`)* — rejected: convenient, but the image silently changes under the developer, which is the reproducibility problem FR-013 exists to prevent.
- *Debian-based `postgres:18.4` instead of Alpine* — a real trade-off. The Alpine variant is built on musl and offers only limited locale/ICU collation support, so text sort order can differ from a glibc-based production image. Alpine was chosen anyway: the spec explicitly places production out of scope, no schema or text index exists yet, and the smaller image serves SC-001 and SC-002. **Recorded risk**: if a future feature depends on a specific collation, switching the database image to the Debian variant requires a volume reset, so that decision is cheapest to revisit before the first migration lands.
- *RabbitMQ 3.13* — rejected; the 3.x line is end-of-life and 4.x is the current supported series.

---

## 2. Readiness checks that prove connections are accepted

**Decision**:
- Broker: `rabbitmq-diagnostics -q check_port_connectivity`
- Database: `pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"`

Both run inside their own container, so neither adds a host dependency (FR-018). Each uses `interval`, `timeout`, `retries`, and `start_period` so that a slow first start is not reported as a failure, while a genuinely dead component eventually goes `unhealthy` (FR-019).

**Rationale**: FR-010 demands that readiness be decided by a real connection check, not by container creation, and the spec's edge cases call out components that accept connections later than their container appears. `check_port_connectivity` opens a TCP connection to every listener the node has published, which is exactly the "does it accept connections" question; `check_running` only asserts that the Erlang application started and can pass before the AMQP listener is bound.

The `-h 127.0.0.1` on `pg_isready` is the important detail. During first-start initialization the official PostgreSQL entrypoint runs a temporary server bound to the Unix socket only (`listen_addresses=''`), so a socket-based `pg_isready` reports "ready" while the real TCP listener does not yet exist — a false positive that would make Compose declare the environment ready too early and break SC-003. Forcing the check over TCP loopback means the healthcheck can only pass once the server a client would actually use is listening.

**Alternatives considered**:
- *`rabbitmq-diagnostics ping` or `check_running`* — rejected as above: passes before the port is bound.
- *Bare `pg_isready`* — rejected for the initialization false positive.
- *`psql -c 'SELECT 1'`* — works, but heavier than `pg_isready` and no more informative here.
- *A shell script healthcheck* — rejected under Principle V; the built-in commands cover the requirement.
- *No healthchecks, relying on application-side retries* — rejected: Principle IV says healthchecks SHOULD gate startup, and FR-010/FR-019/SC-003 require them. Application-side retry (Principle IV) remains the responsibility of the Producer and Worker and is complementary, not a substitute.

---

## 3. Waiting for readiness from the start command

**Decision**: the documented start command is `docker compose up -d --wait`.

**Rationale**: FR-010's second half requires the start command to be able to wait for both checks before reporting ready, and SC-003 requires that a developer never has to guess. `--wait` blocks until every service with a healthcheck is healthy and returns a non-zero exit code if one does not get there, which turns "is it up yet" into an exit status. Plain `up -d` returns as soon as containers are created.

**Alternatives considered**: a polling loop around `docker compose ps` (rejected — a script, Principle V); `up` in the foreground (acceptable for watching logs and documented as such, but it does not give a clean ready signal).

---

## 3a. Tooling available inside the images (verified)

**Decision**: all verification and administration in `quickstart.md` uses tools already inside the containers; nothing is installed on the host and nothing is added to the images.

**Rationale**: FR-018 forbids any host-installed dependency beyond Docker. Inspected `rabbitmq:4.2.4-management-alpine` directly on 2026-10-23:

| Tool | Present | Use |
|---|---|---|
| `rabbitmqctl` | yes | `list_queues`, `list_users` — no HTTP API credentials needed |
| `rabbitmq-diagnostics` | yes | the healthcheck (`check_port_connectivity`) |
| `rabbitmqadmin` | yes — **v2, version 2.27.0** | declaring and purging queues from the command line |
| `curl` | **no** | — HTTP API checks must go through `rabbitmqadmin` |

Two consequences worth recording, because both silently break copied-from-the-internet commands:

1. **`rabbitmqadmin` v2 has different syntax from the v1 Python script.** It is `declare queue --name X --durable true`, not `declare queue name=X durable=true`. It also talks to the HTTP API and therefore needs `-u`/`-p`; it defaults to `guest`, which this environment never creates (FR-008), so every invocation must pass the project account.
2. **Variables must be expanded inside the container.** `.env` is read by Compose for interpolation, not exported into the developer's shell, so `docker compose exec postgres psql -U "$POSTGRES_USER"` expands to an empty username on the host. The correct form is `docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" ...'` with single quotes, letting the container's shell expand variables the image already has.

**Alternatives considered**: installing `curl` or a client into the image via a custom `Dockerfile` (rejected — a build step and a host-visible abstraction for something the bundled tools already do, Principle V and FR-018); documenting host-installed `psql` and an AMQP client (rejected by FR-018, though the spec's acceptance scenarios also allow a host client, which `quickstart.md` keeps as the optional host-side proof).

---

## 4. Supplying configuration, and failing clearly when it is missing

**Decision**: a two-tier interpolation scheme in the Compose file, with no `env_file:` directive.

- Secret-bearing and identity values use required syntax: `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set - copy .env.example to .env}`. The separator is a plain ASCII hyphen, not an em dash, because the message is printed to a terminal that may be running the cp1252 code page.
- Published host ports use defaulted syntax: `${POSTGRES_PORT:-5432}`.

**Rationale**: Compose automatically loads `.env` from the project directory for interpolation, so copying the example file is the only preparation step (FR-006). The `:?message` form makes Compose abort before starting anything, printing the variable name and the message — which is precisely the spec's edge case "the active configuration file is missing or incomplete: the developer is told which setting is missing and where the example file is, instead of getting an opaque authentication failure." The `:-default` form satisfies FR-004's overridability while keeping `5672`, `15672`, and `5432` as the defaults FR-002 and FR-003 name.

Container-side ports stay fixed at their canonical values, so an override changes only the host side. That keeps the internal address stable for FR-014 and FR-015 — a service added later connects to `rabbitmq:5672` and `postgres:5432` by name regardless of what the host publishes.

Credentials are passed into the containers with explicit `environment:` keys rather than `env_file:`, so the Compose file documents exactly which variable each image consumes and nothing extra leaks into the container environment.

**Alternatives considered**:
- *`env_file: .env`* — rejected: it injects every variable into the container, hides which ones the image actually reads, and does not participate in `:?` validation.
- *Docker secrets* — rejected as production machinery for a local development environment (Principle V, and the spec's assumptions).
- *Hard-coded development defaults in the Compose file* — rejected by FR-005 and SC-007.

---

## 5. Broker account, and locking out `guest`

**Decision**: set `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS`, and `RABBITMQ_DEFAULT_VHOST`, and take no other action about `guest`.

**Rationale**: FR-008 requires a project-defined administrative account and that the stock guest account not be reachable. When the official image sees `RABBITMQ_DEFAULT_USER`/`PASS`, it writes a generated configuration that creates that user as the node's administrator in place of the default `guest` account, so `guest` is never created on a fresh volume. That makes acceptance scenario 2.4 — signing in as `guest` is rejected — a property of the configuration rather than a cleanup step.

An explicit `RABBITMQ_DEFAULT_VHOST` is set because the spec's Key Entities name a broker virtual host as part of the configuration variable set, and because naming it now avoids a later change of connection URI for the services.

**Alternatives considered**: shipping a `rabbitmq.conf` with `loopback_users` settings (rejected — more moving parts for the same outcome, Principle V); deleting the guest user after start with a `rabbitmqctl` step (rejected — a script, and unnecessary since the user is never created).

---

## 6. Database and owning account on first start

**Decision**: set `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`; no init script.

**Rationale**: FR-009 requires a named application database and an owning account created on first start with no manual step. The official image's entrypoint does exactly this during initialization: it creates the superuser named by `POSTGRES_USER` and a database named by `POSTGRES_DB` owned by that user. Adding an `init.sql` would mean creating schema, which Principle III reserves for versioned migrations and the spec places out of scope.

**Alternatives considered**: a mounted `/docker-entrypoint-initdb.d` script (rejected for the reasons above); a separate non-superuser application role (rejected as speculative for a local development database — Principle V — and nothing in the spec asks for privilege separation).

---

## 7. Persistence, and the node-name trap

**Decision**: two named volumes; `postgres-data` → `/var/lib/postgresql`, `rabbitmq-data` → `/var/lib/rabbitmq`. The broker service additionally sets a fixed `hostname:`.

**The database path is version-sensitive, and the obvious value is wrong here.** `/var/lib/postgresql/data` is the path every pre-18 example uses, and it is the one this document first specified. The official PostgreSQL 18+ images changed the layout: `PGDATA` is now `/var/lib/postgresql/18/docker`, a major-version-specific subdirectory, and the declared `VOLUME` moved up to `/var/lib/postgresql` so that an eventual `pg_upgrade --link` does not have to cross a mount-point boundary. The image actively refuses to start when it finds a mount at the legacy path, printing `there appears to be PostgreSQL data in: /var/lib/postgresql/data (unused mount/volume)` — a deliberate guard, because that arrangement historically looked like an abandoned version upgrade and risked data loss. Since this feature pins `postgres:18.4-alpine`, the mount goes at `/var/lib/postgresql`. Confirm against any future image bump with `docker image inspect postgres:<tag>` rather than from memory.

**Rationale**: FR-011 requires named persistent storage so that a stop and start preserves database contents and durable broker definitions, and FR-012 requires one documented command to discard it (`docker compose down -v`). Named volumes also satisfy acceptance scenario 3.3 — Docker creates them on first start with no manual preparation.

The fixed `hostname:` is the non-obvious part and it is what makes acceptance scenario 3.1 actually pass for the broker. RabbitMQ derives its node name from the container hostname and stores its Mnesia database in a directory named after that node. Docker assigns a new random hostname whenever a container is recreated, so without a fixed hostname the restarted broker looks for a node directory that does not exist, initializes an empty one, and the developer sees their durable queues gone even though the volume was preserved. Pinning the hostname keeps the node name — and therefore the Mnesia path inside the volume — stable across recreation.

Persistence is also what makes durable queues meaningful for FR-020 and Principle II: the broker ships with durable queue and persistent message support enabled, and this feature's only obligation is to give it storage that survives a restart.

**Alternatives considered**:
- *Host bind mounts* — rejected: permission and path-translation problems across Linux/macOS/Windows hosts, and `down -v` would not clean them up. The root `.gitignore` already anticipates this by ignoring `data/`.
- *No volume for the broker* — rejected by FR-011 and FR-020.
- *`tmpfs`/ephemeral storage* — rejected by the spec's "persistence is on by default" assumption.

---

## 8. Network, and room for the Producer and Worker

**Decision**: one explicitly declared user-defined bridge network, `aegisshield-net`, joined by both services, with the service names `rabbitmq` and `postgres` as the stable internal addresses.

**Rationale**: FR-014 requires reachability from the host at published ports and from inside by a stable internal name; FR-015 requires that application services be addable without restructuring. Compose's default network would satisfy DNS resolution, but declaring the network explicitly makes it visible in the file that a later service joins the same network, and a named network plus `depends_on: {condition: service_healthy}` is the entire extension point SC-010 asks for: adding the Producer means adding a service block that lists the network and declares its dependency, with no edit to the two infrastructure service definitions.

No `container_name:` is set, so Compose keeps its project-scoped names and two projects can coexist; the fixed broker `hostname:` from section 7 is separate from the container name and does not collide.

**Alternatives considered**: relying on the implicit default network (rejected — works, but leaves the extension point undocumented); separate networks per concern (rejected as premature — Principle V, and two components with one consumer each need no segmentation); `container_name:` for prettier names (rejected — it breaks a second project on the same host for no functional gain).

---

## 9. Port-conflict behavior

**Decision**: rely on Docker's own bind failure; document the `*_PORT` override as the remedy.

**Rationale**: SC-009 requires failure within 10 seconds with a message naming the occupied port, and the edge case forbids silently binding elsewhere or starting partially. Docker fails the port bind when it creates the container and reports an error naming the host port and address, well inside 10 seconds; because the failure happens at container creation, the environment does not come up half-started. No preflight port scan is needed (Principle V), and FR-004's overridable ports — section 4 — give the developer the documented way out without editing the Compose file. Verifying both the timing and the message content is a `quickstart.md` scenario.

---

## 10. Logs and status

**Decision**: document `docker compose ps`, `docker compose logs -f <service>`, and the services' own names as the log selectors; add no logging configuration.

**Rationale**: FR-016 asks only that each component's logs be viewable individually through the tooling's standard log command, which both official images already satisfy by logging to stdout. FR-019 is satisfied by `docker compose ps`, which prints each service's health state, and by `up --wait` failing when a service does not become healthy. The constitution's logging rules about event IDs bind the application services, not these two images, so nothing here anticipates them.

**Alternatives considered**: a `logging:` driver block with rotation (rejected as speculative for local development — Principle V); shipping logs to a collector (out of scope).

---

## 11. Documentation placement

**Decision**: the root `README.md` carries the start, status, logs, stop, and reset commands, the three published endpoints, and a statement that credentials come from `.env` (copied from `.env.example`). It also records the credential-change caveat.

**Rationale**: FR-017 requires documentation where a new contributor finds it without being told, SC-008 holds that contributor to under 10 minutes unaided, and the spec's final assumption names the README. The credential-change caveat is called out by the spec's edge cases and matters for both images: once a volume is initialized, the database keeps the credentials it was created with, and a changed `POSTGRES_PASSWORD` or `RABBITMQ_DEFAULT_PASS` in `.env` will not take effect — it will fail to authenticate until the volume is discarded with `down -v`.

**Alternatives considered**: a `docs/` directory (rejected — one page of operational instructions in an otherwise empty repository belongs in the README the contributor already opens).

---

## Open risks carried into implementation

| Risk | Effect if it bites | Handling |
|---|---|---|
| Alpine PostgreSQL collation differs from a glibc production image | Text sort order and index behavior could differ later | Noted in section 1; switch to the Debian variant before the first migration if it matters, which requires a volume reset |
| A pinned patch tag is superseded between now and implementation | None functionally — the pin still resolves | Re-confirm with `docker manifest inspect` at implementation time; bump deliberately, never to a floating tag |
| SC-002's 60-second warm start on a slow workstation | Start-to-healthy might exceed 60s because of healthcheck `start_period` and interval choices | **Resolved during analysis (2026-10-23).** Concrete values are now fixed in `data-model.md` and quoted by tasks T010 and T014 — postgres `5s/5s/5/30s`, rabbitmq `10s/10s/6/60s` — rather than left to implementation-time discretion. A success during `start_period` marks a service healthy immediately, so the longer broker window delays nothing. T020 measures against these values; if they need changing, `data-model.md` and the tasks change together |
