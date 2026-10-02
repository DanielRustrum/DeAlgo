"""Whose work the plugins are doing right now.

A plugin is install-wide; the data it may touch is one account's. The host
says whose work is in hand around each call, and the `dealgo` and `account`
capabilities read it here. Outside such a block they answer for nobody.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator

from ...services.scope import OwnerId


class _Whose(threading.local):
    """Whose work is in hand, on this thread.

    Thread-local because a sync runs in one and a request in another, and the
    two must never borrow each other's answer.
    """

    owner: OwnerId = None
    acting: bool = False


_whose = _Whose()


@contextlib.contextmanager
def acting_for(owner: OwnerId) -> Iterator[None]:
    """Say whose work the plugins about to run are doing.

    Nested deliberately restores rather than clears: a run inside a run is not
    a thing here, but if it ever became one, the inner finishing must not
    leave the outer speaking for nobody.
    """
    was, acted = _whose.owner, _whose.acting
    _whose.owner, _whose.acting = owner, True
    try:
        yield
    finally:
        _whose.owner, _whose.acting = was, acted


def whose() -> tuple[OwnerId, bool]:
    return _whose.owner, _whose.acting
