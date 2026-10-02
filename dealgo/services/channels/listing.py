"""The sources an account watches, and removing one."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...models import Channel
from ..scope import OwnerId, owned


class ChannelError(RuntimeError):
    pass


def list_channels(session: Session, owner: OwnerId = None) -> list[Channel]:
    # Templates render after the session closes, so the targets come eagerly.
    return list(
        session.scalars(
            owned(select(Channel), Channel, owner)
            .options(selectinload(Channel.playlists))
            .order_by(Channel.priority.asc(), Channel.id.asc())
        )
    )


def delete_channel(session: Session, channel: Channel) -> None:
    session.delete(channel)
