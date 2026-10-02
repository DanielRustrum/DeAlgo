"""The engine and the sessions everything else opens.

One engine for the process. SQLite is shared by the scheduler thread and the
request threads, so it is opened for both and put in WAL mode, which lets them
read while one writes.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import CONFIG

_engine: Engine | None = None


_SessionFactory: sessionmaker[Session] | None = None


def _connect_args(url: str) -> dict[str, Any]:
    """Driver options: SQLite is shared between threads and waits on locks."""
    if url.startswith("sqlite"):
        # The scheduler thread and the request threads share one engine.
        return {"check_same_thread": False, "timeout": 30}
    return {}


def get_engine() -> Engine:
    """The process's one engine, made on first use."""
    global _engine, _SessionFactory
    if _engine is None:
        _engine = create_engine(
            CONFIG.database_url,
            future=True,
            connect_args=_connect_args(CONFIG.database_url),
        )
        if CONFIG.database_url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:  # pragma: no cover - driver glue
                """WAL so readers do not block the writer; foreign keys enforced."""
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        _SessionFactory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """The session factory bound to the engine."""
    get_engine()
    assert _SessionFactory is not None
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session that commits on success and rolls back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
