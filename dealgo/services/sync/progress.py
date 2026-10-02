"""Where a run in flight has got to, for anything watching it happen.

Held in memory rather than in the database: it is worth nothing once the run
is over, it changes many times a second, and a crash mid-run should not leave
a run that looks as though it is still going.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace

from ..scope import OwnerId


@dataclass
class RunProgress:
    """Where a run has got to, for anything watching it happen.

    Held in memory rather than in the database: it is worth nothing once the
    run is over, it changes many times a second, and a crash mid-run should
    leave no trace of it. What survives a run is the SyncRun row.
    """

    owner: OwnerId = None
    trigger: str = "manual"
    stage: str = "starting"
    #: The trigger box that set this off, when a person pressed one. The
    #: canvas lights it and the wire out of it, so the run reads as starting
    #: somewhere rather than as several boxes changing at once.
    fired_by: int | None = None
    #: The channel being polled right this moment.
    channel_pk: int | None = None
    #: The channels this run has finished with, and what each brought in.
    polled: dict[int, int] = field(default_factory=dict)
    #: The channels it could not read, and what went wrong. A poll that failed
    #: is not a poll that found nothing, and a canvas that drew them the same
    #: way sent people looking for a wiring fault that was not there.
    unreachable: dict[int, str] = field(default_factory=dict)
    #: How many items each feed has taken so far.
    placed: dict[int, int] = field(default_factory=dict)
    #: Items that got past each channel's own settings, by channel. What a
    #: channel found and what left it are different numbers, and the gap
    #: between them is the channel turning its own uploads away.
    left: dict[int, int] = field(default_factory=dict)
    #: Items each filter box let through and turned away, by graph node id.
    #: Kept per box rather than per run so the canvas can say where the flow
    #: stopped, which is the question a filter exists to answer.
    through: dict[int, int] = field(default_factory=dict)
    stopped: dict[int, int] = field(default_factory=dict)
    finished: bool = False
    #: Which run this is. A run is claimed before the thread that will carry
    #: it starts, so only the claimant may declare it over — otherwise a run
    #: that never got going would mark the one in flight finished.
    token: int = 0


_progress: RunProgress | None = None


_next_token = 0


_progress_lock = threading.Lock()


def progress() -> RunProgress | None:
    """A snapshot of the run in flight, or of the one that just ended."""
    with _progress_lock:
        if _progress is None:
            return None
        return replace(
            _progress,
            polled=dict(_progress.polled),
            placed=dict(_progress.placed),
            unreachable=dict(_progress.unreachable),
        )


def claim(owner: OwnerId, trigger: str, fired_by: int | None = None) -> int:
    """Say a run is about to begin, before the thread carrying it has started.

    The canvas asks where the run has got to the moment the button answers. A
    thread takes a little while to get going, and without this the answer
    would be about the *previous* run — which reads exactly like this one
    having finished instantly, with the last run's marks on the boxes.
    """
    global _progress, _next_token
    with _progress_lock:
        _next_token += 1
        _progress = RunProgress(
            owner=owner, trigger=trigger, fired_by=fired_by, token=_next_token
        )
        return _next_token


def finish(token: int) -> None:
    """Declare a run over, if it is still the run in hand.

    Guarded by the token: a call that never took the lock must not mark
    somebody else's run finished on its way out.
    """
    with _progress_lock:
        if _progress is not None and _progress.token == token:
            _progress.finished = True
            _progress.stage = "done"
            _progress.channel_pk = None


def note(**fields: object) -> None:
    """Move the run on. Silent when nothing is watching."""
    with _progress_lock:
        if _progress is None:
            return
        for name, value in fields.items():
            setattr(_progress, name, value)


def note_polled(channel_pk: int, found: int) -> None:
    with _progress_lock:
        if _progress is None:
            return
        _progress.polled[channel_pk] = found
        _progress.channel_pk = None


def note_unreachable(channel_pk: int, why: str) -> None:
    with _progress_lock:
        if _progress is None:
            return
        _progress.unreachable[channel_pk] = why
        _progress.channel_pk = None


def note_left(channel_pk: int) -> None:
    with _progress_lock:
        if _progress is None:
            return
        _progress.left[channel_pk] = _progress.left.get(channel_pk, 0) + 1


def note_filtered(node_pk: int, passed: bool) -> None:
    with _progress_lock:
        if _progress is None:
            return
        tally = _progress.through if passed else _progress.stopped
        tally[node_pk] = tally.get(node_pk, 0) + 1


def note_placed(playlist_pk: int) -> None:
    with _progress_lock:
        if _progress is None:
            return
        _progress.placed[playlist_pk] = _progress.placed.get(playlist_pk, 0) + 1
