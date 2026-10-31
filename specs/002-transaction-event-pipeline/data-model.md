# Data Model: Transaction Event Pipeline

Phase 1 output. Tables, columns, constraints and indexes, with the reason for each. Values here are **authoritative** — implementation must not vary them, and if measurement shows one is wrong, this file and the corresponding task change together.

Two storage entities live in PostgreSQL. One entity — the transaction event — is never stored as itself; it exists only as a message in transit and is recorded through the decision made about it.

---

## Entity — Transaction event (in transit, never stored as a row)

Created by the Producer, carried as a JSON message, consumed by the Worker. See [contracts/transaction-event.md](./contracts/transaction-event.md) for the wire format.

It deliberately has no table of its own. Storing every event *and* every decision would duplicate the entire payload for no requirement: the decision row already carries the fields needed to understand and audit the verdict, and the full original message remains in the broker until acknowledged. Adding an `events` table would be speculative under Principle V.

---

## Entity — Fraud decision

One row per transaction event, ever. This is the feature's whole output.

**Table**: `fraud_decisions`

| Column | Type | Constraints | Why it exists |
|---|---|---|---|
| `event_id` | `uuid` | **PRIMARY KEY** | The event's unique identifier, from the message. Being the primary key is what makes idempotency a database guarantee rather than an application hope (FR-016). |
| `account_id` | `text` | `NOT NULL` | The card or account the transaction belongs to. Required by the velocity rule, which counts recent transactions per account. |
| `amount` | `numeric(12,2)` | `NOT NULL` | The transaction amount. Required by the amount rule, and kept so a decision can be understood without the original message. |
| `merchant` | `text` | `NOT NULL` | Where the transaction happened. Not used by either rule; kept so a stored decision is self-explanatory when tracing one transaction (SC-010). |
| `occurred_at` | `timestamptz` | `NOT NULL` | When the Producer says the transaction happened. The velocity window is measured against this. |
| `decided_at` | `timestamptz` | `NOT NULL DEFAULT now()` | When the Worker made the decision. Separate from `occurred_at` so end-to-end latency (SC-003) is measurable from stored data rather than from logs. |
| `flagged` | `boolean` | `NOT NULL` | The verdict. |
| `rule` | `text` | `NULL` when `flagged = false` | Which rule fired. Required by FR-013 and acceptance scenario 4.4 — a decision must say *why*, not merely *what*. |

### Constraints, and what each prevents

| Constraint | Definition | What it prevents |
|---|---|---|
| Primary key | `PRIMARY KEY (event_id)` | A duplicate delivery creating a second decision. This is the enforcement FR-016 demands be in the database, not in application logic: a check-then-insert in the Worker has a gap between the check and the insert, and two Workers can both pass the check. A primary key cannot be raced. |
| Verdict consistency | `CHECK ((flagged = true AND rule IS NOT NULL) OR (flagged = false AND rule IS NULL))` | A flagged decision with no reason, or an unflagged decision that names a rule. Both are nonsense states that would make the table untrustworthy as an audit record. |
| Amount sanity | none | Deliberately absent. The spec's edge cases require that zero, negative and enormous amounts receive a *decision* rather than crashing the Worker, so the database must accept them. Rejecting them here would convert a decidable transaction into a dead-lettered one. |

### Index

| Index | Definition | Why |
|---|---|---|
| Velocity lookup | `(account_id, occurred_at)` | The velocity rule runs one `count(*)` filtered by account and time window for **every** message. At the 50/second target that is 50 of these per second; without the index each one becomes a full table scan over a table that grows all day. The column order matters: `account_id` is an equality match and must come first, `occurred_at` is a range match and must come second. |

No index on `flagged` or `rule`. Nothing queries by them yet, and an index that serves no query is pure write-cost (Principle V).

### Insert pattern

The Worker performs the velocity count and the insert **in one transaction**, and the insert is:

```sql
INSERT INTO fraud_decisions (...) VALUES (...) ON CONFLICT (event_id) DO NOTHING
```

`ON CONFLICT ... DO NOTHING` is what turns a redelivery into a harmless no-op instead of an error the Worker has to interpret. The Worker acknowledges the message either way — whether it inserted a row or found one already there, the required end state ("exactly one decision exists") holds. FR-018 additionally requires that a redelivery not *alter* the existing decision, which `DO NOTHING` satisfies and `DO UPDATE` would violate.

Order of operations is fixed and not negotiable (FR-017):

1. Begin transaction
2. Count prior transactions for the account inside the window
3. Evaluate both rules
4. Insert the decision
5. **Commit**
6. **Then** acknowledge the message to the broker

A crash anywhere before step 5 leaves the message unacknowledged, so the broker redelivers it and the work is simply redone. A crash between 5 and 6 also causes a redelivery, which the primary key absorbs. There is no ordering of these six steps that loses a transaction, which is the point of fixing the order here.

---

## Entity — Schema migration record

**Table**: `schema_migrations`

| Column | Type | Constraints | Why |
|---|---|---|---|
| `version` | `text` | **PRIMARY KEY** | The migration filename's numeric prefix, e.g. `001`. Primary key makes re-application a no-op rather than a duplicate (FR-015). |
| `applied_at` | `timestamptz` | `NOT NULL DEFAULT now()` | When it ran. For diagnosis only. |

Created by the migration runner itself before anything else, with `CREATE TABLE IF NOT EXISTS` — the one place that pattern is correct, because there is no earlier migration that could have created it.

The runner holds a PostgreSQL **advisory lock** for the duration, so two Workers starting at the same moment cannot both apply migration `001`. An advisory lock is a lock on an arbitrary number that PostgreSQL arbitrates; it locks no table and exists purely so that only one holder proceeds at a time.

---

## Migration files

| File | Contents |
|---|---|
| `worker/migrations/001_create_fraud_decisions.sql` | `fraud_decisions` with all columns, the primary key, the check constraint, and the velocity index. |

One file, because this feature introduces one table. Numbered with a three-digit prefix so ordering is lexicographic and stays correct past nine migrations.

**Migration files are append-only once applied.** Editing `001` after it has run on any machine means that machine's schema no longer matches the file, and nothing will detect the divergence — the version is already recorded as applied. A change to an applied migration must be a new numbered file. This is the rule that makes versioned migrations worth having, and it is the one most easily broken by accident during development, where deleting the volume and starting again feels equivalent.

---

## Relationships

```text
Transaction event  (message, in transit)
        │
        │  decided by the Worker, exactly once
        ▼
fraud_decisions    (one row, keyed by the event's own id)
        │
        │  read back by the velocity rule for the same account
        └──────────────► counted within the configured window
```

The loop in that diagram is worth noticing: `fraud_decisions` is both the output of the pipeline and the input to one of its rules. That is a deliberate consequence of FR-012's ban on in-memory history, and it is why the read and the write share a transaction.

---

## What is not modelled, and why

- **No `events` table.** See above — the decision row carries what is needed.
- **No `accounts` table.** `account_id` is an opaque string from the message. There is no account entity in this system, nothing to join to, and no requirement for one.
- **No `rules` table.** The two rules are two functions in code with configurable thresholds, not data. A rules table would be the beginning of the rule-engine abstraction Principle V forbids until there are at least three concrete cases.
- **No unprocessable-message table.** Those stay in the dead-letter queue, where the broker can count them and the management interface can show them. See research.md §5.
- **No retention or archival.** Decisions accumulate; `docker compose down -v` discards everything. At 50/second on a developer machine this is not a problem, and a retention policy for data nobody keeps would be speculative.
