"""Process-level configuration, all of it from the environment.

Anything a user should be able to change at runtime lives in the database
(see :mod:`dealgo.models`) so it can be edited from the web UI instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    data_dir: Path
    database_url: str
    host: str
    port: int
    public_url: str
    client_id: str
    client_secret: str
    api_key: str
    log_level: str

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url.rstrip('/')}/oauth/callback"


def load_config() -> Config:
    data_dir = Path(os.getenv("DEALGO_DATA_DIR", "./data")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    default_db = f"sqlite:///{(data_dir / 'dealgo.sqlite3').resolve()}"
    port = int(os.getenv("DEALGO_PORT", "8080"))
    return Config(
        data_dir=data_dir,
        database_url=os.getenv("DEALGO_DATABASE_URL", default_db),
        host=os.getenv("DEALGO_HOST", "0.0.0.0"),
        port=port,
        public_url=os.getenv("DEALGO_PUBLIC_URL", f"http://localhost:{port}"),
        client_id=os.getenv("DEALGO_CLIENT_ID", ""),
        client_secret=os.getenv("DEALGO_CLIENT_SECRET", ""),
        api_key=os.getenv("DEALGO_API_KEY", ""),
        log_level=os.getenv("DEALGO_LOG_LEVEL", "INFO").upper(),
    )


CONFIG = load_config()
