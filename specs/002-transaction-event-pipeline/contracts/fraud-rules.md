# Contract: Fraud rules

The two rules, their defaults, and — most importantly — exactly what each does at its boundary. FR-011 requires boundary behaviour to be defined rather than left to chance, because two implementers given "flag large amounts" will choose `>` and `>=` and both believe they were right.

**These rules are placeholders for a pipeline, not fraud detection.** Their job is to be simple, explicit and demonstrable. Real detection is a later feature's problem; nothing here should be read as a claim about catching fraud.

---

## Rule 1 — Amount threshold

**Name as stored in the `rule` column**: `amount_threshold`

**Definition**: flag the transaction when its amount is **strictly greater than** the threshold.

```
flagged  ⟺  amount > FRAUD_AMOUNT_THRESHOLD
```

| Setting | Variable | Default |
|---|---|---|
| Threshold | `FRAUD_AMOUNT_THRESHOLD` | `5000.00` |

**Boundary**: an amount of exactly `5000.00` is **not flagged**. Strictly greater, not greater-or-equal.

**Comparison is exact decimal.** The amount arrives as a string and is parsed to `Decimal`, and the threshold is parsed the same way — see [transaction-event.md](./transaction-event.md) for why. A binary float comparison at exactly the threshold is the one case where it would visibly give the wrong answer.

**Negative and zero amounts** are not flagged by this rule — they are not greater than a positive threshold. They still receive a decision, which is what the spec's edge case requires; they are simply not interesting to this rule.

---

## Rule 2 — Velocity

**Name as stored in the `rule` column**: `velocity`

**Definition**: flag the transaction when the number of transactions on the same account within the window, **including the one being decided**, reaches the threshold.

```
prior   = count of decisions where account_id matches
                            and occurred_at > (this event's occurred_at − FRAUD_VELOCITY_WINDOW_SECONDS)
flagged ⟺  prior + 1 >= FRAUD_VELOCITY_COUNT
```

| Setting | Variable | Default |
|---|---|---|
| Transactions needed to flag | `FRAUD_VELOCITY_COUNT` | `4` |
| Window | `FRAUD_VELOCITY_WINDOW_SECONDS` | `60` |

With the defaults: the 4th transaction on one account inside 60 seconds is flagged, and so is every one after it while the window stays full.

**Two boundaries, both deliberate**:

1. **The count includes the current transaction.** `prior + 1 >= 4` means three prior transactions plus this one flags. Writing `prior >= 4` would require five transactions to flag the fourth, which is not what "four transactions in a minute" means to a reader.
2. **The window is half-open.** A prior transaction *exactly* `FRAUD_VELOCITY_WINDOW_SECONDS` old is **outside** the window and is not counted — the comparison is strictly greater than `occurred_at − window`. This makes the window contain the instants after its start and not the instant at its start, which keeps a transaction from being counted twice at a window edge.

**The window is measured against `occurred_at`, not `decided_at`.** It asks about when transactions happened, which is what a velocity rule means. A consequence worth knowing: because the Producer supplies `occurred_at`, a badly skewed Producer clock would shift the window. This is accepted — the alternative, trusting only the Worker's own clock, would make the rule's answer depend on queue latency, which is worse. See the spec's clock-skew edge case.

**History comes from the database, not from memory.** FR-012 forbids in-memory history, because memory dies with the process: the same transaction would then get different verdicts depending on when the Worker last restarted, and two Workers would disagree. The count is a `SELECT` against `fraud_decisions`, in the same transaction as the insert.

**Accepted limitation**: only *decided* transactions are counted, so events still in flight do not contribute. The undercount is small at the target rate and, more to the point, it is deterministic — the same input produces the same verdict on every machine and after every restart. Recorded as an accepted risk in plan.md with its revisit condition.

---

## Evaluation order and the `rule` column

Both rules are evaluated for every transaction. If both would flag it, **`amount_threshold` is recorded**, because it is the cheaper and more specific explanation.

`rule` holds the name of exactly one rule, or `NULL` when nothing flagged. A `CHECK` constraint in the database enforces that `flagged` and `rule` agree, so a flagged decision with no reason cannot be stored (see data-model.md).

Recording one rule rather than a list is a Principle V decision: a list implies a rules framework, and there are two rules. If a third arrives and the single-name column becomes genuinely lossy, that is the point to revisit it — not now.

---

## How the rules are made observable

The Producer can be told to emit transactions that plainly violate a rule, so the rules can be watched working rather than taken on trust (FR-005, acceptance scenario 4.3).

| Setting | Variable | Default | Effect |
|---|---|---|---|
| Fraudulent share | `PRODUCER_FRAUD_RATIO` | `0.1` | Fraction of generated transactions deliberately built to be flagged. `0.1` means roughly one in ten. |

At the default, a deliberately-fraudulent transaction is given an amount above `FRAUD_AMOUNT_THRESHOLD`, which makes it flagged by rule 1 predictably.

The velocity rule is exercised differently: the generator draws accounts from a small pool, so at the default rate several transactions naturally land on one account inside a 60-second window. This means the velocity rule fires without any special-casing, but also that its firing rate depends on the generation rate and pool size rather than on `PRODUCER_FRAUD_RATIO`. Worth stating, because someone setting `PRODUCER_FRAUD_RATIO=0` and expecting zero flagged decisions will still see velocity flags.

---

## Testing requirements

FR-031 and SC-011 require each rule to be covered for three cases, and the boundary case is the one that would otherwise be skipped:

| Rule | Must be tested |
|---|---|
| `amount_threshold` | an amount above the threshold (flagged), one below (not flagged), and **exactly at it** (not flagged) |
| `velocity` | enough transactions in the window to flag, too few (not flagged), and **exactly at the window edge** (not counted) |

The rule functions must be importable and callable without a broker or database connection, so these stay unit tests. That is why `rules.py` is a separate file from `worker.py`, and it is the only reason.
