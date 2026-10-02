"""Deposit boxes: holding items in a named pile."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    RepositoryItem,
    Video,
)
from .. import graph
from ..scope import OwnerId, owned


def deposit(
    session: Session,
    video: Video,
    paths: list[graph.Route],
    owner: OwnerId = None,
) -> int:
    """Put one item into every repository its paths end in.

    Once each. Two Deposit boxes carrying the same name are two ways into one
    pile, not two piles — and an item already waiting there is already
    waiting, so a second run does not double it up.
    """
    if not paths:
        return 0

    already = set(
        session.scalars(
            owned(select(RepositoryItem.name), RepositoryItem, owner).where(
                RepositoryItem.video_pk == video.id
            )
        )
    )
    put = 0
    for path in paths:
        if path.store in already:
            continue
        session.add(
            RepositoryItem(
                owner_pk=owner,
                name=path.store,
                video_pk=video.id,
                deposited_by=path.finish.id if path.finish is not None else None,
            )
        )
        already.add(path.store)
        put += 1
    if put:
        session.flush()
    return put


def waiting_in(session: Session, name: str, owner: OwnerId = None) -> int:
    """How many items a repository is holding."""
    wanted = graph.store_name(name)
    if not wanted:
        return 0
    return len(
        list(
            session.scalars(
                owned(select(RepositoryItem.id), RepositoryItem, owner).where(
                    RepositoryItem.name == wanted
                )
            )
        )
    )
