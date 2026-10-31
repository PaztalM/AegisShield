---

description: "Task list for feature 002, the transaction event pipeline"
---

# Tasks: Transaction Event Pipeline

**Input**: Design documents from `/specs/002-transaction-event-pipeline/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Test tasks are included because the specification requires them explicitly — FR-031 (unit tests per rule including the boundary), FR-032 (one integration test against the real broker and real database with no stand-ins), FR-033 (an idempotency test), and SC-011.

**Organization**: Grouped by user story, so each can be implemented and validated as its own increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel — different files, no dependency on an unfinished task
- **[Story]**: `[US1]`–`[US4]`, mapping to the four user stories in spec.md
- Every task names the exact file it touches

## Path Conventions

Three top-level service directories at the repository root — `producer/`, `worker/`, `tests/` — per plan.md's Structure Decision. There is deliberately **no shared package**: Principle I forbids the services importing from one another, so each parses the event format independently against [contracts/transaction-event.md](./contracts/transaction-event.md).

Four files that already exist are **modified**, never replaced: `docker-compose.yml`, `.env.example`, `README.md`, `LEARNING-LOG.md`.

## Values are not open to interpretation

Where a task quotes a type, a default, a constraint or an exact SQL clause, that value comes from a design document and is authoritative. If implementation shows one is wrong, the document and the task change **together** — the code does not quietly diverge. This is the rule that made feature 001's documents trustworthy by the end.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: The build inputs for three container images, plus the two existing files that must be ready before any new service can start.

**Note on the base image**: `python:3.14.10-slim` is pinned to the full patch version and must be **identical in all three Dockerfiles**. This was established by querying the registry (research.md §1), not from memory.

- [x] T001 [P] Create `producer/Dockerfile`: `FROM python:3.14.10-slim`, `WORKDIR /app`, copy and `pip install --no-cache-dir -r requirements.txt`, copy the source, `CMD ["python", "-u", "producer.py"]`. The `-u` flag is required, not cosmetic: without unbuffered output, Python buffers stdout when it is a pipe and `docker compose logs` shows nothing until the buffer fills, which looks exactly like a service that is not running (FR-027). **Verified:** `docker build` succeeded and `docker run --rm <image> python -V` printed exactly `Python 3.14.10`, matching the pin.
- [x] T002 [P] Create `producer/requirements.txt` containing exactly `pika==1.4.4`. No `psycopg` — the Producer never touches the database, and the constitution requires every pinned dependency to serve a present requirement. **Verified:** `Successfully installed pika-1.4.4` during the build — so `pika` does install into `python:3.14.10-slim` with no C compiler present, which research.md asserted and this is the first time it has been true on this machine rather than in a planning note.
- [x] T003 [P] Create `worker/Dockerfile`: same base image and same shape as T001, `CMD ["python", "-u", "worker.py"]`. **Verified:** built clean; `python -V` inside the image reports `3.14.10`, byte-identical `FROM` line to T001.
- [x] T004 [P] Create `worker/requirements.txt` containing exactly `pika==1.4.4` and `psycopg[binary]==3.3.6`. The `[binary]` extra is what avoids needing a compiler in the slim image (research.md §3). **Verified:** pip fetched `psycopg_binary-3.3.6-cp314-cp314-manylinux2014_x86_64.whl` — a prebuilt wheel for Python 3.14, so nothing was compiled — and `psycopg.pq.__impl__` reports `binary` inside the image, confirming the C implementation is the one actually in use rather than the pure-Python fallback silently substituting for it.
- [x] T005 [P] Create `tests/Dockerfile` **and** a root `.dockerignore`. The Dockerfile uses the same base image, but unlike the other two it is built with the **repository root** as its context (see T013), so its paths are repo-relative: `WORKDIR /app`, `COPY tests/requirements.txt .`, `pip install --no-cache-dir -r requirements.txt`, `COPY worker/rules.py ./worker/rules.py`, `COPY tests/ ./tests/`, `ENV PYTHONPATH=/app`, `CMD ["python", "-m", "pytest", "tests", "-v"]`. The wider context is necessary and not laziness: a context of `./tests` would not contain `worker/rules.py`, and the unit tests could not import the rules — which is the entire reason `rules.py` is a separate file. The `.dockerignore` keeps `.git`, `specs/`, `.env`, `*.md` and the two service directories' build artifacts out of that context; it affects **only** this build, because `./producer` and `./worker` are subdirectory contexts and never read a root `.dockerignore`. **Verified:** a throwaway `COPY . /ctx` image shows the context contains only `.dockerignore`, `.env.example`, `.gitignore`, `docker-compose.yml`, `producer/`, `tests/` and `worker/` — `.env`, `.git`, `specs/`, `.specify/`, `.claude/` and all markdown excluded. **Partially verified only:** the build reaches `COPY worker/rules.py` and fails there, correctly, because T016 has not run. The last two `COPY` lines and the `CMD` remain unproven until T025 runs the suite.
- [x] T006 [P] Create `tests/requirements.txt` containing `pytest==9.2.0`, `pika==1.4.4`, `psycopg[binary]==3.3.6`. The test image carries all three because the integration test publishes to the real broker and asserts against the real database; `pytest` appears **here only** and must not enter either service image. **Verified:** a dependency-stage-only build installed `pytest-9.2.0 pika-1.4.4 psycopg-3.3.6 psycopg-binary-3.3.6` with `--no-cache`, and inside the image `pytest 9.2.0`, `pika 1.4.4`, `psycopg 3.3.6` with `impl binary` all report correctly on `python 3.14.10`.
- [x] T007 Add the new variables to `.env.example` with the exact defaults from [contracts/environment-variables.md](./contracts/environment-variables.md), each with a one-line comment naming which component reads it (FR-010, FR-025), grouped under new `# --- Producer ---`, `# --- Worker (fraud rules) ---` and `# --- Both services (operational) ---` headings: `RABBITMQ_HOST=rabbitmq`, `POSTGRES_HOST=postgres`, `PRODUCER_RATE_PER_SECOND=5`, `PRODUCER_FRAUD_RATIO=0.1`, `PRODUCER_ACCOUNT_POOL_SIZE=20`, `FRAUD_AMOUNT_THRESHOLD=5000.00`, `FRAUD_VELOCITY_COUNT=4`, `FRAUD_VELOCITY_WINDOW_SECONDS=60`, `LOG_LEVEL=INFO`, `RETRY_MAX_DELAY_SECONDS=30`, `HEARTBEAT_FILE=/tmp/heartbeat`, `HEARTBEAT_MAX_AGE_SECONDS=30`. That is **twelve** keys, bringing `.env.example` to **twenty-one** — the counts the contract now states, after the cross-check found it claiming eleven and twenty. T053 re-audits the parity at that number. **Done, with one deviation:** the task named three comment headings; the two hostnames did not belong under any of them, so they got a fourth, `# --- Service connections (feature 002) ---`. **Verified:** `.env.example` now holds 21 `KEY=` lines (9 + 12) and `docker compose config` still resolves. Note Compose currently interpolates only the original 9 — the 12 new keys are read by services that do not exist until T011–T013, so the parity audit is deliberately unbalanced until then.
- [x] T008 Correct the header comment in `docker-compose.yml`: it currently states "no profiles" as a design rule, which this feature breaks deliberately. Replace that clause with one naming the single exception and its reason — `tests` carries `profiles: ["test"]` so a one-shot test runner does not start on every `docker compose up`. Justified in plan.md's Complexity Tracking. Leaving the comment as-is would make the file contradict itself, which is worse than either choice alone. **Done.** The `no profiles` clause is replaced with a paragraph naming the single exception, why it exists, and where it is justified, plus the point that feature 001's wording was a statement about its own scope rather than a ban. **Verified:** `docker compose config` still parses.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The database schema, the thing that applies it, and the three Compose entries. No user story can run until the services exist in the environment definition and the table exists in the database.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T009 Create `worker/migrations/001_create_fraud_decisions.sql` with the `fraud_decisions` table exactly as specified in [data-model.md](./data-model.md): `event_id uuid PRIMARY KEY`, `account_id text NOT NULL`, `amount numeric(12,2) NOT NULL`, `merchant text NOT NULL`, `occurred_at timestamptz NOT NULL`, `decided_at timestamptz NOT NULL DEFAULT now()`, `flagged boolean NOT NULL`, `rule text` (nullable); the constraint `CHECK ((flagged = true AND rule IS NOT NULL) OR (flagged = false AND rule IS NULL))`; and the index on `(account_id, occurred_at)` in that column order — `account_id` is an equality match and must come first, `occurred_at` is a range match and must come second. Add **no** constraint on `amount`: the spec requires zero, negative and enormous amounts to receive a decision rather than crash the Worker, so the database must accept them. **Verified against a disposable PostgreSQL 18.4, seven checks:** the migration applies; a valid flagged row is accepted; a duplicate `event_id` is refused (`duplicate key value violates unique constraint`); flagged-with-no-rule and not-flagged-with-a-rule are both refused by the CHECK; `0.00`, `-50.00` and `9999999999.99` are all accepted; and `99999999999.00` fails with `numeric field overflow - must round to an absolute value less than 10^10`, which **demonstrates** the poison-message path T028's range rule exists to close rather than leaving it as a prediction. `CREATE TABLE` is used without `IF NOT EXISTS` deliberately: T010's runner records applied versions, so this file must run exactly once, and a second run means the runner is broken and should error loudly rather than shrug. **Index measured** on 300,000 rows over 20 accounts, running the exact velocity query: with the index, `Bitmap Index Scan`, 6 pages touched, **0.247 ms**; with the index dropped, `Parallel Seq Scan` across 3 workers, 3,704 pages, 99,997 rows discarded per worker, **105.76 ms**. That is **428x slower**, and 105 ms is five times the entire 20 ms per-message budget SC-004 allows - so without this index SC-004 is not merely harder, it is unreachable. This file is the whole of FR-013's stored shape and FR-016's database-enforced uniqueness.
- [x] T010 Create `worker/migrate.py`: create `schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())` with `CREATE TABLE IF NOT EXISTS` — the one place that pattern is correct, because no earlier migration could have created it; take a PostgreSQL advisory lock (`pg_advisory_lock` on a fixed integer) for the whole run so two Workers starting together cannot both apply `001`; list `migrations/*.sql` in lexicographic order; skip any `version` already present; apply each remaining file and record its version **in the same transaction** as the file's own statements; release the lock. Re-running must be a silent no-op (FR-014, FR-015). **Verified against a disposable PostgreSQL 18.4 on a Compose-like network, five checks:** run 1 on a fresh database logs `applying 001_create_fraud_decisions.sql` then `applied 001`; runs 2 and 3 log `up to date, 1 already applied` and change nothing; `\d fraud_decisions` confirms all eight columns, both the primary key and the `(account_id, occurred_at)` index; **two containers launched simultaneously against an empty database** produced exactly one `applying` and one `up to date`, with `count(*) = 1` for version `001` — the advisory lock works; and a deliberately broken `002` left `schema_migrations` untouched with zero advisory locks held, and did not block the next run. **One real defect found by running it and fixed:** the `finally` block needs `conn.rollback()` before the unlock. Without it, a failed migration leaves the transaction aborted, PostgreSQL rejects the unlock too, and the resulting `InFailedSqlTransaction` error *replaces* the actual SQL error — so the operator sees a transaction-state message instead of `syntax error at or near "is"` with the offending line. After the fix the real error surfaces. **One addition beyond the task:** an `if __name__ == "__main__":` block, so the runner can be executed on its own (`docker compose run --rm worker python migrate.py`). Without it nothing here could have been verified until T021 exists. `worker.py` will call `run_migrations(conn)` directly with its own connection, because it owns the retry loop and must not have two.
- [x] T011 Add the `producer` service to `docker-compose.yml`: `build: ./producer`, `depends_on: rabbitmq: condition: service_healthy`, `networks: [aegisshield-net]`, `restart: unless-stopped`, environment passing `RABBITMQ_HOST`, `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS`, `RABBITMQ_DEFAULT_VHOST`, `PRODUCER_RATE_PER_SECOND`, `PRODUCER_FRAUD_RATIO`, `PRODUCER_ACCOUNT_POOL_SIZE`, `LOG_LEVEL`, `RETRY_MAX_DELAY_SECONDS`, `HEARTBEAT_FILE`, `HEARTBEAT_MAX_AGE_SECONDS`. Credentials are passed through by reference to feature 001's existing variables — do **not** introduce a second set (contracts/environment-variables.md). No `container_name`, and no host port: the Producer has no inbound network surface. This entry is what makes FR-022 true — the new services start with the same single command as the rest of the system. **Placed after `rabbitmq` rather than alphabetically between `postgres` and `rabbitmq`,** so the file reads in dependency order: the things that must exist first, then the things that need them. Compose ignores order entirely; this is for the next reader. **Verified:** `docker compose config` parses, no tabs, and all eleven variables resolve — credentials from `.env`, tunables from their `:-` defaults. **Intermediate-state behaviour measured, because it will confuse anyone who meets it unwarned:** with `producer.py` absent until T018, the container exits with `python: can't open file '/app/producer.py': [Errno 2] No such file or directory`, exit code 2, and `restart: unless-stopped` retries it indefinitely — `RestartCount` reached 7 within about 20 seconds, status `Restarting (2)`. `postgres` and `rabbitmq` stayed `healthy` throughout, so a crash-looping new service does not disturb the existing environment. This is also the first real-world confirmation of feature 001's T040/T041 finding from the opposite direction: the restart policy **does** fire when the container's own process exits, where it did **not** fire for a kill issued through the Docker API.
- [x] T012 Add the `worker` service to `docker-compose.yml`: `build: ./worker`, `depends_on` on **both** `rabbitmq` and `postgres` with `condition: service_healthy`, same network and restart policy, environment as T011 plus `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `FRAUD_AMOUNT_THRESHOLD`, `FRAUD_VELOCITY_COUNT`, `FRAUD_VELOCITY_WINDOW_SECONDS`. The services must address the broker and database on their **internal** ports `5672` and `5432`, never `RABBITMQ_PORT` / `POSTGRES_PORT` — those publish to the host and a developer may relocate them, which feature 001's T036 proved is a real scenario. **One deliberate deviation:** “environment as T011 plus…” read strictly would hand the Worker the three `PRODUCER_*` variables. It does not read them, and giving a service settings it ignores is how someone changes a value, sees no effect, and loses an afternoon — so the Worker gets 15 variables, not 18. A variable appears where something reads it. **Verified through the real service definition, not a hand-built `docker run`:** `docker compose run --rm worker python migrate.py` gated on **both** dependencies reporting `Healthy`, then logged `up to date, 1 already applied` — one command proving the build, the four `POSTGRES_*` values, hostname resolution, and both `depends_on` conditions. A second run opened a `pika` connection with the four `RABBITMQ_*` values on internal port 5672, authenticated into vhost `aegisshield`, and declared a server-named exclusive queue — deliberately **not** `transactions`, whose arguments are immutable and must not be created by a test; `rabbitmqctl list_queues --vhost` afterwards showed zero queues, so nothing leaked. `postgres` and `rabbitmq` stayed `healthy` throughout, and both their blocks are **byte-identical** to feature 001 — 21 and 23 lines, zero changes (FR-023).
- [ ] T013 Add the `tests` service to `docker-compose.yml` with `build: { context: ., dockerfile: tests/Dockerfile }` — the repository root, per T005, **not** `./tests` — plus `profiles: ["test"]`, the same network, and the union of both services' environment variables. `depends_on` must name **three** services, each `condition: service_healthy`: `rabbitmq`, `postgres` **and `worker`**. The Worker is easy to leave out and the omission is not obvious, because the unit tests would still pass: the integration test publishes an event and then waits for a *decision*, which only the Worker produces, so with the Worker down the test hangs and then fails for a reason that has nothing to do with what it was testing. The Worker has a healthcheck from T014, so this dependency is available and exact. No `restart` policy — it runs once and exits. Invoked as `docker compose run --rm tests`, which activates the profile automatically.
- [x] T014 Add a heartbeat healthcheck to both the `producer` and `worker` entries in `docker-compose.yml`: a `CMD-SHELL` test asserting the heartbeat file is newer than `HEARTBEAT_MAX_AGE_SECONDS`, comparing `date +%s` against `stat -c %Y` on `$$HEARTBEAT_FILE` (note the `$$` escape — a single `$` is consumed by Compose interpolation), with `interval: 10s`, `timeout: 5s`, `retries: 3`, and a `start_period` long enough to cover image start plus the first loop iteration. This reports *the loop is still turning* rather than *the process exists* — the distinction feature 001's T038 proved matters when it froze PostgreSQL and the container stayed `running` while the healthcheck correctly turned `unhealthy`. **Done before T013, deliberately out of order.** T013's `tests` service must declare `worker: condition: service_healthy`, which is impossible until the Worker has a healthcheck — a dependency created by the U1 remediation that the task numbering never caught up with. Worse, `docker compose config` **accepts** `condition: service_healthy` against a healthcheck-less service and only fails at run time, so doing T013 first would have produced a file that validates and then breaks. **Verified in four stages.** (1) The shell logic, run inside `python:3.14.10-slim`: missing file → unhealthy, just-touched → healthy, 40s stale against a 30s limit → unhealthy, 29s old → healthy. `stat -c %Y`, `date +%s` and `test -f` all exist in the slim image. (2) The `$$` escaping, read back from what Docker actually stored: `test -f "$HEARTBEAT_FILE" && test $(( $(date +%s) - $(stat -c %Y "$HEARTBEAT_FILE") )) -lt "$HEARTBEAT_MAX_AGE_SECONDS"` — single `$` throughout. Note `docker compose config` prints `$$` even for feature 001's working `pg_isready` check, because it re-escapes its own output; `docker inspect` is the only honest source. (3) End to end against a loop touching the file every 2s: `healthy`. (4) The case that matters — a loop that stops while its process stays alive — flipped to `unhealthy` 8 seconds later **with `running=true`**, which is precisely the false-ready failure T038 was about. **One environment gotcha found, worth the same status as feature 001's PowerShell quote-stripping:** Git Bash on Windows rewrites a POSIX-looking value into a Windows path when passing `-e VAR=/tmp/x` to `docker.exe`, so a hand-run test container received `HEARTBEAT_FILE=C:/Users/user/AppData/Local/Temp/heartbeat` and failed for a reason that looked like a broken healthcheck. `MSYS_NO_PATHCONV=1` disables it. Compose is unaffected — it never passes through a shell — and both real containers hold `/tmp/heartbeat` correctly.
- [ ] T015 Verify the environment definition before writing any service code: `docker compose config` resolves with no error, and `git diff docker-compose.yml` shows the `postgres` and `rabbitmq` service blocks **completely unchanged** — FR-023 permits new services to declare a dependency on them but forbids editing their definitions. Confirm the only changes are the header comment and three added entries.

**Checkpoint**: The environment knows about three new containers and the schema can be applied. No pipeline logic exists yet.

---

## Phase 3: User Story 1 - A transaction becomes a stored fraud decision (Priority: P1) 🎯 MVP

**Goal**: One command starts the environment and, with no further action, transaction events are generated, examined, and stored as decisions — some flagged, some not.

**Independent Test**: Start from clean, wait, query `fraud_decisions`. Rows appear with a mix of `flagged = true` and `flagged = false`, and no manual step beyond the documented start command was needed.

**Note on the insert**: the six-step order in data-model.md (begin → count → evaluate → insert → commit → **then** ack) and the `ON CONFLICT (event_id) DO NOTHING` clause are implemented **here**, correctly, from the start. They are not deferred to User Story 2 and then retrofitted: an intermediate version that acknowledges before committing would lose transactions for real, and the whole point of fixing the order in the design document was so that no implementation ever has to pass through the wrong one. User Story 2 proves these mechanisms hold under failure; it does not introduce them.

### Tests for User Story 1

- [ ] T016 [P] [US1] Create `worker/rules.py` with two pure functions and no I/O: one for the amount rule (`flagged ⟺ amount > threshold`, **strictly** greater, both operands `Decimal`) and one for the velocity rule (`flagged ⟺ prior + 1 >= count`, where `prior` is supplied by the caller, so the function itself touches no database). Both exactly as specified in [contracts/fraud-rules.md](./contracts/fraud-rules.md). These are the two rules FR-009 names. This file is separate from `worker.py` for one reason only: so the unit tests can import the rules without opening a broker connection.
- [ ] T017 [P] [US1] Create `tests/unit/test_rules.py` covering eight cases. For the amount rule: above the threshold (flagged), below (not flagged), **exactly at `5000.00` (not flagged)**, plus **zero and a negative amount** (neither flagged, neither raising) — the spec's extreme-amount edge case requires these to produce a decision rather than crash, and `Decimal("-50.00") > Decimal("5000.00")` must simply be false rather than an error. For the velocity rule: enough transactions to flag, too few, and **exactly at the window edge (not counted)**. The three boundary cases are the ones that would otherwise be skipped, and are precisely what FR-011 and SC-011 exist to force.

### Implementation for User Story 1

- [ ] T018 [P] [US1] Create `producer/producer.py` with configuration read from the environment and event generation per [contracts/transaction-event.md](./contracts/transaction-event.md): `event_id` a fresh UUID4 string, `occurred_at` RFC 3339 with an explicit timezone offset, `account_id` drawn from a pool of `PRODUCER_ACCOUNT_POOL_SIZE` identifiers, `amount` as a **decimal string, not a JSON number** (JSON numbers are binary floats and `0.1 + 0.2 != 0.3`, which would surface as a wrong verdict exactly at a threshold), and a non-empty `merchant`. A `PRODUCER_FRAUD_RATIO` share of events get an amount above `FRAUD_AMOUNT_THRESHOLD` so rule 1 fires predictably. Covers FR-001, FR-002, FR-003 and FR-005.
- [ ] T019 [US1] In `producer/producer.py`, declare the full topology from [contracts/queue-topology.md](./contracts/queue-topology.md) at startup — queue `transactions` (durable, argument `x-dead-letter-exchange: transactions.dlx` and **no others**), exchange `transactions.dlx` (direct, durable), queue `transactions.dead` (durable), bound with routing key `transactions` — then publish with `delivery_mode=2` and **publisher confirms enabled on the channel**. The argument must be present the *first* time `transactions` is created: queue arguments are immutable in RabbitMQ, and a queue created without it can only be fixed by deleting it. All of this lives in the `aegisshield` vhost, not the default `/`. Publish to the **default exchange** (`exchange=""`) with `routing_key="transactions"`. That is not an arbitrary detail: dead-lettering preserves a message's original routing key, and the `transactions.dlx` binding matches on exactly `transactions`, so publishing through a named exchange instead would route rejected messages nowhere and the symptom would be dead letters silently vanishing. Durable queue plus persistent messages plus confirms is FR-006; any one of the three missing breaks the guarantee. FR-007 holds — declaring a queue is not writing to it, and the Producer is the only component of the running pipeline that publishes to `transactions`; the integration test harness publishes too, which FR-007 now names as an explicit exemption.
- [ ] T020 [US1] In `producer/producer.py`, add the main loop: publish at `PRODUCER_RATE_PER_SECOND`, touch `HEARTBEAT_FILE` on every iteration, and log one line per event including its `event_id` (FR-028). Run until stopped — no run limit, per the spec's Assumptions. `PRODUCER_RATE_PER_SECOND` is FR-004.
- [ ] T021 [P] [US1] Create `worker/worker.py` with configuration from the environment, a broker connection, the **identical** topology declaration from T019 (both services declare the whole topology idempotently with matching arguments, so neither depends on the other having started), `basic_qos(prefetch_count=1)`, and a consumer with **auto-acknowledge off**. Auto-ack would acknowledge on delivery, before the Worker has done anything, making FR-017 unachievable by construction.
- [ ] T022 [US1] In `worker/worker.py`, call the migration runner from T010 at startup, before consuming. The Worker owns migrations because it is the only service that touches the database, which removes the race rather than managing it. `/docker-entrypoint-initdb.d` is **not** an option: it would require editing the `postgres` service definition (FR-023 forbids it) *and* it only runs on a fresh data directory, so it would appear to work on a new clone and silently do nothing on any volume that already exists. Applying migrations automatically at startup is FR-014.
- [ ] T023 [US1] In `worker/worker.py`, implement the decision path in the fixed order from data-model.md, all inside **one** database transaction: begin; `SELECT count(*)` of prior decisions for the account where `occurred_at > (this event's occurred_at - FRAUD_VELOCITY_WINDOW_SECONDS)` (strictly greater — the window is half-open); evaluate both rules; insert with `INSERT INTO fraud_decisions (...) VALUES (...) ON CONFLICT (event_id) DO NOTHING`; commit; **then** `basic_ack`. When both rules would flag, record `amount_threshold` — it is the cheaper and more specific explanation. Acknowledge whether the insert wrote a row or found one already there: either way the required end state, exactly one decision, holds. This single task carries FR-008, FR-013 and FR-017; reading the velocity count from the table rather than from memory is FR-012, and it is why the count and the insert share one transaction.
- [ ] T024 [US1] In `worker/worker.py`, touch `HEARTBEAT_FILE` on every loop iteration and log one line per event including its `event_id` and the verdict.
- [ ] T025 [US1] Run the unit tests: `docker compose run --rm tests python -m pytest tests/unit -v`. The path is `tests/unit` **inside the container** because T005 copies the suite to `/app/tests/` from a repository-root build context — not because it happens to match the repo layout. Had the image been built from `./tests`, the same path would have been `unit` and this command would have failed at collection. All eight cases from T017 pass, including all three boundaries. Record the actual output.
- [ ] T026 [US1] Validate [quickstart.md](./quickstart.md) Scenario 1 from a genuinely clean state (`docker compose down -v` first): a single `docker compose up -d --wait` produces stored decisions within 60 seconds with no manual step, each row names its event, its verdict and its rule, and both flagged and unflagged rows are present. Measure the actual time to the first stored decision against SC-001's 60-second budget and record the number.
- [ ] T027 [US1] Validate Scenario 2: the `transactions` queue depth is not growing without bound at the default rate, read with `rabbitmqctl -q list_queues --vhost "$RABBITMQ_DEFAULT_VHOST" name messages`. The `--vhost` flag is not optional — feature 001's T042 found that omitting it reads the default `/` vhost, which succeeds, lists nothing, and looks exactly like the queues having vanished.

**Checkpoint**: The pipeline works end to end. This is the MVP and it is independently demonstrable.

---

## Phase 4: User Story 2 - Exactly one decision per transaction, even when things fail (Priority: P2)

**Goal**: Kill the consumer mid-processing, interrupt the database, redeliver a message, or feed in something unparseable — every transaction still ends with exactly one stored decision, and nothing vanishes unrecorded.

**Independent Test**: Publish a known set of transactions, interfere, then count stored decisions against transactions published. Exactly one each, every time.

### Implementation for User Story 2

- [ ] T028 [US2] In `worker/worker.py`, add validation of each message against the eight rejection rules in contracts/transaction-event.md: not valid JSON; not a JSON object at the top level; any required field missing; `event_id` not a valid UUID; `occurred_at` unparseable **or carrying no timezone offset**; `amount` not a valid decimal; **`amount` outside what `numeric(12,2)` can store** (magnitude at or above 10^10); `account_id` or `merchant` empty. That range check is the eighth rule and was added after the cross-check, because without it `"99999999999.00"` passes every other rule, then fails on insert, never commits, never gets acknowledged, and is redelivered forever — blocking every transaction behind it at `prefetch=1`. A type constraint reached the same poison-message loop that FR-019 forbids. Unknown fields must be **accepted and ignored** — this is what lets a future Producer add a field and deploy before the Worker that understands it, instead of making deployment order a correctness concern.
- [ ] T029 [US2] In `worker/worker.py`, reject anything that fails T028's validation with `basic_nack(requeue=False)` so the broker dead-letters it to `transactions.dead`, and log the reason plus the `event_id` where it could be read. `requeue=True` would redeliver the same poison message forever and block everything behind it; dropping it would leave only a log line, which rotates away. A dead-lettered message nobody can explain is barely better than a dropped one, which is why the reason is logged. Together with T028 this is FR-019.
- [ ] T030 [US2] Create `tests/integration/test_pipeline.py` with fixtures that connect to the **real** broker and the **real** database — nothing mocked, per FR-032 — plus the end-to-end test: publish a known transaction, wait for its decision, assert the stored row matches the published event field for field. Mocks are built from the same assumptions as the code they test, so they agree with the code and prove nothing; four of feature 001's five surprises came from a dependency behaving differently than assumed, and no mock would have caught any of them.
- [ ] T031 [US2] Add the idempotency test to `tests/integration/test_pipeline.py` (FR-033): publish the same `event_id` twice, wait, and assert `count(*) = 1` for that `event_id` **and** that the stored `decided_at` and `flagged` values are unchanged from the first decision — `DO NOTHING` satisfies FR-018's "must not alter the existing decision" where `DO UPDATE` would violate it.
- [ ] T032 [US2] Add two more tests to `tests/integration/test_pipeline.py`: a message carrying an unrecognised extra field is processed normally and stored; and a malformed message (invalid JSON, and separately a missing required field) lands in `transactions.dead` rather than being dropped or blocking the queue behind it.
- [ ] T033 [US2] Run the full suite: `docker compose run --rm tests`. Every unit and integration test passes. Record the actual output, including the count of tests run.
- [ ] T034 [US2] Validate Scenario 4: at least 100 repeat deliveries of already-decided transactions produce **zero** additional decisions (SC-005). Record the measured counts before and after.
- [ ] T035 [US2] Validate Scenario 5: kill the Worker mid-processing (`docker compose kill worker`), restart it, and confirm the in-flight transaction is redelivered and ends with exactly one decision. Note while doing this that `restart: unless-stopped` does **not** fire for a kill issued through the Docker API — feature 001's T040/T041 measured `RestartCount 0` after 30 seconds for an API kill versus `RestartCount 6` in 24 seconds for a self-exiting process. Start it yourself; do not wait for a restart that will not come.
- [ ] T036 [US2] Validate Scenario 3 and Scenario 7 together: over a run of at least 1,000 transactions, the count generated and the count stored match exactly with zero duplicates (SC-002, FR-020); and every deliberately malformed message injected is retrievable afterwards from `transactions.dead`, with zero disappearing unrecorded (SC-008). Record both counts.

### Added after the cross-check: three edge cases the spec listed and nothing verified

> **On the out-of-order IDs.** T060–T062 were added after `/speckit-analyze`, and they belong here in execution order despite their numbers. They are not renumbered into sequence because T001–T059 are already cited by the learning log, three commit messages and the analysis report, and silently repointing those references would be worse than a visible gap. Feature 001 set this precedent when it moved T045.
>
> All three close the same kind of hole: an edge case written in the spec with nothing checking it. That is not a safeguard, it is a claim.

- [ ] T060 [US2] Add a two-consumer test to `tests/integration/test_pipeline.py`, or validate it by hand with `docker compose up -d --scale worker=2`: publish a known set of transactions, let both Workers consume, and assert exactly one decision per transaction with zero duplicates. This is the spec's "two consumers running at once" edge case, and it is the most direct possible test of the feature's central guarantee — the primary key is supposed to make a race impossible rather than unlikely, and two Workers is the only configuration that actually puts that to the test. Note the Assumptions say no feature *depends* on running two; the requirement is that doing so must not break, which is a different and weaker claim that still needs checking.
- [ ] T061 [US2] Add two extreme-amount cases to `tests/integration/test_pipeline.py`: an **in-range enormous** amount (`9999999999.99`, the largest `numeric(12,2)` holds) is decided and stored normally; and an **out-of-range** amount (`99999999999.00`) is dead-lettered to `transactions.dead` by T028's range rule, with the queue behind it still draining. The second assertion is the important one — it is what proves the poison-message loop is closed rather than merely described. Zero and negative amounts are covered at the unit level by T017.
- [ ] T062 [US2] Add a clock-skew case to `tests/integration/test_pipeline.py`: publish an event whose `occurred_at` is several minutes **in the future**, and assert it receives a stored decision rather than crashing the Worker or being dead-lettered — a future timestamp is odd, not invalid. Then confirm the velocity count for that account is still computed without error. This is the spec's clock-differences edge case, and it is the same edge case the velocity-window contradiction (finding F1) was really about: now that the window is measured against `occurred_at`, a future-dated event sits ahead of its own window, so the behaviour must be observed rather than reasoned about.

**Checkpoint**: The pipeline is correct under failure, not merely correct when nothing goes wrong.

---

## Phase 5: User Story 3 - The pipeline starts and recovers on its own (Priority: P3)

**Goal**: Cold-start everything at once, or restart the broker or the database underneath a running pipeline. Both services wait, reconnect, and resume without being nursed back by hand.

**Independent Test**: Five consecutive cold starts with no ordering help, then restart the broker and the database independently while the pipeline runs. Both services survive all three events unaided.

**Why this phase exists at all**: Principle IV requires a dependent service to retry rather than exit, and feature 001 recorded that requirement as deliberately unimplemented because it shipped no application service to apply it to. This is where that debt is paid.

### Implementation for User Story 3

- [ ] T037 [P] [US3] In `producer/producer.py`, wrap connection establishment in a bounded exponential backoff loop: retry indefinitely, cap the delay at `RETRY_MAX_DELAY_SECONDS`, log every attempt, and **never exit** because a dependency is unavailable. Unbounded immediate retries would hammer a recovering dependency and fill the logs; the cap is what makes backoff useful. The Producer must not log a successful publish it never got a confirm for — it must not pretend to have published. This is the Producer's half of FR-021.
- [ ] T038 [P] [US3] In `worker/worker.py`, add the same backoff loop for **both** the broker and the database connections. `depends_on: condition: service_healthy` handles only the startup race; it does nothing for a dependency that disappears mid-run, which is exactly this story's second and third acceptance scenarios. This is the Worker's half of FR-021.
- [ ] T039 [US3] In `worker/worker.py`, handle mid-run connection loss without losing an unacknowledged message: on a dropped AMQP connection, reconnect, re-declare, and resume consuming — the unacknowledged message returns to the queue and is redelivered, and the primary key absorbs it if it was in fact already committed. Set an AMQP heartbeat comfortably longer than the worst expected database operation: `pika`'s blocking connection services heartbeats on the calling thread, so a long database stall drops the connection and surfaces as a confusing `StreamLostError` rather than as a database error.
- [ ] T040 [US3] Validate Scenario 10: five consecutive cold starts (`docker compose down -v` then `up -d --wait` each time) all reach a working pipeline with no manual restarts, regardless of which dependency becomes ready first (SC-009 requires 5 of 5). Record the result of each.
- [ ] T041 [US3] Validate Scenario 9: restart the broker underneath a running pipeline three times; both services reconnect unaided and processing resumes with zero transactions lost (SC-007 requires 3 of 3). Record each attempt.
- [ ] T042 [US3] Validate Scenario 6: interrupt the database for up to 60 seconds mid-run; every transaction accepted before the interruption has exactly one decision once it recovers, with no manual repair (SC-006). Confirm from the logs that the Worker did **not** acknowledge anything it could not store.
- [ ] T043 [US3] Validate Scenario 11: stop and start the environment (`docker compose stop` then `start`, and separately `down` without `-v` then `up`); previously stored decisions are still present and unchanged.

**Checkpoint**: The pipeline survives the three things that actually happen on a developer machine.

---

## Phase 6: User Story 4 - A developer can trace one transaction and tune the generator (Priority: P3)

**Goal**: Follow one transaction from generation to stored decision using one identifier and only documented commands; change the generation rate, the fraudulent share, and the rule thresholds without editing any component definition.

**Independent Test**: Pick one event identifier from the Producer's output and find every record of it — Producer log, Worker log, decision row — in under two minutes using only documented commands.

### Implementation for User Story 4

- [ ] T044 [P] [US4] Wire `LOG_LEVEL` through Python's standard `logging` module in both `producer/producer.py` and `worker/worker.py`, logging plain text to stdout. One variable for both services, because there is no present need to set them differently. No `structlog`, no JSON lines, no correlation-ID framework — nothing consumes these logs yet, and one field in a format string does not need machinery (research.md §10).
- [ ] T045 [US4] Audit both services line by line: every log statement that concerns a transaction includes its `event_id` (FR-028), including error and rejection paths. A rejection logged without the identifier is the one case where the log is needed most and is least likely to have been checked.
- [ ] T046 [US4] Add a `## Tracing one transaction` section to `README.md`: the exact commands to find one `event_id` in `docker compose logs producer`, in `docker compose logs worker`, and in `fraud_decisions`. Include the `docker compose exec -T postgres psql` stdin form rather than `-c "..."` — feature 001 found that PowerShell strips the quotes from `-c` and the statement arrives truncated, failing with `syntax error at end of input`.
- [ ] T047 [US4] Add a `## Tuning the generator and the rules` section and an `## Observing the pipeline` section to `README.md`: which variables change the rate, the fraudulent share and both rule thresholds; and the documented commands for queue backlog and dead-letter count (FR-029), with the `--vhost` flag. State plainly that setting `PRODUCER_FRAUD_RATIO=0` does **not** eliminate flagged decisions, because the velocity rule still fires from the small account pool — someone will otherwise read that as a bug.
- [ ] T048 [US4] Validate Scenario 12: locate every record of one chosen transaction in under 2 minutes using only the documented commands (SC-010). Time it and record the actual duration.
- [ ] T049 [US4] Validate Scenario 13: change the generation rate, a rule threshold, and the fraudulent proportion by editing `.env` only, restart, and confirm each takes effect with **zero** edits to `docker-compose.yml` or any Dockerfile (SC-012). Confirm the flagged share rises when the fraudulent proportion rises.

**Checkpoint**: All four user stories are independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: The measurements, the audits, and the documentation the constitution requires. These are not optional cleanup — three of them are the only coverage some success criteria have.

- [ ] T050 Validate Scenario 16: stop a service's loop without stopping its container so the heartbeat goes stale, and confirm its healthcheck turns `unhealthy` within `HEARTBEAT_MAX_AGE_SECONDS` plus one interval (FR-030). This is the test that distinguishes a wedged service from a working one; without it, a passing container status proves nothing.
- [ ] T051 Validate Scenario 17 and record the numbers: sustain ≥50 transactions/second for 5 continuous minutes with no lost transactions and no unbounded backlog growth (SC-004), and measure the 95th-percentile `decided_at - occurred_at` against the 2-second budget (SC-003). Note the assumption that measurement rests on: `occurred_at` comes from the Producer container and `decided_at` from `now()` on the database server, so the figure is only meaningful because both derive from the same host kernel clock. It stops being meaningful the moment any component runs on another machine, and the number should be labelled accordingly rather than quoted bare. This is plan.md's accepted risk 2 — a 20 ms budget per message for one `SELECT` plus one `INSERT`, and the most likely thing to fall short. If it does, the fix is batched commits or more Workers, **not** relaxing the criterion; whichever is chosen gets written into plan.md.
- [ ] T052 Validate Scenario 18: nothing beyond feature 001's container tooling is required on the host (FR-026); `git diff` confirms the `postgres` and `rabbitmq` service definitions are untouched (FR-023); and each service directory has its own Dockerfile and dependency manifest with no import between them (FR-024).
- [ ] T053 Repeat feature 001's T034 audit at the new size: every `${VAR}` interpolated anywhere in `docker-compose.yml` appears in `.env.example`, and every `.env.example` key is actually read by something — no speculative extras. The expected numbers are twelve new and twenty-one total; confirm both, rather than trusting them because a document says so. This parity property is what makes the example file trustworthy, and it is easy to break while adding a dozen at once.
- [ ] T054 Audit that no credential is written into any committed file (FR-025, Principle III): grep the three new directories and `docker-compose.yml` for hard-coded hosts, users and passwords; confirm `.env` is still git-ignored and unstaged; confirm every connection setting arrives from the environment.
- [ ] T055 Add a `## The transaction pipeline` section to `README.md`: what the two services do, the one command that starts everything, how to run the tests (`docker compose run --rm tests`), and the `PRECONDITION_FAILED` recovery from quickstart.md verbatim — a half-finished implementation that creates `transactions` without the dead-letter argument makes the correct implementation fail with an error that looks nothing like its cause, and queue arguments cannot be changed in place.
- [ ] T056 Run the whole of [quickstart.md](./quickstart.md) — all 18 scenarios — end to end against the finished implementation, and record the result of each. Any scenario whose documented steps or expected output turn out to be wrong gets corrected in quickstart.md as part of this task: feature 001's T043 found two such defects, and a validation guide that has never been executed is a guess.
- [ ] T057 Add the implementation entry to `LEARNING-LOG.md` (Principle VI, mandatory): what was built, why it was built that way, what was learned, what broke and how it was fixed, and — explicitly — what does NOT yet exist. Define every new term at first use. Include the measured numbers from T026, T048 and T051 rather than the targets, and state plainly anywhere a measurement contradicted something this plan asserted.
- [ ] T058 Add a `## Stage 2 — The transaction pipeline` section to `PROGRESS.md`, following the ten-part template that file already establishes, in the same plain language: what it does in one sentence, what problem it solves, what was actually built, how you use it, what was proven and how, the key numbers, what does not exist yet, what went wrong, and the plain-words explanation for someone outside the project.
- [ ] T059 Fold every measurement back into the specification documents: tick each task above with its actual result, update `spec.md`'s Status line, and correct any success criterion, threshold or default that measurement showed to be wrong. A document that still states a target after the measurement disagreed with it is worse than one that never stated it.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Needs Phase 1 (the Dockerfiles must exist before Compose can build them). **Blocks every user story.**
- **User Story 1 (Phase 3)**: Needs Phase 2. Blocks nothing, but delivers the only thing the later stories can be tested against.
- **User Story 2 (Phase 4)**: Needs Phase 3 — there must be a pipeline before it can be interfered with.
- **User Story 3 (Phase 5)**: Needs Phase 3. Independent of Phase 4.
- **User Story 4 (Phase 6)**: Needs Phase 3. Independent of Phases 4 and 5.
- **Polish (Phase 7)**: Needs all four stories, because it measures and documents the finished system.

### User Story Dependencies

Unlike a typical feature, these stories are **not** fully independent, and pretending otherwise would be dishonest:

- **US1 (P1)** is the pipeline. Everything else hardens, recovers or observes it.
- **US2 (P2)** depends on US1 existing. Its mechanisms — the six-step order, the primary key, `ON CONFLICT DO NOTHING` — are built in US1 by design; US2 adds the dead-letter path and the tests that prove all of it under failure.
- **US3 (P3)** depends on US1 and is independent of US2. Retry loops can be added while the failure tests are being written.
- **US4 (P3)** depends on US1 and is independent of US2 and US3. It is the only story whose tasks are mostly documentation.

### Within Each User Story

- `rules.py` and its unit tests before the Worker that calls them.
- Topology declaration before publishing or consuming.
- Migrations before the first insert.
- Implementation before the quickstart validation that measures it.

### Parallel Opportunities

- **Phase 1**: T001–T006 are six independent files and can all run together. T007 and T008 edit existing files and should be sequential.
- **Phase 2**: nothing is marked [P] — T011 through T015 all touch `docker-compose.yml`, and two tasks editing one file in parallel is how you get a merge conflict with yourself.
- **Phase 3**: T016, T017, T018 and T021 are four different files and can run together. Within each service, tasks editing the same file are sequential.
- **Phase 5**: T037 and T038 are different files and can run together.
- **Phases 4, 5 and 6** can be worked in parallel by three people once Phase 3 is complete, because they touch largely disjoint concerns — though all three eventually edit `worker.py`, so that file needs coordination.

---

## Parallel Example: Phase 1

```bash
# Six independent build-input files, no shared state:
Task: "Create producer/Dockerfile"
Task: "Create producer/requirements.txt"
Task: "Create worker/Dockerfile"
Task: "Create worker/requirements.txt"
Task: "Create tests/Dockerfile"
Task: "Create tests/requirements.txt"
```

## Parallel Example: User Story 1

```bash
# Four different files at the start of the story:
Task: "Create worker/rules.py with the two pure rule functions"
Task: "Create tests/unit/test_rules.py with eight cases including all three boundaries"
Task: "Create producer/producer.py with config and event generation"
Task: "Create worker/worker.py with config, connection, topology and consumer"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1: Setup — three images can build.
2. Phase 2: Foundational — the environment knows the services and the schema can be applied.
3. Phase 3: User Story 1.
4. **STOP and VALIDATE**: Scenario 1 and Scenario 2, measured, not assumed.
5. At this point the system does the thing it exists to do, and every later phase is improvement rather than completion.

### Incremental Delivery

1. Setup + Foundational → three containers defined, nothing running yet.
2. US1 → a working pipeline. **This is the MVP.**
3. US2 → correct under failure. The point at which the stored decisions can be trusted.
4. US3 → survives restarts unaided. The point at which the Principle IV debt is paid.
5. US4 → diagnosable and tunable. The point at which a failure in 1–3 stops being a mystery.
6. Polish → measured, audited, documented.

### A note on what "done" means here

Feature 001's central lesson, learned five separate times: **a claim about how a dependency behaves is a claim to be executed, not argued.** Static review finds contradictions between documents; only running something establishes a fact about RabbitMQ, PostgreSQL, Docker or Python. Every task above that says *record the actual result* means exactly that — the number that came out, not the number this plan predicted. Where they disagree, the document is what changes.

---

## Notes

- **62 tasks**: 43 write or edit files, 12 validate or measure, 7 are audits or plain-language documentation. IDs run T001–T059 plus T060–T062, which were added to Phase 4 after the `/speckit-analyze` cross-check and are deliberately out of numeric sequence (see the note there).
- `[P]` means different files with no unfinished dependency. Two tasks editing `docker-compose.yml` or `worker.py` are never both `[P]`.
- Commit after each task or logical group, and stop at any checkpoint to validate the story on its own.
- Avoid: acknowledging before committing (the one mistake that silently destroys a transaction), editing a migration file that has already been applied, and creating the `transactions` queue without its dead-letter argument.
