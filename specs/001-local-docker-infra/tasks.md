---

description: "Task list for Local Docker Infrastructure"
---

# Tasks: Local Docker Infrastructure

**Input**: Design documents from `/specs/001-local-docker-infra/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: No automated test tasks. `plan.md` states "Manual and scripted verification through the container tooling and standard clients, per `quickstart.md`. No test framework is added here" — the automated integration test the constitution requires for the Producer → RabbitMQ → Worker → PostgreSQL path belongs to the feature that introduces those services. The verification tasks below execute `quickstart.md` scenarios instead.

**Organization**: Tasks are grouped by user story so each story can be implemented, tested, and delivered independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Flat repository root — this feature ships no code, so there is no `src/` or `tests/` tree (plan.md Structure Decision). All artifacts live at the repository root:

- `docker-compose.yml` — NEW, the environment definition
- `.env.example` — NEW, every variable the Compose file reads
- `README.md` — NEW, operator documentation
- `.gitignore` — EXISTS, already ignores `.env`; no change expected

All `docker compose` commands run from the repository root, which is the Compose project directory.

**Shell convention**: commands needing a credential use `docker compose exec <service> sh -c '...'` with **single** quotes, so the container's shell expands variables the image already has. `.env` is read by Compose for interpolation, not exported into the host shell (research.md §3a).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm host prerequisites and that the pinned images still resolve, before writing anything

- [X] T001 Verify host prerequisites by running `docker compose version` from the repository root — expect Docker Compose v2 or later; confirm no broker, database, client library, or language runtime is required on the host (FR-018, quickstart.md Prerequisites)
- [X] T002 [P] Re-confirm both pinned tags still resolve in the registry: `docker manifest inspect rabbitmq:4.2.4-management-alpine` and `docker manifest inspect postgres:18.4-alpine`. If a tag has been superseded, bump deliberately to another full `major.minor.patch` tag — never to a floating tag (research.md §1 open risks, FR-013)
- [X] T003 [P] Confirm the existing root `.gitignore` already ignores the active config: `git check-ignore -v .env` must print "matched by .gitignore". Do not modify `.gitignore` — plan.md records "no change expected" (FR-007)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The configuration interface and the environment-definition skeleton that every user story builds on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 Create `.env.example` at the repository root with exactly the nine variables from `contracts/environment-variables.md`, each with its default quoted verbatim from that table and a short comment naming its consumer: `POSTGRES_USER=aegis`, `POSTGRES_PASSWORD=aegis_dev_password`, `POSTGRES_DB=aegisshield`, `POSTGRES_PORT=5432`, `RABBITMQ_DEFAULT_USER=aegis`, `RABBITMQ_DEFAULT_PASS=aegis_dev_password`, `RABBITMQ_DEFAULT_VHOST=aegisshield`, `RABBITMQ_PORT=5672`, `RABBITMQ_MANAGEMENT_PORT=15672`. No tenth variable — "a variable is added only when the Compose file reads it". All defaults are development-grade and localhost-only; no value intended to be secret (FR-005, FR-006, FR-007, SC-007, Principle V)
- [X] T005 Create `docker-compose.yml` at the repository root with the top-level skeleton only: a `networks:` block declaring `aegisshield-net` with `driver: bridge`, and a `volumes:` block declaring the two named volumes `rabbitmq-data` and `postgres-data` with no driver options. Exactly one Compose file — no `version:` key, no override file, no `profiles:`, no `include:`, and no `container_name:` on any service (data-model.md "Environment definition", FR-001, FR-011, FR-014, plan.md design rule 1)
- [X] T006 Create the developer's active configuration with `cp .env.example .env` at the repository root — the only preparation step before a first start — then confirm `git status --short` shows no `.env` entry (FR-006, FR-007, contracts/operator-commands.md)

**Checkpoint**: Configuration interface and file skeleton exist — user story implementation can now begin

---

## Phase 3: User Story 1 - Start the whole local environment with one command (Priority: P1) 🎯 MVP

**Goal**: A developer on a machine with only container tooling runs one documented command and ends up with a healthy broker and a healthy database, both reachable from the host with credentials read out of the committed example file, having installed nothing and hand-edited nothing.

**Independent Test**: On a clean machine with container tooling only, run `cp .env.example .env` then `docker compose up -d --wait` — it exits zero. `docker compose ps` lists both services `running (healthy)` with their published host ports. Connect a standard AMQP client and a standard PostgreSQL client from the host using only values from `.env.example`; both connections are accepted, a queue can be declared and a query can be run. No other feature of the system is required (quickstart.md Scenarios 1, 2, 3).

### Implementation for User Story 1

- [X] T007 [US1] Add the `postgres` service to `docker-compose.yml`: service name exactly `postgres` (it is also the internal DNS name services connect to), `image: postgres:18.4-alpine` pinned to the full `major.minor.patch` tag, `networks: [aegisshield-net]`, and `restart: unless-stopped` (data-model.md "Component — relational database", FR-013, FR-014)
- [X] T008 [US1] Add the `postgres` service's `environment:` block in `docker-compose.yml` using explicit per-variable keys, **not** `env_file:`, so the file records which image consumes which variable (contracts/environment-variables.md rule 6). All three are the *required* tier — declare each as `${VAR:?<message>}` with the message form `VAR is not set - copy .env.example to .env` (a plain ASCII hyphen, never an em dash — this string is printed to a terminal that may be cp1252; see contracts/environment-variables.md): `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`. No literal credential or database name appears in the file (FR-005, FR-009, SC-007)
- [X] T009 [US1] Add the `postgres` port mapping to `docker-compose.yml` as `"${POSTGRES_PORT:-5432}:5432"` — the host side is the *defaulted* tier (`${VAR:-<default>}`, default `5432`, so omitting it is legal and it is overridable from `.env` without editing the Compose file); the container side is fixed at `5432` and never interpolated (FR-003, FR-004, contracts/environment-variables.md rule 3)
- [X] T010 [US1] Add the `postgres` healthcheck to `docker-compose.yml`: test `pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"`. The `-h 127.0.0.1` is mandatory — a socket-only check passes during first-start initialization while the TCP listener does not yet exist, a false positive that would break SC-003. Use the authoritative timing from data-model.md: `interval: 5s`, `timeout: 5s`, `retries: 5`, `start_period: 30s` — `start_period` covers first-start `initdb` (10–20s), and after it elapses 5 failures at 5s mark the service unhealthy within ~25s. Do not substitute other values here; if T020's measurement shows they need changing, change data-model.md and this task together (research.md §2 and open risks, FR-010, FR-019, SC-002)
- [X] T011 [US1] Add the `rabbitmq` service to `docker-compose.yml`: service name exactly `rabbitmq` (also the internal DNS name), `image: rabbitmq:4.2.4-management-alpine` pinned to the full `major.minor.patch` tag — the `-management` variant is required so no plugin-enable step or custom image is needed for User Story 2 — `networks: [aegisshield-net]`, and `restart: unless-stopped` (data-model.md "Component — message broker", FR-013, FR-014)
- [X] T012 [US1] Add the `rabbitmq` service's `environment:` block in `docker-compose.yml` with explicit keys, all *required* tier using `${VAR:?<message>}` and the same message form: `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS`, `RABBITMQ_DEFAULT_VHOST`. Setting the default-user variables is what makes the image create the project-defined administrator in place of the stock `guest` account, so `guest` is never created on a fresh volume — take no other action about `guest` (FR-005, FR-008, research.md §5)
- [X] T013 [US1] Add the `rabbitmq` messaging port mapping to `docker-compose.yml` as `"${RABBITMQ_PORT:-5672}:5672"` — defaulted host side, container side fixed at `5672` (FR-002, FR-004)
- [X] T014 [US1] Add the `rabbitmq` healthcheck to `docker-compose.yml`: test `rabbitmq-diagnostics -q check_port_connectivity`, which opens a TCP connection to every listener the node has published. Do not use `ping` or `check_running` — both can pass before the AMQP listener is bound. Use the authoritative timing from data-model.md: `interval: 10s`, `timeout: 10s`, `retries: 6`, `start_period: 60s` — longer than the database's on every axis because an Erlang node boot plus management-plugin start commonly takes 20–40s on a first start, and `rabbitmq-diagnostics` starts a short-lived Erlang VM per invocation so it needs a timeout `pg_isready` does not. A success during `start_period` marks the service healthy immediately, so the 60s window delays nothing (FR-010, FR-019, SC-002, research.md §2)
- [X] T015 [US1] Validate the resolved environment definition with `docker compose config` from the repository root — it must print both services with interpolations applied and no error (contracts/operator-commands.md)
- [X] T016 [US1] Verify the one-command start: run `docker compose down -v`, `cp .env.example .env`, then `docker compose up -d --wait` and check the exit status is `0`. Then `docker compose ps` must list exactly two services, each `running (healthy)`, each showing its published host ports — `5672` for the broker and `5432` for the database. 100% of components report healthy before the command reports ready. Then three further assertions in the same running environment: (a) **per-component logs** — `docker compose logs rabbitmq` and `docker compose logs postgres` each return only that component's output, never the other's (FR-016, quickstart.md Scenario 13); (b) **a repeated start is safe** — run `docker compose up -d --wait` a second time, expect exit `0`, and confirm `docker compose ps` still lists exactly two containers with no duplicates and no volume churn (spec.md edge case "started twice in a row", quickstart.md Scenario 14); (c) **the broker's resource alarms are observable** — `docker compose exec rabbitmq rabbitmq-diagnostics -q check_alarms` exits zero with no alarm in effect, establishing the command a developer uses when the broker stops accepting publishes (spec.md edge case "out of disk", FR-016, quickstart.md Scenario 15) (quickstart.md Scenario 1, acceptance scenarios 1.1 and 1.4, FR-001, FR-010, FR-016, SC-003)
- [X] T017 [US1] Verify the broker accepts connections and holds a durable queue: `docker compose exec rabbitmq rabbitmq-diagnostics -q check_port_connectivity` exits zero; then declare `quickstart.check` with `rabbitmqadmin --non-interactive --vhost "$RABBITMQ_DEFAULT_VHOST" declare queue --name quickstart.check --durable true` run through `docker compose exec rabbitmq sh -c '...'` with the project credentials passed as `-u`/`-p`, and confirm it with `rabbitmqctl list_queues --vhost "$RABBITMQ_DEFAULT_VHOST" name durable`. The bundled `rabbitmqadmin` is v2 (2.27.0) — flag syntax `--name X --durable true`, not `name=X durable=true` — it talks to the HTTP API so it needs credentials and defaults to `guest`, which this environment never creates, and the image ships no `curl`. Also connect any standard AMQP client from the host to `amqp://<user>:<pass>@localhost:5672/<vhost>` using values from `.env`, then publish and consume a message (quickstart.md Scenario 2, acceptance scenario 1.2, FR-002, FR-014, FR-020)
- [X] T018 [US1] Verify the database accepts a connection and runs a query: run `psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT current_database(), current_user, version();"` through `docker compose exec postgres sh -c '...'` — one row, with `current_database` equal to `POSTGRES_DB` and `current_user` equal to `POSTGRES_USER` from `.env`, proving the named database and its owning account were created on first start with no manual step. Also connect any standard PostgreSQL client from the host to `localhost:5432` with the same credentials and run `SELECT 1` (quickstart.md Scenario 3, acceptance scenario 1.3, FR-003, FR-009, FR-014)
- [X] T019 [US1] Create `README.md` at the repository root with: the project name and a one-line description; prerequisites (Docker Engine and Docker Compose v2+, nothing else); the two-step setup (`cp .env.example .env`, then `docker compose up -d --wait`); the start, status (`docker compose ps`), and per-component log commands (`docker compose logs -f rabbitmq`, `docker compose logs -f postgres`); a table of the three published endpoints with the `*_PORT` variable that overrides each; and a statement that all credentials come from `.env`, copied from `.env.example`. State that `--wait` is part of the documented start command and not optional, because plain `up -d` returns before the components accept connections. Introduce no wrapper script, Makefile, or task runner — plain `docker compose` is the interface (FR-016, FR-017, SC-004, SC-008, contracts/operator-commands.md, Principle V)
- [ ] T020 [US1] Measure and record start-to-healthy timing: remove both images and run `docker compose down -v` for a cold state, then time `docker compose up -d --wait` — must be under 5 minutes including first-time image pulls (SC-001); then `docker compose down` and time a second `docker compose up -d --wait` — must be under 60 seconds with images cached (SC-002). If the warm number exceeds 60 seconds, tune the healthcheck `interval` and `start_period` set in T010 and T014 rather than loosening the criterion (research.md open risks)

**Checkpoint**: User Story 1 is fully functional and testable independently — this is the MVP. A developer can now begin writing the Producer and Worker against real dependencies.

---

## Phase 4: User Story 2 - Inspect and administer the broker through its management interface (Priority: P2)

**Goal**: A developer debugging a message flow opens the broker's web management interface on the host, signs in with the documented credentials, inspects queues, message rates, consumers, and individual messages, and can create or purge a queue by hand. The stock `guest` account is not reachable.

**Independent Test**: With the environment running, open the management interface's host address in a browser, sign in with the credentials from `.env.example`, and confirm queues and message rates are visible and that a queue can be created and purged from the interface. Separately confirm that signing in as `guest`/`guest` is rejected (quickstart.md Scenario 4).

### Implementation for User Story 2

- [ ] T021 [US2] Add the management port mapping to the `rabbitmq` service in `docker-compose.yml` as `"${RABBITMQ_MANAGEMENT_PORT:-15672}:15672"` — defaulted host side, container side fixed at `15672`. Confirm the image set in T011 is the `-management-alpine` variant, which enables the management plugin with no custom image and no plugin-enable step (FR-002, FR-004, research.md §1)
- [ ] T022 [US2] Restart with `docker compose up -d --wait` and verify a sign-in page is served at `http://localhost:15672` in a host browser, then sign in with `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` from `.env` — expect access granted, with the broker's queues, connections, and message rates visible (quickstart.md Scenario 4 steps 1-2, acceptance scenarios 2.1 and 2.2)
- [ ] T023 [US2] Verify hand administration through the management interface at `http://localhost:15672` (Queues tab): with messages in a queue, purge it from the interface and confirm the message count drops to zero and the change is visible immediately; also create a queue from the interface. Cross-check from the command line with `docker compose exec rabbitmq sh -c 'rabbitmqctl list_queues --vhost "$RABBITMQ_DEFAULT_VHOST" name messages'` (acceptance scenario 2.3)
- [ ] T024 [US2] Verify the stock guest account is unreachable: `docker compose exec rabbitmq rabbitmqctl list_users` must list the project-defined user with the `administrator` tag and must **not** list `guest`; attempting to sign in to the management interface as `guest`/`guest` must be rejected because the account does not exist (quickstart.md Scenario 4 step 4, acceptance scenario 2.4, FR-008)
- [ ] T025 [US2] Add a management-interface section to `README.md`: the management address `http://localhost:${RABBITMQ_MANAGEMENT_PORT:-15672}`, that it uses the same account as AMQP, that `guest` does not exist in this environment, and that `docker compose exec rabbitmq rabbitmqctl list_queues` inspects the broker with no host client installed (FR-017, FR-018)

**Checkpoint**: User Stories 1 AND 2 both work independently — message flow can now be debugged visually.

---

## Phase 5: User Story 3 - Keep data across restarts, and discard it deliberately (Priority: P3)

**Goal**: Stopping and restarting the environment preserves database rows and durable queue definitions; one documented command discards all stored state so the next start is indistinguishable from a first-ever start.

**Independent Test**: Write a row to the database and declare a durable queue, stop the environment, start it again, and confirm both survived. Then run the documented reset command, start again, and confirm both are gone (quickstart.md Scenarios 5 and 6).

### Implementation for User Story 3

- [ ] T026 [US3] Add the volume mount `postgres-data:/var/lib/postgresql/data` to the `postgres` service in `docker-compose.yml`, referencing the named volume declared in T005 — the data directory holding the application database and its account. No host bind mount: bind mounts bring permission and path-translation problems across Linux, macOS, and Windows hosts, and `docker compose down -v` would not clean them up (FR-011, data-model.md "Persistent storage volume", research.md §7)
- [ ] T027 [US3] Add the volume mount `rabbitmq-data:/var/lib/rabbitmq` to the `rabbitmq` service in `docker-compose.yml` — the Mnesia node directory holding users, the vhost, durable queue definitions, and persistent messages (FR-011, FR-020)
- [ ] T028 [US3] Add a fixed `hostname: aegisshield-rabbitmq` to the `rabbitmq` service in `docker-compose.yml`. This is **required**, not cosmetic: RabbitMQ derives its node name from the container hostname and stores its Mnesia database in a directory named after that node, so without a fixed hostname a recreated container gets a new random hostname, initializes an empty node directory, and durable queues appear to vanish even though the volume was preserved. It is separate from `container_name:`, which stays unset so two projects can coexist on one host (FR-011, acceptance scenario 3.1, research.md §7 and §8)
- [ ] T029 [US3] Verify storage is created with no manual preparation: from a state where the environment has never been started (`docker compose down -v`), run `docker compose up -d --wait` and confirm with `docker volume ls` that both named volumes were created automatically (acceptance scenario 3.3)
- [ ] T030 [US3] Verify data survives a restart: create table `quickstart_check (id int primary key)` and insert one row via `docker compose exec postgres sh -c '...'`, and declare durable queue `quickstart.durable` via `rabbitmqadmin`; then `docker compose down` followed by `docker compose up -d --wait`; then confirm the row count is `1` and `quickstart.durable` is still listed with `durable = true`. Repeat the stop/start and verification across at least 5 consecutive cycles — the row must persist in 100% of attempts. If the queue disappears, check the fixed `hostname:` from T028 before suspecting the volume. Drop `quickstart_check` when finished (quickstart.md Scenario 5, acceptance scenario 3.1, FR-011, FR-020, SC-005)
- [ ] T031 [US3] Verify the reset path: `docker compose down -v`, then `docker volume ls | grep -E 'postgres-data|rabbitmq-data'` expecting no output, then `docker compose up -d --wait` and confirm `psql ... -c "\dt"` reports no relations and `rabbitmqctl list_queues` lists none. Repeat across at least 5 consecutive reset-and-start cycles with no manual repair (quickstart.md Scenario 6, acceptance scenarios 3.2 and 3.3, FR-012, SC-006)
- [ ] T032 [US3] Add a persistence and reset section to `README.md` covering: that `docker compose down` keeps the named volumes while `docker compose down -v` destroys them, made unmissable because the two differ by two characters and one destroys test data; that `docker compose stop` leaves containers in place for a faster restart; that repeating `docker compose up -d --wait` against a running environment is safe and is a no-op or a clean reconcile; and the credential-change caveat — credentials are frozen into a volume at initialization, so changing `POSTGRES_PASSWORD` or `RABBITMQ_DEFAULT_PASS` in `.env` has no effect and will fail authentication until the volume is discarded, the sequence being edit `.env`, then `docker compose down -v`, then start again, with no in-place path (FR-011, FR-012, FR-017, contracts/operator-commands.md, spec.md edge cases)

**Checkpoint**: All three user stories are independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Edge-case verification, requirement audits, and the extension-point proof that span all three stories

- [ ] T033 [P] Audit that no secret is committed and no value is hard-coded: `git check-ignore -v .env` matches, `git ls-files | grep -E '(^|/)\.env$'` returns nothing, and `grep -nE 'password|5672|15672|5432' docker-compose.yml` shows every occurrence only inside a `${...}` interpolation or as a container-side port. Resolved values printed by `docker compose config` are interpolation working, not hard-coded values (quickstart.md Scenario 9, FR-005, FR-007, SC-007)
- [ ] T034 [P] Audit variable parity between `docker-compose.yml` and `.env.example`: every `${VAR}` the Compose file interpolates appears in `.env.example`, and every `.env.example` key is read by the Compose file — nine variables, with no speculative tenth (FR-006, plan.md design rule 4, Principle V)
- [ ] T035 [P] Audit image pins: `grep -nE '^\s+image:' docker-compose.yml` must show exactly two lines, `rabbitmq:4.2.4-management-alpine` and `postgres:18.4-alpine`, each a full `major.minor.patch` tag — no `latest`, no two-part tag, no floating reference (quickstart.md Scenario 10, FR-013)
- [ ] T036 Verify the port-conflict edge case: `docker compose down`, occupy the database host port with something else, then time `docker compose up -d --wait` — expect a non-zero exit within 10 seconds with an error naming the occupied host port, and `docker compose ps` showing nothing partially started. Then prove the override path by appending `POSTGRES_PORT=55432` to `.env` and restarting: exit zero, with `docker compose ps` showing the database published on `55432` and no edit to `docker-compose.yml`. Remove the line afterwards (quickstart.md Scenario 7, FR-004, SC-009)
- [ ] T037 Verify the missing-configuration edge case: `docker compose down`, move `.env` aside, then run `docker compose up -d --wait` — expect a non-zero exit, an error naming the first missing required variable together with the pointer to copy `.env.example` to `.env`, and no container created. Repeat with a single variable commented out in `.env`; the message must name that variable specifically rather than producing an opaque authentication failure from the broker or the database. Restore `.env` afterwards (quickstart.md Scenario 8, FR-005, FR-006)
- [ ] T038 Verify an unhealthy component is never reported healthy: `docker compose up -d --wait`, then `docker compose kill -s SIGSTOP postgres` so the container stays `running` while the server is frozen; after a few healthcheck intervals `docker compose ps` must report it `unhealthy`, and a `docker compose up -d --wait` issued while it is frozen must exit non-zero rather than claiming success. Restore with `docker compose kill -s SIGCONT postgres` and confirm it returns to `healthy` (quickstart.md Scenario 11, FR-019)
- [ ] T039 Verify the extension point on a scratch copy of `docker-compose.yml` (never the committed file): append a throwaway service that joins `aegisshield-net`, declares `depends_on` with `condition: service_healthy` on both `rabbitmq` and `postgres`, and runs a one-shot command resolving `rabbitmq:5672` and `postgres:5432` by internal name. Confirm it waits for both to be healthy and resolves both names with **zero edits** to the `rabbitmq` and `postgres` service definitions. Discard the scratch copy — no application service is added by this feature (quickstart.md Scenario 12, FR-015, SC-010)
- [ ] T040 Verify the broker's disk-space alarm is observable, so a full disk cannot present as an unexplained hang: `docker compose exec rabbitmq sh -c 'rabbitmq-diagnostics -q check_alarms; echo "exit=$?"'` must exit zero with no alarm in effect, and `docker compose exec rabbitmq rabbitmq-diagnostics status` must report the configured `disk_free_limit` and current free space. Confirm `docker compose logs rabbitmq` is where a raised alarm would be reported. **Actual disk exhaustion is deliberately not simulated** — filling the host disk is destructive and the alarm threshold cannot be lowered without adding a tenth variable and a config layer (Principle V). What this task proves is the spec's actual requirement: that the condition is *visible through status or logs* rather than silent. Record the observed `disk_free_limit` in `README.md` next to the log command (spec.md edge case "machine runs out of disk", FR-016, FR-019, quickstart.md Scenario 15)
- [ ] T041 Verify recovery from an unclean shutdown, the laptop-lid-closed case: with data written per T030, kill the containers outright with `docker compose kill` (SIGKILL, no graceful stop — not `docker compose stop`), then `docker compose up -d --wait; echo "exit=$?"`. Expect exit `0` with both components returning to `running (healthy)` and **no manual repair of stored state**: the previously written row is still present and the durable queue is still declared. If either component cannot recover automatically, the fallback the spec permits is that it must say so plainly — capture what `docker compose logs` reports and document the required reset in `README.md` rather than leaving the developer to guess (spec.md edge case "an unclean shutdown", FR-011, FR-019, FR-020, quickstart.md Scenario 16)
- [ ] T042 Review `README.md` against FR-017: the start, status, log, stop, and reset commands are all present, the three published addresses are listed, and where credentials come from is stated. Confirm no wrapper script, Makefile, or task runner was introduced anywhere in the feature (FR-017, FR-018, Principle V). Validate SC-008 by having someone who has not seen the project complete setup from the README alone and timing it — target under 10 minutes of hands-on time with no questions asked
- [ ] T043 Run the full `quickstart.md` validation checklist end to end (Scenarios 1 through 16) against the final `docker-compose.yml`, `.env.example`, and `README.md`, and confirm every row of its coverage table passes
- [ ] T044 Update `LEARNING-LOG.md` at the repository root for this feature's implementation, as Principle VI requires: what was built, what each line of `docker-compose.yml` is for and why it is written that way, which alternatives were rejected during implementation and why, anything that behaved differently from the plan's expectation and what was learned from it, the measured timings from T020, the state of the project now, and any new term defined at first use. State plainly what still does not exist. Note explicitly that `README.md` is operator documentation — how to run the environment — while `LEARNING-LOG.md` is a teaching document explaining why it is built this way; neither replaces the other (Principle VI)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup (T002 confirms the tags T007 and T011 write; T003 confirms the ignore rule T006 relies on) — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational
- **User Story 2 (Phase 4)**: Depends on Foundational; T021 extends the `rabbitmq` service block created in T011
- **User Story 3 (Phase 5)**: Depends on Foundational; T026, T027, and T028 extend the service blocks created in T007 and T011 and reference the volumes declared in T005
- **Polish (Phase 6)**: Depends on all three user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start as soon as Foundational is done — no dependency on any other story. Delivers the MVP on its own.
- **User Story 2 (P2)**: Purely additive to the `rabbitmq` service. Independently testable through the management interface; needs the broker running, which US1 provides.
- **User Story 3 (P3)**: Purely additive to both service blocks. Independently testable through write → restart → verify and reset → verify; needs both components running, which US1 provides.

User Stories 2 and 3 touch no part of each other, so their order between themselves is free.

### Within Each User Story

- Service block before its `environment:`, ports, and healthcheck (T007 → T008 → T009 → T010; T011 → T012 → T013 → T014)
- Resolved-config validation before the first start (T015 → T016)
- Both components healthy before any connection verification (T016 → T017, T018)
- Implementation and verification before the README section that documents it

### Parallel Opportunities

- **Phase 1**: T002 and T003 run in parallel — different concerns, neither writes a file
- **Phase 2**: T004 and T005 write different files and could run in parallel; T006 depends on T004
- **Phase 3**: the two service blocks are independent in content, but both are edits to the single `docker-compose.yml`, so T007-T014 are deliberately **not** marked `[P]` — one file, sequential edits. The two connection verifications T017 and T018 touch different components and can run in parallel once T016 passes
- **Phase 6**: T033, T034, and T035 are read-only audits of different properties and run in parallel. T036-T041 each manipulate the running environment's state and must run one at a time. T041 (unclean shutdown) depends on T030 having written the data it checks for, so run it before any `down -v`

Note: this feature has a single implementation file, so it offers far fewer `[P]` opportunities than a multi-module feature. That is expected — the parallelism here is across verification, not construction.

---

## Parallel Example: Phase 6 audits

```bash
# Launch the three read-only audits together:
Task: "Audit that no secret is committed and nothing is hard-coded in docker-compose.yml"
Task: "Audit variable parity between docker-compose.yml and .env.example"
Task: "Audit image pins in docker-compose.yml"
```

```bash
# Phase 3, after T016 passes — the two connection checks:
Task: "Verify the broker accepts connections and holds a durable queue"
Task: "Verify the database accepts a connection and runs a query"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T003)
2. Complete Phase 2: Foundational (T004-T006) — CRITICAL, blocks all stories
3. Complete Phase 3: User Story 1 (T007-T020)
4. **STOP and VALIDATE**: run quickstart.md Scenarios 1, 2, and 3 — a developer can now build the Producer and Worker against real dependencies
5. Commit; the environment is usable

### Incremental Delivery

1. Setup + Foundational → configuration interface and file skeleton ready
2. Add User Story 1 → broker and database healthy and reachable → **MVP**
3. Add User Story 2 → management interface works and `guest` is locked out → debuggable
4. Add User Story 3 → persistence and the reset path verified → safe to keep test data
5. Polish → edge cases, audits, and the extension-point proof
6. Each story is additive; none breaks a previous one

### Parallel Team Strategy

This feature has one implementation file and a scope of roughly ten variables, so it is a single-developer feature. Splitting Phase 3 across people would mean concurrent edits to the same `docker-compose.yml` for no gain. If a second person is available, the useful split is one developer implementing while the other runs the quickstart verification scenarios behind them.

---

## Notes

- `[P]` tasks = different files, no dependencies. Most tasks here edit the one `docker-compose.yml`, so `[P]` is rare by design
- `[Story]` label maps a task to its user story for traceability; Setup, Foundational, and Polish tasks carry no story label
- Commit after each task or logical group; stop at any checkpoint to validate a story independently
- No test framework, no wrapper script, no Makefile, no custom image build, no RabbitMQ `definitions.json`, and no PostgreSQL `init.sql` is introduced by any task above — if a step cannot be expressed in Compose plus official-image environment variables, it is out of scope rather than scripted around (plan.md design rules 2 and 3, Principle V)
- Remember the single-quote `sh -c` convention for any command needing a credential; `.env` is read by Compose, not exported into the host shell
