"""Logging for a command run from a shell."""

from __future__ import annotations

import logging

from ..config import CONFIG


def configure_logging() -> None:
    logging.basicConfig(
        level=CONFIG.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
