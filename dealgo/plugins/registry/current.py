"""The registry this process is using, read once and rebuilt on demand."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

# Re-exported, so that a caller handling what a plugin did wrong does not have
# to know which module the sentence came from. Said with `as` rather than with
# an `__all__`, which would also hide every function here from the reference.
from ... import outgoing
from . import storage
from .decisions import decided
from .reading import read

if TYPE_CHECKING:
    from .offers import Registry


_lock = threading.Lock()


_loaded: Registry | None = None


def current() -> Registry:
    """The registry as it stands, reading the folders on first use."""
    global _loaded
    with _lock:
        if _loaded is None:
            _loaded = _everything()
        return _loaded


def forget() -> None:
    """Drop what was read, so the next question reads the folders again.

    The registry is built from the plugins folder *and* from the database
    rows saying what is switched off and what is granted. A test that swaps
    the database underneath it would otherwise keep answering from the last
    one — which is how a plugin paused in one test stayed paused for the
    rest of the run.
    """
    global _loaded
    with _lock:
        _loaded = None


def reload() -> Registry:
    """Read the folders again. What the Admin page's button does, what an
    upload does once the file has landed, and what switching one on or off
    does — the switch changes what the registry offers, so the registry has
    to be built again to offer it."""
    global _loaded
    with _lock:
        _loaded = _everything()
        return _loaded


def _everything() -> Registry:
    """Both folders, with the switches and the grants applied."""

    # A plugins folder written by an older version holds loose files. Moved
    # before it is read, so what loads is what will still be there next time.
    storage.settle(storage.folder())
    off, granted = decided()
    return read(
        storage.shipped(), storage.folder(),
        paused=off, granted=granted, trusted=storage.shipped(), http=outgoing.client,
    )
