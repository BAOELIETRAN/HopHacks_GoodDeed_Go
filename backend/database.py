from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL, DB_PATH

log = logging.getLogger("gooddeed.db")


def _engine_for(url: str):
    """Build an engine for Postgres in production, SQLite locally.

    Two normalisations matter in practice:

    - Hosts hand out ``postgres://`` URLs; SQLAlchemy 2 only understands
      ``postgresql://``, and we pin the psycopg (v3) driver explicitly rather
      than depend on whichever DBAPI happens to be installed.
    - Managed Postgres closes idle connections, which surfaces much later as
      a random "server closed the connection unexpectedly". ``pool_pre_ping``
      checks a connection before handing it out, which costs one round trip
      and removes that whole class of flake.
    """
    if not url:
        log.info("No DATABASE_URL set -- using local SQLite at %s", DB_PATH)
        return create_engine(
            f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False}
        )

    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]

    log.info("Using Postgres at %s", url.split("@")[-1].split("/")[0])
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


engine = _engine_for(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
