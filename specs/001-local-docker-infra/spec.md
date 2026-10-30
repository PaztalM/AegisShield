# Feature Specification: Local Docker Infrastructure

**Feature Branch**: `001-local-docker-infra` (spec directory name; no git branch was created — current branch is `dev`)

**Created**: 2026-10-23

**Status**: Implemented (all 45 tasks complete — all three user stories built and verified, all 16 `quickstart.md` scenarios passing; see `tasks.md` and the 2026-10-31 implementation entry in `LEARNING-LOG.md`). One success criterion is partially unmet and recorded as such: SC-001's request to record the measured link speed alongside the cold-start timing — the timing was taken (45.1s against a 300s budget) but link speed was not independently measured.

**Input**: User description: "Local Docker Infrastructure: As a developer, I need a docker-compose setup to run RabbitMQ (ports 5672, 15672) and PostgreSQL (port 5432) locally so I can develop the microservices."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Start the whole local environment with one command (Priority: P1)

A developer clones the repository onto a machine that has only container tooling installed, runs a single documented start command, and ends up with a running message broker and a running database. Both are reachable from the developer's host machine at the agreed addresses, using credentials the developer can read out of a committed example configuration file. The developer does not install a broker or a database on the host, and does not hand-edit any configuration to get a working environment.

**Why this priority**: Nothing else in the project can be built or tested without a broker and a database to talk to. This story alone is the minimum viable product: with it, a developer can begin writing and running the Producer and Worker services against real dependencies.

**Independent Test**: On a clean machine with container tooling only, run the start command, then connect to the broker and to the database from the host using any standard client. Both connections succeed with the documented example credentials. No other feature of the system is required.

**Acceptance Scenarios**:

1. **Given** a freshly cloned repository and no previously created local environment, **When** the developer copies the example configuration file to the active configuration file and runs the documented start command, **Then** the broker and the database both reach a healthy state and the command reports success without the developer taking any further action.
2. **Given** the environment is running, **When** the developer connects a standard message-broker client to the broker's messaging address using the documented credentials, **Then** the connection is accepted and the client can declare a queue and publish and consume a message.
3. **Given** the environment is running, **When** the developer connects a standard database client to the database's address using the documented credentials and database name, **Then** the connection is accepted and the client can run a query.
4. **Given** the environment is running, **When** the developer asks the container tooling for the status of the environment, **Then** every component is reported as running and healthy, and each component shows which host address it is published on.

---

### User Story 2 - Inspect and administer the broker through its management interface (Priority: P2)

A developer debugging a message flow opens the broker's web management interface in a browser on the host, signs in with the documented credentials, and inspects queues, message rates, consumers, and individual messages. They can also create or purge a queue by hand while experimenting.

**Why this priority**: Not required to run code, but it is the primary tool for diagnosing why a message was not consumed or why a queue is backing up. Without it, developers debug message flow blind, which is the most common source of lost time on a broker-based system.

**Independent Test**: With the environment running, open the management interface's host address in a browser, sign in, and confirm that queues and message rates are visible and that a queue can be created and purged from the interface.

**Acceptance Scenarios**:

1. **Given** the environment is running, **When** the developer opens the broker's management address in a host browser, **Then** a sign-in page is served.
2. **Given** the management sign-in page is open, **When** the developer signs in with the credentials from the example configuration file, **Then** access is granted and the broker's queues, connections, and message rates are visible.
3. **Given** a queue holding messages, **When** the developer purges it from the management interface, **Then** the queue's message count drops to zero and the change is visible immediately.
4. **Given** the stock default guest account of an unconfigured broker installation, **When** the developer attempts to sign in as that account, **Then** the attempt is rejected, because the environment defines its own administrative account instead.

---

### User Story 3 - Keep data across restarts, and discard it deliberately (Priority: P3)

A developer stops the environment at the end of the day and starts it again the next morning; the rows they wrote and the queues they declared are still there. Separately, when a developer wants a clean slate — corrupted test data, a changed schema, a bad experiment — a single documented command discards all stored state so the next start is indistinguishable from a first-ever start.

**Why this priority**: Valuable for day-to-day comfort and for reliable testing, but a developer can work without it for a while by recreating test data. It matters most once there is real schema and real test data to protect.

**Independent Test**: Write a row to the database and declare a durable queue, stop the environment, start it again, and confirm both survived. Then run the documented reset command, start again, and confirm both are gone.

**Acceptance Scenarios**:

1. **Given** data has been written to the database and a durable queue has been declared on the broker, **When** the developer stops and then restarts the environment, **Then** the data and the queue definition are both still present.
2. **Given** a running environment with stored state, **When** the developer runs the documented reset command and starts the environment again, **Then** the database contains no project data and the broker has no previously declared queues.
3. **Given** the environment has never been started on this machine, **When** the developer starts it, **Then** storage for both components is created automatically with no manual preparation.

---

### Edge Cases

- **A required host port is already taken** (another broker, another database, or a previous copy of this environment): the start command must fail loudly with a message that names the conflicting port, and must never silently bind elsewhere. The developer must be able to relocate the published port through configuration without editing the environment definition. **A partial start is accepted, because Compose cannot avoid one:** it creates every container and then starts them, so a component whose port is free will be running by the time the conflicted one fails. What matters is that the command exits non-zero, names the port, and leaves a state the documented recovery (`docker compose down`, then start again) fully resolves — verified in T036.
- **One component accepts connections later than the other**: a component must not be reported ready before it actually accepts connections. Readiness is decided by a real connection check, not by the container having been created.
- **A dependency is temporarily unreachable while something is starting** (constitution Principle IV): the dependent party must retry rather than exit permanently. **Deferred to the Producer and Worker features, deliberately.** The party that must retry is an application service, and this feature ships none, so there is nothing here to make retry. What this feature owes the retry requirement is the means to satisfy it: a readiness check per component (FR-010) and support for declaring a startup dependency on a healthy component (FR-015). Both are delivered and verified. The retry loop itself is a requirement on the first service that connects, and belongs in that service's spec.
- **The active configuration file is missing or incomplete**: the developer is told which setting is missing and where the example file is, instead of getting an opaque authentication failure from the broker or the database.
- **Credentials are changed in configuration after storage was first created**: the database keeps the credentials it was initialised with, so a changed value will fail to authenticate. The documentation must state that changing credentials requires discarding stored state.
- **The environment is started twice in a row**: the second start is a no-op or a clean restart; it must not create duplicate components or corrupt stored state.
- **The machine runs out of disk while the broker holds persistent messages**: the broker's refusal to accept further publishes must be visible through status or logs, not appear as an unexplained hang.
- **An unclean shutdown** (machine sleep, forced kill): the next start must either recover without manual repair of stored state, or state plainly that a reset is required.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The environment MUST define the two infrastructure components this feature delivers — a message broker and a relational database — in a single environment definition at the repository root, startable with one command. "Two" is the count this feature adds, not a ceiling on the file: the constitution requires the Producer and the Worker to live in this same definition later, which FR-015 provides for.
- **FR-002**: The broker MUST publish its messaging endpoint on host port `5672` and its web management endpoint on host port `15672` by default, each overridable per FR-004.
- **FR-003**: The database MUST publish its endpoint on host port `5432` by default, overridable per FR-004.
- **FR-004**: Each published host port MUST be overridable through configuration, so a developer whose host already uses one of these ports can relocate it without editing the environment definition.
- **FR-005**: All credentials, database names, virtual host names, and port values MUST be supplied through environment variables, with no value hard-coded in the environment definition.
- **FR-006**: A committed example configuration file MUST list every variable the environment reads, with working development defaults, so that copying it to the active configuration file is the only preparation step required before the first start.
- **FR-007**: The active configuration file MUST be excluded from version control, and no credential intended to be secret may be committed.
- **FR-008**: The broker MUST be configured with a project-defined administrative account, and MUST NOT be reachable through the stock default guest account.
- **FR-009**: The database MUST create a named application database and an owning account on first start, with no manual setup step.
- **FR-010**: Both components MUST declare a readiness check that verifies the component actually accepts connections, and the start command MUST be able to wait for both checks to pass before reporting the environment ready.
- **FR-011**: Both components MUST store their state in named persistent storage, so that stopping and restarting the environment preserves database contents and durable broker definitions.
- **FR-012**: A documented command MUST discard all persistent storage for the environment, returning it to a first-start state.
- **FR-013**: Every third-party image used MUST be pinned to an explicit version tag; floating tags such as `latest` MUST NOT be used.
- **FR-014**: Both components MUST be reachable from the host at the published ports, and reachable from other components inside the environment by a stable internal name, so that application services added later connect by name rather than by host address.
- **FR-015**: The environment definition MUST accept application services (the Producer and the Worker) later without restructuring — it MUST provide a shared internal network and support declaring a startup dependency on the two infrastructure components.
- **FR-016**: Each component's logs MUST be viewable individually through the container tooling's standard log command.
- **FR-017**: The repository MUST document the start, status, log, stop, and reset commands, the published addresses, and where credentials come from, in a place a new contributor finds without being told.
- **FR-018**: Starting the environment MUST require no host-installed dependency beyond the container tooling itself — no locally installed broker, database, client library, or language runtime.
- **FR-019**: A component that fails its readiness check MUST be surfaced as unhealthy in the environment's status output, never reported as healthy.
- **FR-020**: The broker MUST support queues that hold messages durably across a broker restart, so that services built later can rely on durable queues and persistent messages as the constitution requires.

### Key Entities

- **Environment definition**: the single declarative description of the local stack — which components run, which images and versions they use, which host ports they publish, which internal network they share, which persistent storage they attach, and which readiness checks gate them.
- **Configuration variable set**: the named settings the environment reads at start time — credentials, database name, broker virtual host, and host port numbers. Exists in two forms: a committed example carrying development defaults, and an uncommitted active file per developer.
- **Persistent storage volume**: one named store per component, holding the database's data directory and the broker's durable definitions and messages. Survives stopping the environment; removed only by the documented reset command.
- **Broker administrative account**: the project-defined account used both by application services to connect and by a developer to sign in to the management interface.
- **Application database and owning account**: the named database that services read and write later, plus the account that owns it — both created on first start.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a machine with container tooling and nothing else installed, a developer reaches a fully healthy local environment from a single start command plus one preparation step (copying the example configuration), in under 5 minutes including first-time image downloads on a connection of at least 50 Mbit/s. The link speed is part of the criterion because the image pull dominates the cold number; a slower connection is not a failure of this environment, so the measured link speed is recorded alongside the timing.
- **SC-002**: Once images are cached locally, a start-to-healthy cycle completes in under 60 seconds.
- **SC-003**: 100% of the environment's components report healthy before the start command reports the environment ready; a developer never has to guess whether a component is accepting connections yet.
- **SC-004**: A developer can reach the broker's messaging endpoint, the broker's management interface, and the database from the host using only values read from the committed example configuration — 3 of 3 endpoints reachable, with zero undocumented values needed.
- **SC-005**: Data written before a stop is present after the next start in 100% of attempts, across at least 5 consecutive stop/start cycles.
- **SC-006**: The documented reset command returns the environment to a state indistinguishable from a first-ever start, verified over at least 5 consecutive reset-and-start cycles with no manual repair.
- **SC-007**: Zero secrets are present in version control and zero configuration values are hard-coded in the environment definition, verified by inspection of the committed files.
- **SC-008**: A contributor who has never seen the project completes setup from the written documentation alone, without asking anyone for help, in under 10 minutes of hands-on time. Because this project has one maintainer, the criterion is verified as a property of the documentation rather than by recruiting a stranger: every value the setup needs appears in the committed documentation or the example configuration, no step in the documented path depends on a value or command written down nowhere, and no step assumes the reader has seen this feature's design documents. Timing an uninvolved person is the better evidence and is taken when one is available, but the audit is what gates the criterion.
- **SC-009**: When a required host port is already occupied, the start command fails within 10 seconds with a message naming the occupied port, in 100% of attempts.
- **SC-010**: Adding the first application service to the environment definition later requires no change to the two infrastructure components' own definitions beyond that service declaring a dependency on them.

## Assumptions

- **The audience is developers on their own machines.** This environment is for local development and automated testing. Production deployment, orchestration at scale, and hardened security settings are explicitly out of scope; development-grade default credentials in the committed example file are acceptable because nothing here is intended to be exposed beyond localhost.
- **Container tooling is a prerequisite, not part of this feature.** Installing Docker and Docker Compose is the developer's responsibility; this feature assumes a recent version with Compose support and does not script its installation.
- **The ports named in the description are defaults, not the only option.** `5672`, `15672`, and `5432` are what the environment publishes unless overridden in configuration. Overridability is required because these ports collide with any host-installed broker or database.
- **Application services are out of scope for this feature.** The Producer and the Worker are separate features; this one delivers the broker and the database, plus an environment definition shaped so those services drop in later (shared network, dependency ordering, connection by internal name).
- **Message topology and database schema are out of scope.** Exchanges, queues, bindings, and tables are owned by the services that use them, and are created by those services or through versioned migration files per constitution Principles II and III. This feature delivers an empty broker and an empty named database, and nothing more.
- **Persistence is on by default.** Named volumes are used rather than ephemeral storage, with an explicit documented reset path, because losing test data on every restart is a worse default than occasionally running one reset command.
- **One instance of each component per machine.** No clustering, replication, or multi-node setup.
- **Throughput and latency targets are not set here.** Per the constitution, measurable "real-time" numbers belong in the feature specs that define the fraud-detection path, not in this infrastructure feature. The only timing commitments here concern environment startup.
- **Documentation lives in the repository README** (or a file it links to), which is where a new contributor looks first.
