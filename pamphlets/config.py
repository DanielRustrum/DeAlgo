"""Process-level configuration, all of it from the environment.

Anything a user should be able to change at runtime lives in the database
(see :mod:`pamphlets.models`) so it can be edited from the web UI instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    """An environment variable as a switch: 1, true, yes or on."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Everything read from the environment at start-up."""

    data_dir: Path
    database_url: str
    host: str
    port: int
    public_url: str
    log_level: str
    # The admin account, and the only account defined outside the database.
    # Setting both is what switches authentication on at all.
    admin_user: str
    admin_password: str
    session_days: int

    @property
    def redirect_uri(self) -> str:
        """Where a service sends the browser back to after a sign-in.

        One address for every plugin's service: which sign-in it was is in
        the `state` the host made, not in the path, so the address registered
        with a service never has to change.
        """
        return f"{self.public_url.rstrip('/')}/oauth/callback"

    @property
    def auth_enabled(self) -> bool:
        """Whether Pamphlets asks who you are.

        Off unless an admin is configured, so upgrading an existing instance
        does not lock its owner out of it. The app says so, loudly, on every
        page until an admin is set.
        """
        return bool(self.admin_user and self.admin_password)

    @property
    def admin_password_weak(self) -> bool:
        """Whether the admin password would be refused if a person typed it.

        The environment's password is not held to the length the app asks of
        everyone else: it is the operator's own choice, and refusing it would
        mean refusing to start. It is said out loud instead — in the log at
        boot, and on the Admin page for as long as it stands.
        """
        return self.auth_enabled and len(self.admin_password) < 8


def setting(name: str, default: str = "") -> str:
    """A setting from the environment: `PAMPHLETS_<NAME>`, or — for an install
    set up before the app was called Pamphlets — `DEALGO_<NAME>`."""
    for prefix in ("PAMPHLETS_", "DEALGO_"):
        found = os.getenv(prefix + name)
        if found is not None:
            return found
    return default


def _adopt_old_database(data_dir: Path) -> None:
    """Move a database made before the app was called Pamphlets to its new name.

    Its write-ahead log is folded in first, so the one file carries
    everything and the move cannot leave half of it behind.
    """
    old, new = data_dir / "dealgo.sqlite3", data_dir / "pamphlets.sqlite3"
    if new.exists() or not old.exists():
        return
    import sqlite3

    connection = sqlite3.connect(old)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    old.rename(new)
    for suffix in ("-wal", "-shm"):
        leftover = data_dir / f"dealgo.sqlite3{suffix}"
        if leftover.exists():
            leftover.unlink()


def load_config() -> Config:
    """Read the environment into a `Config`, making the data folder if needed."""
    data_dir = Path(setting("DATA_DIR", "./data")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    _adopt_old_database(data_dir)
    default_db = f"sqlite:///{(data_dir / 'pamphlets.sqlite3').resolve()}"
    port = int(setting("PORT", "8080"))
    return Config(
        data_dir=data_dir,
        database_url=setting("DATABASE_URL", default_db),
        host=setting("HOST", "0.0.0.0"),
        port=port,
        public_url=setting("PUBLIC_URL", f"http://localhost:{port}"),
        log_level=setting("LOG_LEVEL", "INFO").upper(),
        admin_user=setting("ADMIN_USER", "").strip(),
        admin_password=setting("ADMIN_PASSWORD", ""),
        session_days=max(1, int(setting("SESSION_DAYS", "30"))),
    )


CONFIG = load_config()
