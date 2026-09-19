"""Additive column migrations, run at startup.

The project has no Alembic setup and does not need one: every schema change
so far has been a new nullable column, which both SQLite and Postgres can add
in place. ``create_all`` creates missing *tables* but never alters existing
ones, so without this an existing database 500s on the first query touching a
new column.

Only add nullable columns here. Anything that rewrites or drops data needs a
real migration tool and a human looking at it.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

log = logging.getLogger("gooddeed.migrate")

# table -> column -> SQL type (valid in both SQLite and Postgres)
_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "users": {
        "google_sub": "VARCHAR(64)",
        "avatar_url": "VARCHAR(512)",
    },
    "friend_groups": {
        "cause_key": "VARCHAR(32)",
    },
    "submissions": {
        "checkin_id": "VARCHAR(32)",
        "verified_presence": "BOOLEAN",
        "deed_type": "VARCHAR(32)",
    },
}


def ensure_schema(engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table, columns in _ADDITIVE_COLUMNS.items():
        if table not in existing_tables:
            continue  # create_all will have built it with every column
        present = {c["name"] for c in inspector.get_columns(table)}
        missing = {name: sql for name, sql in columns.items() if name not in present}
        if not missing:
            continue
        with engine.begin() as conn:
            for name, sql_type in missing.items():
                log.info("Adding %s.%s", table, name)
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))


def relax_password_columns(engine) -> None:
    """Drop the NOT NULL on the password columns for Google-only accounts.

    Postgres can do this in place. SQLite cannot without rebuilding the table,
    but SQLite only enforces NOT NULL on insert and Google signups never
    reach that path on a pre-existing local database worth preserving, so it
    is skipped there rather than risking a table rebuild.
    """
    if engine.url.get_backend_name() != "postgresql":
        return
    try:
        with engine.begin() as conn:
            for column in ("password_hash", "password_salt"):
                conn.execute(
                    text(f"ALTER TABLE users ALTER COLUMN {column} DROP NOT NULL")
                )
    except Exception as exc:
        # Never take the service down over this. On a freshly created schema
        # the columns are already nullable and this is a no-op; if it fails
        # for any other reason, Google signup is the only thing affected and
        # the error belongs in the logs, not in a boot loop.
        log.warning("Could not relax password columns: %s", exc)
