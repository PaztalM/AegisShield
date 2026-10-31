"""Apply numbered SQL migration files to PostgreSQL, exactly once each.

Called by worker.py at startup. The Worker owns migrations because it is the
only service that touches the database, which removes the race over who
applies them rather than managing it.

Safe to run repeatedly: already-applied versions are skipped (FR-015).
Safe to run from two Workers at once: an advisory lock means one waits.
"""

import logging
import os
import pathlib

import psycopg

log = logging.getLogger(__name__)

MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"

# Any fixed number works. It only has to be identical in every Worker - two
# Workers locking different numbers would both proceed, which is the whole
# thing this is here to prevent.
MIGRATION_LOCK_ID = 8274591


def _ensure_migrations_table(conn):
    """Create the bookkeeping table if it is not there yet.

    This is the one place IF NOT EXISTS is correct: no earlier migration could
    have created this table, so there is nothing else to ask.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    text        PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()


def _applied_versions(conn):
    """The set of migration versions already recorded as applied."""
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def _pending_files(applied):
    """Migration files not yet applied, in lexicographic order.

    The three-digit prefix is what makes that order correct past the ninth
    migration: "010" sorts after "009", where "10" would sort before "9".
    """
    return [
        path
        for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
        if path.name.split("_")[0] not in applied
    ]


def run_migrations(conn):
    """Bring the database up to date. Does nothing if it already is."""
    _ensure_migrations_table(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
    conn.commit()

    try:
        # Read the applied list only after holding the lock. Reading it first
        # would reintroduce exactly the race the lock exists to remove.
        applied = _applied_versions(conn)
        pending = _pending_files(applied)

        if not pending:
            log.info(
                "migrations: up to date, %d already applied", len(applied)
            )
            return

        for path in pending:
            version = path.name.split("_")[0]
            log.info("migrations: applying %s", path.name)
            with conn.cursor() as cur:
                # The file's own statements and the record that it ran go in
                # ONE transaction. Separately, a crash in the gap would leave
                # the schema changed but unrecorded, and the next startup
                # would try to apply it again and fail.
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
            conn.commit()
            log.info("migrations: applied %s", version)
    finally:
        # finally: runs even if something above raised.
        #
        # rollback() first, and it is not optional. A failed migration leaves
        # the transaction in an aborted state, where PostgreSQL rejects every
        # further command - including this unlock. Measured: without the
        # rollback, a broken migration surfaced as
        # "InFailedSqlTransaction: current transaction is aborted" from this
        # block, which REPLACED the actual SQL error and said nothing about
        # the real cause.
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))
        conn.commit()


def _connect():
    """Connect using the environment settings.

    Port 5432 is hard-coded on purpose: that is the port INSIDE the Compose
    network. POSTGRES_PORT is the host-side port and a developer may move it
    to clear a conflict, which would break this if we used it.
    """
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=5432,
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
    )


if __name__ == "__main__":
    # Lets this be run on its own for debugging:
    #     docker compose run --rm worker python migrate.py
    # worker.py calls run_migrations(conn) directly with its own connection,
    # because it owns the retry loop and should not have two of them.
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with _connect() as conn:
        run_migrations(conn)