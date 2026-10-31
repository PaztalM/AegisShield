# Quickstart & Validation: Transaction Event Pipeline

How to run the pipeline and how to prove it works. Every scenario maps to requirements and success criteria from [spec.md](./spec.md); the coverage table at the end must be fully green before the feature is considered done.

This is a **validation guide**, not an implementation guide. It contains commands to run and outcomes to expect. Schema details are in [data-model.md](./data-model.md), message format in [contracts/transaction-event.md](./contracts/transaction-event.md), rule behaviour in [contracts/fraud-rules.md](./contracts/fraud-rules.md), and queue settings in [contracts/queue-topology.md](./contracts/queue-topology.md).

## Prerequisites

Docker Engine and Docker Compose v2 or later. Nothing else — no Python, no database client, no broker client. Feature 001 established this and it must remain true: every command below runs inside a container.

## Setup

Unchanged from feature 001, which is the point:

```bash
cp .env.example .env
docker compose up -d --wait
```

`--wait` now waits for four services instead of two. If it returns `0`, the whole pipeline is healthy, not just the infrastructure.

## A note on Windows shells before you start

Windows PowerShell strips inner double quotes when passing arguments to `docker.exe`, so SQL passed with `-c "SELECT ..."` arrives mangled. Send SQL on standard input instead:

```powershell
'SELECT count(*) FROM fraud_decisions;' | docker compose exec -T postgres sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Feature 001's README documents this in full. The commands below use that form throughout.

---

## Scenario 1 — A transaction becomes a stored decision

*Covers acceptance scenarios 1.1–1.3, FR-001, FR-008, FR-013, SC-001.*

```bash
docker compose down -v
cp .env.example .env
docker compose up -d --wait; echo "exit=$?"
```

Wait a few seconds, then:

```bash
'SELECT count(*) FROM fraud_decisions;' | docker compose exec -T postgres sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
'SELECT event_id, account_id, amount, flagged, rule FROM fraud_decisions ORDER BY decided_at DESC LIMIT 5;' | docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

**Expected**: `exit=0`. The count is non-zero **within 60 seconds of the start command** (SC-001) and rises on repeated queries. Rows show a mix of `flagged = f` and `flagged = t`, and every flagged row names a rule while every unflagged row has `rule` empty. No manual step of any kind was performed.

---

## Scenario 2 — The queue does not grow without bound

*Covers acceptance scenario 1.4, FR-029.*

```bash
docker compose exec rabbitmq sh -c 'rabbitmqctl -q list_queues --vhost "$RABBITMQ_DEFAULT_VHOST" name messages'
```

Run it several times over a minute.

**Expected**: `transactions` stays near zero and does not climb steadily — the Worker keeps pace at the default rate. `transactions.dead` is `0`.

Note the `--vhost`. Omitting it reads the default `/` virtual host, succeeds, and lists nothing, which looks identical to the queues having vanished. Feature 001's T042 found exactly that bug in its own README.

---

## Scenario 3 — Every transaction has exactly one decision

*Covers FR-020, SC-002.*

Let it run until at least 1,000 transactions have been generated, then compare what the Producer says it published against what is stored:

```bash
docker compose logs producer | grep -c "published"
'SELECT count(*), count(DISTINCT event_id) FROM fraud_decisions;' | docker compose exec -T postgres sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

**Expected**: the two counts from the database are **identical** — `count(*)` equals `count(DISTINCT event_id)`, proving no duplicates — and together they account for every published transaction. 100% coverage, zero duplicates.

---

## Scenario 4 — A redelivered transaction produces no second decision

*Covers acceptance scenario 2.1, FR-018, SC-005.*

The direct test is to republish an `event_id` that is already stored:

```bash
'SELECT event_id, account_id, amount, merchant, occurred_at FROM fraud_decisions LIMIT 1;' | docker compose exec -T postgres sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Republish that exact event as a message to `transactions` (the integration test automates this; by hand, use the management interface's Publish panel on the `transactions` queue with the same JSON).

```bash
'SELECT count(*) FROM fraud_decisions WHERE event_id = '"'"'<that id>'"'"';' | docker compose exec -T postgres sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

**Expected**: still exactly `1`. The row is also **unchanged** — `decided_at` has not moved, which distinguishes `ON CONFLICT DO NOTHING` from an update. FR-018 requires both.

---

## Scenario 5 — A crash mid-processing loses nothing

*Covers acceptance scenario 2.2, FR-017.*

```bash
before=$('SELECT count(*) FROM fraud_decisions;' | docker compose exec -T postgres sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"')
docker compose kill worker
docker compose up -d --wait worker
```

**Expected**: the Worker returns, the stored count resumes climbing, and `transactions.dead` is still `0` — a killed Worker causes redelivery, not dead-lettering. Any message in flight at the moment of the kill was unacknowledged, so the broker redelivered it and it ends with exactly one decision.

Recall from feature 001's T041 that `docker compose kill` leaves the container `Exited (137)` and the restart policy does **not** bring it back, because Docker does not apply a restart policy to an API-initiated kill.

---

## Scenario 6 — The database going away does not lose a transaction

*Covers acceptance scenarios 2.3 and 3.3, FR-021, SC-006.*

```bash
docker compose stop postgres
# let the pipeline run for ~30 seconds against a missing database
docker compose logs --tail=20 worker
docker compose start postgres
docker compose up -d --wait
```

**Expected**: while the database is down the Worker **logs retries and stays running** — it does not exit (FR-021). Messages accumulate in `transactions` rather than being lost or dead-lettered. After the database returns, the backlog drains and every transaction accepted before the outage has exactly one decision, with no manual repair.

The key assertion is that nothing was acknowledged during the outage. If the Worker had acknowledged before committing, those transactions would be gone.

---

## Scenario 7 — An unprocessable message is set aside, not dropped

*Covers acceptance scenario 2.4, FR-019, SC-008.*

Publish deliberate rubbish to `transactions` — use the management interface's Publish panel with a payload of `not json at all`, and a second with valid JSON missing a required field, e.g. `{"event_id": "x"}`.

```bash
docker compose exec rabbitmq sh -c 'rabbitmqctl -q list_queues --vhost "$RABBITMQ_DEFAULT_VHOST" name messages'
docker compose logs --tail=20 worker
```

**Expected**: `transactions.dead` shows `2`. The Worker logged a rejection reason for each. **Crucially, `transactions` keeps draining** — the poison messages did not block the queue, and the Worker did not crash or loop. The messages themselves are retrievable from `transactions.dead` through the management interface.

---

## Scenario 8 — Unknown fields are tolerated

*Covers the forward-compatibility edge case.*

Publish a valid event with an extra field, e.g. `"channel": "mobile"` added to an otherwise-correct payload.

**Expected**: it is processed normally and a decision is stored. It does **not** appear in `transactions.dead`. This is what allows a future Producer to add a field without the older Worker treating every message as poison.

---

## Scenario 9 — The broker restarting does not lose anything

*Covers acceptance scenario 3.2, FR-021, SC-007.*

```bash
docker compose restart rabbitmq
docker compose logs --tail=20 producer
docker compose logs --tail=20 worker
```

**Expected**: both services log reconnection attempts and then resume by themselves, with no manual restart. Because the queue is durable and messages are persistent, anything already queued survives the broker restart. The stored count resumes climbing.

---

## Scenario 10 — Everything starts from cold regardless of order

*Covers acceptance scenario 3.1, FR-021, FR-022, SC-009.*

```bash
docker compose down
docker compose up -d --wait; echo "exit=$?"
docker compose ps
```

Repeat five times.

**Expected**: `exit=0` every time, with all four services `running (healthy)`. Neither application service crashes because a dependency was not ready. `depends_on: condition: service_healthy` handles most of this, but the retry loops are what make it robust — and Scenario 6 is what proves the retries exist, since healthcheck gating alone would pass this scenario while failing that one.

---

## Scenario 11 — Data survives a restart

*Covers acceptance scenario 3.4.*

```bash
'SELECT count(*) FROM fraud_decisions;' | docker compose exec -T postgres sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose down
docker compose up -d --wait
'SELECT count(*) FROM fraud_decisions;' | docker compose exec -T postgres sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

**Expected**: the second count is **greater than or equal to** the first — previously stored decisions are still present, and the pipeline has added more since. Nothing was lost by stopping.

---

## Scenario 12 — One transaction can be traced end to end

*Covers acceptance scenario 4.1, FR-028, SC-010.*

Pick an `event_id` from the Producer's output, then find it everywhere:

```bash
docker compose logs producer | grep <event_id>
docker compose logs worker   | grep <event_id>
'SELECT * FROM fraud_decisions WHERE event_id = '"'"'<event_id>'"'"';' | docker compose exec -T postgres sh -c 'psql -x -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

**Expected**: the identifier appears in both services' logs and in exactly one database row. Total time to do this: **under 2 minutes** (SC-010), using only the commands above.

---

## Scenario 13 — Configuration changes behaviour without touching any definition

*Covers acceptance scenarios 4.2 and 4.3, FR-004, FR-005, FR-010, SC-012.*

Edit `.env` only — never `docker-compose.yml`:

```bash
# raise the rate and the fraudulent share
PRODUCER_RATE_PER_SECOND=20
PRODUCER_FRAUD_RATIO=0.5
```

```bash
docker compose up -d --wait
```

**Expected**: transactions are generated faster, and the share of `flagged = t` rows among new decisions rises towards half. `git status` shows **no change to `docker-compose.yml`**.

Then lower `FRAUD_AMOUNT_THRESHOLD` and confirm more transactions flag on the amount rule. Restore `.env` afterwards.

One thing to expect rather than be surprised by: setting `PRODUCER_FRAUD_RATIO=0` does **not** eliminate flagged decisions, because the velocity rule still fires naturally when several transactions land on one account inside the window. Raise `PRODUCER_ACCOUNT_POOL_SIZE` to suppress that too.

---

## Scenario 14 — The rules do what the contract says

*Covers FR-031, SC-011.*

```bash
docker compose run --rm tests python -m pytest unit -v
```

**Expected**: all pass, including the three cases per rule that [contracts/fraud-rules.md](./contracts/fraud-rules.md) requires — above, below, and **exactly at** the boundary. The boundary cases are the reason this scenario exists; the other two would pass under either `>` or `>=`.

These are unit tests: they import the rule functions and touch no broker and no database.

---

## Scenario 15 — The full path works against the real broker and real database

*Covers FR-032, FR-033.*

```bash
docker compose run --rm tests python -m pytest integration -v
```

**Expected**: all pass. The test publishes a known transaction to the real `transactions` queue, waits for the real Worker to decide it, and asserts the row in the real database — with neither the broker nor the database replaced by a stand-in.

It also covers idempotency (FR-033) by publishing the same event twice and asserting exactly one row.

No mocking is permitted here, and that is deliberate: the failures this feature must not have — acknowledging before committing, duplicate rows, a poison message blocking the queue — are all failures of the *interaction* between a service and its dependencies. A mock is built from the same assumptions as the code it tests, so it agrees with the code and proves nothing.

---

## Scenario 16 — A stale service is reported unhealthy

*Covers FR-030.*

```bash
docker compose kill -s SIGSTOP worker
# wait for HEARTBEAT_MAX_AGE_SECONDS plus one healthcheck interval
docker compose ps
docker compose up -d --wait; echo "exit=$?"
docker compose kill -s SIGCONT worker
```

**Expected**: the Worker's container stays `running` while its health becomes `unhealthy`, because the heartbeat file stopped being touched. A `docker compose up -d --wait` issued while it is frozen exits **non-zero** rather than claiming the pipeline is ready. After `SIGCONT` it returns to `healthy`.

This is the same technique feature 001's T038 used on PostgreSQL, and for the same reason: a frozen process is still `running`, so only a real liveness signal distinguishes working from wedged.

---

## Scenario 17 — Throughput and latency targets

*Covers SC-003, SC-004.*

Set `PRODUCER_RATE_PER_SECOND=50` in `.env`, restart, and let it run for five minutes.

```bash
# backlog should stay bounded, not climb
docker compose exec rabbitmq sh -c 'rabbitmqctl -q list_queues --vhost "$RABBITMQ_DEFAULT_VHOST" name messages'

# end-to-end latency, measured from stored data
'SELECT percentile_disc(0.95) WITHIN GROUP (ORDER BY decided_at - occurred_at) AS p95 FROM fraud_decisions WHERE decided_at > now() - interval '"'"'5 minutes'"'"';' | docker compose exec -T postgres sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

**Expected**: the backlog stays bounded over the five minutes, and the 95th-percentile `decided_at - occurred_at` is **under 2 seconds** (SC-003). Record both numbers.

This is the scenario most likely to fail, and plan.md records it as an accepted risk: a single synchronous Worker has a 20 ms budget per message for one `SELECT` plus one `INSERT`. If it falls short, the documented fix is a larger prefetch with batched commits, or several Workers — which the primary key already makes safe — **not** relaxing the criterion.

Restore `.env` afterwards.

---

## Scenario 18 — Nothing new is required on the host, and feature 001 is untouched

*Covers FR-023, FR-024, FR-026.*

```bash
git diff --stat HEAD -- docker-compose.yml
grep -A2 "^  rabbitmq:\|^  postgres:" docker-compose.yml
docker compose config | grep -E "^\s+image:"
```

**Expected**: the `rabbitmq` and `postgres` service definitions are **unchanged** except for nothing at all — the new services declare `depends_on` on them, which is a property of the new services, not an edit to the old ones (FR-023). Four images, all pinned to explicit versions, with both Python services on the **same** version. Every command in this document ran through `docker compose`, with nothing installed on the host.

---

## Recovery: `PRECONDITION_FAILED` on the queue

Worth knowing before it happens, because the error does not look like its cause.

Queue arguments in RabbitMQ are immutable. If `transactions` was ever created without the `x-dead-letter-exchange` argument — by a half-finished implementation, for instance — every later declaration with the correct arguments fails with `PRECONDITION_FAILED` and the channel closes.

The fix is to delete the queue and let it be recreated:

```bash
docker compose exec rabbitmq sh -c 'rabbitmqctl delete_queue transactions --vhost "$RABBITMQ_DEFAULT_VHOST"'
docker compose restart producer worker
```

Or, more bluntly, `docker compose down -v`, which discards everything including the decisions.

---

## Coverage

| Scenario | Covers |
|---|---|
| 1 | 1.1, 1.2, 1.3, FR-001, FR-002, FR-008, FR-013, SC-001 |
| 2 | 1.4, FR-029 |
| 3 | FR-020, SC-002 |
| 4 | 2.1, FR-016, FR-018, SC-005 |
| 5 | 2.2, FR-017 |
| 6 | 2.3, 3.3, FR-021, SC-006 |
| 7 | 2.4, FR-019, SC-008 |
| 8 | unknown-field edge case, FR-003 |
| 9 | 3.2, FR-006, FR-021, SC-007 |
| 10 | 3.1, FR-021, FR-022, FR-030, SC-009 |
| 11 | 3.4 |
| 12 | 4.1, FR-027, FR-028, SC-010 |
| 13 | 4.2, 4.3, FR-004, FR-005, FR-010, FR-025, SC-012 |
| 14 | 4.4, FR-009, FR-011, FR-031, SC-011 |
| 15 | FR-032, FR-033 |
| 16 | FR-030 |
| 17 | SC-003, SC-004 |
| 18 | FR-023, FR-024, FR-026 |

Requirements not covered by a scenario here, because they are structural and verified by inspection during implementation rather than at runtime: FR-007 (the Producer is the only publisher), FR-012 (velocity does not use in-memory history — enforced by the design and visible in the code), FR-014 and FR-015 (migrations are versioned files, applied automatically and safely more than once — exercised by every start in every scenario above), FR-024 (separate directories and manifests, visible in the tree).
