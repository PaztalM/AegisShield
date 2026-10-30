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
| Inspect broker queues | `docker compose exec rabbitmq sh -c 'rabbitmqctl list_queues --vhost "$RABBITMQ_DEFAULT_VHOST"'` |
| Show the resolved configuration | `docker compose config` |

There is no `make up`, no wrapper script, and no task runner. `docker compose` is the interface —
adding a layer over a one-line command would only create another thing to install and learn.

**`--vhost` is not optional on the broker commands.** This environment runs in its own virtual host,
`aegisshield`, not RabbitMQ's default `/`. A bare `rabbitmqctl list_queues` succeeds, prints
`Listing queues for vhost / ...`, and shows **nothing** — which looks exactly like your queues having
vanished. Pass the vhost, as the table above does.

### Running SQL from PowerShell on Windows

Windows PowerShell strips the inner double quotes when it passes arguments to `docker.exe`, so the
obvious form fails — `psql` receives only `CREATE` and reports `syntax error at end of input`:

```powershell
# broken on Windows PowerShell
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -c "CREATE TABLE t (id int);"'
```

Send the SQL on standard input instead, which keeps it off the command line entirely:

```powershell
'CREATE TABLE t (id int);' | docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

`-T` is what lets standard input through. The same applies to psql's backslash commands: pipe `'\dt'`
rather than passing `-c "\dt"`, which the container's shell would otherwise reduce to `dt`.

Commands whose quoted values contain no spaces are unaffected — that is why the `rabbitmqctl` and
`rabbitmq-diagnostics` examples work as written. On macOS and Linux shells, none of this applies.

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

The start fails in about two seconds and names the port:

```text
Bind for 0.0.0.0:5432 failed: port is already allocated
```

To relocate it, set the corresponding variable in `.env` — for example `POSTGRES_PORT=55432` — and
start again. The variable is already in the file, so change that line rather than adding a second
one. Do not edit `docker-compose.yml`; the override exists precisely so you never have to. Only the
host side moves; inside the container network the address stays `postgres:5432`.

**Always run `docker compose down` before retrying a failed start.** This matters more than it
sounds. A failed start leaves one container created but never started, and Docker programs a
container's published ports when it is *created*, not when it is started. So if you clear the
conflict and simply run `docker compose up -d --wait` again, the command exits `0` and
`docker compose ps` reports the service **healthy** — while its port is not published and nothing on
your host can reach it. The healthcheck cannot catch this, because it runs *inside* the container,
where the database is genuinely fine.

If you suspect you are in that state, `docker compose port postgres 5432` prints nothing. (Use that
rather than `docker port <container>`: container names are derived from the directory you cloned
into — `aegisshield-postgres-1` here — because `container_name:` is deliberately unset so two copies
of this project can run on one host.) The cure is the same either way:

```bash
docker compose down
docker compose up -d --wait
```

## Broker management interface

The broker ships with its web management interface already enabled — the image is the
`-management-alpine` variant, so there is no plugin to turn on and no custom image to build.

Open **http://localhost:15672**, or whichever port `RABBITMQ_MANAGEMENT_PORT` names in `.env`.

Sign in with the **same account you use for AMQP** — `RABBITMQ_DEFAULT_USER` and
`RABBITMQ_DEFAULT_PASS` from `.env`. There is no separate web password. That account carries the
`administrator` tag, so the whole interface is available: queues, connections, channels, exchanges,
and live message rates.

You can administer the broker by hand from there — create a queue, publish a test message, purge a
queue — and the result is real broker state, visible immediately from the command line as well.

### `guest` does not exist here

Out of the box, RabbitMQ creates a `guest`/`guest` account. This environment never does: setting
`RABBITMQ_DEFAULT_USER` and `RABBITMQ_DEFAULT_PASS` makes the image create the project account
*instead of* the stock one, on the first start of a fresh volume.

Signing in as `guest` is therefore rejected — not because the password is wrong, but because no such
user was ever created. Confirm with:

```bash
docker compose exec rabbitmq rabbitmqctl list_users
```

which lists exactly one user:

```text
user    tags
aegis   [administrator]
```

### Inspecting the broker without a browser

Everything the interface shows is also reachable through `rabbitmqctl` inside the container, so
**no broker client needs to be installed on your host**:

| Intent | Command |
|---|---|
| List queues with message counts | `docker compose exec rabbitmq sh -c 'rabbitmqctl list_queues --vhost "$RABBITMQ_DEFAULT_VHOST" name messages'` |
| List users and their tags | `docker compose exec rabbitmq rabbitmqctl list_users` |
| Check the messaging listener is reachable | `docker compose exec rabbitmq rabbitmq-diagnostics -q check_port_connectivity` |
| Check for resource alarms | `docker compose exec rabbitmq rabbitmq-diagnostics -q check_alarms` |
| Show limits and free space | `docker compose exec rabbitmq rabbitmq-diagnostics status` |

#### If the broker stops accepting messages

RabbitMQ does not fail when it runs low on disk or memory — it raises a **resource alarm** and
blocks publishers while continuing to accept and deliver existing messages. Publishing simply hangs,
which is easy to mistake for a network problem.

The configured thresholds in this environment are the image defaults:

| Alarm | Threshold |
|---|---|
| Free disk space | **50 MB** (`Disk free limit set to 50MB`, reported at boot) |
| Memory high watermark | **0.6 of available memory** |

Both are visible two ways, so a raised alarm is never silent:

```bash
docker compose exec rabbitmq rabbitmq-diagnostics -q check_alarms   # exits non-zero, names the alarm
docker compose logs rabbitmq | grep -i alarm                        # warning when set, and when cleared
```

With an alarm in effect, `check_alarms` prints e.g. `Memory alarm on node rabbit@aegisshield-rabbitmq`
and exits `69`, and the log carries
`[warning] memory resource limit alarm set on node ...` followed by
`*** Publishers will be blocked until this alarm clears ***`. Clearing is logged too. Note that the
healthcheck stays `healthy` throughout, because the broker is working as designed — an alarm is
back-pressure, not a fault.

The `sh -c '...'` form with **single** quotes matters: it lets the container's own shell expand
`$RABBITMQ_DEFAULT_VHOST`, which the image already has. `.env` is read by Compose for interpolation
into `docker-compose.yml`; it is not exported into your host shell.

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

## Persistence and reset

Each component keeps its state in a Docker **named volume**, created automatically on the first
start. Nothing on your host is written to, and there is no directory to prepare.

| Volume | Mounted at | Holds |
|---|---|---|
| `postgres-data` | `/var/lib/postgresql` | The database cluster, at `18/docker` inside the mount: your tables, your rows, and the `aegis` account |
| `rabbitmq-data` | `/var/lib/rabbitmq` | The broker's Mnesia directory: users, the vhost, durable queue definitions, persistent messages |

The database mount is `/var/lib/postgresql`, **not** `/var/lib/postgresql/data`. PostgreSQL 18 moved
the cluster into a major-version-specific subdirectory and declares its volume one level up; a mount
at the old path makes the image refuse to start.

### What each stop command does to your data

| Command | Containers | Data |
|---|---|---|
| `docker compose stop` | Stopped, left in place | Kept |
| `docker compose down` | Removed | **Kept** |
| `docker compose down -v` | Removed | **Destroyed** |

`docker compose stop` is the quickest way to pause. The containers survive, so the next start skips
container creation and only has to wait for each service to become healthy again — use it when you
are coming back shortly. `docker compose down` removes the containers and the network, which is the
clean way to stop for the day; your volumes are untouched either way.

### `down` and `down -v` are two characters apart and do very different things

- `docker compose down` removes the containers and the network. **Your data survives**, in the two
  named volumes.
- `docker compose down -v` also removes the volumes. **Every row in the database and every queue in
  the broker is destroyed, irreversibly.**

`down -v` is the documented way to start completely fresh. It is not the way to stop for the day.
There is no confirmation prompt and no undo.

### Starting an already-running environment is safe

`docker compose up -d --wait` against a running environment is a no-op or a clean reconcile. It does
not duplicate containers, re-create volumes, or touch stored data: a service that has drifted from
`docker-compose.yml` is recreated to match, and anything already correct is left alone. Run it as
often as you like — it is the right command whenever you are unsure what state things are in.

### Changing a credential needs a reset

See [Changing a credential requires a reset](#changing-a-credential-requires-a-reset) under
Credentials. In short: the accounts are frozen into their volume when it is initialized, so editing
`.env` afterwards has no effect until the volume is discarded with `down -v`. There is no in-place
path.

### Verified, not assumed

Both halves of this were measured rather than taken on trust:

- A row in PostgreSQL and a durable queue in RabbitMQ were both present after the next start in
  **5 of 5** consecutive `docker compose down` / `up -d --wait` cycles.
- `docker compose down -v` left **no** volume behind, and the following start came up empty — no
  tables, no queues — in **5 of 5** consecutive reset cycles, with no manual repair.

If a durable queue ever does go missing across a restart while the database row survives, suspect the
broker's `hostname:` before the volume. RabbitMQ names its storage directory after its node name,
which it derives from the container hostname, so an unpinned hostname makes a recreated broker read
an empty directory beside your intact data. `docker-compose.yml` pins it to `aegisshield-rabbitmq`
for exactly this reason.
