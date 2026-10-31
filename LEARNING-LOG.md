# AegisShield — Learning Log

**A plain-language record of what we did, why we did it, and what we chose not to do.**

Last updated: 2026-10-31

This file assumes you know nothing in advance. Every term gets defined the first time it shows up. It is written to be read top to bottom, but you can jump to any section.

> **The single most important thing to understand right now:** feature 001 (the local environment) is **complete** — 45 of 45 tasks, one command brings up a healthy RabbitMQ and PostgreSQL. Feature 002 (the Producer and Worker that will actually detect fraud) is **specified, planned, broken into 59 ordered tasks, and cross-checked — still no code exists**. So there is a verified foundation and nothing running on top of it. Read the 2026-10-31 entries newest first: the feature 002 spec entry, then the feature 001 implementation entry, which explains the finished environment line by line.

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

Then the **entry log**, newest first. If you want the finished feature explained from scratch — every line of `docker-compose.yml`, what was rejected, what surprised us, and what still does not exist — read [Feature 001 is implemented: the whole thing, explained](#2026-10-31--feature-001-is-implemented-the-whole-thing-explained), the newest entry. Sections 1–12 above are the background that led to it.

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

### Task progress: 45 of 45 done — feature complete

| Phase | Tasks | Status |
|---|---|---|
| 1 — Setup | T001–T003 | ✅ complete |
| 2 — Foundational | T004–T006 | ✅ complete |
| 3 — User Story 1: one-command start 🎯 MVP | T007–T020 | ✅ complete |
| 4 — User Story 2: management interface | T021–T025 | ✅ complete |
| 5 — User Story 3: data across restarts | T026–T032 | ✅ complete |
| 6 — Polish & cross-cutting | T033–T045 | ✅ complete |

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

**Feature 001 is complete — 45 of 45 tasks.** There is no next task in it. The 2026-10-31 implementation entry in the entry log below explains the finished feature line by line, lists what was rejected, records the cold and warm timings with what their comparison shows, and states plainly what still does not exist.

**Feature 002 is now specified, planned and broken into 59 ordered tasks — and no code has been written.** `/speckit-analyze` has been run and found twelve defects; the critical one and all three high ones are fixed — most importantly, the test image could not have been built at all, because its build context did not contain the rules file its unit tests import. Eight medium and low findings are recorded and deliberately unfixed. The next step is T001, the first task in this project that writes application code.

**Feature 002 introduces the application services** — a Producer and a Worker — and three things this feature built exist specifically for it: `postgres` and `rabbitmq` as internal DNS names, `depends_on` with `condition: service_healthy` to wait for both, and the extension point proven by T039 (a throwaway service joined the environment and reached both components with zero edits to their definitions). The constitution's Principle IV retry-on-unavailable-dependency requirement was deliberately deferred to that feature, because the party that must retry is an application service and this one ships none.

All three user stories are done. One command brings up a healthy broker and a healthy database; the broker's web interface is published with the project's own administrator account and no reachable `guest`; and data survives a stop while `down -v` provably discards it, each measured over five consecutive cycles.

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

### 2026-10-31 (last entry of the day) — The cross-check found four real defects, and one of them would have stopped the tests from building at all

**What:** Ran `/speckit-analyze` on feature 002 — a read-only pass that compares `spec.md`, `plan.md` and `tasks.md` against each other and against the constitution. It produced twelve findings: one critical, three high, six medium, two low. The critical and the three high ones are now fixed. Still no code.

---

#### What this check is, and what it provably cannot do

`/speckit-analyze` reads the documents and looks for places where they disagree with each other: a requirement no task covers, a task covering nothing, two documents stating different things, a rule the constitution forbids. It writes nothing; it only reports.

What it cannot do is run anything. That limit is not theoretical — on feature 001 this same check produced a confident, wrong claim about how Docker's restart policy behaves, which took a measurement to overturn. So its output is a **list of contradictions to adjudicate**, not a list of things that will go wrong. Four of feature 001's five genuine surprises came from a dependency behaving differently than assumed, and no amount of document-reading would have caught any of them.

One suspicion from this pass was checked rather than reported. `rule` is the name of a column in the new table, and `RULE` used to be a PostgreSQL keyword (from the long-obsolete `CREATE RULE`). Reporting "this column name may need quoting" would have been plausible and would have cost somebody an hour. Instead: start a throwaway PostgreSQL 18.4, create the table with the exact `CHECK` constraint from the design, insert a row, select it back. It works unquoted. **Finding dropped before it was written down**, which is the second time in two days that has happened and is becoming the most useful habit in this project.

---

#### The critical one: the unit tests could not have been built

New term: a **build context** is the set of files Docker is allowed to see while building an image. Everything the image copies in must be inside it. It is set per service, and for the two real services it is that service's own folder — `producer/` and `worker/` — which is exactly right, because each service should contain only itself.

The plan applied the same pattern to the test runner: `build: ./tests`. And the plan *also* said, two paragraphs earlier, that `rules.py` lives in `worker/` "purely so the rule functions can be imported by the unit tests".

Both sentences are reasonable. Together they are impossible. With a context of `./tests`, the file `worker/rules.py` is not visible to the build, so it cannot be copied into the image, so `tests/unit/test_rules.py` cannot import it. Two tasks (T017 and T025) were unexecutable, and the constitution's requirement that the fraud rules have unit tests could not have been met.

The fix: the `tests` service alone builds from the **repository root**, with `dockerfile: tests/Dockerfile`, copying both `worker/rules.py` and `tests/`. A new root `.dockerignore` keeps `.git`, `specs/` and the markdown out of that context — and applies only to this one build, because the other two contexts are subdirectories and never read it.

Two alternatives were rejected, both instructive:

- **Bind-mount `worker/` into the test container.** A **bind mount** shares a folder from the host machine straight into a running container. It would work, and the tests would then run against whatever is in the working tree rather than against a built image — so "the tests pass" would stop meaning "the image is correct", and the command would behave differently on a machine with a different layout.
- **Copy `rules.py` into `tests/`.** Two copies of the fraud rules, which will drift. The whole reason `rules.py` is one file in one place is to prevent exactly that.

**This does not weaken Principle I.** The rule is that one *service* must not import another's code. `tests` is a test runner that is never deployed, and what it imports is the code under test. What would break the principle is a shared package that both `producer/` and `worker/` import — and there is none. The distinction matters because the lazy reading ("tests import worker code, therefore the boundary is broken") would push you toward the shared package that genuinely *is* forbidden.

**Why it survived four earlier reviews** — a spec, a quality checklist, a plan and a constitution gate — is the interesting part. None of those steps required anyone to ask *which files can this image see*. The task list was the first artifact specific enough to make the question unavoidable. **A document is only as checked as the most specific thing anyone has tried to do with it.**

---

#### The three high findings

**1. The velocity window was attributed to two different columns.** The rules contract and the data model both said the window is measured against `occurred_at` — when the transaction says it happened. The spec's Assumptions said the opposite: the store's view of when the decision was *made*. Those produce different verdicts for the same transaction, and two implementers would each have written a different `WHERE` clause with a document to point at.

`occurred_at` wins, and the spec sentence was rewritten. The reasoning, since it is a genuine trade-off rather than an obvious call:

| Basis | What it means | What goes wrong |
|---|---|---|
| `occurred_at` (chosen) | "how many transactions happened on this account in a minute" — the question a velocity rule is actually asked | The generator supplies the timestamp, so a badly skewed generator clock shifts the window |
| `decided_at` (rejected) | "how many did we get round to looking at in a minute" | The verdict depends on how long the message sat in the queue — the same transaction is flagged on a busy machine and not on an idle one |

The deciding argument is determinism. A skewed clock is a visible, diagnosable fault, and both timestamps are stored so it can be found after the fact. A verdict that depends on queue depth is not diagnosable at all: nothing is broken, the answer is just different each time. **Prefer a wrong answer you can detect over an unstable one you cannot.**

**2. FR-007 said the generator must be the *only* writer to the queue — and the integration tests publish to it.** Not a misunderstanding; both are required. FR-032 demands a test against the real broker with nothing mocked, and such a test has to publish from the outside, including malformed messages and deliberate repeats. The requirement has been narrowed to the running pipeline, with the test harness named as an explicit exemption. Written down rather than left implicit so that the next person who finds a second `basic_publish` reads it as a decision instead of a bug.

**3. The test runner did not wait for the Worker.** Its `depends_on` listed the broker and the database. But the integration test publishes an event and then waits for a *decision*, and only the Worker makes those. With the Worker down the test would hang and then fail for a reason unrelated to what it was testing — the worst kind of test failure, because it sends you to look in the wrong place. Fixed by adding `worker: condition: service_healthy`, which works because the Worker now has a healthcheck of its own.

Also folded in while rewriting the same task: the Producer must publish to the **default exchange** with routing key `transactions`. Dead-lettering preserves a message's original routing key and the dead-letter binding matches on exactly that string, so publishing through a named exchange would send rejected messages nowhere — and the symptom would be dead letters quietly disappearing, which is the one failure FR-019 exists to prevent.

---

#### What was found and deliberately left alone

Six medium and two low findings are recorded in full in the analysis but not yet fixed, because fixing them is a separate decision. The three worth knowing about are all the same shape — an edge case the spec lists and nothing verifies:

- **Two consumers at once.** The design makes this safe through the primary key, and nothing tests it. About five minutes of work (`--scale worker=2`) and it exercises the feature's central guarantee.
- **Zero, negative and enormous amounts.** The table deliberately has no constraint on `amount` so these are storable, but no test confirms one is actually decided rather than crashing the Worker.
- **A timestamp in the future.** Listed as an edge case, tested nowhere — and it is the same edge case the velocity-window contradiction was really about.

An edge case written in a spec with nothing checking it is not a safeguard, it is a claim. These three should either get a task each or be demoted to explicitly stated non-goals.

---

#### What does NOT exist

- **Still no code.** `producer/`, `worker/` and `tests/` do not exist on disk. `docker-compose.yml` still defines two services.
- Nothing has been measured. Every number in the plan is a target copied from the spec.
- Eight findings from this pass remain unfixed, by choice, and are listed above and in the analysis output.

**State:** feature 001 complete and verified. Feature 002 specified, planned, broken into 59 tasks, and cross-checked — with the critical and three high findings corrected in the spec, the plan, the task list and the queue-topology contract. Implementation has not started. The next thing that happens is T001, and it is the first task in this project that writes a line of application code.

### 2026-10-31 (later again) — Feature 002 has a task list: 59 steps, and two contradictions the list exposed

**What:** Ran `/speckit-tasks` for feature 002. Produced `specs/002-transaction-event-pipeline/tasks.md`: 59 numbered tasks in seven phases. Still no code. This is the last planning artifact — the next command actually writes files.

---

#### What a task list is for, and why it is not just a to-do list

The three documents before this one each answer a different question. The spec says **what** must be true. The plan says **how** it will be built. The task list says **in what order, and who is allowed to be working on what at the same time.**

The reason the order matters more than it sounds: a task list is also a dependency statement. If the database table does not exist, the Worker cannot insert into it. If the Dockerfiles do not exist, Compose cannot build the images. Getting this wrong does not produce a bug — it produces an afternoon of confusing failures that all have the same boring cause.

The seven phases:

| Phase | Tasks | What it is |
|---|---|---|
| 1. Setup | T001–T008 | Six build-input files (three `Dockerfile`s, three `requirements.txt`), plus the two existing files that must be edited first |
| 2. Foundational | T009–T015 | The database table, the thing that creates it, and the three new Compose entries. **Blocks everything.** |
| 3. User Story 1 | T016–T027 | The working pipeline. This is the MVP. |
| 4. User Story 2 | T028–T036 | Correct under failure: dead-lettering, and the tests that prove nothing is lost or duplicated |
| 5. User Story 3 | T037–T043 | Retrying and recovering on its own |
| 6. User Story 4 | T044–T049 | Tracing one transaction, and tuning the generator |
| 7. Polish | T050–T059 | The measurements, the audits, the documentation |

New term: **MVP** means *minimum viable product* — the smallest version that genuinely does the thing, rather than a version that is partly built everywhere. Phase 3 is deliberately the MVP: after T027, a transaction travels the whole path and ends up as a stored decision. Everything after that makes it reliable, recoverable or diagnosable, not *real*.

---

#### A choice about where correctness goes, which is worth understanding

The obvious reading of the four user stories is: build the happy path in Story 1, then make it correct in Story 2. That is wrong, and rejecting it is the one genuinely consequential decision in this task list.

The pipeline's whole correctness rests on two things — acknowledging the message only **after** the database commit, and `ON CONFLICT (event_id) DO NOTHING` on the insert. If those arrived in Story 2, then for the length of Story 1 the system would acknowledge messages it had not stored. That is not an incomplete feature; it is a system that destroys transactions, and the broker would believe each one was handled.

So both are built in Story 1, in T023, from the start. **Story 2 does not introduce them; it proves they hold.** Its tasks are the dead-letter path, the integration test, the idempotency test, killing the Worker mid-message, and reconciling a thousand generated transactions against a thousand stored decisions.

The general rule, stated plainly because it will come up again: **you do not stage work in an order that passes through a known-broken state.** An increment that is less capable is fine. An increment that silently loses data is not an increment, it is a bug with a schedule.

---

#### Two contradictions between documents, found by writing tasks against them

This is the thing a task list does that nothing before it does: it forces every statement in the design documents to be turned into an instruction. A sentence that cannot be turned into an instruction, or that turns into two different ones, is a defect — and both of these had survived the spec, the plan, the quality checklist and a gate check.

**1. The velocity window is measured against two different columns, depending on which document you read.** This one is a real behavioural contradiction, not a wording slip.

- `spec.md`, in the Assumptions, says: "Velocity uses the store's own view of when decisions were made, so a skewed clock in the generator cannot corrupt a rule outcome." That means `decided_at` — the Worker's own clock.
- `contracts/fraud-rules.md` says the opposite, in bold: "The window is measured against `occurred_at`, not `decided_at`", and accepts the consequence that a skewed Producer clock would shift the window.
- `data-model.md` agrees with the contract: `occurred_at` is "when the Producer says the transaction happened. The velocity window is measured against this."

The two are not interchangeable. `occurred_at` asks *when did these transactions happen*, which is what a velocity rule means, and trusts a clock we do not control. `decided_at` asks *when did we look at them*, which cannot be skewed by the Producer but makes the verdict depend on queue latency — the same transaction gets a different answer on a busy machine. Each is defensible; **having both written down is not**, because two implementers would write two different `WHERE` clauses and both would be able to point at a document.

The task list implements `occurred_at` (T023), because two of the three documents say so and because the contract states the trade-off explicitly rather than in passing. But that is a decision that should be *made*, not inherited from a majority vote, so it is flagged rather than quietly resolved — `spec.md`'s Assumptions is the sentence that has to change.

**2. The environment-variable count does not add up.** `contracts/environment-variables.md` says this feature adds eleven variables, bringing `.env.example` to twenty. Its own tables list twelve: the twelfth is `HEARTBEAT_MAX_AGE_SECONDS`, which has its own row, its own default and its own consumer, and so is a variable like any other. The real totals are twelve new and twenty-one.

Trivial on its own. It matters because feature 001's T034 audit — every variable Compose interpolates exists in `.env.example`, and every key in `.env.example` is actually read by something — works by counting. An audit whose expected number is wrong either passes when it should fail or fails when it should pass, and in both cases the next person stops trusting it. T053 repeats that audit and reconciles the count.

**The lesson, and it is a new one for this project:** the previous lesson was that *claims about dependencies must be executed, not argued*. This is its paper counterpart — **a document is only as checked as the most specific thing anyone has tried to do with it.** The spec was read, checklisted, planned against and gate-checked, and this contradiction survived all four, because none of those steps required anyone to write a `WHERE` clause. Turning prose into 59 instructions is itself a test, and it failed two of them.

---

#### What `[P]` means, and the one place it is deliberately absent

Thirteen tasks carry a `[P]` marker, meaning they touch different files with no unfinished dependency and could be done at the same time by different people.

Phase 2 has none at all, and that is on purpose: T011 through T015 all edit `docker-compose.yml`. Marking those parallel would invite two people to edit one file simultaneously, which is how you create a merge conflict with yourself. Phase 1, by contrast, is six brand-new files that share nothing, so all six are parallel.

---

#### What does NOT exist

- **Still no code.** Not one line. `producer/`, `worker/` and `tests/` are described in detail and none of the three directories exists on disk.
- `docker-compose.yml` is unchanged and still defines two services.
- Nothing has been measured. Every number in the task list — 50 events/second, a 2-second 95th percentile, a 60-second cold start — is a **target copied from the spec**, not a result. Twelve of the 59 tasks exist specifically to replace those targets with measurements, and the instruction in each is to record the number that came out, not the number predicted.

**State:** feature 001 complete and verified. Feature 002 specified, planned, and now broken into 59 ordered tasks. Two document defects found and recorded, both still unfixed. `/speckit-analyze` is the sensible next step, because it now has all three artifacts to cross-check — and it should find at least the velocity-window contradiction, which is a useful test of whether that check is worth running.

### 2026-10-31 (later still) — Feature 002 is planned: how the pipeline will be built, and the four abstractions we turned down

**What:** Ran `/speckit-plan` for feature 002. Produced `plan.md`, `research.md`, `data-model.md`, four contract documents, and a validation guide with 18 scenarios. Still no code — this is the "how" to the spec's "what".

---

#### The versions were measured, not remembered

Feature 001 lost time twice to confident claims about dependencies that used to be true. So this time the first thing done was to ask the actual tools:

```
docker manifest inspect python:3.14.10-slim   -> exists
docker run --rm python:3.14-slim python -V    -> Python 3.14.10
docker run --rm python:3.15-slim python -V    -> Python 3.15.2
pip install pika "psycopg[binary]" pytest     -> works on 3.14 AND on 3.15
```

Chosen: `python:3.14.10-slim`, pinned to the full patch version, identical in all three Dockerfiles. Library versions `pika==1.4.4`, `psycopg[binary]==3.3.6`, `pytest==9.2.0`.

**And one of my own arguments was destroyed by checking it, which is the useful part.** The standard reason to avoid the newest Python minor is that compiled packages lag behind it: a new release means no prebuilt wheel, so `psycopg` would try to compile from source and fail in a slim image with no compiler. That is a real phenomenon and it was my reason for picking 3.14 over 3.15.

It is not true here. All three packages install cleanly on 3.15. So the honest reason for choosing 3.14 is much thinner: it is one version behind the newest, which leaves more room for some future dependency that has not caught up, and nothing in this feature needs anything 3.15 added. That is conservatism, not a technical constraint, and research.md says so — including that 3.15.2 is verified working and switching is a one-line change in three files.

The lesson is small but keeps recurring: **a plausible reason is not a verified one, and the gap between them is one command.** This is the fifth time in this project that checking has overturned something I was confident about. The difference this time is that it was caught before it was written down as fact.

---

#### The design, and what it rests on

The correctness of this feature does not rest on writing careful code. It rests on three mechanisms that make the dangerous mistakes impossible rather than unlikely:

**1. Acknowledge last.** The Worker tells the broker "handled" only after the database commit. data-model.md fixes the order as six numbered steps and makes the point explicitly: a crash at *any* point in that sequence either redelivers the message or hits the primary key, so no ordering of those steps loses a transaction. Get the order backwards and a crash in the gap destroys a transaction permanently, with the broker believing it was handled.

**2. The event id is the primary key.** Idempotency becomes something the database enforces rather than something the Worker remembers to do. The alternative — check whether the row exists, then insert — has a gap between the check and the insert, and two Workers can both pass the check. A primary key cannot be raced. The insert uses `ON CONFLICT (event_id) DO NOTHING`, which turns a redelivery into a harmless no-op.

New term: **`ON CONFLICT DO NOTHING`** tells PostgreSQL that if the row already exists, succeed quietly and change nothing. `DO UPDATE` would also succeed, but it would modify the existing decision, which FR-018 specifically forbids.

**3. Rejected messages go to a dead-letter queue.** A message the Worker cannot parse is rejected with `requeue=False` into a separate queue where it can be counted and read.

New term: **dead-lettering** is the broker's own mechanism for setting a rejected message aside by republishing it to a nominated exchange, so it ends up in an ordinary queue rather than being destroyed. The alternatives were worse in instructive ways: `requeue=True` redelivers the same unparseable message forever and blocks everything behind it, and "log it and drop it" leaves only a log line, which rotates away.

---

#### Four abstractions turned down, and the one rule that decided each

Principle V says write the direct, concrete solution, and do not abstract until at least three concrete cases need it. It did real work here — each of these is a thing an experienced developer would reach for by reflex:

| Tempting | Rejected because |
|---|---|
| **An ORM** (SQLAlchemy) | One table, one insert pattern. An abstraction over a single concrete case. |
| **A rule registry / plugin system** | There are **two** rules. Principle V's threshold is three. Two functions in a file is the correct shape today, and the moment a third rule makes that genuinely awkward is the moment to revisit. |
| **A retry library** (`tenacity`) | A dependency for roughly ten lines of loop. |
| **An HTTP health endpoint** | Adds a web framework and a listening port to a service that otherwise has no network surface, in order to report a fact a file can carry. |

Instead, health is reported by a **heartbeat file**: each service touches a path on every loop iteration, and the Compose healthcheck checks the file is recent. This reports the thing that actually matters — *the loop is still turning* — which is precisely the distinction feature 001's T038 proved matters when it froze PostgreSQL and watched the container stay `running` while the healthcheck correctly turned `unhealthy`. Checking "is the process alive" would have been the false-ready failure all over again.

---

#### Two decisions the spec deliberately left open, now closed

**Where unprocessable messages go:** a dead-letter queue, as above. The constitution permitted either rejection or dead-lettering; dead-lettering wins because FR-029 requires the count to be *observable*, and a dead-letter queue gives that for free — `rabbitmqctl list_queues` shows the depth and the management interface shows the payloads.

**How velocity history is read:** a `SELECT count(*)` against the decisions table, in the same transaction as the insert, with an index on `(account_id, occurred_at)`.

The reason the spec banned in-memory history is worth restating because it is the kind of bug that would survive for months: memory dies with the process, so the same transaction would get a *different verdict* depending on how recently the Worker restarted, and two Workers would disagree with each other. **A decision that depends on uptime is not a decision.** Reading from the database costs one query per message and makes the answer deterministic everywhere.

The accepted cost: only *decided* transactions are counted, so events still in flight do not contribute, and the count can undercount slightly. It is deterministic, which is what the requirement actually asks for. *Revisit when* throughput rises enough that in-flight events become a large fraction of a window.

---

#### Boundaries, written down because otherwise they get invented

The first draft of the spec said nothing about a transaction exactly at a threshold. Two implementers would pick `>` and `>=` and both be certain they were right. So the rules contract fixes both:

- **Amount**: flagged when `amount > threshold`, strictly. Exactly at the threshold is **not** flagged.
- **Velocity**: the transaction being decided **counts toward its own total** (`prior + 1 >= count`), so with a threshold of 4, three priors plus this one flags. The window is **half-open**: a prior transaction exactly `window` seconds old falls outside and is not counted.

Related, and the kind of detail that produces an unreproducible bug: **the amount crosses the wire as a string, not a JSON number.** JSON numbers are binary floating point in most parsers, where `0.1 + 0.2 != 0.3`. A threshold comparison at exactly the boundary is the single place that error would surface — as a wrong verdict that cannot be reproduced reliably. String on the wire, `Decimal` in Python, `numeric(12,2)` in PostgreSQL: exact decimal the whole way.

---

#### A rule from feature 001 deliberately broken

Feature 001 wrote "no profiles" into its own Compose file header. This plan adds a third Compose entry, `tests`, carrying `profiles: ["test"]`.

The reasoning: FR-032 requires an integration test against the real broker and real database, and FR-026 forbids requiring anything on the host — so the test must run in a container. A plain service would start on every `docker compose up`, which is wrong for something that runs once and exits. Profiles are the mechanism Compose provides for exactly that.

Alternatives and why they lost: baking `pytest` into the Worker image puts test-only dependencies into a runtime image; a second Compose file breaks the stronger "exactly one Compose file" rule and splits the environment definition into two places that drift; running `pytest` on the host violates FR-026 outright.

It is recorded in plan.md's Complexity Tracking, and the Compose header comment will be corrected in the same change so the file does not contradict itself. Feature 001's rule was a statement about its own scope — it had nothing to put behind a profile — not a constitutional ban.

**On why the integration test may not mock anything:** the failures this feature must not have — acknowledging before committing, a duplicate row, a poison message blocking a queue — are all failures of the *interaction* between a service and its dependencies. A mock is built from the same assumptions as the code it tests, so it agrees with the code and proves nothing. Feature 001 is the evidence: four of its five surprises came from a dependency behaving differently than assumed, and no mock would have caught any of them.

---

#### Something the design work surfaced that the gate check missed

The conventional way to create a database schema in Docker is to drop SQL files into the postgres image's `/docker-entrypoint-initdb.d`. It is unusable here, for two independent reasons, and the second is the dangerous one:

1. It requires mounting a directory into the `postgres` service — which FR-023 forbids, because adding these services must not change feature 001's definitions.
2. **Those scripts run only when the data directory is first initialised.** On a fresh clone it would work. On the volume that already exists on this machine it would silently do nothing. A setup step that works for new developers and quietly fails for existing ones is worse than one that fails for everybody.

So migrations are numbered `.sql` files applied by the Worker at startup, tracked in a `schema_migrations` table, under a PostgreSQL advisory lock.

New term: an **advisory lock** is a lock the application asks PostgreSQL to hold on an arbitrary number. It locks no table; it only guarantees one holder at a time. It is what makes migration safe if two Workers start simultaneously, without inventing any coordination of our own.

The Worker owns migrations because it is the only service that touches the database, which removes the race entirely rather than managing it.

---

#### Accepted risks, with the condition for revisiting each

Recorded in plan.md and repeated here, because the constitution requires risks to carry their revisit condition rather than leaving it implicit:

1. **Queue arguments are immutable in RabbitMQ.** The dead-letter configuration must be right the first time the queue is created; changing it later needs the queue deleted. A half-finished implementation that creates `transactions` without the argument will make the correct implementation fail with `PRECONDITION_FAILED` — an error that looks nothing like its cause. *Revisit when:* the topology must change, at which point the migration path gets written down rather than improvised. The quickstart carries the recovery command.
2. **A single synchronous Worker must reach 50 events/second** — a 20 ms budget per message for one `SELECT` plus one `INSERT`. This is the most likely thing to fail. *Revisit when:* measurement shows it falls short. The fix is a larger prefetch with batched commits, or several Workers (safe, because of the primary key) — **not** relaxing the criterion.
3. **Velocity undercounts in-flight events.** As above.
4. **`pika`'s blocking connection services heartbeats on the calling thread**, so a long database stall drops the AMQP connection and surfaces as a confusing `StreamLostError` rather than a database error. Mitigated by prefetch 1, a generous heartbeat, and the reconnect loop. *Revisit when:* reconnect churn shows up in logs under normal load.

---

#### What does NOT exist

- **No code.** Not one line. Three directories are described in the plan and none exists on disk.
- **No tasks list.** `/speckit-tasks` is next, and that is what turns this plan into ordered, checkable work.
- Nothing in the running environment has changed. `docker-compose.yml` is untouched; it still defines two services, and the pipeline it describes is entirely on paper.

**State:** feature 001 complete and verified. Feature 002 specified and planned; implementation not started. Next step is `/speckit-tasks`.

### 2026-10-31 (later) — Feature 002 is specified: the first stage that actually does something

**What:** Wrote the specification for **002-transaction-event-pipeline**. No code yet — this is the "what and why" document that planning and implementation will work from. Feature 001 built the room; this describes the machine that goes in it.

**The feature in one sentence:** a **Producer** that invents transaction events and a **Worker** that examines each one for fraud and records the verdict, so that a transaction can travel the whole path Producer → RabbitMQ → Worker → PostgreSQL and come out the other end as a stored decision.

---

#### Why both services at once, instead of one at a time

This was the first real decision and it went against the instinct to keep each stage as small as possible.

Doing the Producer alone would have been smaller. But nothing would consume what it produced: messages would pile up in a queue, the only way to see anything working would be to stare at the management interface, and the constitution's requirement for an integration test across the full path still could not be written — because half the path would not exist.

Doing the Worker alone has the mirror problem: you have to hand-publish messages to test it, so the real path is still unproven.

So: **both, deliberately thin.** One event type, two rules, one decision record. The slice is end-to-end but shallow. The reason to prefer this shape is that an end-to-end slice proves the connections work, and connections are where this kind of system actually fails — a service that cannot reach the broker, a message nobody can parse, a decision written twice. Depth is cheap to add later; a wrong connection is expensive to find later.

New term: a **thin vertical slice** is a feature that goes all the way through a system end to end while doing as little as possible at each layer. The opposite approach — build one layer completely, then the next — leaves the risky part, the joins between layers, untested until the end.

**Rejected: a public fraud dataset or a file of sample transactions**, in favour of synthetic generated events. A real dataset would give realistic data and genuine fraud labels, but it has to be found, vendored into the repository, and its format then dictates the message contract. Generated events have no external dependency, run forever, and can be dialled to produce obviously-fraudulent transactions on demand so the rules are visibly working. The cost is that the "fraud detection" is demonstrably fake at this stage, which is acceptable because the rules are placeholders for a pipeline, not a product.

**Rejected: an HTTP endpoint for ingesting transactions.** More realistic as a front door, but it adds a web framework, a port, and something that has to call it — machinery for a requirement nobody has yet (Principle V).

---

#### What the specification demands, and the parts that matter most

Thirty-three requirements, grouped. The interesting ones are not the obvious ones.

**Acknowledge last, not first.** The Worker must tell the broker "I have handled this message" **only after** the decision is safely in the database. Get that order wrong and a crash in the gap between the two loses a transaction permanently, with no trace — the broker believes it was handled and throws it away. This is the single most important ordering constraint in the feature.

New term: **acknowledgement** is the consumer telling the broker a message was handled, which is what permits the broker to forget it. Until then the broker keeps it and will deliver it again if the consumer dies.

**Duplicates are a certainty, not a risk.** A broker's realistic guarantee is *at-least-once* delivery: if it is unsure whether a consumer handled something, it sends it again. So the same transaction will arrive twice, and the system must produce one decision, not two.

New term: **idempotent** means doing something twice has the same effect as doing it once. The spec requires this to be enforced **by the database itself**, through a uniqueness constraint on the transaction identifier, rather than only by the Worker checking first. The difference matters: a check-then-write in the Worker has a gap between the check and the write, and two Workers can both pass the check. A database constraint cannot be talked around.

**Nothing may be dropped silently.** A message that cannot be understood at all must be set aside where a developer can go and look at it, and must not be retried forever in a way that blocks everything behind it. The failure this prevents is the worst kind: a pipeline that looks healthy while quietly discarding what it cannot parse.

**Velocity cannot live in memory.** One of the two fraud rules is a velocity rule — "several transactions on one card in a short window". The obvious implementation keeps recent transactions in the Worker's memory. The spec forbids depending on that, because memory dies with the process: restart the Worker and its idea of recent history silently resets, so the same transaction gets a different verdict depending on when the Worker last restarted. A decision that depends on uptime is not a decision. The recorded default is to derive history from the database, which is already the system's source of truth, at the cost of a read per transaction.

**Boundaries must be decided, not discovered.** The first draft said nothing about a transaction exactly at the amount threshold, or exactly at the edge of the velocity window. That would have failed the spec's own "testable and unambiguous" bar — two people would implement it two ways and both would believe they were right. The spec now requires each boundary outcome to be written down and tested.

**And the debt from feature 001 comes due.** The constitution requires that a service retry a dependency rather than exit when it is not yet available. Feature 001 recorded this as deliberately deferred, because the thing that must retry is an application service and feature 001 shipped none. User Story 3 and FR-021 are where that is paid off. It was logged as deferred rather than silently skipped, which is exactly why it is being picked up now instead of discovered missing in six months.

---

#### Measurable targets, because "real-time" is not a number

The constitution insists that performance targets be stated as numbers in the feature spec rather than assumed globally. So:

| Target | Number |
|---|---|
| First stored decision after a cold start | under 60s |
| Transactions with exactly one decision | 100%, over at least 1,000 |
| Creation to stored decision | under 2s for 95% |
| Sustained throughput | at least 50/second for 5 minutes |
| Duplicate deliveries producing an extra decision | 0, over at least 100 |

These are targets for a thin slice on one laptop, with everything in containers on the same machine. They are not production figures and the specification says so, because a number without its conditions is the kind of thing that gets quoted back years later as a guarantee.

---

#### One deliberate rule-break, recorded rather than hidden

The specification template says to keep implementation details out. This spec names **JSON** in FR-003 and describes **durable queues** and **dead-lettering** in FR-006 and FR-019.

That is deliberate. Those are not free choices being made here — the constitution already fixes the broker, the database, the language, and states that every message payload must be JSON carrying an event ID and a timestamp. Writing those requirements technology-agnostically would pretend to a freedom the project does not have, and would let a plan satisfy the spec while breaking the constitution.

The deviation is limited to constraints the constitution already imposes, and the **Success Criteria section is kept clean** — it can be read by someone who has no idea what the system is built from. The reasoning is written into the quality checklist rather than left for a reviewer to guess at, because an unexplained rule-break looks identical to carelessness.

---

#### What does NOT exist

Stated plainly, because a specification is the easiest artifact in the world to mistake for progress:

- **No code whatsoever.** No Producer, no Worker, no Dockerfiles, no dependency lists, no database tables, no tests. Not one line.
- **No plan and no task list yet.** `/speckit-plan` and `/speckit-tasks` come next, and the plan is where the Constitution Check happens and where the design decisions this spec deliberately left open get made.
- **Two decisions deliberately left to the plan**, recorded in the checklist so they are not forgotten: exactly how velocity history is read, and exactly where unprocessable messages are set aside (the constitution permits either rejection or dead-lettering).
- Everything feature 001 did not build still does not exist. The only thing that changed today is that there is now a written description of what to build next.

**Accepted risk, and when to revisit it:** reading velocity history from the database on every transaction is a read per message. At the 50-per-second target that is fine. If a later feature raises the throughput target substantially, or adds rules that each need their own history query, this is the first thing that will need revisiting — and the trigger to revisit it is a throughput target the Worker cannot meet, not a vague sense that a query per message feels wasteful.

**State:** feature 001 complete and verified; feature 002 specified only. Next step is `/speckit-plan`, or `/speckit-clarify` first if any of the assumptions in the spec look wrong on a second reading.

### 2026-10-31 — Feature 001 is implemented: the whole thing, explained

**What this entry is.** Principle VI requires that after a feature is built, this log explains it from scratch: what exists, what every line of it is for, what was rejected, what surprised us, and what still does not exist. This is that entry for **001-local-docker-infra**, and it is written to be readable by someone who has never seen the project. The individual entries above are a diary; this one is the explanation.

**Two documents, two jobs, and neither replaces the other.** `README.md` is **operator documentation**: how to run the environment, what the commands are, what the addresses are, what to do when something fails. If you want to use this thing, read that. `LEARNING-LOG.md` — this file — is a **teaching document**: why it is built the way it is, what each decision cost, and what we got wrong on the way. If you want to understand or change this thing, read this. Someone following the README should never need this file; someone modifying the Compose file should read this one first.

---

#### 1. What was built

One file does the work: **`docker-compose.yml`**, 59 lines, defining two containers.

- **RabbitMQ 4.2.4** (the *message broker* — software that accepts messages from one program and holds them until another program collects them), with its web management interface, on host ports 5672 and 15672.
- **PostgreSQL 18.4** (the relational database), on host port 5432.

Supporting it: **`.env.example`** (nine configuration variables with working development defaults), **`.env`** (your private copy, git-ignored), and **`README.md`**.

Two commands take you from a fresh clone to a working environment:

```bash
cp .env.example .env
docker compose up -d --wait
```

Measured at **45.1 seconds** from nothing — no images on the machine at all — and **14.2 seconds** once the images are cached.

That is the whole feature. **No application code was written**, and that is deliberate: this feature's job was to provide the infrastructure that the Producer and Worker will later run against.

---

#### 2. Every line of `docker-compose.yml`, and why it is that way

New term first: **Docker Compose** reads one YAML file describing a set of containers and runs them together as a unit. A **container** is a program plus everything it needs to run, isolated from the rest of your machine. An **image** is the template a container is made from.

##### The header and `services:`

```yaml
# AegisShield — local development environment.
services:
```

There is **no `version:` key**. Older Compose files began with `version: "3.8"` or similar; that field is obsolete in Compose v2 and emits a warning. Its absence is intentional, not an omission.

##### `postgres` — lines 7–27

```yaml
  postgres:
```

**The service name is load-bearing.** It is also the hostname other containers use: a future Worker connects to `postgres:5432`. Renaming this service would silently break every future service's connection string, which is why the task specified it exactly.

```yaml
    image: postgres:18.4-alpine
```

Pinned to an exact release. `-alpine` means it is built on Alpine Linux, a deliberately tiny base — which is why the whole image is 412 MB rather than over a gigabyte. **Rejected: `postgres:latest`.** A floating tag means two developers can get different databases from the same file on the same day, and a build that worked yesterday can break overnight with no change on your side (FR-013).

Note `18.4` has only two parts. PostgreSQL has versioned as *major.patch* since version 10, so `18.4` is the complete version — there is no `18.4.0`. Earlier revisions of the design documents demanded a "full major.minor.patch tag", which is unsatisfiable here; see the 2026-10-30 audit entry.

```yaml
    environment:
      POSTGRES_USER: ${POSTGRES_USER:?POSTGRES_USER is not set - copy .env.example to .env}
```

This is **interpolation** — Compose substitutes a value from `.env` before Docker sees the file. The `:?message` form means *required*: if the variable is missing or empty, Compose refuses to start and prints that message.

Three decisions are packed in here. **The value is never written in this file**, so no credential is committed (FR-005). **Each variable is listed explicitly rather than using `env_file:`**, so the file records which image consumes which variable — `env_file:` would hand the whole file to both containers and tell the reader nothing. And **the error message names the variable and the fix.** Without the `:?`, a missing password reaches PostgreSQL and surfaces as an authentication failure that points nowhere; T037 confirmed that with `.env` absent you get all six missing variables named at once, before any container is created.

The message uses a plain ASCII hyphen, never an em dash, because it is printed to terminals that may be cp1252 (see the 2026-10-23 entry).

```yaml
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
```

The form is `host:container`. The **host** side uses `:-5432`, the *defaulted* form — omit the variable and you get 5432, so the file works without configuration but a developer whose machine already uses 5432 can move it (FR-004). The **container** side is the fixed literal `5432` and is never interpolated: inside the container network the address must not move, or every future service's connection string becomes a guess.

So there are two tiers of variable, and the difference is checkable: T037 commented out a *required* variable and the start was refused by name; commenting out this *defaulted* one started normally on 5432.

```yaml
    volumes:
      - postgres-data:/var/lib/postgresql
```

Attaches a **named volume** — storage with a name you chose, which Docker keeps when the container is destroyed and finds again by name on the next start. Without this, the database writes into an *anonymous* volume that `docker compose down` orphans, so every restart starts empty.

**The path is `/var/lib/postgresql`, not `/var/lib/postgresql/data`,** and this cost us a debugging session. The `/data` path is correct for PostgreSQL 9 through 17 and wrong for 18, which stores the cluster in a version-specific subdirectory (`/var/lib/postgresql/18/docker`) and declares its volume one level up so a future `pg_upgrade --link` need not cross a mount boundary. The image **refuses to start** if it finds a mount at the old path. **Rejected: a host bind mount** such as `./data:/var/lib/postgresql` — bind mounts bring file-permission and path-translation problems across Linux, macOS and Windows, and `docker compose down -v` would not clean them up, which would silently break the documented reset command.

```yaml
    healthcheck:
      test:
        - CMD-SHELL
        - pg_isready -h 127.0.0.1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"
```

A **healthcheck** is a command Docker runs *inside* the container on a schedule to decide whether the service is actually working. `CMD-SHELL` means "run this through a shell", which is what allows the quoting and variable expansion.

The `$$` is a Compose escape: it emits a single `$`, so the container's own shell expands `$POSTGRES_USER` at runtime. A single `$` would make Compose try to interpolate it from `.env` instead — same text, completely different timing.

**`-h 127.0.0.1` is mandatory, not decoration.** Without it `pg_isready` checks a Unix socket, which answers during first-start initialization *before* the TCP listener exists — a false "ready" that would break the promise that nothing is reported healthy before it accepts connections (FR-010, SC-003).

```yaml
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 30s
```

Check every 5s; a check that hangs longer than 5s counts as failed; 5 consecutive failures mark the service **unhealthy**; and for the first 30s failures don't count, because first-start initialization legitimately takes 10–20s.

T038 measured the time from freezing the server to `unhealthy` as **41s**, not the ~25s originally written here. The original arithmetic was `retries × interval` = 25s, which assumes each failed check returns instantly. Against a *frozen* server each round costs `timeout + interval`. Against a *crashed* server the original number would be right. `timeout` only costs you anything when a check hangs — which is precisely the case the healthcheck exists to catch.

```yaml
    networks:
      - aegisshield-net
    restart: unless-stopped
```

An explicit user-defined **bridge network** — a private virtual network for these containers, which gives them DNS resolution by service name. `restart: unless-stopped` asks Docker to start the container again if its process dies, or after the host or Docker itself restarts.

**That policy does *not* apply to `docker compose kill` or `stop`**, and this log previously claimed the opposite. Docker treats a stop or kill issued through its API as deliberate — which is what "unless stopped" names — so a killed container stays `Exited (137)`. Measured: `RestartCount` stayed `0` for 30s after an API kill, while a container whose process exited on its own reached `RestartCount 6` in 24s. What the policy actually buys is the crashed-process case and the reboot case.

##### `rabbitmq` — lines 29–51

Most lines mirror the database's, for the same reasons. The differences are what matter.

```yaml
    image: rabbitmq:4.2.4-management-alpine
```

The `-management` variant ships the web interface already enabled. **Rejected: the plain image plus a plugin-enable step, or a custom `Dockerfile`** — both add a build or a start-up step to save nothing (Principle V: no speculative machinery).

```yaml
    hostname: aegisshield-rabbitmq
```

**The subtlest line in the file, and it is required rather than cosmetic.** RabbitMQ derives its node name from the container hostname and stores its database in a directory named after that node — verified: `rabbit@aegisshield-rabbitmq`, with `/var/lib/rabbitmq/mnesia/rabbit@aegisshield-rabbitmq`. Docker assigns a *random* hostname to a recreated container. So without this line, a restart produces a new node name, RabbitMQ looks for a directory that does not exist, initializes an empty one *beside* your intact data, and your durable queues appear to have vanished.

New term: **Mnesia** is the database built into Erlang (the language RabbitMQ is written in) where the broker keeps its users, virtual hosts and queue definitions.

It is deliberately **not** `container_name:`, which stays unset so two copies of this project can run on one machine without colliding.

```yaml
      - "${RABBITMQ_MANAGEMENT_PORT:-15672}:15672"
```

The web interface. Same account as the messaging port; there is no separate web password.

```yaml
      RABBITMQ_DEFAULT_VHOST: ${RABBITMQ_DEFAULT_VHOST:?...}
```

New term: a **virtual host** (vhost) is a named partition inside one broker, with its own queues and permissions. This environment uses `aegisshield` rather than RabbitMQ's default `/`.

That choice has a consequence worth knowing, and T042 caught the README getting it wrong: a bare `rabbitmqctl list_queues` reads vhost `/`, succeeds, and lists **nothing** — indistinguishable from your queues having disappeared. Broker commands here need `--vhost`.

Setting these three `RABBITMQ_DEFAULT_*` variables is also what causes the image to create the project's administrator **instead of** the stock `guest`/`guest` account on a fresh volume. No separate step deletes `guest`; it is never created (FR-008, verified in T024).

```yaml
      test:
        - CMD-SHELL
        - rabbitmq-diagnostics -q check_port_connectivity
```

This opens a TCP connection to every listener the node has published. **Rejected: `rabbitmq-diagnostics ping` and `check_running`** — both can pass before the messaging listener is bound, which is the same false-ready failure `-h 127.0.0.1` prevents on the database side.

```yaml
      interval: 10s
      timeout: 10s
      retries: 6
      start_period: 60s
```

Longer than the database's on every axis. An Erlang node boot plus the management plugin commonly takes 20–40s on a first start, and `rabbitmq-diagnostics` starts a short-lived Erlang VM *per invocation*, so it needs a timeout `pg_isready` does not. A success during `start_period` marks the service healthy immediately, so the 60s window costs nothing when things are fast.

##### The bottom of the file — lines 53–59

```yaml
networks:
  aegisshield-net:
    driver: bridge

volumes:
  rabbitmq-data:
  postgres-data:
```

Declaring the network explicitly rather than relying on Compose's implicit default makes it a named thing a future service can join. The two volumes are declared with no options — the defaults are correct, and options nobody needs would be speculative.

---

#### 3. What behaved differently from the plan

Five things, and the pattern across them is the most useful thing in this entry.

| Expectation | Reality |
|---|---|
| Mount the database at `/var/lib/postgresql/data` | PostgreSQL 18 moved it; the image refuses to start |
| Both images pinned to `major.minor.patch` | PostgreSQL has no third version component |
| `docker compose ps` shows nothing partially started on a port conflict | The broker is left running; Compose cannot avoid this |
| `restart: unless-stopped` fires on `docker compose kill` | It does not; API kills are exempt |
| 5 failed checks mark a service unhealthy in ~25s | 41s, because a hanging check also costs its timeout |

Four of the five are the same mistake: **a confident statement about how a dependency behaves, written from reasoning or memory rather than from asking the dependency.** Every one was settled in seconds by a command — `docker image inspect`, `docker manifest inspect`, `docker inspect --format '{{.RestartCount}}'`, `docker compose ps`.

The one that hurt most was the restart policy, because it did not come from carelessness. It came from `/speckit-analyze`, as a confidently argued HIGH finding complete with a rejected-alternatives table, and it propagated into three documents and a logged lesson within a day. What separated it from that review's many *correct* findings is that the correct ones were contradictions **between documents**, which static reading genuinely does find, while this one was a claim **about a dependency**, which static reading cannot settle.

So: **static review finds contradictions; only execution establishes facts.**

A sixth item belongs here even though it is about our own tooling rather than the environment: **the test harness was wrong more often than the thing under test.** A port-conflict "failure" at 72 seconds turned out to be a stopwatch stopped by hand at a later shell prompt. A squatter socket that excluded nothing, because Windows permits a second bind where Linux does not. An assertion that a table list was empty, when the tool prints "Did not find any tables." A `grep -c` returning exit 1 for a legitimate count of zero, aborting a `&&` chain before the environment started. **A test that reports a false failure is as much a defect as one that reports a false pass**, and all four were caught only because the results looked odd enough to re-examine.

---

#### 4. The timings, and what the comparison shows

| | Cold (no images) | Warm (images cached) |
|---|---|---|
| **T020** — measured before the volumes were mounted | 50.5s | 14.5s |
| **T045** — measured against the final configuration | **45.1s** | **14.2s** |
| Budget | 300s (SC-001) | 60s (SC-002) |

**The re-measurement was prompted by a reasonable worry that turned out not to matter.** The analyze pass observed that T020's numbers were taken before the volume mounts existed, so its "warm" start had been rebuilding the database from scratch each time rather than reattaching to storage — meaning the figures might not describe the finished environment. Correct reasoning; the numbers came back the same.

What the equality actually tells us is more interesting than the numbers:

1. **`initdb` is cheap.** T020's warm run re-created the whole database cluster; T045's reused an existing one. The difference is 0.3s, which is noise. First-time database initialization is not a meaningful cost at this scale.
2. **The warm time is set by the broker, not the database.** Across every run, PostgreSQL reached healthy in 6.3–7.2s and RabbitMQ in 13.7–14.8s, and the two start in parallel. So the ~14s warm figure *is* RabbitMQ's Erlang boot; the database's work is entirely hidden inside it. Any future attempt to make startup faster must target the broker, and effort spent on the database would show up as nothing at all.
3. **The cold run is mostly download.** 670 MB of uncompressed image content in 45.1s, against a start that takes 14s warm.

One clause of SC-001 is **not** satisfied and should not be claimed: it asks for the measured link speed recorded alongside the timing, and no link-speed measurement was taken. What can honestly be said is that a 45.1s cold start against a 300s budget leaves the connection obviously not the limiting factor.

A caution recorded in passing: an earlier entry speculated that T020's 14.5s might be a per-container figure rather than wall-clock, implying a much thinner margin. T045's 14.2s, measured wall-clock and non-interactively, shows T020 was right. That speculation was withdrawn when the faulty stopwatch was found, and this confirms the withdrawal.

---

#### 5. Where the project stands

**45 of 45 tasks in feature 001 are complete.** All three user stories are built and verified, every edge case is exercised, and all 16 quickstart scenarios pass.

What works, and has been measured rather than assumed:

- One command brings up a healthy broker and a healthy database, 45.1s cold, 14.2s warm, and nothing is reported ready before it accepts connections.
- Data survives a stop and start — proven over 5 consecutive cycles — and `docker compose down -v` genuinely returns the environment to a first-start state, proven over 5 more.
- The broker's web interface is published, using the project's own administrator account, with `guest` never created.
- A port conflict fails in 1.8s naming the port, and the published port can be moved from `.env` without editing the Compose file.
- Missing configuration is refused before any container is created, naming every missing variable.
- A frozen component is reported `unhealthy` and the start command refuses to claim success.
- A SIGKILL of both containers loses nothing: PostgreSQL replays its write-ahead log, RabbitMQ recovers its Mnesia directory.
- A new service can join the environment, wait for both components to be healthy, and reach them by internal DNS — with **zero edits** to the two existing service definitions.
- No secret is committed, nothing is hard-coded, both images are exactly pinned, and the nine variables match the example file exactly.

##### What still does not exist

Plainly, so nobody is surprised:

- **No Producer and no Worker.** No application code of any kind — no source directory, no dependency manifest, no Dockerfile.
- **No database schema and no migrations.** The `aegisshield` database is created empty. The only table that has ever existed in it was `quickstart_check`, a throwaway used to prove persistence.
- **No queues or exchanges are declared by this feature.** The broker starts with an empty vhost; the services that need queues will declare them.
- **No automated test suite, and no CI.** Verification here was manual and scripted against `quickstart.md`. The constitution requires an automated integration test for the Producer → RabbitMQ → Worker → PostgreSQL path, and that belongs to the feature introducing those services — it cannot be written against infrastructure alone.
- **Nothing about deployment, production, or anything beyond one developer's machine.** Every credential in `.env.example` is development-grade and localhost-only.

##### One behaviour to know before you use it

If a start fails, run **`docker compose down` before retrying** rather than `up` again. A failed start can leave a container in `Created` state, and Docker programs published ports at container *creation* — so the next `up` starts it without its port binding, exits `0`, and reports the service **healthy** while nothing on your host can reach it. The healthcheck cannot see this, because it runs inside the container where the database genuinely is fine. `docker compose port postgres 5432` prints nothing when you are in that state. This is in `README.md` too, because it can happen in ordinary use.

---

#### 6. What to read next

Feature 001 is done. The next feature introduces an application service, and three things this one built exist specifically for it: the service name `postgres` and `rabbitmq` as internal DNS names, `depends_on` with `condition: service_healthy` to wait for both, and the extension point proven by T039. The retry-on-unavailable-dependency requirement from the constitution's Principle IV was deliberately deferred to that feature, because the party that must retry is an application service and this feature ships none.

### 2026-10-31 — The disk alarm, the unclean shutdown, and correcting a finding this log got wrong

**What:** T040 and T041. Both pass. 41 of 45. One of them overturns a conclusion recorded in this log on 2026-10-30, so that correction is the main business of this entry.

---

**T040 — the broker's resource alarms are observable.**

RabbitMQ does not crash when it runs low on disk. It raises a **resource alarm** and blocks publishers while continuing to serve existing messages, so a full disk shows up as publishing that mysteriously hangs. The spec's requirement is only that the condition be *visible through status or logs* rather than silent, because actually filling the disk is destructive and lowering the threshold would need a tenth variable and a configuration layer that Principle V rules out.

Healthy-state readings:

| Reading | Value |
|---|---|
| `check_alarms` | exit `0`, "reported no alarms, local or clusterwide" |
| Disk threshold | `Low free disk space watermark: 0.05 gb` |
| Free space | `1022.6777 gb` |
| Memory high watermark | `0.6` of available memory → 4.96 gb |
| Boot log | `Enabling free disk space monitoring` → `Disk free limit set to 50MB` |

The task said to "confirm `docker compose logs rabbitmq` is where a raised alarm would be reported", which could have been discharged by reading the documentation and asserting it. Instead the alarm path was **demonstrated**, by raising the *memory* alarm rather than the disk one — the same `rabbit_alarm` subsystem, one command to set and one to clear, nothing destroyed:

```
rabbitmqctl set_vm_memory_high_watermark 0.0001

check_alarms -> Memory alarm on node rabbit@aegisshield-rabbitmq
                exit=69
logs         -> [warning] memory resource limit alarm set on node 'rabbit@aegisshield-rabbitmq'
                *** Publishers will be blocked until this alarm clears ***

rabbitmqctl set_vm_memory_high_watermark 0.6     # restores; clearing is logged too
```

Both channels work, so the requirement holds for disk as well — a disk alarm travels the identical path.

**The finding worth keeping, which the task did not anticipate: the healthcheck stays `healthy` for the whole duration of an alarm.** That is correct behaviour, not a gap. `rabbitmq-diagnostics check_port_connectivity` asks whether the broker accepts connections, and under an alarm it does — the broker is deliberately applying back-pressure, not failing. But the consequence for a developer is sharp: when publishing hangs, `docker compose ps` will report everything healthy and tell you nothing. `README.md` now has an "If the broker stops accepting messages" section with both thresholds and the two commands that do reveal it.

New term: a **resource alarm** is RabbitMQ refusing new publishes while a resource is scarce, to protect itself. It is a throttle, not an error, which is exactly why it is easy to misdiagnose: nothing is broken, and nothing is moving.

---

**T041 — recovery from an unclean shutdown. Passes, in both passes.**

Killed outright with `docker compose kill` (SIGKILL, no graceful stop), the environment came back with **no manual repair of stored state**: the row was still there, `quickstart.durable` was still declared, and `docker compose up -d --wait` exited `0`. The recovery logs show the mechanisms doing their jobs — PostgreSQL replaying the write-ahead log (`redo starts at 0/1BD6558` → `redo done` → `checkpoint complete: end-of-recovery immediate wait`) and RabbitMQ recovering its Mnesia queues.

The analyze pass's instruction that this task must write its own state rather than inherit T030's was **correct and load-bearing**: T031's five `down -v` cycles sit between them, so there was nothing left to inherit. Phase 0 wrote the row and the queue itself, and the task only worked because of that change.

---

**The correction: this log recorded a conclusion about `restart: unless-stopped` that is false.**

The 2026-10-30 analyze entry, under "HIGH 1 — A verification step that could never observe what it claimed", says that T041's original expectation was impossible:

> That check cannot pass. Both services set `restart: unless-stopped`, and Docker's restart policy fires on **any** non-zero exit — a kill included. The containers come back on their own, before you can type the next command.

**They do not.** Measured:

| Case | Policy | Result |
|---|---|---|
| A — `docker compose kill` on the real container | `unless-stopped` | `exited`, **`RestartCount 0`**, still exited after 30s |
| B — container's own process runs `exit 1` | `unless-stopped` | `running`, **`RestartCount 6`** within 24s |
| C — `docker kill` on a throwaway container | `unless-stopped` | `exited`, **`RestartCount 0`** after 10s |

The rule is: **Docker applies a restart policy when the container's own process exits. It does not apply one when the container is stopped or killed through the Docker API.** The daemon records an API stop or kill as deliberate — which is literally what the name `unless-stopped` describes. Case B is the proof that the policy is live and working; cases A and C are the proof that a kill you issue yourself is exempt.

So the original T041 and the original Scenario 16 — which said to run `docker compose ps` and see the containers exited — were **right**, and the analyze pass inverted a correct expectation. Three consequences have been fixed:

- `tasks.md` T041 and `quickstart.md` Scenario 16 now expect `Exited (137)`, with the measurement and the mechanism recorded so nobody re-derives the wrong answer from the policy's name.
- The second "suspend the policy and kill again" pass the analyze entry added is **redundant**, not merely unnecessary: an API kill already *is* the developer-initiated path. T041 ran both passes and they were identical in every observable — `Exited (137)`, recovery exit 0, `rows=1`, queue durable. Both task and scenario now say so.
- `data-model.md`'s restart-policy row had been edited to say "the policy also fires after `docker compose kill`, so a killed container comes back on its own". That is now corrected, along with what the policy genuinely buys: a crashed server process, and the host or daemon restart — which is the actual laptop-lid case, and the one that justifies the policy under Principle V.

**What the analyze pass got right, and it is worth being precise about this.** Its conclusion that the policy should be *kept* was correct, and its rejected alternative — delete `restart: unless-stopped` so the test is convenient — was rightly rejected. Its reasoning about *why* the test needed changing was wrong, but the configuration it defended is good. Only the factual premise failed.

**The lesson, and it is uncomfortable because of where it comes from.** The HIGH-1 finding was confident, mechanically argued, and wrong, and it arrived inside a process whose entire purpose is catching exactly this. It then propagated into three documents and a logged lesson within one day, because a plausible explanation for a real-sounding problem is very easy to accept — especially when it comes with a tidy rejected-alternatives table.

What distinguishes it from the findings that held up is simply that **nobody ran it.** The volume-path defect was caught by a container refusing to start. The pin-shape defect was caught by `docker manifest inspect` returning not-found. HIGH 1 was caught by reading the Compose file and reasoning about Docker's documented behaviour — and reasoning is where this one went wrong. `docker inspect --format '{{.RestartCount}}'` would have settled it in seconds, and that is the same four-second check that would have caught the PostgreSQL 18 path and the two-part version tag.

So the rule this project keeps relearning, now in its fourth costume: **a claim about how a dependency behaves is a claim to be executed, not argued.** Static review is excellent at finding contradictions *between documents* — that is what every one of the analyze pass's surviving findings was. It is unreliable at establishing facts *about a dependency*, because the only authority there is the dependency.

Second, smaller, and aimed at this log specifically: **a document that records its reasoning can be wrong in a way that is harder to dislodge than a bare assertion**, because the reasoning makes the conclusion feel checked. This entry exists so the next reader of the 2026-10-30 entry finds the correction rather than the confident paragraph. A pointer has been added there too.

---

**State:** 41 of 45. `docker-compose.yml` is unchanged since T028; everything since has been verification and documentation. Remaining: T045 (re-measure start-to-healthy timing against the final configuration, wall-clock, non-interactively), T042 (README review against FR-017), T043 (the full 16-scenario quickstart run), T044 (the implementation entry this log owes).

The project's own test data (`quickstart_check` with one row, and the durable queue `quickstart.durable`) is deliberately left in place from T041's Phase 0.

### 2026-10-30 (night) — Three edge cases, all passing, and one estimate that was wrong in a useful way

**What:** T037, T038 and T039. All three pass. No configuration changed; the only edits were one corrected estimate and the task records themselves. 39 of 45.

---

**T037 — missing configuration. Passes, and more informatively than the task expected.**

With `.env` moved aside entirely, `docker compose up -d --wait` exits 1 and prints:

```text
error while interpolating services.postgres.environment.POSTGRES_DB: required variable POSTGRES_DB is missing a value: POSTGRES_DB is not set - copy .env.example to .env
... the same for POSTGRES_PASSWORD, POSTGRES_USER,
    RABBITMQ_DEFAULT_PASS, RABBITMQ_DEFAULT_USER, RABBITMQ_DEFAULT_VHOST
```

Six errors, one per required variable, each carrying the pointer to `.env.example`. **No container was created** — the failure happens during interpolation, before Compose touches the Docker daemon at all.

The task asked for "an error naming the **first** missing required variable". Compose names all six, which is better: a developer fixes one `.env` in one pass instead of rediscovering the next missing variable on each retry. The task text now records the real behaviour.

With a single variable commented out (`#POSTGRES_PASSWORD=...`), the error names `POSTGRES_PASSWORD` and nothing else. That is the specific thing this edge case exists to prevent: without the `${VAR:?message}` guards, a missing password would reach the image and surface later as an opaque authentication failure from PostgreSQL, which tells the developer nothing about where to look.

I added a check the task did not ask for, because the contract defines **two tiers** of variable and only one was being tested. Commenting out `POSTGRES_PORT` — a *defaulted* variable, `${POSTGRES_PORT:-5432}` — correctly did **not** fail: the start exited 0 and published 5432 from the default. So the required tier fails loudly and the defaulted tier falls back silently, exactly as `contracts/environment-variables.md` specifies. Testing only the required tier would have left half the design unverified.

`.env` was backed up outside the repository during this, and confirmed byte-identical afterwards with `diff`. Keeping the backup in the scratch directory rather than the working tree matters: a file named `.env.bak` in the repository is **not** matched by the `.gitignore` entry for `.env`, so a careless `git add -A` would commit it.

---

**T038 — an unhealthy component is never reported healthy. Passes.**

The technique is to freeze the server without stopping the container, so that Docker still sees a running process while nothing inside answers:

```
docker compose kill -s SIGSTOP postgres
```

New term: **SIGSTOP** suspends a process without terminating it. The container stays in `running` state because its main process still exists — it is simply not executing. This is the right test for FR-019 precisely because every cheap signal of health still looks fine: the container is up, the process is there, nothing crashed. Only an actual connection attempt can tell.

| Observation | Result |
|---|---|
| Container state while frozen | `running` throughout |
| Health state | `healthy` → **`unhealthy` after 41s** |
| `docker compose up -d --wait` while frozen | **exit 1** — did not claim success |
| After `kill -s SIGCONT` | back to `healthy` |

The important line is the third. A developer who runs the documented start command against a broken environment gets a non-zero exit, not a false "ready".

**The estimate that was wrong.** T010 recorded that after `start_period` elapses, "5 failures at 5s mark the service unhealthy within ~25s". The measurement says **41s**. The arithmetic behind ~25s was `retries × interval` = 5 × 5s, which assumes each failed check returns instantly. Against a *frozen* server it does not: `pg_isready` opens a TCP connection and waits, so each round costs roughly `timeout + interval` — 5s + 5s — giving something near 40–50s. Against a *crashed* server the original estimate would be right, because a refused connection fails immediately.

So the figure was not wrong so much as unlabelled: it was the best case stated as if it were the only case. T010 now carries both numbers and the reason they differ. Neither threatens FR-019, which asks only that an unhealthy component be reported as such, with no deadline.

**The lesson:** **`timeout` only costs you anything when a check hangs, which is exactly the situation you wrote it for.** It is easy to reason about healthcheck timing using `interval` and `retries` alone, because in the common case — a check that fails fast — `timeout` never comes into play. The one scenario where it dominates is the one the healthcheck exists to catch.

---

**T039 — the extension point. Passes, and this is the one that matters for what comes next.**

FR-015 and SC-010 promise that adding the first application service later will need **no change** to the broker and database definitions. That is a promise about the future, so it has to be tested now, on a scratch copy — never the committed file.

The scratch stack held the two infrastructure services verbatim plus one throwaway `probe` service declaring `depends_on` with `condition: service_healthy` on both. Running it from a fully stopped environment:

```text
Container aegisshield-rabbitmq-1  Waiting
Container aegisshield-postgres-1  Waiting
Container aegisshield-postgres-1  Healthy
Container aegisshield-rabbitmq-1  Healthy
Container aegisshield-probe-1     Starting
-- up -d returned after 16s --

probe exit code: 0
172.18.0.3   postgres
172.18.0.2   rabbitmq
postgres:5432 reachable
rabbitmq:5672 reachable
query over internal dns ok
PROBE_OK
```

The probe resolved both services by their internal DNS names, reached both internal ports, and ran a real `psql` query through `postgres:5432` — never through a published host port. The `Waiting` → `Healthy` → `Starting` sequence is `depends_on` doing its job: the probe did not run until both dependencies passed their healthchecks, which is the entire reason the healthchecks were specified as connection tests rather than process checks.

Two deliberate precautions, each of which caught or prevented a problem:

- **The scratch file was placed outside the repository and run with an explicit `-p aegisshield` project name.** Compose derives the project name from the compose file's directory, so without `-p` this would have become a *second* project named after the scratch directory, creating duplicate containers that then collided on ports 5432 and 5672. The `--env-file` had to be given explicitly for the same reason: Compose looks for `.env` beside the compose file.
- **The two services in the scratch copy were compared line-by-line against the committed ones.** This caught a real error: the first draft had silently omitted the `rabbitmq-data` volume mount. Had it run that way the probe would still have printed `PROBE_OK`, and T039 would have "passed" while testing a configuration the project does not have. The comparison now runs as part of the task, so "zero edits" is demonstrated rather than claimed.

That second point generalises: **a test of "X works unchanged" is worthless unless you verify X is actually unchanged.** The interesting part of T039 was never whether a container can resolve a DNS name — it was whether *this* environment supports extension without modification, and that claim lives entirely in the equality between the two files.

---

**State:** 39 of 45. `docker-compose.yml` has not changed since T028; everything since has been verification and documentation. Remaining: T040 (the broker's disk alarm), T041 (unclean shutdown), T045 (re-measure timings against the final configuration), T042 (README review), T043 (the full 16-scenario quickstart run), T044 (this log's implementation entry).

### 2026-10-30 (evening) — The port-conflict test, a healthy service nobody could reach, and a stopwatch that measured typing

**What:** T036, the port-conflict edge case. It passes, but getting there took three attempts and produced two corrections to the documents plus one genuine behavioural discovery that a developer could easily hit by accident.

---

**Attempt 1 failed because the test never created a conflict.**

To occupy host port 5432 the first instinct on Windows was a .NET socket listener:

```powershell
$squat = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, 5432)
$squat.Start()      # reports IsBound : True
```

It reported success, and then `docker compose up -d --wait` started normally with the database published on 5432 as if nothing were holding it. The listener excluded nobody.

The reason, confirmed by experiment rather than reasoning — with Docker already publishing 5432, a fresh `TcpListener` on the same port **still bound successfully**:

**Windows lets a second socket bind an address that is already in use**, unless the first socket asked for exclusivity with `SO_EXCLUSIVEADDRUSE`. .NET's `TcpListener` does not ask. On Linux the same code would have failed with `EADDRINUSE`, which is why the trick is so commonly suggested. It is a genuine platform difference, not a quirk of this project.

New term: **`SO_EXCLUSIVEADDRUSE`** is a Windows socket option meaning "no other socket may bind this address while I hold it". Its absence is the default, and the default on Windows is permissive. `SO_REUSEADDR`, the option people reach for on Unix to allow quick rebinding, has materially different semantics on the two platforms — this is the kind of detail that makes a test look like it passed.

**The method that works is Docker itself:**

```
docker run -d --name portsquat --entrypoint sleep -p 5432:5432 postgres:18.4-alpine 300
```

Docker's port allocator keeps its own bookkeeping and refuses a duplicate host port regardless of what the OS would allow. It is also the more faithful test: the spec's edge case is "another broker, another database, or a previous copy of this environment", all of which are Docker publishing a port, not a bare socket. And it reuses an image already on the machine, so there is no pull.

---

**Attempt 2 produced a number that was 36 times too large, because the stopwatch was wrong.**

The measured failure time came back as **72.1 seconds** against SC-009's 10-second budget — an apparent, serious failure. It was an artifact. The harness looked like this, across three separate interactive prompts:

```powershell
$sw = [Diagnostics.Stopwatch]::StartNew()
docker compose up -d --wait
$code = $LASTEXITCODE          # <- typed by hand, seconds later
$sw.Stop()                     # <- typed by hand, seconds later still
```

The stopwatch ran until a human typed `$sw.Stop()`. It was measuring typing speed. Run non-interactively, in one shot:

| Command | Exit | Elapsed |
|---|---|---|
| `docker compose up -d` | fails | **2.07s** |
| `docker compose up -d --wait` | 1 | **2.04s** |

So SC-009 passes with a wide margin: about 2 seconds against 10, with the port named in the error.

**This also required retracting a claim made earlier the same day.** An earlier successful start, timed with the same broken harness, read 34.5s while Compose's own output showed the containers healthy at 7.0s and 14.0s. From that gap I inferred that T020's recorded warm figure of 14.5s might be a per-container number rather than wall-clock, and that the true margin against SC-002 was therefore nearer 40% than the 76% recorded. **That inference was built on the bad number and is withdrawn.** There is no evidence T020's figure is wrong. T045 should still measure wall-clock explicitly and say so — that part stands on its own — but the specific claim about the margin was unfounded.

Worth sitting with: the log already contains a lesson from this morning that *a measurement is only as good as your model of what the measurement did*, written up after the `initdb` subtraction turned out to measure nothing. Hours later the same mistake was made in a new costume — accepting a number because the instrument reported it, without asking what the instrument was actually timing. **Knowing the lesson is not the same as applying it.** The practical form is narrower and more useful than the general principle: *an elapsed time is only valid if nothing human happened between the start and the stop.*

---

**Finding 1: "nothing partially started" is not something Compose can deliver.**

T036 and `quickstart.md` Scenario 7 both expected `docker compose ps` to show no component partially started after a conflict. What actually happens:

| Service | State after a conflicted start |
|---|---|
| `rabbitmq` | `Up (healthy)`, both ports published |
| `postgres` | `Created`, no ports |

Compose creates every container and then starts them. The port bind fails at start time, so any component whose ports are free is already running by then. There is no flag that makes this atomic, and building one would mean a wrapper script — which Principle V forbids and FR-018 argues against.

So the expectation was corrected rather than the behaviour. `spec.md`'s edge case now accepts a partial start explicitly and states what actually matters: the command exits non-zero, names the port, never silently binds elsewhere, and leaves a state the documented recovery fully resolves. This is the same resolution shape as the `restart: unless-stopped` finding from the analyze pass — when the configuration's real behaviour is reasonable and the test's expectation is not, the expectation is what is wrong.

---

**Finding 2, and this one is a real trap: a service reported healthy that the host cannot reach.**

Clearing the conflict and running the documented start command again:

```
docker compose up -d --wait          -> exit 0
docker compose ps                    -> postgres   Up (healthy)
docker port aegisshield-postgres-1   -> (nothing)
NetworkSettings.Ports                -> {"5432/tcp":[]}
HostConfig.PortBindings              -> {"5432/tcp":[{"HostPort":"5432"}]}
connect to 127.0.0.1:5432            -> NOT REACHABLE
```

Exit zero. Reported healthy. Unreachable.

The cause is that **Docker programs a container's published ports when the container is created, not when it is started.** The conflicted attempt left the database container in `Created` state; the next `up` started that existing container rather than recreating it, and the port binding was never programmed. The configuration still *says* 5432 — `HostConfig.PortBindings` is intact — while the runtime mapping is empty. Configuration and reality disagree, and `docker compose ps` reports the configuration.

The healthcheck cannot catch it, and that is the part worth understanding. `pg_isready -h 127.0.0.1` runs **inside** the container, where the database is genuinely listening and genuinely fine. T010 chose `-h 127.0.0.1` over a socket check precisely to test a real TCP listener rather than a Unix socket, and that was the right call — but the listener it tests is the container's, and it can say nothing about whether the host can reach it. A healthcheck verifies the component, never the plumbing between the component and you.

This does not break FR-019 as written, which is about a component being reported healthy when the *component* is not ready. But it produces exactly the experience FR-019 exists to prevent: a developer trusts `running (healthy)` and then cannot connect, with nothing in the output pointing at why.

A second `up -d --wait` happens to repair it, because Compose eventually notices the divergence and recreates the container. Relying on running the same command twice is not a documented procedure. `docker compose down` first fixes it deterministically in one step, which is now in `README.md` under "If a port is already in use", alongside `docker port` as the way to detect the state.

**The lesson:** **a status that reports configuration rather than observed reality will eventually lie to you, and the more trustworthy it usually is, the worse the lie.** `docker compose ps` is right virtually always, which is exactly why nobody double-checks it. The general habit worth keeping is to verify the property you actually care about: `docker port` and a connection attempt answer "can I reach this?", while `ps` answers "what is this supposed to be?".

---

**T036's other half passed cleanly.** Changing `POSTGRES_PORT` to `55432` in `.env` published the database on `0.0.0.0:55432->5432/tcp` with **zero edits to `docker-compose.yml`** — FR-004 demonstrated. The container side stayed `5432`, which is what lets a future application service keep using `postgres:5432` internally no matter what the host publishes.

One wording fix there too: the task said to *append* `POSTGRES_PORT=55432` to `.env`. But `.env` is a copy of `.env.example`, which T004 required to contain all nine variables — so `POSTGRES_PORT` is always already present, and appending creates a duplicate key whose winner depends on dotenv precedence. The task and Scenario 7 now say to edit the existing line.

---

**State:** 36 of 45. Remaining: T037 (missing configuration), T038 (a frozen container must never report healthy), T039 (the extension point), T040 (the broker's disk alarm), T041 (unclean shutdown), T045 (re-measure timings), T042 (README review), T043 (full quickstart run), T044 (this log's implementation entry).

No change to `docker-compose.yml` in this entry. The edits were to `spec.md`, `quickstart.md`, `tasks.md` and `README.md` — three corrections and one new warning, all of them things the environment taught us rather than things we designed.

### 2026-10-30 (later still) — User Story 3 is proven, and the three audits found a requirement that could not be met

**What:** T030 through T035. User Story 3 is complete and the first three Phase 6 audits are done. 35 of 45 tasks.

---

**T030 and T031: persistence stopped being an assumption.**

Up to this point the volumes were mounted and a clean start worked, but nothing had actually written data, stopped the environment, started it again and looked. These two tasks did that, ten cycles in total.

| Test | Cycles | Result |
|---|---|---|
| T030 — data survives `docker compose down` | 5 | Row present and durable queue still declared, 5 of 5 |
| T031 — `docker compose down -v` truly resets | 5 | No leftover volume, no tables, no queues, 5 of 5, no manual repair |

That settles **SC-005** and **SC-006**, and acceptance scenarios 3.1, 3.2 and 3.3.

The ten cycles also produced an incidental result worth keeping: start-to-healthy times barely moved. PostgreSQL reached healthy in 6.3–7.2s every time and RabbitMQ in 13.7–14.8s, whether the volume was being reused or created from scratch. The consistency is the interesting part — it means `initdb` and a first-boot Erlang node are not meaningfully slower than reattaching to existing storage at this data volume. It does **not** discharge T045, which still owes a proper cold measurement with the images removed; this is a side observation from runs that were not set up to measure timing.

A practical note that cost a command during T030: **Windows PowerShell strips the inner double quotes** when it passes arguments to `docker.exe`. So this fails —

```
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -c "CREATE TABLE t (id int);"'
```

— because `psql` receives only `CREATE` and reports `syntax error at end of input`. Piping the SQL in on standard input keeps it off the command line entirely and works:

```
'CREATE TABLE t (id int);' | docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Earlier commands in this project were unaffected only by luck: their quoted values (`aegis`, `aegisshield`) contain no spaces, so losing the quotes changed nothing. This is now documented in `README.md` under "Running SQL from PowerShell on Windows", because every `psql` example here hits it on Windows and SC-008 says a contributor should not have to ask anyone for help.

---

**T033 — secrets and hard-coded values. Pass.**

- `.env` is matched by `.gitignore` line 2, is not tracked, and **has never been committed in the repository's history** (checked with `git log --all --diff-filter=A`, not just the working tree — a file can be ignored today and still sit in an old commit forever).
- `docker-compose.yml` contains no literal credential. The only match for a case-insensitive search of `passw|secret|token|credential` is `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?...}` — a variable name and an error message, no value.
- The only literals in the file are container-side ports (`:5432`, `:5672`, `:15672`), which are fixed by the images and are not configuration.

One thing the audit surfaced that is worth stating rather than glossing: the literal string `aegis_dev_password` **is** in version control, in `.env.example`, in the `README.md` connection strings, and in several design documents. That is deliberate and not a finding. FR-006 requires the example file to yield a working environment when copied, SC-004 requires every value a developer needs to be readable from committed documentation, and the spec's Assumptions section explicitly accepts development-grade credentials in the committed example. The values are localhost-only and nothing is intended to be secret. SC-007's "zero secrets" means no *real* secret — not the absence of a development default that the spec asks for by name.

I widened the audit beyond the command the task specified, which mattered: the task's own `grep -nE 'password|...'` is case-sensitive and would have sailed past `POSTGRES_PASSWORD` entirely. A case-sensitive search for a lowercase word is not an audit for credentials.

---

**T034 — variable parity. Pass, exactly.**

Nine variables interpolated by `docker-compose.yml`, nine declared in `.env.example`, and the two sets are identical — nothing in the Compose file that the example omits, and nothing in the example that the Compose file never reads. No speculative tenth variable, which is Principle V.

I compared the two sets programmatically rather than reading them side by side. Nine against nine is small enough to eyeball, and eyeballing is exactly how you miss one.

---

**T035 — image pins. The configuration passes; the task's own requirement could not be satisfied.**

T035 required each image to carry "a full `major.minor.patch` tag — no `latest`, no two-part tag, no floating reference". Checking that mechanically:

| Image | Verdict |
|---|---|
| `rabbitmq:4.2.4-management-alpine` | Three-part. Passes. |
| `postgres:18.4-alpine` | **Two-part. Fails as written.** |

The instinct is to go find `postgres:18.4.0-alpine`. It does not exist:

```
$ docker manifest inspect postgres:18.4.0-alpine   -> not found
$ docker manifest inspect postgres:18.4-alpine     -> resolves
$ SHOW server_version;                             -> 18.4
```

**PostgreSQL changed its versioning scheme at version 10.** Before that, releases looked like `9.6.24` — three parts, where `9.6` together formed the major version. From 10 onwards the major version is a single integer and the second component is the patch level, so `18.4` means "major release 18, patch 4" and is already the complete version. There is no third number to pin. RabbitMQ, by contrast, uses ordinary three-part semver, so `4.2.4` is correct for it. The two dependencies simply do not have the same version shape.

New term: a **floating tag** is one that points at different images over time — `latest`, or `postgres:18`, which moves as new patch releases land. The thing the requirement is actually protecting against is a tag whose meaning changes under you. `18.4-alpine` does not move.

**And FR-013 was never the problem.** It says only: *"Every third-party image used MUST be pinned to an explicit version tag; floating tags such as `latest` MUST NOT be used."* Both images satisfy that completely. The `major.minor.patch` phrasing was never a requirement — it was a *restatement* of FR-013 that smuggled in an assumption about dot-counting, and it had spread to seven places across `research.md`, `data-model.md`, `plan.md`, `quickstart.md` and three tasks.

All seven are now reworded to "the most specific tag its project publishes", with the per-project difference spelled out. T035 records that its original wording was unsatisfiable, and says to verify by resolving each tag with `docker manifest inspect` rather than by counting dots.

**The lesson:** **a requirement restated in your own words is a new requirement, and it can be stricter than the one it came from.** FR-013 asked for something true and checkable. Somewhere between the spec and the research document it became `major.minor.patch`, which sounds like the same thing, is more precise, and is wrong for half the dependencies. Precision added during a restatement is not free — it has to be checked against reality like anything else.

This is the second time in one day that an assumption about a dependency's conventions outlived its truth. The PostgreSQL 18 volume path was the first. Both were cases of writing down what the ecosystem used to look like; both were settled in seconds by asking the thing itself (`docker image inspect`, `docker manifest inspect`, `SHOW server_version`). The pattern is clear enough to name: **when a document states a fact about a dependency, that fact has a source, and the source is the dependency.**

A smaller thing in the same family: the audit mechanically checked the tag *shape*, which is why this surfaced at all. Had the task been done by reading the two lines and nodding — both obviously pinned, neither saying `latest` — it would have passed and the contradiction would have stayed in six documents.

---

**State:** 35 of 45. All three user stories complete and verified. Remaining: T036–T041 (the edge cases — port conflict, missing configuration, a frozen container, the extension point, the disk alarm, unclean shutdown), T045 (re-measure timings against the final configuration), T042 (README review), T043 (the full 16-scenario quickstart run), T044 (this log's implementation entry).

No configuration changed in this entry. T030–T035 were all verification, and the only edits were documentation corrections and the README additions.

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

> **CORRECTED 2026-10-31 — this finding's premise is false.** `restart: unless-stopped` does **not** fire after `docker compose kill`. Docker applies a restart policy when the container's own process exits, not when it is stopped or killed through the API. Measured: `RestartCount` stayed `0` for 30s after an API kill, while a self-exiting process reached `RestartCount 6` in 24s. T041's *original* expectation was right and this finding inverted it. Read the 2026-10-31 entry before acting on anything below.

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
