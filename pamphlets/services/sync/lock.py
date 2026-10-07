"""One playlist operation at a time."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class Busy(RuntimeError):
    """Another playlist operation holds the lock."""


_run_lock = threading.Lock()


@contextmanager
def playlist_lock() -> Iterator[None]:
    """Serialize everything that writes to the playlist.

    A sync inserting while a removal pass deletes would race over the same
    items, so the two take turns rather than overlapping.
    """
    if not _run_lock.acquire(blocking=False):
        raise Busy("Another playlist operation is already running.")
    try:
        yield
    finally:
        _run_lock.release()


def is_running() -> bool:
    """Whether a playlist operation holds the lock right now."""
    return _run_lock.locked()
