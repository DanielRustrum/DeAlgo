"""What each question on the `dealgo` object actually asks of one account's data.

Always handed an owner by `Site`, which is the one place that decides whose
data a plugin may see. Nothing here decides that for itself.
"""

from __future__ import annotations

import logging
from typing import Any

from ... import outgoing
from ...services.scope import OwnerId

log = logging.getLogger(__name__)


def sources_of(session: Any, owner: OwnerId) -> list[dict[str, object]]:
    from ...services import channels as channel_service

    return [
        {
            "key": channel.channel_id,
            "title": channel.title or channel.channel_id,
            "kind": channel.source_kind,
            "enabled": channel.enabled,
        }
        for channel in channel_service.list_channels(session, owner)
    ]


def feeds_of(session: Any, owner: OwnerId) -> list[dict[str, object]]:
    from ...services import playlists as playlist_service

    return [
        {
            "title": playlist.title,
            "generic": playlist.is_generic,
            "enabled": playlist.enabled,
            "sources": len(playlist.channels),
        }
        for playlist in playlist_service.list_playlists(session, owner)
    ]


def find_source(session: Any, owner: OwnerId, key: str) -> Any:
    from sqlalchemy import select

    from ...models import Channel
    from ...services.scope import owned

    if not key:
        return None
    return session.scalar(
        owned(select(Channel), Channel, owner).where(Channel.channel_id == key)
    )


def pause_source(session: Any, owner: OwnerId, key: str, on: bool) -> bool:
    channel = find_source(session, owner, key)
    if channel is None:
        return False
    channel.enabled = on
    session.flush()
    return True


def watch_source(session: Any, owner: OwnerId, reference: str) -> str | None:
    from ...services import channels as channel_service

    if not reference:
        return None
    with outgoing.client() as http:
        try:
            channel = channel_service.add_source(session, reference, http, owner=owner)
        except channel_service.ChannelError as exc:
            log.info("a plugin could not watch %r: %s", reference, exc)
            return None
    return channel.channel_id
