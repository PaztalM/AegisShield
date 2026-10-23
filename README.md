# AegisShield

Real-time fraud detection system. A Producer publishes transaction events to RabbitMQ; a Worker
consumes them, evaluates them for fraud, and persists results to PostgreSQL.

This repository currently provides the **local development environment** — a message broker and a
database, running in containers, reachable from your host. No application services yet.

## Prerequisites

- **Docker Engine**
- **Docker Compose v2 or later** (the `docker compose` subcommand, not the older `docker-compose` script)

Nothing else. You do not install a broker, a database, or any client on your host — every
administrative and verification command in this document runs inside the containers.

## Setup

Two steps, from the repository root:

```bash
cp .env.example .env
docker compose up -d --wait
```

The first step is the only preparation ever needed. `.env` is git-ignored; `.env.example` is
committed and holds working development defaults, so the copy needs no editing.

### `--wait` is part of the start command, not an option

Plain `docker compose up -d` returns as soon as the containers are *created*, which is several
seconds before either component accepts a connection. `--wait` blocks until both report healthy and
exits non-zero if either fails to get there, so the exit status answers "is it ready yet" instead of
leaving you to guess.

## Commands

All commands run from the repository root.

| Intent | Command |
|---|---|
| Prepare configuration (once) | `cp .env.example .env` |
| **Start and wait for ready** | `docker compose up -d --wait` |
| Start in the foreground, watching logs | `docker compose up` |
| **Status and health** | `docker compose ps` |
| **Logs, broker only** | `docker compose logs -f rabbitmq` |
| **Logs, database only** | `docker compose logs -f postgres` |
| **Stop, keeping all data** | `docker compose down` |
| Stop without removing containers | `docker compose stop` |
| **Reset — discard all data** | `docker compose down -v` |
| Open a database shell | `docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'` |
| Inspect broker queues | `docker compose exec rabbitmq rabbitmqctl list_queues` |
| Show the resolved configuration | `docker compose config` |

There is no `make up`, no wrapper script, and no task runner. `docker compose` is the interface —
adding a layer over a one-line command would only create another thing to install and learn.

Running `docker compose up -d --wait` a second time against a running environment is safe. It
reconciles rather than duplicating, and it does not touch your data.

### `down` and `down -v` are two characters apart and do very different things

- `docker compose down` removes the containers and the network. **Your data survives**, in the two
  named volumes.
- `docker compose down -v` also removes the volumes. **Every row in the database and every queue in
  the broker is destroyed, irreversibly.**

`down -v` is the documented way to start completely fresh. It is not the way to stop for the day.

## Endpoints

| Endpoint | Host address | Override with |
|---|---|---|
| Broker — messaging (AMQP) | `localhost:5672` | `RABBITMQ_PORT` |
| Broker — web management interface | `localhost:15672` | `RABBITMQ_MANAGEMENT_PORT` |
| Database — PostgreSQL | `localhost:5432` | `POSTGRES_PORT` |

With the committed defaults, the connection strings from your host are:

```text
amqp://aegis:aegis_dev_password@localhost:5672/aegisshield
postgresql://aegis:aegis_dev_password@localhost:5432/aegisshield
```

Inside the container network the addresses are `rabbitmq:5672` and `postgres:5432`, and those never
change. Only the host side of each mapping is adjustable, so a service added later can rely on the
internal name whatever you publish locally.

### If a port is already in use

The start fails immediately, naming the occupied port, and leaves nothing half-running. Set the
corresponding variable in `.env` — for example `POSTGRES_PORT=55432` — and start again. Do not edit
`docker-compose.yml`; the override exists precisely so you never have to.

## Credentials

Every credential, database name, and host port comes from `.env`, which you create by copying
`.env.example`. No value is hard-coded in `docker-compose.yml`.

The defaults in `.env.example` are development-grade and reachable only from your own machine. They
are not secrets and are committed deliberately, so that a new contributor needs nothing beyond this
repository to get a working environment.

If a required credential is missing or empty, the start aborts before creating any container and
prints the name of the variable along with a pointer back to `.env.example`.

### Changing a credential requires a reset

The broker and database accounts are created once, while their volume is being initialized, and the
values are then frozen inside that volume. Editing `.env` afterwards has no effect — you simply get
authentication failures, because the old credential is still the real one.

To change one:

```bash
# 1. edit the value in .env
docker compose down -v        # 2. discard the volumes (destroys all data)
docker compose up -d --wait   # 3. re-initialize with the new values
```

There is no in-place path. This is the most common way to lose an afternoon with this kind of setup,
which is why it is written down here.
