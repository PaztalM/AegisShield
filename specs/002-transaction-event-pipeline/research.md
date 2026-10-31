# Research: Transaction Event Pipeline

Phase 0 output. Every decision that shaped the plan, why it was chosen, and what was rejected.

**Everything versioned below was established by querying the registry or installing the package, not from memory.** Feature 001 lost time twice to confident statements about dependencies that used to be true — a PostgreSQL data path that moved in version 18, and a version-tag shape PostgreSQL does not use. The rule that came out of it: a claim about how a dependency behaves is a claim to be executed, not argued.

---

## 1. Python version and base image

**Decision**: `python:3.14.10-slim`, pinned to the full patch version, identical in all three Dockerfiles.

**Verified, not assumed**:

```
docker manifest inspect python:3.14.10-slim   -> exists
docker run --rm python:3.14-slim python -V    -> Python 3.14.10
docker run --rm python:3.15-slim python -V    -> Python 3.15.2
pip install pika "psycopg[binary]" pytest     -> succeeds on 3.14, and on 3.15
```

**Rationale**: The constitution fixes Python 3 and requires the exact minor version to be pinned once per service and kept identical across services. 3.14 is one minor version behind the newest, which leaves more room for a future dependency that has not caught up yet, and nothing in this feature needs anything 3.15 introduced.

**A rationale I had and discarded, because checking disproved it**: the obvious argument for avoiding the newest minor is that compiled wheels lag behind a new Python release, so `psycopg[binary]` would have to build from source and fail in a `slim` image with no compiler. **That is not true here** — all three packages install cleanly on `python:3.15-slim`. So the honest reason for choosing 3.14 is conservatism with no requirement pulling the other way, not a wheel problem. Recorded because an invented justification is worse than a thin one: 3.15.2 is verified to work, and moving to it is a one-line change in three Dockerfiles if a reason ever appears.

**Alternatives considered**:

- **`python:3.15.2-slim`** — newest stable, verified working with our exact dependencies. Rejected only on the conservative ground above. This is a close call, not a clear one.
- **`python:3.14-slim`** (two-part tag) — satisfies the constitution's words ("exact minor version") but is a floating tag: it resolves to 3.14.10 today and something else next month. Feature 001's FR-013 lesson applies — pin what cannot move.
- **An Alpine-based image** (`python:3.14-alpine`) — smaller still, but Alpine uses musl rather than glibc, so manylinux wheels do not apply and C-extension packages like `psycopg[binary]` either need musl-specific wheels or a compiler in the image. Trading a reliable install for ~40 MB is a bad trade, and feature 001 already chose `-alpine` variants for the broker and database where no Python wheels are involved.
- **The full `python:3.14.10` image** — several hundred megabytes more for build tooling neither service needs at runtime.

---

## 2. RabbitMQ client library

**Decision**: `pika==1.4.4`, using `BlockingConnection`.

**Rationale**: Principle V says to use client libraries directly rather than wrapping them. `pika` is the reference Python client for AMQP 0-9-1 and the one RabbitMQ's own documentation uses. The blocking, single-threaded model is a good fit for a Worker that must do one thing at a time: read a message, decide, commit, acknowledge — in that order. Introducing concurrency would make the ordering guarantee in FR-017 harder to see and harder to prove.

**Alternatives considered**:

- **`aio-pika` / asyncio** — would require an async database driver too, an event loop, and careful reasoning about when a commit has actually happened relative to an acknowledgement. The throughput target (50/second) does not need concurrency, so this is complexity bought with no requirement behind it.
- **`kombu`, or Celery** — a task framework layered over the broker. Rejected on Principle II grounds as much as Principle V: Celery would own acknowledgement, retry and redelivery, which are precisely the behaviours the constitution requires this feature to control explicitly and prove. Handing them to a framework would mean the ack-after-commit rule is Celery's business rather than ours.
- **Writing AMQP by hand** — absurd, noted only for completeness.

**Known sharp edge, mitigated rather than ignored**: `pika`'s `BlockingConnection` services heartbeats on the same thread that runs your code. If a database operation blocks for longer than the heartbeat timeout, the broker concludes the consumer is dead and closes the connection — which surfaces later as a confusing `StreamLostError` rather than as a database problem. Mitigations: `basic_qos(prefetch_count=1)` so only one message is outstanding, a heartbeat comfortably longer than the slowest expected database call, and the reconnect loop that FR-021 requires in any case. Recorded as an accepted risk in plan.md with the condition for revisiting it.

---

## 3. PostgreSQL client library

**Decision**: `psycopg[binary]==3.3.6`, used directly.

**Rationale**: psycopg 3 is the current generation of the standard PostgreSQL adapter for Python. The `[binary]` extra installs a prebuilt wheel, so the image needs no compiler and no `libpq-dev` — verified above. Used directly with explicit transactions, because the ack-after-commit rule depends on knowing exactly when a commit happens.

**Alternatives considered**:

- **`psycopg2`** — the previous generation. Still widely used, but there is no reason to start new code on it.
- **SQLAlchemy, or any ORM** — explicitly excluded by Principle V. There is one table and one insert pattern; an ORM would be an abstraction over a single concrete case.
- **A repository or data-access layer of our own** — same objection, and Principle V names "repository layer" as an example of what not to add.
- **`asyncpg`** — fast, but async; see the `aio-pika` reasoning.

---

## 4. How the schema is created and changed

**Decision**: numbered plain SQL files in `worker/migrations/`, applied automatically at Worker startup by a short runner (`migrate.py`) that records applied versions in a `schema_migrations` table and holds a PostgreSQL **advisory lock** while it works.

New term: an **advisory lock** is a lock the application asks PostgreSQL to hold on an arbitrary number, which PostgreSQL itself arbitrates. It does not lock any table; it just guarantees that only one holder at a time gets it. It is the standard way to make "only one process does this at once" safe without inventing a coordination mechanism.

**Rationale**: Principle III requires versioned SQL migration files checked into the repository, applied automatically, with manual schema edits prohibited. Three constraints then narrow the design sharply:

- The Worker is the **only** service that touches the database, so letting it run migrations means there is no cross-service race to coordinate.
- The advisory lock means that even two Workers starting simultaneously cannot both apply the same migration — which matters because FR-015 requires repeated application to be safe.
- FR-023 forbids changing the `postgres` service definition, which rules out the usual Docker trick entirely (see below).

**Alternatives considered**:

- **`/docker-entrypoint-initdb.d` on the postgres image** — the conventional way to seed a schema. Rejected for two independent reasons, either sufficient: it requires mounting a directory into the `postgres` service, which **FR-023 forbids**; and those scripts run only when the data directory is first initialised, so they would silently not apply to the volume that already exists on this machine. The second reason is the more dangerous one — it would appear to work on a fresh clone and do nothing for every existing developer.
- **Alembic** — a real migration framework, but it brings SQLAlchemy and a migration DSL to manage one table. Principle V, plainly.
- **A separate one-shot `migrate` service in Compose** — a defensible pattern, and the usual answer when several services share a database. Rejected here because there is exactly one database writer, so the extra component buys nothing but adds a startup ordering dependency and another thing to explain.
- **Creating the table from application code with `CREATE TABLE IF NOT EXISTS` and no version tracking** — simplest of all, and it fails Principle III's requirement for *versioned* migration files. It also has no answer for the second change, which is when the absence of versioning actually hurts.

---

## 5. Where unprocessable messages go

*The specification deliberately left this open — the constitution permits either rejection or dead-lettering.*

**Decision**: a **dead-letter queue**. The main queue is declared with an `x-dead-letter-exchange` argument; the Worker rejects a message it cannot understand with `basic_nack(requeue=False)`, which routes it to the dead-letter queue instead of discarding it.

New term: **dead-lettering** is the broker's own mechanism for setting aside a message that was rejected, expired, or overflowed, by republishing it to a nominated exchange. The messages are then sitting in an ordinary queue that can be counted and inspected.

**Rationale**: FR-019 requires unprocessable messages to be retrievable afterwards and to not block what is behind them, and FR-029 requires the count to be observable. A dead-letter queue delivers all three for free: `rabbitmqctl list_queues` shows the depth, the management interface shows the payloads, and the main queue keeps moving.

**Alternatives considered**:

- **`basic_nack(requeue=True)`** — puts the message back. For a message that can never be parsed this is an infinite loop that redelivers the same poison message forever, which is exactly the blocking failure FR-019 forbids.
- **Reject and log the payload** — satisfies "not silently dropped" in the weakest possible sense. The message itself is gone; only a log line remains, and logs rotate. Counting failures would mean grepping.
- **An `unprocessable_events` table in PostgreSQL** — rejected on two grounds: the message could not be understood well enough to record meaningfully as structured data, and it puts a messaging concern into the system of record. The broker already has a purpose-built mechanism.

**Sharp edge, recorded as an accepted risk**: queue arguments in RabbitMQ are **immutable**. Declaring a queue that already exists with different arguments fails with `PRECONDITION_FAILED` rather than updating it. So the dead-letter configuration must be right the first time the queue is created. Changing it later means deleting the queue or running `docker compose down -v`. This must be written into the quickstart as a known operational step, not discovered by whoever changes it first.

---

## 6. How the velocity rule reads history

*The specification deliberately left the mechanism open, fixing only the property: FR-012 forbids depending on history held in memory.*

**Decision**: a `SELECT count(*)` against `fraud_decisions`, filtered by account and time window, executed in the **same transaction** as the insert that follows it, supported by an index on `(account_id, occurred_at)`.

**Rationale**: FR-012 exists because memory dies with the process. An in-memory sliding window means the same transaction gets a different verdict depending on how recently the Worker restarted, and two Workers would disagree with each other — a decision that depends on uptime is not a decision. The decisions table is already the system of record under Principle III, so reading history from it adds no new component. Doing the read and the write in one transaction makes them atomic.

**Boundary behaviour, which FR-011 requires to be defined rather than discovered**:

- **Amount rule**: flagged when `amount > threshold`, strictly greater. A transaction exactly at the threshold is **not** flagged.
- **Velocity rule**: count prior decisions for the same account whose `occurred_at` is strictly later than `now - window`, then flag when `count + 1 >= threshold` — the transaction being decided counts toward its own total. A prior transaction exactly `window` seconds old falls **outside** the window and is not counted.

Both are arbitrary but must be written down, because two implementers would otherwise choose differently and both believe they were right.

**Alternatives considered**:

- **An in-memory deque per account** — fastest, and forbidden by FR-012. Would also leak memory across unbounded account identifiers unless pruned, which is more code than the query.
- **Redis or any cache** — Principle III permits exactly one datastore and says adding another requires a constitution amendment. Not worth an amendment for a count.
- **A materialised counter column updated on write** — faster reads, but it is a denormalisation that has to be kept correct under redelivery and rollback, which is far more subtle than a count. Premature.

**Accepted limitation**: only *decided* transactions are in the table, so events still in flight are not counted and the velocity count can undercount slightly. It is deterministic and identical across restarts and across Workers, which is what FR-012 actually asks for. Revisit if throughput rises enough that in-flight events become a meaningful fraction of a window.

---

## 7. How the new services report health

**Decision**: each service touches a **heartbeat file** on every loop iteration; the Compose healthcheck checks that the file was modified recently.

**Rationale**: FR-030 requires each service to report whether it is working, so that `docker compose up -d --wait` waits for the whole pipeline rather than only for the broker and database. Neither service listens on a port, so the usual HTTP health endpoint does not exist. A heartbeat file requires no port, no framework, and no dependency, and it reports the thing that actually matters: *the loop is still turning*.

**Alternatives considered**:

- **An embedded HTTP health endpoint** — the familiar answer, and it means adding a web framework and exposing a port to a service that otherwise has no network surface. Principle V: no machinery for a requirement that a file satisfies.
- **Checking the process is alive** (`pgrep`, or Docker's default of "the container is running") — this is precisely the false-ready failure feature 001 spent effort eliminating. A process can be alive and wedged; T038 proved the distinction matters by freezing PostgreSQL and watching the container stay `running` while the healthcheck correctly turned `unhealthy`.
- **Having the healthcheck open its own connection to the broker and the database** — tests the dependencies rather than the service, duplicates the service's connection logic, and would report healthy while the service's own loop is stuck.

---

## 8. Where tests run, and how

**Decision**: a third Compose entry, `tests`, carrying `profiles: ["test"]`, invoked with `docker compose run --rm tests`. Unit tests import the rule functions directly; one integration test publishes to the real broker and asserts against the real database.

**Rationale**: FR-026 forbids host-installed dependencies, so `pytest` cannot run on the host — it must run in a container. A plain Compose service would start on every `docker compose up`, which is wrong for something that runs once and exits. A profile is the mechanism Compose provides for precisely this, and `docker compose run` activates a service's profile automatically.

This breaks a rule feature 001 wrote into its own Compose file header ("no profiles"), so it is justified in plan.md's Complexity Tracking and the header comment is corrected in the same change. Feature 001's rule was a statement about its own scope — it had nothing to put behind a profile — not a constitutional ban.

**Alternatives considered**:

- **`pytest` in the Worker image, run via `docker compose exec worker pytest`** — no profile needed, but it puts test-only dependencies into a runtime image, cutting against the constitution's rule that each service's pinned dependencies serve a present requirement.
- **A second Compose file** (`docker-compose.test.yml`) — breaks feature 001's stronger "exactly one Compose file" rule and splits the environment definition in two places that then drift.
- **`pytest` on the host** — violates FR-026 outright.

**On mocking**: FR-032 requires the integration test to run against the real broker and real database with neither replaced. This is deliberate and worth stating: the failures this feature must not have — a message acknowledged before its commit, a duplicate row, a poison message blocking a queue — are all failures *of the interaction* between the service and its dependencies. A mock is built from the same assumptions as the code it tests, so it would agree with the code and prove nothing. Feature 001's experience is the evidence: four of five surprises came from a dependency behaving differently than assumed, and no mock would have caught any of them.

---

## 9. Retrying dependencies instead of exiting

**Decision**: a small bounded-exponential-backoff loop around connection establishment in both services — retry indefinitely with a capped delay, logging each attempt, never exiting on a dependency being unavailable.

**Rationale**: Principle IV requires it explicitly, and feature 001 recorded this requirement as deliberately deferred because the party that must retry is an application service and it shipped none. `depends_on: condition: service_healthy` handles the startup race, but it does nothing for a dependency that disappears *mid-run* — which is exactly User Story 3's second and third acceptance scenarios, restarting the broker and the database underneath a running pipeline.

**Alternatives considered**:

- **Relying only on Compose healthcheck gating** — covers startup, not mid-run loss. A broker restart would kill both services permanently.
- **`tenacity` or a retry library** — a dependency for roughly ten lines of loop. Principle V.
- **Exiting and letting `restart: unless-stopped` handle it** — tempting, because the restart policy exists. Two objections. First, Principle IV says "retry connections instead of crashing permanently", which is a direct instruction. Second, and more practical: feature 001 measured that Docker's restart policy does **not** fire for a stop or kill issued through the Docker API, only for the container's own process exiting — so the behaviour here would be subtly different from what the policy appears to promise, and reasoning about it would be one more thing to get wrong.
- **Unbounded immediate retries** — hammers a recovering dependency and fills the logs. The cap is what makes backoff useful.

---

## 10. Logging

**Decision**: Python's standard `logging` module to stdout, plain text, with the event identifier included in every line concerning an event.

**Rationale**: The constitution requires logging to stdout/stderr with the event ID present so a transaction can be traced from Producer to Worker, and SC-010 puts a two-minute budget on doing exactly that. Standard library, no dependency, directly readable with `docker compose logs`.

**Alternatives considered**:

- **`structlog`, or JSON log lines** — better for machine consumption, and nothing consumes these logs yet. Principle V. Worth revisiting the moment log aggregation appears, which is a concrete trigger rather than a vague "later".
- **A correlation-ID framework or logging filter** — one field in a format string does not need machinery.

---

## 11. Publishing durably

**Decision**: durable queue, `delivery_mode=2` (persistent messages), and **publisher confirms** enabled on the Producer's channel.

New term: a **publisher confirm** is the broker telling the publisher it has taken responsibility for a message. Without confirms, `basic_publish` returns as soon as the message is written to the socket, which says nothing about whether the broker ever got it.

**Rationale**: FR-006 requires transactions to be handed over durably, and the spec's edge cases require that the Producer "must not pretend to have published". Those are the same requirement from two directions, and confirms are what make the difference between knowing and assuming. Durable queue plus persistent messages plus confirms is the combination that survives a broker restart; any one of the three missing breaks the guarantee.

**Alternatives considered**:

- **Fire-and-forget publishing** — faster, and it makes the Producer's success log a lie whenever the broker is struggling. Explicitly ruled out by the spec's edge case.
- **Transactions (`tx_select`)** — AMQP's older alternative to confirms, substantially slower and offering nothing extra here.
