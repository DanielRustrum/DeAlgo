"""Moving channels and playlists up and down the fill order.

Priorities are kept dense (0, 1, 2, …) so "up" and "down" are a swap with the
neighbour, and the numbers stay readable when someone looks at the database.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Channel, Playlist


def _ordered(session: Session, model):
    return list(session.scalars(select(model).order_by(model.priority, model.id)))


def normalize(session: Session, model) -> None:
    for position, row in enumerate(_ordered(session, model)):
        row.priority = position
    session.flush()


def move(session: Session, model, pk: int, direction: str) -> bool:
    """Swap a row with its neighbour. Returns False if it could not move."""
    rows = _ordered(session, model)
    index = next((i for i, row in enumerate(rows) if row.id == pk), None)
    if index is None:
        return False

    target = index - 1 if direction == "up" else index + 1
    if not 0 <= target < len(rows):
        return False

    rows[index], rows[target] = rows[target], rows[index]
    for position, row in enumerate(rows):
        row.priority = position
    session.flush()
    return True


def append(session: Session, row) -> None:
    """Put a newly added row at the end of the order."""
    model = type(row)
    highest = session.scalar(select(model.priority).order_by(model.priority.desc()).limit(1))
    row.priority = 0 if highest is None else highest + 1
    session.flush()


def move_channel(session: Session, pk: int, direction: str) -> bool:
    return move(session, Channel, pk, direction)


def move_playlist(session: Session, pk: int, direction: str) -> bool:
    return move(session, Playlist, pk, direction)
