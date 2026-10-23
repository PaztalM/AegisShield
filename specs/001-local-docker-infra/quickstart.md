# Quickstart & Validation: Local Docker Infrastructure

**Feature**: `001-local-docker-infra` | **Date**: 2026-10-23

How to bring the environment up, and the runnable scenarios that prove it satisfies the spec. Every scenario maps to acceptance scenarios and success criteria in [spec.md](./spec.md). Commands come from [contracts/operator-commands.md](./contracts/operator-commands.md); addresses and credentials from [contracts/service-endpoints.md](./contracts/service-endpoints.md) and [contracts/environment-variables.md](./contracts/environment-variables.md).

Run everything from the repository root.

## Prerequisites

- Docker Engine and Docker Compose v2 or later. Nothing else — no broker, database, client library, or language runtime on the host (FR-018). Verified against Docker 29.9.1 / Compose v5.6.0.
- Check: `docker compose version` prints a version.
- The database and broker clients used below run **inside** the containers via `docker compose exec`, so they need no host installation.

**One shell convention used throughout.** Commands that need a credential are written as `docker compose exec <service> sh -c '...'` with **single** quotes. The variables inside are expanded by the shell *in the container*, where the image already has them; your host shell does not have them, because `.env` is read by Compose, not exported into your session. Writing `docker compose exec postgres psql -U "$POSTGRES_USER"` directly would expand to an empty username on the host.

## Setup

```bash
cp .env.example .env          # the only preparation step
docker compose up -d --wait   # starts and blocks until both components are healthy
```

Expected: the command exits zero. On a cold machine this includes image pulls and should finish in under 5 minutes (SC-001); with images cached, under 60 seconds (SC-002). Time it with `time docker compose up -d --wait` to record the number.

---

## Scenario 1 — One-command start, both components healthy

*Covers acceptance scenarios 1.1 and 1.4, SC-003, FR-001, FR-010.*

```bash
docker compose down -v                        # ensure a first-start state
cp .env.example .env
docker compose up -d --wait; echo "exit=$?"
docker compose ps
```

**Expected**: `exit=0`. `docker compose ps` lists exactly two services, each `running (healthy)`, each showing its published host ports — `5672` and `15672` for the broker, `5432` for the database. No further action was needed.

---

## Scenario 2 — Broker accepts a connection and round-trips a message

*Covers acceptance scenario 1.2, FR-002, FR-014, FR-020.*

Declare a durable queue, publish a persistent message, consume it — using the broker's own tooling inside the container, so no host client is required.

```bash
# Does the broker accept connections on its listeners?
docker compose exec rabbitmq rabbitmq-diagnostics -q check_port_connectivity

# Declare a durable queue, then confirm it exists
docker compose exec rabbitmq sh -c 'rabbitmqadmin --non-interactive \
  -u "$RABBITMQ_DEFAULT_USER" -p "$RABBITMQ_DEFAULT_PASS" \
  --vhost "$RABBITMQ_DEFAULT_VHOST" \
  declare queue --name quickstart.check --durable true'

docker compose exec rabbitmq sh -c \
  'rabbitmqctl list_queues --vhost "$RABBITMQ_DEFAULT_VHOST" name durable'
```

`rabbitmqadmin` is the v2 CLI bundled in the `-management` image (version 2.27.0 in `rabbitmq:4.2.4-management-alpine`, confirmed). It talks to the HTTP API, so it needs `-u`/`-p` — it defaults to `guest`, which this environment does not create. Note the v2 flag syntax (`--name X --durable true`), not the `name=X durable=true` form of the old Python v1 script. The image ships no `curl`, so HTTP API checks go through `rabbitmqadmin` rather than a raw request.

**Expected**: the connectivity check exits zero; `list_queues` shows `quickstart.check` with `durable = true`.

To prove the host-side endpoint specifically (acceptance scenario 1.2 as written), connect any standard AMQP client from the host to `amqp://<user>:<pass>@localhost:5672/<vhost>` using values from `.env`, declare a queue, publish, and consume. Expected: the connection is accepted and the published message is received.

---

## Scenario 3 — Database accepts a connection and runs a query

*Covers acceptance scenario 1.3, FR-003, FR-009, FR-014.*

```bash
docker compose exec postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT current_database(), current_user, version();"'
```

**Expected**: the query returns one row, `current_database` equals `POSTGRES_DB` and `current_user` equals `POSTGRES_USER` from `.env` — the named database and its owning account were created on first start with no manual step.

To prove the host-side endpoint, connect any standard PostgreSQL client from the host to `localhost:5432` with the same credentials and run `SELECT 1`. Expected: the connection is accepted and the query returns.

---

## Scenario 4 — Management interface, and `guest` is locked out

*Covers User Story 2, acceptance scenarios 2.1–2.4, FR-008.*

1. Open `http://localhost:15672` in a host browser. **Expected**: a sign-in page is served.
2. Sign in with `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` from `.env`. **Expected**: access granted; queues, connections, and message rates are visible.
3. With messages in a queue, purge it from the interface. **Expected**: the message count drops to zero immediately.
4. Attempt to sign in as `guest` / `guest`. **Expected**: rejected — the account does not exist, because the environment defines its own administrative account.

Scriptable form of step 4, no browser needed:

```bash
docker compose exec rabbitmq rabbitmqctl list_users
```

**Expected**: the project-defined user is listed with the `administrator` tag; `guest` is absent.

---

## Scenario 5 — Data survives a restart

*Covers User Story 3, acceptance scenario 3.1, FR-011, FR-020, SC-005.*

```bash
# Write state
docker compose exec postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE TABLE IF NOT EXISTS quickstart_check (id int primary key); INSERT INTO quickstart_check VALUES (1) ON CONFLICT DO NOTHING;"'
docker compose exec rabbitmq sh -c 'rabbitmqadmin --non-interactive \
  -u "$RABBITMQ_DEFAULT_USER" -p "$RABBITMQ_DEFAULT_PASS" \
  --vhost "$RABBITMQ_DEFAULT_VHOST" \
  declare queue --name quickstart.durable --durable true'

# Restart the environment
docker compose down
docker compose up -d --wait

# Verify both survived
docker compose exec postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM quickstart_check;"'
docker compose exec rabbitmq sh -c \
  'rabbitmqctl list_queues --vhost "$RABBITMQ_DEFAULT_VHOST" name durable'
```

**Expected**: the count is `1` and `quickstart.durable` is still listed. SC-005 asks for this across at least five consecutive stop/start cycles — repeat the middle two commands five times and confirm the row persists each time.

The broker half of this scenario is the one that fails if the Compose file omits a fixed container `hostname:` — the volume is intact but the node name changed, so the queue appears to have vanished. See section 7 of [research.md](./research.md). If the queue disappears here, check the hostname before suspecting the volume.

Drop `quickstart_check` when finished, or reset with the next scenario.

---

## Scenario 6 — Reset returns to a first-start state

*Covers acceptance scenarios 3.2 and 3.3, FR-012, SC-006.*

```bash
docker compose down -v
docker volume ls | grep -E 'postgres-data|rabbitmq-data'   # expect no output
docker compose up -d --wait

docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
docker compose exec rabbitmq sh -c 'rabbitmqctl list_queues --vhost "$RABBITMQ_DEFAULT_VHOST"'
```

**Expected**: after `down -v` neither volume exists. After the restart, `\dt` reports no relations and `list_queues` lists none — storage was recreated automatically with no manual preparation. SC-006 asks for five consecutive reset-and-start cycles with no manual repair.

---

## Scenario 7 — A port conflict fails loudly

*Covers the port-conflict edge case, SC-009, FR-004.*

```bash
docker compose down
# Occupy the database port with something else, then:
time docker compose up -d --wait; echo "exit=$?"
```

**Expected**: non-zero exit within 10 seconds, with an error message naming the occupied host port. No component is left partially started — confirm with `docker compose ps`.

Then prove the override path:

```bash
echo 'POSTGRES_PORT=55432' >> .env
docker compose up -d --wait; echo "exit=$?"
docker compose ps
```

**Expected**: `exit=0`; `ps` shows the database published on `55432`. The Compose file was not edited (FR-004). Remove the line afterwards.

---

## Scenario 8 — Missing configuration is reported by name

*Covers the missing/incomplete configuration edge case, FR-005, FR-006.*

```bash
docker compose down
mv .env .env.bak
docker compose up -d --wait; echo "exit=$?"
mv .env.bak .env
```

**Expected**: non-zero exit, and an error naming the first missing required variable along with the pointer to copy `.env.example` to `.env`. No container is created. Repeat with a single variable commented out in `.env` — the message must name that variable specifically, not produce an authentication failure from the broker or the database.

---

## Scenario 9 — No secrets committed, no values hard-coded

*Covers FR-005, FR-007, SC-007.*

```bash
git check-ignore -v .env                      # expect: matched by .gitignore
git ls-files | grep -E '(^|/)\.env$'          # expect: no output
docker compose config | grep -nE 'aegis_dev_password|5672|5432'
grep -nE 'password|5672|15672|5432' docker-compose.yml
```

**Expected**: `.env` is ignored and untracked. `docker compose config` shows resolved values — that is interpolation working, not a hard-coded value. The last command must show every occurrence inside a `${...}` interpolation or as a container-side port only; no literal credential, database name, or host port value appears in `docker-compose.yml`.

Also confirm the two files agree (FR-006): every `${VAR}` in `docker-compose.yml` appears in `.env.example`, and every `.env.example` key is used by the Compose file.

---

## Scenario 10 — Image pins

*Covers FR-013.*

```bash
grep -nE '^\s+image:' docker-compose.yml
```

**Expected**: two lines, each a full `major.minor.patch` tag — `rabbitmq:4.2.4-management-alpine` and `postgres:18.4-alpine`. No `latest`, no two-part tag, no digest-less floating reference.

---

## Scenario 11 — An unhealthy component is never reported healthy

*Covers FR-019.*

Freeze the database's processes so it stops answering, without stopping the container — the container stays `running`, which is exactly the case where a naive status check would lie:

```bash
docker compose up -d --wait
docker compose kill -s SIGSTOP postgres    # container still running, server frozen
docker compose ps                          # wait a few healthcheck intervals, then look
docker compose kill -s SIGCONT postgres    # restore
docker compose ps
```

**Expected**: while frozen, the database is reported `unhealthy` — never `healthy` — even though the container is still running. After `SIGCONT` it returns to `healthy`. A `docker compose up -d --wait` issued while it is frozen exits non-zero rather than claiming success.

---

## Scenario 12 — The environment accepts a new service without restructuring

*Covers FR-015, SC-010.* Validation only — no application service is added by this feature.

Append a throwaway service to a scratch copy of the Compose file that joins `aegisshield-net`, declares `depends_on` with `condition: service_healthy` on both components, and runs a one-shot command resolving `rabbitmq` and `postgres` by name. Start it and confirm it waits for both to be healthy and resolves both names.

**Expected**: it works with **zero edits** to the `rabbitmq` and `postgres` service definitions — that is the SC-010 claim. Discard the scratch copy; the real services arrive with their own features.

---

## Validation checklist

| # | Scenario | Spec coverage |
|---|---|---|
| 1 | One-command start, both healthy | 1.1, 1.4, SC-001, SC-002, SC-003, FR-001, FR-010 |
| 2 | Broker connection and durable queue | 1.2, FR-002, FR-014, FR-020 |
| 3 | Database connection and query | 1.3, FR-003, FR-009, FR-014 |
| 4 | Management interface; `guest` rejected | 2.1–2.4, FR-008, SC-004 |
| 5 | Data survives restart | 3.1, FR-011, SC-005 |
| 6 | Reset returns to first-start state | 3.2, 3.3, FR-012, SC-006 |
| 7 | Port conflict fails loudly; override works | SC-009, FR-004 |
| 8 | Missing configuration named | FR-005, FR-006 |
| 9 | No secrets committed, nothing hard-coded | FR-007, SC-007 |
| 10 | Images pinned | FR-013 |
| 11 | Unhealthy never reported healthy | FR-019 |
| 12 | Accepts a new service unchanged | FR-015, SC-010 |

Not validated by command, by nature: SC-008 (a new contributor completes setup from the README alone in under 10 minutes) — validate by having someone who has not seen the project follow the README and time it.
