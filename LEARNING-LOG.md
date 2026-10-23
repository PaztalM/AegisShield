# AegisShield — Learning Log

**A plain-language record of what we did, why we did it, and what we chose not to do.**

Last updated: 2026-10-23

This file assumes you know nothing in advance. Every term gets defined the first time it shows up. It is written to be read top to bottom, but you can jump to any section.

> **The single most important thing to understand right now:** the planning is complete and implementation has *just* started. Six of the 44 tasks are done — the configuration file and an empty skeleton of `docker-compose.yml` exist, but **neither RabbitMQ nor PostgreSQL is defined yet**, so there is still nothing to run. Section 10 states the exact position. Sections 1–9 explain the reasoning that got us here.

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

`specs/001-local-docker-infra/tasks.md` — **44 numbered tasks**, T001 through T044, grouped into six phases.

I read all seven documents above first, then derived the tasks from them. Each task names its exact file and quotes its constraints verbatim, so no decision gets re-made at implementation time.

The phases:

| Phase | Tasks | What for |
|---|---|---|
| 1 — Setup | T001–T003 | Check Docker works, check the image versions still exist, check `.gitignore` |
| 2 — Foundational | T004–T006 | Create `.env.example`; create the skeleton of `docker-compose.yml`; copy `.env` |
| 3 — User Story 1 | T007–T020 | Both services defined and verified working. **This is the MVP.** |
| 4 — User Story 2 | T021–T025 | The RabbitMQ web interface |
| 5 — User Story 3 | T026–T032 | Volumes, data survival, the reset command |
| 6 — Polish | T033–T044 | Edge cases, audits, final checks, update this log |

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

**Required** — `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set — copy .env.example to .env}`

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
├── .env.example                       ← NOT committed yet; all 9 variables, done (T004)
├── .env                               ← NEVER committed; your copy, done (T006)
├── docker-compose.yml                 ← NOT committed yet; SKELETON ONLY (T005)
├── LEARNING-LOG.md                    ← this file
├── .specify/
│   ├── .gitignore                     ← committed; Spec Kit's own local state
│   └── memory/constitution.md         ← modified, not committed; now 6 principles
└── specs/001-local-docker-infra/
    ├── spec.md                        ← committed; WHAT the feature must do
    ├── plan.md                        ← NOT committed; HOW we'll do it
    ├── research.md                    ← NOT committed; decisions + rejected options
    ├── data-model.md                  ← NOT committed; exact field values
    ├── quickstart.md                  ← NOT committed; 12 verification scenarios
    ├── contracts/                     ← NOT committed; variables, endpoints, commands
    ├── checklists/requirements.md     ← spec quality checklist
    └── tasks.md                       ← the 44 numbered tasks
```

### Task progress: 6 of 44 done

| Task | Status | Result |
|---|---|---|
| T001 Verify Docker works | ✅ `[X]` | — |
| T002 Verify image tags still exist | ✅ `[X]` | — |
| T003 Verify `.gitignore` ignores `.env` | ✅ `[X]` | Already true; ticked after I confirmed `.gitignore:2:.env` |
| T004 Create `.env.example` | ✅ `[X]` | All 9 variables present, with comments |
| T005 Create `docker-compose.yml` skeleton | ✅ `[X]` | Network + 2 volumes. **No services.** |
| T006 Copy `.env.example` → `.env` | ✅ `[X]` | Done, and correctly ignored by Git |
| T007–T044 | ⬜ | Not started |

### What this means in practice

`docker-compose.yml` exists, but it is a **skeleton**: it declares the network and the two volumes and nothing else. I checked what Compose makes of it:

```
$ docker compose config
name: aegisshield
services: {}
```

`services: {}` means **zero services**. So `docker compose up` would start nothing — there is no RabbitMQ and no PostgreSQL yet. Those arrive in Phase 3, tasks T007–T014.

This is exactly what Phase 2 was supposed to produce, so nothing is wrong. But it's worth seeing clearly, because "the file exists" and "the thing works" are very different statements, and `docker compose config` is how you tell them apart. Get in the habit of asking a tool what it actually sees rather than trusting that a file's presence means it's doing something.

### Files that still do NOT exist

```
README.md            ← the documentation task, T019
producer/            ← a whole future feature
worker/              ← a whole future feature
```

### Nothing is committed since the planning phase

`git status` shows the constitution as modified and everything else — `.env.example`, `docker-compose.yml`, this file, and all six planning documents — as **untracked**. Untracked means Git is not recording them: if you deleted one, Git could not get it back.

`.env` is the exception and is correctly absent from that list, because `.gitignore` hides it. That's T003 working, which is why I was able to confirm T003 above without changing anything.

Committing is worth doing soon. See Section 11.

---

## 11. What happens next

### Immediately

**`/speckit-implement`** — picks up the list where it stands (next unticked task: T003, then the real work at T007) and runs through to T044. The substance of what remains: add the `postgres` and `rabbitmq` service definitions to the skeleton in `docker-compose.yml`, write `README.md`, then verify the whole thing against the 12 scenarios in `quickstart.md`.

Two things you could reasonably do first:

- **`/speckit-analyze`** — cross-checks spec, plan, and tasks for contradictions and gaps before you build on them. Cheap insurance; a contradiction found now is far cheaper than one found at T030.
- **Commit the planning documents.** Right now `plan.md`, `research.md`, `data-model.md`, `quickstart.md`, `contracts/`, and `tasks.md` are untracked — meaning they exist only on your disk, unprotected by Git history. Committing them is a natural checkpoint: the planning phase is done, record it before implementation starts mixing new changes in.

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
