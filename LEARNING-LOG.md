# AegisShield — Learning Log

**A plain-language record of what we did, why we did it, and what we chose not to do.**

Last updated: 2026-10-23

This file assumes you know nothing in advance. Every term gets defined the first time it shows up. It is written to be read top to bottom, but you can jump to any section.

> **The single most important thing to understand right now:** 29 of the 45 tasks are done. One command brings up a healthy RabbitMQ and a healthy PostgreSQL, the broker's web interface is published, and both named volumes are now mounted — so a stop no longer discards the data. What is **not yet proven** is that the data survives: nothing has written a row, stopped, started again and found it still there. That is T030, and until it passes, persistence is an expectation rather than a measured fact. Section 10 states the exact position and explains why. Sections 1–9 explain the reasoning that got us here.

---

## Table of contents

1. [What AegisShield is supposed to be](#1-what-aegisshield-is-supposed-to-be)
2. [The vocabulary you need first](#2-the-vocabulary-you-need-first)
3. [Why we wrote documents instead of code](#3-why-we-wrote-documents-instead-of-code)
4. [What we have actually done, in order](#4-what-we-have-actually-done-in-order)
5. [The constitution, explained line by line](#5-the-constitution-explained-line-by-line)
6. [The first feature: local Docker infrastructure](#6-the-first-feature-local-docker-infrastructure)
7. [Every real engineering decision we made, and why](#7-every-real-engineering-decision-we-made-and-why)
8. [Things we deliberately did NOT do](#8-things-we-deliberately-did-not-do)
9. [The two .gitignore files](#9-the-two-gitignore-files)
10. [Where we are right now](#10-where-we-are-right-now)
11. [What happens next](#11-what-happens-next)
12. [Glossary](#12-glossary)

---

## 1. What AegisShield is supposed to be

A **real-time fraud detection system**. The idea: transactions (someone paying for something) flow into the system, and the system decides whether each one looks fraudulent.

It is being built as four pieces:

| Piece | What it does | Built by us? |
|---|---|---|
| **Producer** | Creates or receives transaction events and sends them onward | Yes, Python — not built yet |
| **Worker** | Receives transaction events, decides if they're fraud, saves the result | Yes, Python — not built yet |
| **RabbitMQ** | The mailroom that carries messages from Producer to Worker | No — we use the official off-the-shelf version |
| **PostgreSQL** | The database where results are permanently stored | No — we use the official off-the-shelf version |

"Real-time" here means transactions get judged as they arrive, not in a nightly batch job.

### Why split it into separate pieces at all?

A single program could do all of this. We're splitting it because:

- **Independent scaling.** If fraud-checking is slow, you can run ten Workers and one Producer. In a single program you'd have to duplicate everything.
- **Isolation.** If the Worker crashes, the Producer keeps accepting transactions. Messages pile up safely in RabbitMQ and get processed when the Worker comes back. In a single program, a crash loses everything in flight.
- **Replaceability.** You can rewrite the Worker completely without touching the Producer, as long as the message format between them stays the same.

This architecture style is called **microservices**. The cost is real: more moving parts, more things to configure, harder debugging. That's why the constitution (Section 5) has rules about not adding more services casually.

---

## 2. The vocabulary you need first

Nothing below this line will make sense without these. Read this section even if some of it looks familiar.

### Docker, images, and containers

**The problem Docker solves:** "it works on my machine." Software needs a specific operating system, specific libraries, specific versions. Install PostgreSQL on your Windows laptop and on a Linux server and you get two subtly different things. Debugging that difference wastes days.

**Docker's answer:** package the software *together with* everything it needs into a sealed box that runs identically everywhere.

Two words that are easy to mix up:

- **Image** — the frozen template. Like a recipe, or an `.iso` file. It doesn't run; it just sits there. `postgres:18.4-alpine` is an image.
- **Container** — a running copy made from an image. Like a cake baked from the recipe. You can make many containers from one image.

The relationship: **image is to container what a class is to an object**, if you've done object-oriented programming. Or: image is the blueprint, container is the house.

**Critical consequence:** when you delete a container, everything it wrote to its own filesystem is deleted with it. Containers are designed to be disposable. This is why volumes exist (below).

### Image tags

`postgres:18.4-alpine` has three parts:

- `postgres` — the image name
- `18.4` — the **tag**, usually a version
- `-alpine` — a variant. Alpine is a tiny Linux distribution, so `-alpine` images are much smaller (faster to download) but built on different low-level libraries than the standard version.

A tag is just a **label pointing at a specific image**, and labels can be moved. `postgres:latest` points at whatever the newest version is *today*. Tomorrow it points somewhere else. Your build silently changes under you.

This is why the constitution bans `latest`. We pin `18.4` — a specific, immutable point.

### Volumes

A **volume** is storage that Docker manages, living *outside* any container's own filesystem. A container mounts it at a path, writes to that path, and the data survives the container being destroyed and rebuilt.

Analogy: the container is a laptop you throw away every day; the volume is the external USB drive you plug into the new one each morning.

We use **named volumes** — Docker creates and manages them, and you refer to them by name (`postgres-data`). The alternative is a **bind mount**, where you point at a real folder on your own computer (`./data:/var/lib/postgresql/data`). We rejected bind mounts, and Section 7 explains why.

### Networks and DNS

Containers are isolated from each other by default. A **Docker network** is a virtual network you put containers on so they can talk.

The useful magic: on a user-defined Docker network, **containers can find each other by name**. The Worker can connect to the hostname `postgres` and Docker's built-in DNS resolves it to the right container's address. You never need to know or hardcode an IP address.

**DNS** (Domain Name System) is the general internet mechanism that turns a name like `google.com` into a numeric address. Docker runs a small private DNS server for your containers.

### Ports, and the two sides of a port mapping

A **port** is a numbered door on a machine. One machine has one address but 65,535 ports, so many programs can listen at once without colliding. By convention certain numbers mean certain services: PostgreSQL listens on 5432, RabbitMQ on 5672.

A container's ports are private by default. To reach one from your own computer you **publish** it:

```
"5432:5432"
 ↑     ↑
 │     └── container side: the port inside the container. Fixed. The software chose it.
 └──────── host side: the port on YOUR computer. Yours to choose.
```

If something on your laptop already uses 5432, you change the left number only — `"55432:5432"` — and connect to 55432 from your laptop. Inside the Docker network nothing changed; the container still listens on 5432.

**This distinction is the single most confusing thing for beginners with Docker, and it explains a design rule we'll come back to repeatedly.**

### Docker Compose

Starting one container is a long command. Starting four containers, wiring them onto a network, attaching volumes, and setting configuration is an unmanageable pile of commands.

**Docker Compose** lets you write all of it down in one file — `docker-compose.yml` — and then run `docker compose up`. One command, the whole environment.

The file is **declarative**: you describe the desired end state ("two services, one network, two volumes") rather than the steps to get there. Compose figures out the steps. Contrast with **imperative**, where you'd write out each command in order. Declarative is better here because running it twice is safe — Compose compares reality to your description and fixes the difference.

### YAML

`docker-compose.yml` is written in **YAML**, a format for structured data that uses indentation instead of brackets:

```yaml
services:          # a key
  postgres:        # nested under services (2 spaces in)
    image: postgres:18.4-alpine   # nested under postgres
    ports:
      - "5432:5432"               # a list item (the dash)
```

Two rules that will bite you: **indentation must be spaces, never tabs**, and indentation level is what determines nesting. A single wrong space breaks the file.

### Environment variables

An **environment variable** is a named value handed to a program when it starts, from outside the program. `POSTGRES_PASSWORD=secret123`.

Why they matter: they let the *same* image behave differently in different places without editing the image. The official PostgreSQL image reads `POSTGRES_PASSWORD` and sets up that password. You didn't modify PostgreSQL; you configured it from outside.

They're also the standard way to keep **secrets** out of your code. If the password is written in `docker-compose.yml` and you commit that file to Git, the password is now in your project history forever — visible to everyone with access, and very hard to truly remove. Environment variables let the file say "read the password from somewhere else."

### `.env` and `.env.example`

Compose automatically reads a file named `.env` in the project folder and uses its values to fill in blanks in `docker-compose.yml`.

So we need two files, and the pairing is a standard industry pattern:

| File | Committed to Git? | Purpose |
|---|---|---|
| `.env.example` | **Yes** | A template listing every variable with safe fake values. Documentation you can copy. |
| `.env` | **No, never** | Your real values. Ignored by Git so secrets never get committed. |

A new contributor runs `cp .env.example .env` and has a working configuration. They can see exactly which variables exist, because the example lists them all. Without the example file, a newcomer would have no way to know what the system needs.

### Git and `.gitignore`

**Git** records the history of your project — every change, who made it, when. **GitHub** is a website that hosts Git repositories; Git itself runs on your machine.

**Commit** = a saved snapshot with a message. **Branch** = an independent line of work. You're on a branch called `dev`.

**Tracked** = Git is watching this file. **Untracked** = Git sees it but isn't recording it.

`.gitignore` is a list of patterns Git should pretend not to see. Critically: **`.gitignore` prevents accidents, it does not undo them.** If you commit a password and *then* add it to `.gitignore`, the password is still in your history. This is why `.env` is in `.gitignore` before `.env` ever exists.

### Healthchecks

Here is a problem that catches everyone:

A container can be **running** without the software inside it being **ready**. PostgreSQL takes a few seconds to start up. During that window the container exists, Docker reports it as running, and every connection attempt fails.

If the Worker starts the instant the container exists, it tries to connect, gets refused, and crashes.

A **healthcheck** is a command Docker runs inside the container on a repeating schedule to ask "are you *actually* ready?" The container's status becomes `healthy` only when that command succeeds. Other services can then wait for `healthy` rather than merely `running`.

Getting a healthcheck *right* is harder than it looks, and Section 7 covers the trap we specifically avoided.

### AMQP, queues, and the message broker

**RabbitMQ** is a **message broker** — a mailroom. The Producer drops a message in; the Worker picks it up later. Neither needs the other to be online at that moment.

**AMQP** (Advanced Message Queuing Protocol) is the language they speak to RabbitMQ. It uses port 5672.

Key terms:

- **Queue** — a line where messages wait to be picked up.
- **Durable queue** — a queue whose *definition* survives a RabbitMQ restart. A non-durable queue vanishes on restart.
- **Persistent message** — a message written to disk, so the *message itself* survives a restart. Durable queue + persistent message together is what stops transactions from being lost.
- **Virtual host (vhost)** — a named compartment inside one RabbitMQ server, holding its own separate set of queues and permissions. Like separate folders, or separate databases within one database server. Ours is `aegisshield`.
- **Management interface** — a web page RabbitMQ can serve (port 15672) where you click around and inspect queues, message rates, and individual messages. Invaluable for debugging.

### `localhost` — and the mistake everyone makes once

`localhost` means "this machine, right here." But **inside a container, "this machine" is the container itself**, not your laptop.

So if the Worker container tries to connect to `localhost:5672`, it is looking for a RabbitMQ inside its *own* container, finds nothing, and fails.

The rule: **from your laptop, use `localhost:5672`. From inside a container, use `rabbitmq:5672`** — the service name, resolved by Docker's DNS.

---

## 3. Why we wrote documents instead of code

This will feel like the slow path. It is worth understanding why it isn't.

We're using **Spec Kit**, a workflow that forces four phases in order:

```
specify  →  plan  →  tasks  →  implement
 WHAT       HOW      STEPS      DO IT
```

Each phase produces documents the next phase consumes. The slash commands you've been running (`/speckit-specify`, `/speckit-plan`, `/speckit-tasks`) are each one phase.

### The reasoning

**Phase 1 — specify.** Describe *what* the feature must do and how you'll know it worked. **Deliberately contains no technical choices.** Our `spec.md` never says "RabbitMQ" or "Docker" — it says "a message broker," "the container tooling." That forces you to be clear about the requirement before you fall in love with a solution.

**Phase 2 — plan.** Now decide *how*. Pick versions, pick commands, write down why. This is where the real engineering thinking happens.

**Phase 3 — tasks.** Break the plan into a numbered checklist where each item is small, concrete, and names the exact file it touches. The point: a task should be executable without re-deriving any decisions.

**Phase 4 — implement.** Work the checklist. Because the thinking is done, this becomes mechanical — which is exactly what you want, because mechanical work is where you make the fewest mistakes.

### Why this makes you an engineer rather than a prompt engineer

You named the distinction yourself, so let me be direct about it.

Prompting is asking for an outcome. Engineering is being able to answer **"why is it this way and not another way?"** for every choice in the system — and knowing what would have to change for a different answer to become correct.

Compare:

- *"Add a healthcheck for Postgres"* → you get something that works, and you learn nothing. Six months later it breaks and you can't fix it.
- *"The healthcheck must be `pg_isready -h 127.0.0.1`, because without `-h 127.0.0.1` it checks the Unix socket, which answers during initialization before the TCP port is open, so Compose would declare the database ready too early"* → you now understand a whole class of startup bugs.

The documents exist so that every decision has a recorded reason. `research.md` is the most valuable file in the project right now: it holds not just what we chose but **what we rejected and why**. That's Section 8.

Also worth being blunt: this much documentation is heavy for a project this small. For a two-service learning project, writing a constitution, a spec, a plan, research notes, a data model, three contracts, a quickstart, and 44 tasks is more process than a professional team would use. You're doing it to *learn the discipline*. Once you've internalized it you'll know which parts to keep for a given project. Knowing when to skip a step is also engineering — but you have to learn the step before you earn the right to skip it.

---

## 4. What we have actually done, in order

Four things have happened. Only the third and fourth happened in our current conversation.

### Step 1 — Wrote the constitution *(committed to Git)*

`.specify/memory/constitution.md`. Five rules the whole project must obey, with the reasoning for each. Explained in full in Section 5.

**Why first:** if you decide architectural rules per-feature, every feature drifts. Writing them once, up front, means every later decision has something to be checked against. This is where the project's standards live.

### Step 2 — Wrote the specification *(committed to Git)*

`specs/001-local-docker-infra/spec.md`. What the first feature must achieve, with:

- **3 user stories**, prioritized P1/P2/P3
- **20 functional requirements** (FR-001 … FR-020) — things the system MUST do
- **10 success criteria** (SC-001 … SC-010) — measurable proof it worked
- **8 edge cases** — the awkward situations

**On the numbering:** FR-012 is a *label*, so later documents can say "this task exists because of FR-012" and you can trace any line of code back to the requirement that justifies it. That chain — requirement → design decision → task → code — is called **traceability**, and it's how you avoid building things nobody asked for and how you avoid silently dropping things someone did.

**On "measurable":** SC-002 says "under 60 seconds," not "fast." "Fast" can't be tested; two people will disagree forever. 60 seconds can be timed, and the answer is yes or no.

### Step 3 — Wrote the plan and its supporting research *(NOT yet committed)*

Five files from `/speckit-plan`:

| File | What's in it |
|---|---|
| `plan.md` | The technical approach, plus a **Constitution Check** table proving the feature obeys all five principles |
| `research.md` | Every decision, with rationale and the rejected alternatives. The richest file here. |
| `data-model.md` | Each "thing" in the feature and its exact field values and rules |
| `contracts/environment-variables.md` | The 9 configuration variables, their defaults, and which image reads each |
| `contracts/service-endpoints.md` | The addresses — from your laptop, and from inside the network |
| `contracts/operator-commands.md` | The exact commands you'll type, and what each guarantees |

**Why a "Constitution Check":** a gate. Before any implementation, you prove in writing that the design doesn't violate your own rules. It's a forcing function — the moment you have to write "PASS" next to Principle V, you have to actually look at whether you snuck in an abstraction.

### Step 4 — Wrote the task list *(this conversation, NOT yet committed)*

`specs/001-local-docker-infra/tasks.md` — **44 numbered tasks**, T001 through T044, grouped into six phases. *(Now 45: the 2026-10-30 analysis entry added T045.)*

I read all seven documents above first, then derived the tasks from them. Each task names its exact file and quotes its constraints verbatim, so no decision gets re-made at implementation time.

The phases:

| Phase | Tasks | What for |
|---|---|---|
| 1 — Setup | T001–T003 | Check Docker works, check the image versions still exist, check `.gitignore` |
| 2 — Foundational | T004–T006 | Create `.env.example`; create the skeleton of `docker-compose.yml`; copy `.env` |
| 3 — User Story 1 | T007–T020 | Both services defined and verified working. **This is the MVP.** |
| 4 — User Story 2 | T021–T025 | The RabbitMQ web interface |
| 5 — User Story 3 | T026–T032 | Volumes, data survival, the reset command |
| 6 — Polish | T033–T045 | Edge cases, audits, final checks, re-measure the timings, update this log |

**MVP** = Minimum Viable Product: the smallest version that is genuinely useful. Here, finishing Phase 3 means you can start writing the Producer and Worker. Phases 4 and 5 make life nicer but you aren't blocked without them.

**Why group by user story rather than by file type?** The obvious grouping would be "all the YAML tasks, then all the docs tasks." But then you have nothing working until the very end. Grouping by user story means that after Phase 3 you have something that *runs*. You can stop at any phase boundary and have real, working value. That's **incremental delivery**, and it's one of the highest-leverage habits in software.

### Also in this conversation

You asked why there are two `.gitignore` files. Answer in Section 9. Nothing needed changing.

---

## 5. The constitution, explained line by line

The file is at `.specify/memory/constitution.md`. Here is each principle in plain words.

A note on **MUST** / **MUST NOT** / **SHOULD**: these are deliberate, from a standard called RFC 2119. **MUST** = absolute requirement, no exceptions. **SHOULD** = strong recommendation, deviate only with a stated reason. Precise words prevent arguments later.

### Principle I — Explicit Service Boundaries

> Each service in its own directory with its own Dockerfile. Services must not import each other's code. A new service must be justified.

**Plain version:** Producer and Worker stay genuinely separate. They never `import` from each other. If they need to agree on a message format, that format is written down as a document, not shared as code.

**Why:** the instant two services share a code file, changing one can break the other, and you no longer have two services — you have one program in two directories with extra deployment complexity and none of the benefits. Sharing code is the most common way a microservice architecture quietly collapses into a worse version of a single program.

**Cost:** you will duplicate a little code. That is the accepted price.

### Principle II — Message-Driven Communication via RabbitMQ

> RabbitMQ is the only channel between Producer and Worker. No direct HTTP calls. No communicating through the database. Durable queues, persistent messages. Acknowledge only after the database commit. Idempotent processing. JSON payloads with an event ID and timestamp.

**Plain version:** they talk *only* through the mailroom.

The two subtle rules are the ones worth dwelling on:

**"Acknowledge only after the result is committed to PostgreSQL."** An **acknowledgement** ("ack") is the Worker telling RabbitMQ "done, you can delete this." If the Worker acks first and *then* crashes before saving, the message is gone and the transaction was never judged. By acking last, a crash means RabbitMQ never got the ack, so it redelivers the message. Nothing is lost.

**"Processing must be idempotent."** **Idempotent** means doing it twice has the same effect as doing it once. This is *required* because of the rule above — redelivery means the Worker will sometimes see the same message twice. If it blindly inserted a row each time, you'd get duplicate fraud decisions for one transaction.

The chain of reasoning is worth tracing, because it's a great example of how real constraints cascade:

```
Brokers can only promise "at-least-once" delivery
  → so duplicates WILL happen
    → so ack-after-commit is required (don't lose messages)
      → which guarantees duplicates on crash
        → so processing MUST be idempotent
          → so you need a unique event ID
            → so every message MUST carry one   (Principle II, last bullet)
              → and uniqueness MUST be enforced by the database  (Principle III)
```

Every one of those bullets exists because of the one above it. None of them is arbitrary.

### Principle III — PostgreSQL as the System of Record

> One database. Schema changes only through versioned migration files. Uniqueness enforced by database constraints, not just application code. Credentials from environment variables.

**System of record** = the one authoritative place. If two stores disagree, you need a tie-breaker rule, and that's a bug factory. So: one store.

**Migration file** = a numbered SQL file checked into Git that describes a schema change (`001_create_transactions.sql`). Running them in order rebuilds the schema from scratch on any machine. The alternative — typing `CREATE TABLE` by hand into the live database — means the schema exists only in that one database, nobody can reproduce it, and there's no record of what changed or why. The constitution flatly prohibits it.

**"Enforced by database constraints, not only application logic"** — this is an important instinct. Application code can be bypassed: a second copy of the service, a manual query, a bug. A `UNIQUE` constraint in the database cannot be bypassed by anything. Put your guarantees at the lowest level that can enforce them.

### Principle IV — Docker Compose Runs Everything

> Everything in one `docker-compose.yml`, started with `docker compose up`. No host dependencies beyond Docker. Config through environment variables with a committed `.env.example`. Services must retry connections rather than crashing. Images pinned to explicit versions.

This is the principle our first feature *implements*, so it's the one to know best.

**"No host dependencies beyond Docker"** — you should never have to install PostgreSQL, RabbitMQ, or even Python on your laptop. Everything lives in containers. This is what makes a new contributor productive in ten minutes instead of a day, and it's why our `quickstart.md` runs `psql` *inside* the container via `docker compose exec` rather than assuming you have `psql` installed.

**"Services must retry rather than crash"** — and note that healthchecks do **not** replace this. Healthchecks order the *startup*. But PostgreSQL could restart at 3am, long after startup, and the Worker must survive that. Startup ordering and runtime resilience are different problems and you need both. (Compose has a `depends_on` with `condition: service_healthy` for the first; retry loops in your code for the second.)

### Principle V — No Premature Abstraction

> Write the direct, concrete solution first. No abstraction until three concrete cases need it. No interface with one implementation. No speculative configuration or features "for later." Any abstraction must be justified in the plan.

**Abstraction** = a layer that hides details behind a simpler interface. A function is an abstraction. A base class, a plugin system, a "database layer" wrapping the real driver — all abstractions.

Abstractions are genuinely good *when they're right*. The problem is predicting correctly before you have real cases. Guess the shape wrong and you get a layer that fights you — and removing it is far more work than adding it was, because by then everything depends on it.

The "**rule of three**" is the industry heuristic: one case, write it directly. Two cases, maybe tolerate the duplication. Three cases, now you can actually see the pattern, so abstract.

**Where this principle bit in our feature, concretely:** it was tempting to write a `start.sh` script, or a `Makefile` so you could type `make up`. We didn't. Why? `docker compose up -d --wait` is already one line. A wrapper would add a file to maintain, hide the real command (so you'd never learn it), and — on Windows — require you to install `make`, which breaks Principle IV's "no host dependencies." A layer that adds a dependency to save eleven characters is a bad trade.

That's the principle doing its job: it stopped us from building something that felt helpful and was actually a net negative.

### Technology Stack, Workflow, Governance

The rest of the file pins the stack (Python 3, RabbitMQ, PostgreSQL, Compose), requires the Spec Kit flow and tests, and sets **semantic versioning** for the constitution itself:

- **MAJOR** (1.0.0 → 2.0.0): a principle removed or redefined incompatibly
- **MINOR** (1.0.0 → 1.1.0): a new principle or section added
- **PATCH** (1.0.0 → 1.0.1): typos and clarifications

Versioning a *document* like this may look over-formal, but it means "we're on constitution 1.1.0" is a precise statement, and a future reader of an old plan knows which rules applied at the time.

---

## 6. The first feature: local Docker infrastructure

### Why this feature first

The Producer needs RabbitMQ to send to. The Worker needs RabbitMQ to read from and PostgreSQL to write to. **Neither service can be built, run, or tested until a broker and a database exist.** So this is the only possible starting point. Everything else is blocked on it.

### What it will produce — three files

```
docker-compose.yml   ← the environment: 2 services, 1 network, 2 volumes
.env.example         ← the 9 configuration variables, with safe defaults
README.md            ← the commands, the addresses, where credentials come from
```

Three files. Forty-four tasks. That ratio is normal and worth internalizing: most of the tasks are *verification*, not writing. Writing the file is quick; proving it behaves correctly under restart, reset, port conflicts, missing config, and a frozen process is the actual work.

### The three user stories

**US1 (P1) — Start everything with one command.** Run `cp .env.example .env`, then `docker compose up -d --wait`, and get a healthy broker and database reachable from your laptop. This is the MVP.

**US2 (P2) — Use RabbitMQ's web interface.** Open `http://localhost:15672`, sign in, inspect queues and message rates, purge a queue by hand. Not needed to run code; the primary tool for diagnosing why a message wasn't consumed.

**US3 (P3) — Data survives restarts, and can be deliberately discarded.** Stop at night, start in the morning, your data's still there. And one command wipes it clean when you want a fresh start.

**On the priorities:** P1 is a hard blocker. P2 and P3 are real value but you could work for a while without them. Ordering by priority means that if you stop at any point, you've built the most valuable things first. That's not a scheduling detail — it's a risk management strategy.

### The nine configuration variables

From `contracts/environment-variables.md`:

| Variable | Default | Who reads it |
|---|---|---|
| `POSTGRES_USER` | `aegis` | The PostgreSQL image |
| `POSTGRES_PASSWORD` | `aegis_dev_password` | The PostgreSQL image |
| `POSTGRES_DB` | `aegisshield` | The PostgreSQL image |
| `POSTGRES_PORT` | `5432` | Compose (host port) |
| `RABBITMQ_DEFAULT_USER` | `aegis` | The RabbitMQ image |
| `RABBITMQ_DEFAULT_PASS` | `aegis_dev_password` | The RabbitMQ image |
| `RABBITMQ_DEFAULT_VHOST` | `aegisshield` | The RabbitMQ image |
| `RABBITMQ_PORT` | `5672` | Compose (host port) |
| `RABBITMQ_MANAGEMENT_PORT` | `15672` | Compose (host port) |

Note the rule: **exactly nine, no tenth.** No variable gets added until the Compose file actually reads it. That's Principle V applied to configuration — a variable nobody reads is a speculative feature, and it misleads the next person into thinking it does something.

---

## 7. Every real engineering decision we made, and why

These came out of `research.md`. Each one is a place where a reasonable person might have chosen differently, so the reasoning matters more than the choice.

### Decision 1 — Pin to three-part version tags

**Chose:** `rabbitmq:4.2.4-management-alpine` and `postgres:18.4-alpine`, both verified to exist in the registry on 2026-10-23.

**Why three parts and not two?** `postgres:18` looks pinned but isn't — it moves to 18.5, 18.6, and so on. Only `18.4` is a fixed point. Two-part tags are a common, subtle mistake: people believe they've pinned and haven't.

**Why 4.2.4 and not the newer 4.3.0?** 4.3.0 is the first release of a new minor line, meaning it has had the least real-world exposure. 4.2.4 has had four patch releases land on it — bugs found and fixed. We need nothing from 4.3. Choosing the mature option when you don't need the new one is usually right.

**Why `-management`?** That variant ships with the web interface already enabled. The plain variant would need a plugin-enable step, which means a custom image and a build step — more complexity for the same result.

**The Alpine trade-off, honestly stated.** Alpine uses a different low-level C library (musl instead of glibc), which gives it limited support for locale-aware text sorting. Text could sort differently than on a standard production image. We accepted that because this is a local development environment, production is explicitly out of scope, and there's no schema yet. But `research.md` **records it as a risk** with the note that switching later requires wiping the database volume — so it's cheapest to revisit before the first migration.

That last part is the engineering habit worth copying: when you knowingly accept a risk, write it down with the condition under which it should be revisited. Undocumented accepted risks become mysteries.

### Decision 2 — Healthchecks that prove the port is actually open

This is the best example in the whole project of why "it works" isn't good enough.

**For PostgreSQL we chose:** `pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"`

The `-h 127.0.0.1` looks like noise. It is the most important part, and here's the trap:

PostgreSQL can be reached two ways — through a **Unix socket** (a local file-based channel, only usable from inside the same machine) or over **TCP** (a network port, which is what your laptop and other containers use).

When the official image starts for the very first time, its setup script launches a **temporary PostgreSQL** that listens on the Unix socket *only*, so it can create your user and database privately without anything outside connecting mid-setup.

Plain `pg_isready` with no `-h` checks the socket. So during that setup window it reports **"ready"** — truthfully, from its own point of view — while the TCP port isn't open at all.

Consequence: Docker marks the container `healthy`, `docker compose up --wait` exits 0 and declares success, the Worker starts, tries to connect over TCP, and fails. And it's intermittent — it depends on timing — which makes it one of the worst categories of bug to chase.

Adding `-h 127.0.0.1` forces the check over TCP, so it can only pass once the server a real client would use is listening.

**For RabbitMQ we chose:** `rabbitmq-diagnostics -q check_port_connectivity`

Same reasoning. The obvious alternatives, `ping` and `check_running`, only confirm the Erlang application started — which happens *before* the AMQP listener is bound to its port. Same false-positive class of bug. `check_port_connectivity` opens an actual TCP connection to every listener, which is precisely the question "can a client connect?"

**The generalizable lesson:** a healthcheck must test *the same path a real client uses*. Any shortcut that's easier to check than the real thing is a potential false positive. This pattern shows up everywhere in monitoring, not just Docker.

### Decision 3 — Two tiers of configuration variable

Compose has special syntax for interpolating variables, and we use two forms for two different purposes:

**Required** — `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set - copy .env.example to .env}`

The `:?` means: if this is missing or empty, **stop immediately**, print the variable name and that message, and create nothing.

Why: without it, a missing password means Compose substitutes an empty string, PostgreSQL starts with no password, and your eventual error is an opaque authentication failure from the database — which tells you nothing about the real cause. With `:?`, the error names the exact variable and tells you the fix. Nothing partially starts.

**Defaulted** — `${POSTGRES_PORT:-5432}`

The `:-` means: if missing, use `5432`.

Why: ports should work out of the box but be overridable. If your laptop already runs PostgreSQL on 5432, you put `POSTGRES_PORT=55432` in your `.env` and you're done — **no editing of `docker-compose.yml`**. That matters because `docker-compose.yml` is committed and shared; your port conflict is yours alone. Personal settings belong in personal files.

**The general principle:** fail loudly and specifically for things that must be set; provide a sensible default for things that are merely preferences.

### Decision 4 — `environment:` keys, not `env_file:`

Compose offers `env_file: .env`, which dumps every variable in the file into the container. We instead list each variable explicitly:

```yaml
environment:
  POSTGRES_USER: ${POSTGRES_USER:?...}
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?...}
  POSTGRES_DB: ${POSTGRES_DB:?...}
```

More typing. Three reasons it's worth it:

1. **The file documents itself.** Reading it tells you exactly which variables PostgreSQL consumes. With `env_file:` you'd have to go read the image's documentation.
2. **Nothing extra leaks.** `env_file:` would push the RabbitMQ password into the PostgreSQL container, where it has no business being. Giving a process only what it needs is the **principle of least privilege**, and it's a reflex worth building even when the stakes are low.
3. **`:?` validation still works.** The required-variable check happens during interpolation, which `env_file:` skips entirely.

### Decision 5 — The fixed `hostname:` on RabbitMQ

This is the most non-obvious line in the entire feature, and it's the kind of thing that costs people an afternoon.

RabbitMQ is written in Erlang, and stores its data in Erlang's built-in database, **Mnesia**. Mnesia puts its files in a directory **named after the node**. And the node name is derived from the **container's hostname**.

Docker assigns a **new random hostname** every time it creates a container.

So, without a fixed hostname:

1. You declare durable queues. They're saved to `/var/lib/rabbitmq/mnesia/rabbit@a1b2c3/`.
2. You run `docker compose down`, then `up`. New container, new random hostname — say `d4e5f6`.
3. RabbitMQ looks for `rabbit@d4e5f6/`, doesn't find it, and **initializes a fresh empty node**.
4. Your queues are gone.

And here's what makes it genuinely nasty: **the volume worked perfectly.** Your old data is right there on disk, in the old directory. The volume isn't the problem — but the volume is the first and only thing you'd suspect. You could spend hours checking volume configuration that was correct all along.

Setting `hostname: aegisshield-rabbitmq` fixes the node name, so the Mnesia path stays the same across container recreation.

`quickstart.md` and task T028 both call this out explicitly, so if queues ever vanish, the first thing you check is the hostname rather than the volume.

**Note also:** `hostname:` is *not* the same as `container_name:`. We deliberately leave `container_name:` unset so Compose can prefix container names with the project name, which lets two copies of the project run on one machine without colliding.

### Decision 6 — Named volumes, not bind mounts

**Chose:** `postgres-data:/var/lib/postgresql/data` (Docker-managed named volume)

**Rejected:** `./data:/var/lib/postgresql/data` (bind mount to a real folder on your computer)

Bind mounts seem nicer — you can see the files. Three problems:

1. **File permissions.** Containers run as specific internal user IDs. On Linux, the container's postgres user often can't write to a folder your host user owns, and you get permission errors that differ by operating system.
2. **Path translation.** Windows paths and Linux paths differ, and Docker Desktop translates between them with its own quirks. One more thing that works on your machine and not a colleague's.
3. **`down -v` wouldn't clean it up.** Docker removes volumes it manages. It won't delete a folder on your computer. So our documented reset command would silently not work, which is worse than not having one.

Named volumes avoid all three. The cost is that you can't browse the files directly — and you work around that with `docker compose exec` to get a shell inside, which you need to know how to do anyway.

### Decision 7 — `--wait` is part of the documented start command

**Chose:** `docker compose up -d --wait`

`-d` means **detached** — run in the background and give you your terminal back.

`--wait` means **block until every service with a healthcheck reports healthy**, then exit — with a non-zero exit code if any service fails to get there.

Without `--wait`, `up -d` returns the moment containers are *created*, which (per Decision 2) tells you nothing about readiness. You'd be left guessing, or writing a polling loop — which would be a script, which Principle V rejects when a built-in flag already does the job.

**On exit codes:** by convention a program exits 0 for success and non-zero for failure. This is what lets you chain commands and what lets automated systems know whether something worked. `--wait` turns "is it up yet?" from a judgment call into a number a machine can check.

### Decision 8 — Let Docker handle port conflicts; don't pre-check

If port 5432 is already in use, Docker's own attempt to bind it fails at container creation, within a couple of seconds, with an error naming the port. Nothing half-starts.

We could have written a script to scan ports first and print a prettier message. We didn't: the tool already does the job correctly and fast, and a pre-check script would be a new layer to maintain (Principle V) that could also drift out of sync with reality — a port can be taken in the gap between your check and Docker's bind.

**The lesson:** before building something, check whether your tools already do it. A surprising amount of "necessary" code exists because nobody read the manual.

### Decision 9 — No `init.sql`, no `definitions.json`

We could have pre-created database tables (`init.sql`) and RabbitMQ queues (`definitions.json`) at startup. We deliberately didn't.

**Why:** Principle III says schema comes from versioned migration files, and Principle II implies queue topology belongs to whichever service owns it. If this feature created tables, there'd be two competing sources of truth for the schema — the init script and the migrations — and they'd eventually disagree.

So this feature delivers an **empty** database with a name, and an **empty** broker with an account and a vhost. The first table arrives with the Worker. The first queue arrives with whichever service declares it.

**The general idea:** **ownership**. Each piece of the system owns its own stuff. Infrastructure provides the empty container; the services fill it. Blurring that is how you get a project where nobody knows which file is authoritative.

---

## 8. Things we deliberately did NOT do

Knowing what you rejected — and why — is as much a part of the design as what you chose. Everything here was considered and declined.

| We didn't | Why not |
|---|---|
| Write a `start.sh` or `Makefile` | The real command is already one line. A wrapper hides it (so you never learn it), adds a file to maintain, and `make` isn't on Windows by default — breaking "no host dependencies" (Principle IV, Principle V) |
| Use a second Compose file or `profiles:` or `include:` | One file, read top to bottom, for two services. Splitting it would be organizing for a complexity we don't have (Principle V) |
| Use `latest` or two-part version tags | `latest` and `18` both move. Your environment would change without you changing anything — the exact reproducibility problem Docker exists to solve |
| Use `env_file:` | Hides which image reads which variable, leaks unrelated secrets into containers, and skips `:?` validation |
| Use bind mounts for data | Permission problems, path problems across operating systems, and `down -v` couldn't clean them up |
| Use Docker secrets | Production machinery (designed for Swarm/Kubernetes). This is a local dev environment where the credentials are deliberately fake |
| Write a custom healthcheck script | `pg_isready` and `rabbitmq-diagnostics` already ship inside the images and answer the question correctly |
| Use `rabbitmq-diagnostics ping` or `check_running` | Both pass before the AMQP port is open — the false-positive trap from Decision 2 |
| Use plain `pg_isready` without `-h` | Same trap: passes during first-start initialization while TCP is closed |
| Add a port pre-check script | Docker already fails correctly in under 10 seconds with a useful message |
| Delete the `guest` user after startup | It's never created in the first place when you set `RABBITMQ_DEFAULT_USER`. Better to prevent than to clean up |
| Ship a `rabbitmq.conf` to restrict `guest` | Same outcome, more files, more to understand |
| Create tables or queues here | Schema belongs to migrations; queue topology belongs to the owning service (Principles II, III) |
| Create a separate non-superuser app role | Nothing in the spec asks for privilege separation in local dev. Speculative (Principle V) |
| Add a `logging:` block with rotation | Both images already log to stdout, which `docker compose logs` reads. Nothing needs rotating locally |
| Add a `docs/` folder | One page of operational instructions, in an otherwise empty repository, belongs in the README the contributor already opens |
| Set `container_name:` | Prettier names, but it stops two copies of the project from running on one machine |
| Use RabbitMQ 3.13 | The 3.x line is end-of-life. Don't start on unsupported software |
| Add a Python test framework | This feature ships no Python. The integration test the constitution requires arrives with the services it tests |

Look at how many of these are "we didn't add a layer." That's Principle V earning its place. The instinct to add helpers, wrappers, and config options feels like diligence; most of the time it's accumulating liability.

---

## 9. The two `.gitignore` files

You asked about this. Short answer: it's correct, leave it alone.

Git supports **nested** `.gitignore` files on purpose. Each one applies to its own folder and everything beneath it. You have two because they have two different owners:

| File | Owner | Covers |
|---|---|---|
| `.gitignore` (root) | You / the project | `.env`, Python caches, `venv/`, IDE files, `data/` — the whole repo |
| `.specify/.gitignore` | The Spec Kit CLI | `feature.json`, local extension config, downloaded packages — only inside `.specify/` |

The `.specify` one hides **machine-local state**: which feature you're currently working on, your per-machine settings. That's specific to your computer and shouldn't be shared with other contributors — which is exactly what a `.gitignore` is for.

Verified: `.env` is ignored by root line 2; `.specify/feature.json` is ignored by `.specify/.gitignore` line 6 and is genuinely untracked; zero overlapping patterns between the two.

**Going forward:** project-wide ignores go in the root file. Leave `.specify/.gitignore` alone unless the CLI asks you to change it.

---

## 10. Where we are right now

### Files that exist

```
AegisShield/
├── .gitignore                         ← committed; already ignores .env
├── .env.example                       ← committed; all 9 variables (T004)
├── .env                               ← NEVER committed; your copy (T006)
├── docker-compose.yml                 ← committed; both services, complete for US1
├── README.md                          ← committed; operator documentation (T019)
├── LEARNING-LOG.md                    ← this file
├── .specify/
│   ├── .gitignore                     ← committed; Spec Kit's own local state
│   └── memory/constitution.md         ← committed; 6 principles
└── specs/001-local-docker-infra/
    ├── spec.md                        ← committed; WHAT the feature must do
    ├── plan.md                        ← committed; HOW we'll do it
    ├── research.md                    ← committed; decisions + rejected options
    ├── data-model.md                  ← committed; exact field values
    ├── quickstart.md                  ← committed; 16 verification scenarios
    ├── contracts/                     ← committed; variables, endpoints, commands
    ├── checklists/requirements.md     ← committed; spec quality checklist
    └── tasks.md                       ← committed; the 45 numbered tasks
```

### Task progress: 29 of 45 done

| Phase | Tasks | Status |
|---|---|---|
| 1 — Setup | T001–T003 | ✅ complete |
| 2 — Foundational | T004–T006 | ✅ complete |
| 3 — User Story 1: one-command start 🎯 MVP | T007–T020 | ✅ complete |
| 4 — User Story 2: management interface | T021–T025 | ✅ complete |
| 5 — User Story 3: data across restarts | T026–T032 | 🟨 configuration done (T026–T029); verification outstanding (T030–T032) |
| 6 — Polish & cross-cutting | T033–T045 | ⬜ not started |

### What this means in practice

The MVP is real. One command brings up the whole environment, and it does not report ready until both components actually accept connections:

```
$ docker compose up -d --wait
$ docker compose ps
NAME                     SERVICE    STATUS                  PORTS
aegisshield-postgres-1   postgres   Up (healthy)            0.0.0.0:5432->5432/tcp
aegisshield-rabbitmq-1   rabbitmq   Up (healthy)            0.0.0.0:5672->5672/tcp
```

Both components were then verified by doing real work rather than by trusting the word "healthy": a `psql` query confirmed the named database and its owning account were created on first start with no init script (T018), and a durable queue was declared and listed through the broker's own tooling (T017).

The management interface arrived with User Story 2 and is now published too: `http://localhost:15672`, same account as AMQP, no `guest`.

Both named volumes are now mounted (T026, T027) and the broker's hostname is pinned (T028), so the two gaps this section used to describe are closed. What remains in User Story 3 is proof rather than configuration: T030, T031 and T032.

The history is worth keeping, because it explains what the volumes are *for*:

- **Before T026 and T027, there were no volume mounts.** Both services wrote into *anonymous* volumes — storage Docker invents on the fly because the official images declare a `VOLUME` for their data directory. Anonymous volumes are not reused: `docker compose down` orphaned the old one, and the next `up` attached a brand-new empty one. So **data did not survive a stop** — PostgreSQL re-ran `initdb` and the broker initialized an empty node every time. T026 and T027 attach the two *named* volumes instead, which Compose does reuse by name. (This is also why T020's warm-start timing is provisional; see the 2026-10-30 entry.)
- **Before T028 there was no fixed broker `hostname:`.** The node name was `rabbit@a339da951fd6`, derived from a random container hostname; durable queues would appear to vanish across a restart. It is now `rabbit@aegisshield-rabbitmq`, and the Mnesia directory inside the volume is named after it.

New term: an **anonymous volume** is a Docker volume with no name you chose, created automatically to back a path the image marked as needing storage. A **named volume** is one declared in the `volumes:` section and attached by name, so the same storage is found again on the next start. The difference between them is the whole of User Story 3.

### Files that still do NOT exist

```
producer/            ← a whole future feature
worker/              ← a whole future feature
```

### Everything is committed and pushed

Two commits today, both on `dev` and pushed to `origin`:

- `369d213` — the `postgres` service (T007, T008)
- `99ca09a` — the broker service and operator docs (T009–T019)

`.env` is correctly absent from both, because `.gitignore` hides it. That is T003 still working.

---

## 11. What happens next

### Immediately

**T030** is the next unticked task. User Story 3's configuration is in — the two named volumes are mounted (T026, T027), the broker's `hostname:` is pinned (T028), and Docker creates both volumes unaided (T029). What is left is the proof: the five-cycle restart test (T030), the five-cycle reset test (T031), and the README section documenting both (T032). Note the distinction: the data is no longer *discarded* on a stop, but that it genuinely *returns* is not yet measured — that is exactly what T030 settles.

Then Phase 6: the three read-only audits (T033–T035), the edge cases (T036–T041), the re-measurement of start-to-healthy timing against the finished configuration (T045), the README review (T042), the full quickstart run (T043), and this log's implementation entry (T044).

User Stories 1 and 2 are both done. One command brings up a healthy broker and a healthy database, and the broker's web interface is published with the project's own administrator account and no reachable `guest`.

### After this feature

Roughly, in order:

1. **Producer** — a Python service that generates transaction events and publishes them to RabbitMQ. Its own folder, its own `Dockerfile`, added to the same `docker-compose.yml` without touching the two existing service definitions (that's what SC-010 and task T039 are proving in advance).
2. **Worker** — consumes events, applies fraud rules, writes to PostgreSQL. Brings the first database migration and the first real schema.
3. **Fraud rules** — with unit tests covering both flagged and non-flagged cases, as the constitution requires.
4. **The integration test** — the full Producer → RabbitMQ → Worker → PostgreSQL path, running against real containers with nothing mocked.

### A suggestion for how to actually learn during implementation

When `/speckit-implement` runs a task, don't just watch it pass. For each one, try to answer:

- What file changed, and what exactly changed in it?
- Which requirement (FR-xxx) does this exist to satisfy?
- What would break if this task were skipped?
- What was the rejected alternative, and why is this better?

The fourth question is the one that separates understanding from pattern-matching. Sections 7 and 8 above are there so you can answer it.

And if you can't answer one — ask. "Why does T028 set a hostname?" is exactly the right kind of question, and it has a real, interesting answer.

---

## 12. Glossary

Alphabetical, for when a term shows up and you've forgotten it.

**Abstraction** — a layer hiding details behind a simpler interface. Good when it matches reality, expensive when it doesn't.

**Acknowledgement (ack)** — a consumer telling the broker "I'm done with this message, delete it."

**AMQP** — the protocol for talking to RabbitMQ. Port 5672.

**At-least-once delivery** — the realistic guarantee of a message broker: every message arrives, but some may arrive more than once. The reason idempotency is mandatory.

**Bind mount** — attaching a real folder from your computer into a container. We avoid these for data.

**Branch** — an independent line of development in Git. You're on `dev`.

**Commit** — a saved snapshot in Git, with a message.

**Container** — a running instance made from an image. Disposable.

**Contract** — a documented agreement about an interface (variable names, addresses, commands) that both sides rely on.

**Declarative** — describing the desired end state rather than the steps. `docker-compose.yml` is declarative.

**DNS** — the system that turns names into network addresses. Docker runs a private one for your containers.

**Durable queue** — a queue whose definition survives a broker restart.

**Edge case** — an unusual but real situation (port taken, disk full, unclean shutdown) that correct software must handle.

**Environment variable** — a named value passed to a program from outside it, at startup.

**Exit code** — a number a program returns: 0 means success, non-zero means failure.

**FR-xxx** — Functional Requirement, numbered in `spec.md`. Something the system MUST do.

**Healthcheck** — a repeating command Docker runs inside a container to determine whether the software is genuinely ready, not merely running.

**Idempotent** — doing it twice has the same effect as doing it once.

**Image** — the frozen template a container is made from.

**Imperative** — describing the steps rather than the end state. The opposite of declarative.

**Integration test** — a test exercising several real components together, with nothing mocked.

**Interpolation** — substituting a variable's value into text. `${POSTGRES_PORT:-5432}` is interpolated by Compose.

**localhost** — "this machine." Inside a container, it means the container itself, not your laptop. Source of a classic bug.

**Migration** — a numbered SQL file, checked into Git, that applies one schema change. The only legal way to change the schema here.

**Mnesia** — Erlang's built-in database. RabbitMQ stores its state there, in a directory named after the node — which is why the fixed hostname matters.

**MVP** — Minimum Viable Product. The smallest version that's genuinely useful.

**Named volume** — Docker-managed storage that outlives containers. What we use for data.

**Persistent message** — a message written to disk so it survives a broker restart.

**Pinning** — locking a dependency to an exact version so it can't change under you.

**Port** — a numbered door on a machine, letting many programs listen at once.

**Principle of least privilege** — give each component only the access it actually needs.

**Publishing a port** — mapping a container's internal port to a port on your computer so you can reach it.

**Rule of three** — don't abstract until you have three real cases. Two may look alike by coincidence.

**SC-xxx** — Success Criterion, numbered in `spec.md`. A measurable test that the feature worked.

**Semantic versioning** — MAJOR.MINOR.PATCH, where each position signals how big the change is.

**Service** — in Compose, one named component (`postgres`, `rabbitmq`). Also, more generally, one independently deployable piece of the system.

**System of record** — the single authoritative source for data. Ours is PostgreSQL.

**Traceability** — being able to follow a chain from requirement → decision → task → code, in both directions.

**Tracked / untracked** — whether Git is recording a file's history.

**Unix socket** — a local file-based communication channel, usable only from the same machine. Distinct from TCP, and the cause of the `pg_isready` trap.

**Virtual host (vhost)** — a named compartment inside one RabbitMQ server with its own queues and permissions.

**Volume** — storage that exists independently of any container.

**YAML** — the indentation-based data format `docker-compose.yml` is written in. Spaces only, never tabs.

---

## Entry log

Newest first. Each entry is one unit of work, as Principle VI requires.

### 2026-10-30 (later) — The volumes are mounted, and PostgreSQL 18 moved the path everyone has memorized

**What:** T026 through T029. Both named volumes are now attached, the broker's node name is pinned, and the environment starts healthy from a clean slate. Stopping the environment no longer destroys the data — the gap that had been open since User Story 1.

The three edits to `docker-compose.yml`:

| Edit | Value | What it does |
|---|---|---|
| T026 | `postgres-data:/var/lib/postgresql` | Attaches the database's named volume |
| T027 | `rabbitmq-data:/var/lib/rabbitmq` | Attaches the broker's Mnesia directory |
| T028 | `hostname: aegisshield-rabbitmq` | Pins the broker's node name so the Mnesia path is stable |

T029 confirmed Docker created both volumes by itself — `aegisshield_postgres-data` and `aegisshield_rabbitmq-data` — with no `mkdir`, no permission fixing, no preparation step.

---

**The defect: the obvious path was the wrong path.**

T026 originally said to mount `postgres-data` at `/var/lib/postgresql/data`. That is the path in every PostgreSQL Docker example written in the last decade, it is what `data-model.md`, `plan.md` and `research.md` all specified, and it is wrong for the image this feature pins.

The start failed:

```text
container aegisshield-postgres-1 is unhealthy
```

That message says nothing useful on its own. The logs did:

```text
Error: in 18+, these Docker images are configured to store database data in a
       format which is compatible with "pg_ctlcluster" (specifically, using
       major-version-specific directory names).
       Counter to that, there appears to be PostgreSQL data in:
         /var/lib/postgresql/data (unused mount/volume)
       The suggested container configuration for 18+ is to place a single mount
       at /var/lib/postgresql
```

And the image itself settles it:

```text
PGDATA=/var/lib/postgresql/18/docker    VOLUMES=/var/lib/postgresql
```

**What changed in PostgreSQL 18.** For versions 9 through 17 the official images put the cluster directly at `/var/lib/postgresql/data` and declared that as the volume. The 18+ images store it in a *major-version-specific* subdirectory — `PGDATA=/var/lib/postgresql/18/docker` — and declare the volume one level up at `/var/lib/postgresql`. The reason is upgrades: `pg_upgrade --link` has to see the old and the new cluster within the same filesystem, and if each version's directory were its own mount point, that link step would cross a mount boundary and fail. Moving the mount up one level puts both versions inside it.

The image does not silently ignore a mount at the legacy path, and that is a kindness. It refuses to start, because historically that arrangement looked exactly like a half-finished version upgrade — someone bumping the image tag without running `pg_upgrade` — and starting anyway would have meant an empty database sitting next to the real data, or worse.

New term: **`PGDATA`** is the environment variable naming the directory where a PostgreSQL server keeps one *cluster* — the data directory. A **cluster** here means one running server and all the databases inside it, not multiple machines; it is an unfortunate word. **`pg_upgrade`** is the tool that migrates a cluster from one major version to the next, and `--link` is its fast mode, which hard-links files instead of copying them and therefore requires both clusters on one filesystem.

**The fix:** drop `/data`. The mount goes at `/var/lib/postgresql`, and the cluster lands at `18/docker` inside it — verified in the running container:

```text
$ ls /var/lib/postgresql
18
$ ls $PGDATA          # PGDATA=/var/lib/postgresql/18/docker
PG_VERSION  base  global  pg_commit_ts  ...
```

The `docker compose down -v` before retrying was necessary, not ritual: the first attempt left content in `postgres-data` laid out for the wrong path, and reusing it would have shadowed the image's own `/var/lib/postgresql` directory.

**Fixed in five places, not one.** The wrong path was written in `data-model.md` (twice), `plan.md`, `research.md` section 7, and T026's own text. Correcting only `docker-compose.yml` would have left four documents instructing the next reader to reintroduce the bug. `research.md` section 7 now carries the full explanation and the instruction to check `docker image inspect` on any future image bump rather than trusting memory. T026 records that it originally specified the legacy path and what the failure looked like, so the next person who sees `is unhealthy` has somewhere to land.

**The lesson:** **a pinned version is a promise that the thing will not change under you — not a promise that what you know about it is still true.** T002 and T035 are careful about pinning `postgres:18.4-alpine` exactly, and that discipline worked perfectly; it simply has nothing to say about whether the *contents* of that image match the convention in your head. The path was written from memory of how PostgreSQL images have always worked, and it had been true for roughly ten years. `docker image inspect` would have taken four seconds and settled it.

It is the same failure the 2026-10-23 entry already recorded in a different costume — *describing state from memory instead of checking the disk* — and that is worth noticing. The first time it was the project's own state; this time it was a dependency's. The general form: **when a value is going into a file, get it from the thing itself, not from recollection.** The authoritative source was available locally and free to query the whole time.

One small thing in the environment's favour: the failure was loud, immediate, and arrived with its own fix in the error text. `--wait` is what turned a silently broken database into a non-zero exit, and `restart: unless-stopped` is why the error block kept repeating in the logs until the mount was corrected, rather than scrolling past once.

---

**T028, and what it looks like when it works.** The fixed hostname is the other non-obvious piece, and now there is evidence for the explanation `research.md` has been carrying since planning:

```text
$ rabbitmqctl eval 'node().'
'rabbit@aegisshield-rabbitmq'

$ ls /var/lib/rabbitmq/mnesia
rabbit@aegisshield-rabbitmq
rabbit@aegisshield-rabbitmq-feature_flags
rabbit@aegisshield-rabbitmq-plugins-expand
rabbit@aegisshield-rabbitmq.pid
```

Every one of those names contains the hostname. That is the whole trap in one listing: without `hostname:`, Docker hands the recreated container a new random name, RabbitMQ becomes `rabbit@<something-else>`, looks for a Mnesia directory of that name, finds none, and initializes an empty one *beside* the intact old data. The queues are still on disk and the broker cannot see them. T030 is the task that would catch it, and that task already says to check the hostname before suspecting the volume.

---

**Where this leaves the feature:** 29 of 45 tasks done. The remaining User Story 3 work is verification rather than configuration — T030 proves data survives five consecutive stop/start cycles, T031 proves `down -v` returns the environment to a first-ever-start state across five reset cycles, and T032 documents both in `README.md`. Then Phase 6.

Worth stating plainly: **the persistence claim is not yet proven.** The volumes are attached and a single clean start works, but nothing has yet written a row, stopped the environment, started it again, and found the row still there. That is T030, and until it passes, "data survives a restart" is a reasonable expectation rather than a measured fact.

### 2026-10-30 — User Story 2, and a second `/speckit-analyze` that found four real defects

**What:** Two pieces of work in one entry, because the second was prompted by the first.

1. **User Story 2 is built and complete** — T021 through T025. The broker's web management interface is published on host port `15672`, reachable at `http://localhost:15672`, and `README.md` gained a section covering it. Queues, message rates, and connections are visible; a queue can be created and purged by hand from the Queues tab. T024 confirmed the stock `guest` account does not exist in this environment — setting `RABBITMQ_DEFAULT_USER` and `RABBITMQ_DEFAULT_PASS` makes the image create the project's own administrator *instead of* `guest`, rather than creating `guest` and then removing it, so there is no window in which the default account is reachable.
2. **Ran `/speckit-analyze` again** over `spec.md`, `plan.md`, and `tasks.md`. It reported 13 findings: no CRITICAL, four HIGH, five MEDIUM, four LOW. Requirement coverage came back clean — all 20 functional requirements and all 10 success criteria have at least one task — so every finding was about *correctness of the documents*, not holes in them. All 13 are now fixed. The four HIGH ones are the interesting ones and each taught something.

---

**HIGH 1 — A verification step that could never observe what it claimed.** T041 exists to prove the "unclean shutdown" edge case: kill the environment outright, start it again, confirm nothing was lost. It said to run `docker compose kill`, then check `docker compose ps` shows the containers *exited*, then start them.

That check cannot pass. Both services set `restart: unless-stopped`, and Docker's restart policy fires on **any** non-zero exit — a kill included. The containers come back on their own, before you can type the next command. `quickstart.md` Scenario 16 had the same instruction and the same comment (`# containers exited, not stopped cleanly`).

New term: a **restart policy** is a standing instruction to the Docker daemon about what to do when a container's main process exits. `unless-stopped` means "start it again, unless I stopped it deliberately with `docker stop`". A kill is not a deliberate stop, so the policy applies.

The fix had two candidate shapes and the choice matters:

| Option | Verdict |
|---|---|
| Remove `restart: unless-stopped` so containers stay dead after a kill | **Rejected.** The policy is the feature that makes the laptop-lid case *work* — close the lid, reopen it, your environment is running. Deleting a useful behaviour to make a test convenient is backwards. |
| Keep the policy; fix the test to assert what the spec actually requires | **Chosen.** The spec says "the next start must recover without manual repair of stored state". It is about state surviving, not about who issues the start. |

T041 and Scenario 16 now expect the containers to come back by themselves, wait for health, and assert the row and the durable queue survived. Both also describe a second pass with the policy suspended (`docker update --restart=no $(docker compose ps -q)`), so the developer-initiated path is covered too — belt and braces, since both paths are real.

**The lesson:** a test that asserts a state your own configuration prevents will fail for a reason that has nothing to do with the thing under test, and whoever hits it will spend an hour on PostgreSQL recovery before noticing the restart policy. Write down what the configuration will *do*, not what the scenario name suggests.

---

**HIGH 2 — Two tasks fighting over the same test data.** T041 said "with data written per T030". But T030 ended with "Drop `quickstart_check` when finished", and T031 — which sits between them — runs `docker compose down -v` five times, destroying both volumes. So T041's data was guaranteed gone three different ways. A note in the dependency section tried to patch this with "run T041 before any `down -v`", which contradicted the task numbering it appeared next to.

Fixed by making T041 write its own state before it kills anything, which removes the dependency instead of sequencing around it, and by deleting the stale ordering note. T030 and `quickstart.md` Scenario 5 no longer drop the table either — Scenario 6's `down -v` is what removes it, and that removal is precisely what Scenario 6 sets out to prove.

**The lesson:** **a shared-state dependency between two tests is a bug even when the ordering works.** It couples them, it breaks silently when anything is inserted between them, and the fix — have each test set up what it needs — is cheaper than the note explaining the ordering.

---

**HIGH 3 and 4 — The measurement, and the wrong conclusion drawn from it.** T020 measured start-to-healthy timing and passed comfortably: 50.5s cold against a 5-minute budget, 14.5s warm against 60s. Both numbers were taken during User Story 1 — **before T026–T028 mount the volumes**, which is User Story 3 and still unbuilt.

That matters more than it sounds. With no volume mounted, PostgreSQL's data directory lives inside the container, `docker compose down` destroys it, and the next start builds it again from scratch. So the "warm" run was not doing what a developer's warm start does. Two consequences:

- The figures do not describe the finished environment. **T045** is now added to Phase 6 to re-measure once the volumes are in, and that run is what settles SC-001 and SC-002. T020's text now marks its own numbers provisional — a task recording a result that will change should say so.
- The entry below drew a specific conclusion from those numbers that does not hold: it read the 2.3s gap between the cold (8.4s) and warm (6.1s) PostgreSQL timings as the cost of first-time database initialization. It isn't. `initdb` ran on *both* runs, because both started from an empty data directory. Point 2 of that entry is now corrected in place, with the reasoning kept rather than quietly deleted.

**The lesson, and it is the most general one here:** **a measurement is only as good as your model of what the measurement did.** Two numbers and a subtraction look like evidence. That subtraction was meaningless because both runs did the same work — and nothing in the numbers said so. Only knowing that no volume was mounted said so. Before trusting a difference between two runs, state what you believe differs between them, then check that it actually does.

---

**The nine smaller findings, grouped by what kind of problem they were:**

| Finding | Fix |
|---|---|
| T016 and T040 both ran `rabbitmq-diagnostics check_alarms` and both cited Scenario 15 | Clause (c) removed from T016; T040 owns the disk-alarm check alone. Two places to update is one too many |
| The "dependency temporarily unreachable → must retry" edge case had no requirement and no task | Annotated as deliberately deferred. The party that must retry is an application service and this feature ships none; what it owes is the *means* (healthchecks, `depends_on: service_healthy`), both delivered |
| SC-008 needed "a contributor who has never seen the project" — this project has one maintainer | Restated as an audit of the documentation itself: every value the setup needs is written down, no step depends on something recorded nowhere. Timing a stranger is better evidence and is still taken when one is available, but it no longer blocks T042 |
| US1's independent test says "a clean machine with container tooling only", then T017/T018 ask for a host AMQP and psql client | Left as-is in substance but noted: FR-018 constrains *starting* the environment, not verifying it. Host clients are test-time tooling |
| SC-001's "typical broadband connection" was unmeasurable | Now "at least 50 Mbit/s", with the measured link speed recorded alongside the timing. The image pull dominates the cold number, so the link speed is part of the criterion or the criterion means nothing |
| FR-001 said the environment "MUST define **exactly two** components" — which Principle IV makes false the moment the Producer and Worker land | Reworded to "the two components this feature delivers", with the ceiling point made explicit |
| `plan.md` called the non-blank development password in `.env.example` a "deliberate deviation from the spec" | It is not a deviation — FR-006 *requires* working defaults and the Assumptions section accepts development-grade credentials. The false-conflict framing is gone |
| `restart: unless-stopped` traced to no requirement (Principle V bans speculative configuration) | Traced in `data-model.md` to the "unclean shutdown (machine sleep, forced kill)" edge case it genuinely serves, with the testing consequence from HIGH 1 noted right there |
| `spec.md` still said **Status: Draft** with half the feature built | Now "In implementation", with which stories are done |

**Why `/speckit-analyze` earns its keep.** Every one of these documents was reviewed when it was written and each was fine *on its own*. The defects were all in the **joins** — a task relying on data another task deletes, a test asserting a state the configuration forbids, a conclusion resting on a run that did not do what it appeared to. Nothing finds those except reading the artifacts against each other, deliberately, with the implementation in view. A second pass over documents you believe are finished is not wasted effort; it is where this class of bug lives.

**What does NOT exist yet:** User Story 3 in full — the volume mounts (T026, T027), the fixed broker hostname (T028), and every persistence and reset verification (T029–T032). Until T026–T028 land, **stopping the environment still destroys your data**, which is the opposite of what the spec requires and the single most important thing to know about the current state. Also outstanding: all of Phase 6 (T033–T045), the Producer, the Worker, any schema, any message topology, and any application code at all.

**State:** 25 of 45 tasks done — T001–T025 complete, T026–T045 remaining. User Stories 1 and 2 both work end to end. The task count rose from 44 to 45 because this analysis added T045.

### 2026-10-23 (end of day) — User Story 1 is finished and measured

**What:** Implemented T009–T019 and measured T020. The environment now starts with one command, both components report healthy before that command returns, and `README.md` documents how to operate it. Everything is committed and pushed — `99ca09a` on `dev`, the first commit since the planning phase.

**The measurements (T020).** Two runs on this machine (Windows 10, Docker Desktop):

| Run | Budget | Measured | Headroom |
|---|---|---|---|
| Cold — images deleted, volumes discarded (SC-001) | under 5 min | **50.5s** | 83% |
| Warm — images cached (SC-002) | under 60s | **14.5s** | 76% |

Per container, as Compose reported them:

| | cold | warm |
|---|---|---|
| `postgres` healthy | 8.4s | 6.1s |
| `rabbitmq` healthy | 16.4s | 14.1s |

**What those numbers actually tell us.** Four things, and none of them was obvious before measuring.

1. **The cold run was mostly downloading.** The two image pulls took 33.5s and 23.3s, concurrently, so roughly two thirds of the 50.5s was network. That is a property of the internet connection, not of anything we wrote — which is exactly why SC-001's budget is generous and SC-002's is the one that measures our own choices.

2. **`initdb` is cheap — but this pair of runs cannot say how cheap.** postgres reached healthy at 8.4s cold and 6.1s warm, and the first version of this entry read the 2.3s difference as the cost of first-time initialization. That inference was wrong, and the reason is worth keeping: **at the time of this measurement the volumes were declared but not yet mounted** (T026–T028 belong to User Story 3, which had not been built). Without a mount, the data directory lives in the container's writable layer, `docker compose down` destroys it, and the next `up` creates a fresh container — so `initdb` ran on the *warm* run too. Both numbers include it; the 2.3s gap is pull/layer-extraction residue and run-to-run variance, not initialization cost.

   What the runs do establish: `initdb` plus a healthy TCP listener together cost well under 8.4s, comfortably inside `start_period: 30s`, which is what the grace period was sized to cover. So the conclusion stands even though the arithmetic behind it did not — `start_period: 30s` is generous and it stays. An over-generous grace period costs nothing, because a healthcheck that succeeds inside it marks the service healthy immediately. `start_period` is not a delay; it is suspended judgment. Pricing initialization properly needs a warm start that actually reuses an initialized data directory, which is what **T045** was added to measure once the volumes are mounted.

   The general lesson, which is the more valuable one: **a measurement is only as good as your model of what the measurement did.** Two numbers and a subtraction looked like evidence. The subtraction was meaningless because both runs did the same work, and nothing in the numbers themselves said so — only knowing that no volume was mounted said so. Before trusting a difference, state what you believe differs between the two runs, then check that it actually does.

3. **RabbitMQ is the critical path, and the reason is visible in its number.** It was healthy at 14.1s warm, with `interval: 10s`. Docker waits one full interval before the *first* probe, so the earliest possible answer was 10s — and the probe then took about 4 more seconds to come back. Those 4 seconds are `rabbitmq-diagnostics` booting a short-lived Erlang VM, precisely what Decision 2 claimed when it gave the broker a `timeout` that the database does not need. A prediction written during planning turned up in the measurement, which is most of the reason for writing predictions down.

4. **`interval` sets the floor on how fast a service can be called ready** — not `start_period`, not `retries`. postgres cannot be reported healthy before ~5s and rabbitmq not before ~10s, however fast they actually start.

**The tuning decision, which was not to tune.** T020 says that if the warm start exceeds 60 seconds, change the healthcheck timings rather than relax the criterion. It didn't — 14.5s against a 60s budget.

A tempting change was still available: drop rabbitmq's `interval` to 5s and the warm start would likely fall to about 9s. Rejected. It would double how often a 4-second Erlang VM spawn runs, forever, on every developer's machine, to win five seconds nobody is waiting for — and it would mean editing `data-model.md`'s authoritative values with no requirement asking for it. **Headroom is not a budget to be spent.** The values stand unchanged.

**A Windows lesson that cost real time: PowerShell mangles nested quotes.** Every `docker compose exec` command in `quickstart.md` has the shape `sh -c 'psql -U "$POSTGRES_USER" ... -c "SELECT ..."'`. Windows PowerShell 5.1 wraps that whole argument in double quotes when handing it to `docker.exe`, but does **not** escape the double quotes already inside it — so the argument reaches the container in pieces. The failure mode is quiet and misleading: psql ran, reported `(1 row)`, and printed nothing useful, because the query that arrived was not the query that was typed. `--%` does not rescue it.

Two forms that do work, both verified:

```bash
# Git Bash — the quickstart.md commands run verbatim
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT current_database(), current_user;"'
```

```powershell
# PowerShell — outer double quotes, inner single quotes, backtick before every $
docker compose exec postgres sh -c "psql -U `$POSTGRES_USER -d `$POSTGRES_DB -Atc 'SELECT current_database(), current_user;'"
```

The backtick is PowerShell's escape character; it stops PowerShell expanding the variable so the literal `$POSTGRES_USER` reaches the container's shell, which is the only place the value exists. The general lesson is bigger than the syntax: **when a command "runs" but produces nothing, suspect that your shell rewrote it before the program ever saw it.** Echo the argument and look at it.

**Two Compose details worth keeping.**

- **`$$` is Compose's escape for a literal `$`.** The postgres healthcheck must read `pg_isready -h 127.0.0.1 -U "$$POSTGRES_USER"`. A single `$` is expanded by *Compose* at parse time, baking the value into the command string; `$$` leaves the expansion to the container's shell at check time, where `.env`'s values actually live. `docker compose config` tells you which happened: `$$POSTGRES_USER` in the output is right, `aegis` is wrong.
- **Indentation decides what a key *is*.** The `rabbitmq:` block was first written at column 0, which made it a top-level key beside `services:` instead of a service inside it. Compose rejected it with `additional properties 'rabbitmq' not allowed` — an error about the shape of the whole document, which never mentions whitespace. The four lines of content were correct; only the leading spaces were wrong. Compare a new block against a working sibling before reading anything else.

**`guest` is genuinely absent, confirmed from the outside.** Running T017's `rabbitmqadmin declare queue` *without* `-u`/`-p` falls back to its default login, `guest`, and returns `Not_Authorized` with exit 64. That is Decision 9 proven: `guest` is not disabled or restricted, it was never created, because `RABBITMQ_DEFAULT_USER` was set before the volume initialized. Most of acceptance scenario 2.4 is therefore already established, ahead of T024.

**One known gap, deliberately accepted.** `README.md` documents three endpoints, including the management interface at `localhost:15672` — but T021 has not published that port yet, so the README currently describes one endpoint the Compose file does not expose. T019 explicitly requires all three endpoints, and T021 closes the gap tomorrow. Better written down than discovered.

**State now:** 20 of 44 tasks done; User Story 1 complete. `docker compose up -d --wait` brings up a healthy broker and a healthy database, both reachable from the host, documented by a README covering the five operator commands, the three endpoints and their override variables, and the credential-freeze reset path. Still missing: the management port (T021), the two named volume mounts (T026, T027), and the fixed broker `hostname:` (T028) — without which durable queues appear to vanish across a restart, as today's random node name `rabbit@a339da951fd6` shows plainly.

---

### 2026-10-23 (later still) — ASCII-only in operator-facing error messages

**What:** Changed the required-variable message form from `VAR is not set — copy .env.example to .env` (em dash) to `VAR is not set - copy .env.example to .env` (plain hyphen), in `contracts/environment-variables.md`, `tasks.md` (T008; T012 inherits it), `research.md`, and the example in Section 7 above.

**Why:** the implementation was written with a hyphen and the documents specified an em dash, so the two disagreed. The hyphen is the better choice, so the documents changed rather than the code — with direct evidence from this session: a Python script run here failed with `UnicodeEncodeError: 'charmap' codec can't encode character`, which means this machine's console is on the **cp1252** code page, not UTF-8. A non-ASCII character in text printed to that console can come out as mojibake or a replacement glyph.

An error message is the single worst place to risk unreadable characters: it is read exactly once, under pressure, by someone who already has a problem. So the rule recorded in the contract is narrow and specific — **prose in these documents may use em dashes freely; strings that reach a console may not.**

**The general lesson, which is bigger than one hyphen.** When the implementation and the specification disagree, the reflex is to "fix" the implementation. That's backwards when the implementation is right. The question to ask is *which one is correct*, not *which one came second*. Here the code was correct and the document was wrong, so the document moved. What matters either way is that they stop disagreeing — because the next person reads the contract, writes em dashes, and the inconsistency propagates.

**Rejected alternative:** change the three lines in `docker-compose.yml` to em dashes to match the contract. Equally consistent, and rejected because it would make the error message worse on the only machine this project currently runs on.

**State now:** 8 of 44 tasks done (T007 and T008 complete, both verified — including watching the `:?` guard actually fire by commenting out `POSTGRES_DB`). The `postgres` service has an image, a network, a restart policy, and credentials; it still has no published port, no healthcheck, and no volume. The leftover `postgres:15` and `rabbitmq:3-management` containers from an earlier attempt are still running and still need clearing before T016 binds port 5432.

---

### 2026-10-23 (later) — Ran `/speckit-analyze` and fixed what it found

**What:** Analysed `spec.md`, `plan.md`, and `tasks.md` against each other and against the constitution, then applied every remediation. No CRITICAL issues; one HIGH, four MEDIUM, four LOW.

**What "analyse" means here:** a read-only cross-check for four kinds of defect that only show up when you compare documents rather than read them one at a time:

- **Coverage gaps** — a requirement with no task to satisfy it. The requirement silently never gets built.
- **Underspecification** — a task that tells you to do something without saying what value to use. The implementer invents one, and nobody later knows whether it was reasoned or guessed.
- **Inconsistency** — two documents that contradict each other, so following one breaks the other.
- **Constitution conflict** — anything that violates a MUST principle. Automatically critical.

**The HIGH finding, and why it mattered most.** Tasks T010 and T014 said to set healthcheck `interval`, `timeout`, `retries`, and `start_period` — but **no document gave a single number.** Eight values would have been invented at the keyboard. That's bad for a specific reason: SC-002 requires a warm start under 60 seconds, and those numbers *determine* whether it passes. You would have been tuning a measurement against a target you'd made up minutes earlier, with no record of why. Concrete values now live in `data-model.md`, quoted verbatim by both tasks:

| | postgres | rabbitmq |
|---|---|---|
| `interval` | 5s | 10s |
| `timeout` | 5s | 10s |
| `retries` | 5 | 6 |
| `start_period` | 30s | 60s |

**Why the broker's are all larger:** an Erlang node boot plus management-plugin start commonly takes 20–40s on a first start, and `rabbitmq-diagnostics` launches a short-lived Erlang VM on every invocation, so it needs a timeout that `pg_isready` — one cheap connection attempt — does not.

**And the non-obvious bit worth knowing:** a longer `start_period` does **not** delay anything. If a check succeeds during that window, Docker marks the service healthy immediately. `start_period` only suppresses *failures* from counting while the service is still booting. So the broker's 60s window costs nothing against SC-002 — which is exactly why it was safe to set it generously. If you believed `start_period` was a mandatory wait, you'd have set it too low and reintroduced false failures on slow machines.

**The coverage gaps.** Three of the spec's eight edge cases had no task and no scenario — not deferred, just missing:

| Edge case | Fix |
|---|---|
| Logs viewable per component (FR-016) | Only *documented*, never run. Added as an assertion in T016 and quickstart Scenario 13 |
| Started twice in a row | Added to T016 and Scenario 14 |
| Machine runs out of disk | New task **T040** + Scenario 15 |
| Unclean shutdown (lid closed, forced kill) | New task **T041** + Scenario 16 |

**A judgment call on the disk one, stated openly.** The spec requires that a full disk be *visible through status or logs* rather than appearing as an unexplained hang. It does not require preventing it. Genuinely filling the host disk is destructive, and lowering RabbitMQ's alarm threshold to make it reachable would need a tenth environment variable and a config layer — rejected under Principle V. So T040 verifies the **observability path** in the healthy state: `rabbitmq-diagnostics check_alarms` exits zero, `status` reports the current `disk_free_limit` and free space, and the logs are where a raised alarm appears. The limitation is written into the task rather than left implicit.

This is a pattern worth copying: **when you can't fully test a requirement, test the part you can and write down exactly which part you didn't.** An undocumented gap looks identical to an oversight.

**The inconsistencies.** FR-002 said the broker **MUST** publish on 5672/15672; FR-004 said every port **MUST** be overridable. Read literally, satisfying one broke the other — the Assumptions section resolved it, but only if you read that far. FR-002 and FR-003 now say "by default … overridable per FR-004". Wording only; the design was always right. Separately, T003 was unticked while T004–T006 were ticked, violating tasks.md's own stated dependency order. Its condition was verified true (`.gitignore:2`), so it's now ticked.

**Renumbering, and why I bothered.** Inserting two tasks meant old T040–T042 became T042–T044. I could have appended the new tasks as T043/T044 instead and skipped the churn — but then the learning-log task would have run *before* two verifications whose results it's supposed to record, and task IDs would no longer match execution order. A numbering scheme that doesn't mean anything is worse than no scheme, because people still trust it.

**Files changed:** `spec.md` (FR-002, FR-003), `data-model.md` (two readiness-timing rows), `research.md` (the SC-002 risk marked resolved), `tasks.md` (T003 ticked, T010/T014 given values, T016 extended, T040/T041 added, tail renumbered), `quickstart.md` (Scenarios 13–16, coverage table now cites all 20 FRs), `plan.md` (T044 reference), and this file.

**Rejected alternatives:**

- *Leave the healthcheck values to implementation.* Rejected — that's precisely how an unexamined number ends up load-bearing for a success criterion.
- *Drop the three uncovered edge cases from the spec.* Rejected — they're real (a closed laptop lid is not exotic). Deleting a requirement to make coverage look complete is the worst available option.
- *Add tasks without matching quickstart scenarios.* Rejected — T043 runs the quickstart checklist end to end, so a task with no scenario would never actually be exercised by the final validation pass.

**State now:** planning complete and internally consistent; **6 of 44 tasks done**; still no services defined in `docker-compose.yml`, so still nothing to run. Coverage: 20/20 FRs, 10/10 SCs, 8/8 edge cases.

---

### 2026-10-23 — This document, and constitution 1.1.0

**What:** Created `LEARNING-LOG.md` (everything above). Amended the constitution from 1.0.0 to **1.1.0**, adding **Principle VI — Explain the Work in Plain Language**, which makes maintaining this file a requirement rather than a nice idea.

**Why:** Planning had produced seven documents across two directories, written in precise specification language. Precise and followable are not the same thing — the documents were correct but not teachable, and a project you can't explain is a project you only appear to own.

**What else changed, and why consistency matters:** adding a principle meant four other places were instantly out of date, and leaving any of them stale would make the documents contradict each other:

| File | Change |
|---|---|
| `.specify/memory/constitution.md` | Principle VI added; workflow gate added; "Principles I–V" → "I–VI"; version 1.0.0 → 1.1.0 with an amendment-history entry |
| `specs/001-local-docker-infra/plan.md` | Constitution Check table gained a sixth row; `LEARNING-LOG.md` added to the file listing |
| `specs/001-local-docker-infra/tasks.md` | New task **T042** — update this log after implementation (41 → 42 tasks). *Later renumbered to T044 by the analysis entry above.* |

**Why MINOR and not PATCH or MAJOR:** semantic versioning — a *new* principle is added material (MINOR). No existing principle changed meaning, so it isn't MAJOR. It's more than a typo fix, so it isn't PATCH.

**Rejected alternatives:**

- *Put the rule in `README.md`.* Rejected — the README is for operators who want to run the thing. A rule that governs how work is done belongs with the other rules governing how work is done, where every plan's Constitution Check will test it.
- *Put it in `CLAUDE.md` or a memory file.* Rejected — those are assistant-facing configuration. This is a project standard and should hold regardless of who or what is doing the work.
- *Make it a workflow gate only, not a principle.* Rejected — principles get checked explicitly in every plan's Constitution Check table. A gate buried in a list is easier to skip. Making it a principle gives it teeth.
- *Write a separate explainer per feature.* Rejected — you'd have to hunt across directories to reconstruct the story, and cross-feature context (why the constitution says what it says) would have nowhere to live. One running log, newest entry first.

**Correction made during this work:** I first wrote that nothing had been built. That was wrong — T001, T002, T004, T005, and T006 had been ticked off, and `.env.example`, `.env`, and a skeleton `docker-compose.yml` already existed. Section 10 now reflects the real state, including the fact that the skeleton defines `services: {}` and therefore still runs nothing.

The lesson is worth keeping, because it's a mistake with a general shape: **I described the project state from memory of what I had written, instead of checking the disk.** Documentation drifts from reality the moment reality moves. The fix is mechanical — look before you write, and prefer a command's output (`docker compose config`, `git status`) over your recollection.

**State as of that entry:** planning complete; 5 of 42 tasks done; no services defined yet; nothing committed since the planning phase.

---

## How this file gets maintained

Constitution **Principle VI** now requires it: after any meaningful piece of work — a new spec, plan, task list, implemented feature, or significant decision — this file gets updated with what happened, why, what was rejected, and any new terms, in plain language assuming no prior knowledge.

If you ever read an entry here and can't follow it, that's a defect in this file, not in you. Say so and it gets rewritten.
