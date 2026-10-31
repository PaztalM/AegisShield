# Feature Specification: Transaction Event Pipeline

**Feature Branch**: `002-transaction-event-pipeline`

**Created**: 2026-10-31

**Status**: Draft

**Input**: User description: "Transaction event pipeline: a Producer and a Worker, built as one deliberately thin end-to-end slice so that a transaction event can travel the whole path Producer → RabbitMQ → Worker → PostgreSQL and produce a stored fraud decision. The Producer generates synthetic transaction events on a timer; the Worker consumes them, evaluates a small set of simple fraud rules, and persists the decision. Keep the slice thin on purpose: one event type, a small number of rules, one results table."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A transaction becomes a stored fraud decision (Priority: P1) 🎯 MVP

A developer starts the environment with one command. Without any further action, transaction events begin to be generated, each is examined for fraud, and a decision for each is stored durably. The developer can query the store and see decisions accumulating, including some that are flagged.

**Why this priority**: This is the first time the system does the thing it exists to do. Feature 001 delivered infrastructure that held no data and ran no logic; this story turns it into a working pipeline. Every later story improves the reliability or observability of this one, so nothing else has value without it.

**Independent Test**: Start the environment, wait, and query the decision store. If rows appear — some flagged, some not — with no manual step beyond the documented start command, this story is delivered.

**Acceptance Scenarios**:

1. **Given** a clean environment that has never run, **When** the developer runs the documented start command and waits, **Then** transaction events are generated continuously and a stored decision exists for each one, with no manual intervention.
2. **Given** the pipeline is running, **When** the developer inspects the decision store, **Then** each record identifies the transaction it came from, whether it was flagged, and which rule produced that outcome.
3. **Given** the pipeline is running, **When** events that plainly violate a rule are generated, **Then** those events are stored as flagged and events that violate no rule are stored as not flagged.
4. **Given** the pipeline is running, **When** the developer inspects the queue, **Then** it is not growing without bound: the consumer keeps pace with the generator at the default rate.

---

### User Story 2 - Exactly one decision per transaction, even when things fail (Priority: P2)

A developer kills the consumer in the middle of processing, or the database becomes briefly unavailable, or the broker redelivers a message it is not sure was handled. In every case, each transaction ends up with exactly one stored decision — never zero, never two — and nothing vanishes silently.

**Why this priority**: Fraud decisions are a financial record. A lost transaction is an undetected fraud; a double-counted one is a false accusation and a corrupted count. At-least-once delivery is the realistic guarantee of any broker, so duplicate delivery is a certainty rather than a risk, and the pipeline has to absorb it. This ranks below Story 1 only because there must be a pipeline before it can be made reliable.

**Independent Test**: Publish a known set of transactions, interfere (kill the consumer mid-processing, interrupt the database, force redelivery), then count stored decisions against transactions published. Exactly one each, every time.

**Acceptance Scenarios**:

1. **Given** a transaction has been fully processed and stored, **When** the same transaction is delivered again, **Then** no second decision is stored and no existing decision is altered.
2. **Given** the consumer is processing a transaction, **When** it is killed before the decision is stored, **Then** the transaction is delivered again after restart and ends with exactly one stored decision.
3. **Given** the consumer is processing a transaction, **When** the decision store is unavailable, **Then** the transaction is not acknowledged, is retried, and no decision is lost once the store recovers.
4. **Given** a message arrives that cannot be understood or processed at all, **When** the consumer rejects it, **Then** it is set aside somewhere a developer can retrieve and inspect it afterwards, and is never discarded unrecorded.
5. **Given** a run of transactions has been generated, **When** the developer compares transactions generated against decisions stored, **Then** the two counts match exactly.

---

### User Story 3 - The pipeline starts and recovers on its own (Priority: P3)

A developer starts everything at once from cold, or restarts just the broker, or closes their laptop and comes back. The services wait for what they need rather than crashing, and the pipeline resumes without being nursed back by hand.

**Why this priority**: The project's governing rules require a dependent service to retry rather than exit permanently, and feature 001 deliberately left that requirement unimplemented because it had no service to apply it to. This story is where that debt is paid. It ranks third because a developer can work around a startup race manually, but cannot work around lost data.

**Independent Test**: Start all components simultaneously from cold with no ordering help, then restart the broker and the database independently while the pipeline runs. Both services must survive all three events and resume on their own.

**Acceptance Scenarios**:

1. **Given** nothing is running, **When** everything is started simultaneously, **Then** both services reach a working state without manual restarts, regardless of which dependency becomes ready first.
2. **Given** the pipeline is running, **When** the broker is restarted underneath it, **Then** both services reconnect by themselves and processing resumes with no transactions lost.
3. **Given** the pipeline is running, **When** the decision store is restarted underneath it, **Then** the consumer reconnects by itself and every transaction already accepted still ends with exactly one decision.
4. **Given** the pipeline has been stopped, **When** it is started again, **Then** previously stored decisions are still present and unchanged.

---

### User Story 4 - A developer can trace one transaction and tune the generator (Priority: P3)

A developer picks a single transaction and follows it from the moment it was generated, through being examined, to its stored decision — using one identifier and nothing but documented commands. They can also change how fast transactions are generated, and make the obviously-fraudulent ones more or less frequent, to watch the rules work.

**Why this priority**: Without this, a failure in Stories 1–3 is undiagnosable: a missing decision tells you nothing about where it was lost. It also makes the fraud rules demonstrable rather than theoretical. It ranks with Story 3 because it changes nothing about correctness, only about how long it takes to understand a problem.

**Independent Test**: Pick one transaction identifier from the generator's output and locate every record of it — in the generator's log, the consumer's log, and the decision store — in under two minutes using only documented commands.

**Acceptance Scenarios**:

1. **Given** a transaction has passed through the pipeline, **When** the developer searches by its identifier, **Then** they find it in the generator's output, in the consumer's output, and in the decision store.
2. **Given** the pipeline is running, **When** the developer changes the configured generation rate and restarts, **Then** transactions are generated at the new rate with no change to any component's definition.
3. **Given** the pipeline is running, **When** the developer increases the proportion of plainly-fraudulent transactions, **Then** the share of flagged decisions rises correspondingly.
4. **Given** a stored decision, **When** the developer reads it, **Then** it states which rule caused the outcome, not merely that an outcome occurred.

---

### Edge Cases

- **A message that is not valid JSON, or is JSON but missing a required field**: it must be rejected and set aside for inspection, not retried forever and not dropped. One bad message must not stall every message behind it.
- **A message carrying an unrecognised extra field**: must be processed normally. A future producer version adding a field must not break the consumer.
- **The same transaction identifier arriving twice**: exactly one decision exists afterwards. Uniqueness must be guaranteed by the store itself, not only by the consumer's own bookkeeping, so that a second consumer cannot defeat it.
- **The decision store is unavailable at the moment a decision would be written**: the transaction must not be acknowledged, and must be processed later. A decision must never be acknowledged as handled when it was not stored.
- **The broker is unavailable when a transaction is generated**: the generator must retry rather than exit, and must not pretend to have published.
- **The consumer is slower than the generator**: the backlog must be visible, and work already queued must survive a restart of either service.
- **Two consumers running at once**: no transaction gets two decisions.
- **A transaction with an extreme or boundary amount** (zero, negative, enormous): it must receive a decision rather than crash the consumer, and the rule outcome at the exact threshold must be defined rather than accidental.
- **The velocity rule's window boundary**: whether a transaction exactly at the window edge counts must be defined, and the answer must not change depending on when the consumer last restarted.
- **The consumer restarts mid-window**: velocity decisions must not silently become wrong because in-memory history was lost.
- **The schema setup runs more than once** (restart, or a second consumer): it must not fail or duplicate structures.
- **Clock differences between generating and processing**: a timestamp slightly in the future or past must not cause a crash or a silently wrong velocity decision.
- **The set-aside store for unprocessable messages grows**: it must be observable, so a persistent fault is noticed rather than accumulating unseen.

## Requirements *(mandatory)*

### Functional Requirements

**Generating transactions**

- **FR-001**: The system MUST generate synthetic transaction events continuously, with no external data source and no inbound network dependency.
- **FR-002**: Each transaction event MUST carry a unique identifier, a creation timestamp, an account or card identifier, an amount, and a merchant.
- **FR-003**: The event format MUST be structured data (JSON) and MUST be documented as a written contract that both services refer to, rather than as code shared between them.
- **FR-004**: The rate of generation MUST be configurable without modifying any component definition.
- **FR-005**: The proportion of transactions that plainly violate a fraud rule MUST be configurable, so the rules can be observed working.
- **FR-006**: Transactions MUST be handed to the broker durably: the queue survives a broker restart and queued transactions are not lost with it.
- **FR-007**: The generator MUST be the only writer to the transaction queue.

**Examining transactions**

- **FR-008**: The system MUST evaluate every transaction against a small, explicit, documented set of fraud rules.
- **FR-009**: The rule set MUST include an amount-threshold rule and a velocity rule (several transactions on one account within a short window).
- **FR-010**: Each rule's threshold and window MUST be configurable without modifying any component definition, and MUST have a documented default.
- **FR-011**: The outcome of each rule at its exact boundary MUST be defined explicitly rather than left to chance.
- **FR-012**: Velocity decisions MUST remain correct across a restart of the examining service: they MUST NOT depend on history held only in memory.

**Storing decisions**

- **FR-013**: The system MUST store exactly one decision per transaction, recording the transaction identifier, whether it was flagged, which rule produced that outcome, and when the decision was made.
- **FR-014**: Storage structure MUST be created through versioned change files kept in the repository, applied automatically; no manual setup against a running store is permitted.
- **FR-015**: Applying the storage setup more than once MUST be safe and MUST NOT duplicate structures or fail.
- **FR-016**: One decision per transaction MUST be enforced by the store itself through a constraint, not only by the examining service's logic.

**Not losing and not double-counting**

- **FR-017**: A transaction MUST be acknowledged to the broker only after its decision has been durably committed to the store.
- **FR-018**: Re-delivery of an already-decided transaction MUST NOT create a second decision and MUST NOT alter the existing one.
- **FR-019**: A transaction that cannot be understood or processed MUST be set aside where a developer can retrieve and inspect it; it MUST NOT be discarded unrecorded and MUST NOT be retried indefinitely in a way that blocks other transactions.
- **FR-020**: The count of transactions generated and the count of decisions stored MUST be reconcilable, so loss or duplication is detectable rather than assumed absent.

**Running, restarting, recovering**

- **FR-021**: Both services MUST retry their connections to the broker and the store rather than exiting permanently when a dependency is not yet available or goes away.
- **FR-022**: Both services MUST be defined in the single existing environment definition and start with the same one command as the rest of the system.
- **FR-023**: Adding these services MUST NOT require any change to the existing broker and store definitions beyond each new service declaring its dependency on them being ready.
- **FR-024**: Each service MUST be independently buildable and runnable, living in its own directory with its own dependency list, and MUST NOT import code from the other.
- **FR-025**: All configuration — connection settings, credentials, rates, thresholds — MUST come from environment settings with committed examples; no credential may be written into any committed file.
- **FR-026**: No component may require anything installed on the host beyond the container tooling already required by feature 001.

**Understanding what happened**

- **FR-027**: Both services MUST write their output to standard output and standard error, viewable per service.
- **FR-028**: Every log line concerning a transaction MUST include that transaction's identifier, so one transaction can be followed across both services.
- **FR-029**: The backlog of waiting transactions and the number of set-aside unprocessable transactions MUST both be observable through documented commands.
- **FR-030**: Each service MUST report whether it is working, so the start command can wait for the whole pipeline rather than only for the broker and the store.

**Proving it works**

- **FR-031**: The fraud rules MUST have automated tests covering at least one flagged and one non-flagged case for each rule, including the boundary case.
- **FR-032**: The full path from generation to stored decision MUST have at least one automated test that runs against the real broker and the real store, with neither replaced by a stand-in.
- **FR-033**: Idempotency MUST be covered by an automated test that delivers the same transaction twice and asserts exactly one decision.

### Key Entities

- **Transaction event**: One purported card transaction. Carries a unique identifier, a creation time, an account identifier, an amount, and a merchant. Created by the generator, never modified afterwards.
- **Fraud decision**: The verdict on exactly one transaction event — flagged or not, which rule decided it, and when. Keyed by the transaction's identifier, which is what makes a repeat delivery harmless.
- **Fraud rule**: A named, documented test applied to a transaction, with a configurable threshold and a defined outcome at its boundary. Two exist in this feature: an amount threshold and a velocity rule.
- **Unprocessable transaction**: A message that could not be understood or decided. Retained for inspection with enough context to diagnose why, and counted so a persistent fault is visible.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a clean environment, a single documented start command produces stored fraud decisions within 60 seconds, with no manual step of any kind.
- **SC-002**: At the default generation rate, every generated transaction has exactly one stored decision: 100% coverage and zero duplicates, measured over a run of at least 1,000 transactions.
- **SC-003**: The time from a transaction being created to its decision being durably stored is under 2 seconds for 95% of transactions at the default rate.
- **SC-004**: The pipeline sustains at least 50 transactions per second for 5 continuous minutes with no lost transactions and no unbounded growth in the waiting backlog.
- **SC-005**: Delivering an already-decided transaction again produces zero additional decisions, across at least 100 repeat deliveries.
- **SC-006**: After the decision store is interrupted for up to 60 seconds mid-run, every transaction accepted before the interruption has exactly one decision once it recovers, with no manual repair.
- **SC-007**: After the broker is restarted mid-run, both services reconnect unaided and processing resumes, with zero transactions lost, in 100% of at least 3 attempts.
- **SC-008**: Every transaction that cannot be processed is retrievable afterwards: zero disappear unrecorded, verified by deliberately injecting malformed messages.
- **SC-009**: Both services start successfully regardless of dependency readiness order, in 100% of at least 5 consecutive cold starts.
- **SC-010**: A developer can locate every record of one chosen transaction — in both services' output and in the decision store — in under 2 minutes using only documented commands.
- **SC-011**: Each fraud rule produces its documented outcome for a flagged example, a non-flagged example, and the exact boundary value, verified automatically.
- **SC-012**: Changing the generation rate, a rule threshold, or the fraudulent proportion requires editing configuration only, with zero edits to any component definition.

## Assumptions

Reasonable defaults chosen where the description did not specify. Each is a decision that can be revisited, not a discovery.

- **Scope is one thin slice, deliberately.** One event type, two rules, one decision record per transaction. No scoring, no rule chaining, no machine learning, no case management, no alerting, no user interface. Depth is for later features.
- **A flagged transaction results in a stored record and nothing else.** No notification, no block, no downstream action. There is nothing yet to notify.
- **The generator runs continuously until stopped** rather than producing a fixed batch and exiting, because a continuously running pipeline is what later features need to develop against.
- **Default rule values** are an amount threshold and a short velocity window with a small count, each with a documented default and each configurable. The precise numbers are chosen so that the default generator settings produce both flagged and non-flagged transactions visibly — their job is to be demonstrable, not to be realistic fraud detection.
- **Velocity history is derived from the decision store**, the system's existing source of truth, rather than from memory in the examining service. This follows from FR-012 and from the project's rule that the store is the single system of record; it also means a restart or a second consumer cannot produce different answers. The cost is a read per transaction, which is accepted at these volumes.
- **One instance of each service** is run by default. The design must not *break* with two consumers — uniqueness is enforced by the store — but no feature depends on running two, and none is configured.
- **Performance targets** in SC-003 and SC-004 are stated for one developer machine of the kind feature 001 was measured on, with the broker and store running locally in containers. They are targets for a thin slice on a laptop, not production figures.
- **Unprocessable messages are kept in the messaging system** rather than in the decision store, since they could not be understood well enough to record as decisions.
- **No retention or archival policy.** Decisions accumulate. At these volumes and on a developer machine this is not a problem, and the documented reset from feature 001 discards everything.
- **Timestamps are recorded as given** and treated as information, not as a trusted ordering. Velocity uses the store's own view of when decisions were made, so a skewed clock in the generator cannot corrupt a rule outcome.
- **Feature 001 is a dependency and is treated as finished.** This feature adds to the existing environment definition and must not modify the broker or store service definitions — a property feature 001 verified in advance by connecting a throwaway service with no edits to either.
- **The queue topology is created by the services themselves** at startup, idempotently, rather than by a separate setup step, so that the single start command remains the only thing a developer runs.
