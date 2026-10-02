"""The sources an account watches, and removing one."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...models import Channel
from ..scope import OwnerId, owned


class ChannelError(RuntimeError):
    """A source could not be added or changed; the message says why."""

    pass


def list_channels(session: Session, owner: OwnerId = None) -> list[Channel]:
    """The account's sources in fill order, with the feeds each fills."""
    # Templates render after the session closes, so the targets come eagerly.
    return list(
        session.scalars(
            owned(select(Channel), Channel, owner)
            .options(selectinload(Channel.playlists))
            .order_by(Channel.priority.asc(), Channel.id.asc())
        )
    )


def delete_channel(session: Session, channel: Channel) -> None:
    """Stop watching a source, deleting its items with it."""
    session.delete(channel)
