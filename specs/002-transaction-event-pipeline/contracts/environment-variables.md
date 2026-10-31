# Contract: Environment variables

Every variable this feature adds, its default, which component reads it, and what it does. Feature 001 established nine variables; this feature adds **twelve**, bringing `.env.example` to **twenty-one**.

> **Corrected 2026-10-31** after the `/speckit-analyze` cross-check: this file previously said eleven and twenty, while its own tables listed twelve. The miscount matters because feature 001's variable-parity audit works by comparing counts, so a wrong expected number makes the audit pass when it should fail.

Feature 001's rules carry over and are not restated per-row:

1. A variable exists only when something reads it. No speculative settings (Principle V).
2. Credentials and connection settings come from the environment, never hard-coded (Principle III).
3. Every variable appears in `.env.example` with a working development default, so `cp .env.example .env` yields a running system with no editing (FR-025).
4. Error messages printed to a terminal use plain ASCII hyphens, never em dashes — feature 001 found that terminals on Windows may be cp1252.

## The two tiers, carried over from feature 001

| Tier | Form in `docker-compose.yml` | Behaviour when unset |
|---|---|---|
| **Required** | `${VAR:?VAR is not set - copy .env.example to .env}` | Compose refuses to start and names the variable, before any container is created |
| **Defaulted** | `${VAR:-default}` | Falls back silently to the default |

The distinction is not cosmetic. Feature 001's T037 verified both halves: a missing *required* variable is refused by name before anything starts, and a missing *defaulted* one starts normally on its default.

**Credentials are required. Everything tunable is defaulted.** A missing password must stop the start with a clear message rather than silently connect as something unexpected; a missing generation rate should just use its default.

---

## New variables

### Both services — connection settings

These are **defaulted** tier, as the table below states. (This paragraph previously said "required", contradicting its own table — corrected 2026-10-31.) Defaulted is correct because a hostname is not a secret and the default is simply the Compose service name: a missing one should start normally rather than refuse to boot. Contrast the credentials, which stay required tier precisely because silently falling back to a default password is worse than not starting.

They are not duplicated credentials: they are the same values feature 001 already defines, referenced by the new services. The reason they appear as separate variables at all is that the services need the broker and database *hostnames*, which are internal to the Compose network and have no meaning to the broker or database images themselves.

| Variable | Tier | Default | Read by | Purpose |
|---|---|---|---|---|
| `RABBITMQ_HOST` | defaulted | `rabbitmq` | producer, worker, tests | Internal DNS name of the broker. Defaulted because it is the Compose service name and will not vary; overridable so a developer can point a service at something else without editing the Compose file. |
| `POSTGRES_HOST` | defaulted | `postgres` | worker, tests | Internal DNS name of the database, same reasoning. |

Credentials, the virtual host and the database name are **not** re-declared here. The new services read the existing `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS`, `RABBITMQ_DEFAULT_VHOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`. Introducing a second set of variables for the same secrets would be the beginning of two sources of truth, and the first time they disagreed the failure would be an authentication error pointing at nothing.

Note the services use the **internal** ports `5672` and `5432`, not `RABBITMQ_PORT` / `POSTGRES_PORT`. Those publish to the host and can be moved; the container-side ports are fixed. A service inside the network that used the host-side port would break the moment a developer relocated it for a port conflict — which feature 001's T036 proved is a real scenario.

### Producer — generation

| Variable | Tier | Default | Purpose |
|---|---|---|---|
| `PRODUCER_RATE_PER_SECOND` | defaulted | `5` | Transactions generated per second (FR-004). Default kept modest so the default experience is readable in `docker compose logs` rather than a blur; SC-004's 50/second is a target the system must *sustain*, not the default it runs at. |
| `PRODUCER_FRAUD_RATIO` | defaulted | `0.1` | Fraction of transactions deliberately built to be flagged, so the rules are observably working (FR-005). |
| `PRODUCER_ACCOUNT_POOL_SIZE` | defaulted | `20` | How many distinct account identifiers to draw from. Small on purpose: it is what makes several transactions land on one account inside the velocity window, so the velocity rule fires without special-casing. Raising this suppresses velocity flags. |

### Worker — rules

| Variable | Tier | Default | Purpose |
|---|---|---|---|
| `FRAUD_AMOUNT_THRESHOLD` | defaulted | `5000.00` | Amount above which a transaction is flagged, strictly greater. See [fraud-rules.md](./fraud-rules.md). |
| `FRAUD_VELOCITY_COUNT` | defaulted | `4` | Transactions on one account within the window needed to flag, counting the current one. |
| `FRAUD_VELOCITY_WINDOW_SECONDS` | defaulted | `60` | Length of the velocity window. |

### Both services — operational

| Variable | Tier | Default | Purpose |
|---|---|---|---|
| `LOG_LEVEL` | defaulted | `INFO` | Standard logging level for both services. One variable rather than one per service, because there is no present need to set them differently. |
| `RETRY_MAX_DELAY_SECONDS` | defaulted | `30` | Ceiling on the exponential backoff both services use when reconnecting to a dependency (FR-021). The backoff grows to this and stays there; there is no attempt limit, because Principle IV requires retrying rather than exiting. |
| `HEARTBEAT_FILE` | defaulted | `/tmp/heartbeat` | Path each service touches each loop iteration, and that its Compose healthcheck checks the freshness of (FR-030). See research.md §7. |
| `HEARTBEAT_MAX_AGE_SECONDS` | defaulted | `30` | How stale the heartbeat may be before the healthcheck reports the service unhealthy. Must be comfortably longer than one loop iteration at the slowest configured rate, or a healthy service will be reported unhealthy. |

---

## Full count

| Source | Variables |
|---|---|
| Feature 001 | 9 |
| This feature | 12 |
| **Total in `.env.example`** | **21** |

Feature 001's T034 audited that every `${VAR}` the Compose file interpolates appears in `.env.example` and that every `.env.example` key is actually read, with no speculative extras. That audit must be repeated for this feature at twenty-one variables — the parity property is what keeps the example file trustworthy, and it is easy to break while adding twelve at once.

## Variables deliberately not added

Recorded so their absence reads as a decision rather than an oversight:

- **No `WORKER_PREFETCH`.** Prefetch is fixed at 1 by [queue-topology.md](./queue-topology.md) because the ack-after-commit guarantee is easiest to reason about with one outstanding message. Making it tunable invites someone to raise it and quietly widen the window in which a crash loses work.
- **No `QUEUE_NAME` or exchange names.** They are fixed by the topology contract. Queue arguments are immutable in RabbitMQ, so a configurable name would create a class of confusing `PRECONDITION_FAILED` failures for no benefit.
- **No `DATABASE_URL`.** The individual `POSTGRES_*` variables already exist from feature 001; a combined URL would duplicate them and create the two-sources-of-truth problem described above.
- **No `PRODUCER_TOTAL_EVENTS` or run limit.** The Producer runs until stopped, per the spec's Assumptions. A limit would be a feature nobody asked for.
- **No separate test-specific credentials.** The tests run against the same environment, by design — FR-032 requires the real broker and real database.
