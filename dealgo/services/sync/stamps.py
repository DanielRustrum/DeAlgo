"""What the Decay and Tag boxes an item passed leave on it."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...models import (
    Video,
)
from .. import graph
from ..scope import OwnerId


def apply_stamps(
    session: Session,
    video: Video,
    paths: list[graph.Route],
    owner: OwnerId = None,
) -> None:
    """Leave on an item what the boxes it passed said about it.

    A Tag box names it, a Decay box says how long you get with it, a Lock
    piece says that time cannot be held. Read after the path has let the
    item through, because these turn nothing away — a Decay box is not a
    reason to refuse something, only a reason to hurry.
    """
    marks = [node for path in paths for node in path.stamps]
    if not marks:
        return

    known = graph.pieces_of(session, owner)
    named = graph.stamped_tags(marks)
    if named:
        already = video.tag_list
        video.tags = ", ".join(already + [one for one in named if one not in already])[:400]

    seconds = graph.stamped_seconds(marks, known)
    if seconds is not None:
        # The shortest wins where an item came down two paths that disagree,
        # for the same reason it does within one: a limit is a limit.
        video.view_seconds = (
            seconds if video.view_seconds is None else min(video.view_seconds, seconds)
        )
    if graph.stamped_locked(marks, known):
        video.view_locked = True
    session.flush()
