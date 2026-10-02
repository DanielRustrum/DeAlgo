"""Phase two: filing everything waiting, after finishing what earlier runs left owing."""

from __future__ import annotations

import logging
from collections.abc import Collection
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...models import (
    Channel,
    Settings,
    Video,
)
from ...plugins.publisher import Publisher, PublishError, VideoDetails
from .. import graph, quota, runlog
from ..scope import OwnerId, owned
from .ordering import reorder

if TYPE_CHECKING:
    from .result import SyncResult

from .owed import reconsider_routing, retry_deferred
from .placing import Placing

log = logging.getLogger(__name__)


def publish(
    session: Session,
    client: Publisher,
    settings: Settings,
    result: SyncResult,
    owner: OwnerId = None,
    pen: runlog.Pen | None = None,
    sources: Collection[int] | None = None,
) -> None:
    """File everything waiting: what earlier runs owe first, then each item in order."""
    say = pen or runlog.Quiet()
    placing = Placing(session, client, settings, result, owner, say)
    if retry_deferred(session, client, result, placing.added_per_playlist, owner):
        return

    brought = reconsider_routing(session, result, owner)
    if brought:
        say.write(f"{brought} item(s) had nowhere to go before, and now do")

    pending = _waiting(session, owner)
    if not pending:
        say.write("nothing was waiting to be filed")
        return
    say.write(f"{len(pending)} waiting to be filed")

    routes_for = _routes_by_channel(session, owner, sources)
    details = _details_for(session, client, result, owner, pending)
    reorder(pending, routes_for)

    for video in pending:
        if placing.quota_spent:
            break
        placing.file(video, details.get(video.video_id), routes_for.get(video.channel.id, []))


def _waiting(session: Session, owner: OwnerId) -> list[Video]:
    """Every pending item, in the order they are filed.

    Channel priority decides who gets in first when the budget is short;
    within a channel it stays chronological, so playlists read in order.
    With every channel left at the default priority this is exactly
    chronological, which is what it was before priorities existed.
    """
    return list(
        session.scalars(
            owned(select(Video), Video, owner)
            .join(Channel, Channel.id == Video.channel_pk)
            .options(selectinload(Video.placements), selectinload(Video.channel).selectinload(Channel.playlists))
            .where(Video.status == "pending")
            .order_by(Channel.priority.asc(), Video.published_at.asc(), Video.id.asc())
        )
    )


def _routes_by_channel(
    session: Session, owner: OwnerId, sources: Collection[int] | None
) -> dict[int, list[graph.Route]]:
    """The live paths out of each channel, read once rather than per item."""
    routes_for: dict[int, list[graph.Route]] = {}
    for path in graph.routes(session, owner):
        # Set off from a trigger, this run belongs to the boxes that trigger
        # is wired to. A channel drawn twice is one channel and two boxes,
        # each starting a path of its own, and only one of them was asked to
        # run — the other waits for whatever sets it off.
        if sources is not None and (path.source is None or path.source.id not in sources):
            continue
        # A path into a repository has no feed to be switched off; whether it
        # is live is the Deposit box's own switch, which the walk checked.
        if path.deposits or (path.playlist is not None and path.playlist.enabled):
            routes_for.setdefault(path.channel.id, []).append(path)
    return routes_for


def _details_for(
    session: Session, client: Publisher, result: SyncResult, owner: OwnerId, pending: list[Video]
) -> dict[str, VideoDetails]:
    """What YouTube says about the waiting videos, laid onto them.

    Only a YouTube video has details to read; a post has none, and an item
    from somewhere else is not YouTube's to answer for. They go onto the
    videos before anything reads them: a sort box orders by duration and by
    counts, and those arrive here — left until later, the first run of a new
    batch would sort it by nothing.
    """
    details: dict[str, VideoDetails] = {}
    clips = [v.video_id for v in pending if v.kind == "video"]
    if clips and client.can_read and quota.can_afford(session, 1, use_reserve=True, owner=owner):
        try:
            details = client.video_details(clips)
        except PublishError as exc:
            log.warning("could not load video details: %s", exc)
            result.messages.append("Video details unavailable; duration filters were not applied.")

    for video in pending:
        arrived = details.get(video.video_id)
        if arrived is None:
            continue
        video.duration_sec = arrived.duration_sec
        video.view_count = arrived.view_count
        video.like_count = arrived.like_count
        if arrived.title:
            video.title = arrived.title
    return details
