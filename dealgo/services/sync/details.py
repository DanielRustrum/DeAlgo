"""Filling in what a source added by bare id does not say about itself."""

from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...models import (
    Channel,
)
from ...plugins.publisher import Publisher
from .. import quota
from ..scope import OwnerId, owned
from .result import SyncResult

log = logging.getLogger(__name__)


def fill_missing_details(
    session: Session, client: Publisher, result: SyncResult, owner: OwnerId = None
) -> None:
    """Fetch avatars, handles and about text for channels added by bare id.

    The Atom feed gives a title and nothing else, so a channel added by its
    UC… id has no picture. Fifty of them cost one quota unit, and it only
    happens once per channel. A NULL description also counts as missing, so
    channels tracked before there was such a column get filled in too.
    """
    if not client.can_read:
        return
    missing = list(
        session.scalars(
            owned(select(Channel), Channel, owner)
            .where(or_(Channel.thumbnail_url.is_(None), Channel.description.is_(None)))
            .order_by(Channel.id)
        )
    )
    if not missing or not quota.can_afford(session, 1, use_reserve=True, owner=owner):
        return

    try:
        found = client.get_channels([channel.channel_id for channel in missing])
    except Exception as exc:
        # Cosmetic enrichment: whatever goes wrong here, the videos still matter.
        log.warning("could not look up channel details: %s", exc)
        return

    for channel in missing:
        info = found.get(channel.channel_id)
        if info is None:
            continue
        channel.thumbnail_url = info.thumbnail_url
        channel.handle = channel.handle or info.handle
        # "" is a real answer here — the channel simply has no about text —
        # so store it rather than leaving NULL and asking again next run.
        channel.description = info.description or ""
        if info.title:
            channel.title = channel.title or info.title
    session.flush()
