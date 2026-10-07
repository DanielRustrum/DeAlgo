"""Parts of a page that more than one route renders."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .. import outgoing
from ..models import (
    Channel,
    GraphNode,
    Placement,
    Playlist,
    Video,
)
from ..plugins.publisher import PlaylistInfo, PublishError
from ..services import channels as channel_service
from ..services import graph as graph_service
from ..services import playlists as playlist_service
from ..services import quota as quota_service
from ..services import watched as watched_service
from ..plugins.publisher import publishing_plugin
from ..services import connections
from ..services.connections import build_client
from ..services.scope import OwnerId, belongs_to, owned
from .responses import redirect
from .templates import Context


def quota_context(session: Session) -> Context:
    """The publishing service's allowance today: one ledger for the install."""
    state = quota_service.state(session)
    return {"quota": state, "quota_resets_in": quota_service.describe_reset()}


def stats_context(session: Session, owner: OwnerId = None) -> Context:
    """The counts row on the Configuration page: items by status, and what is in feeds."""
    counts: dict[str, int] = {
        status: held
        for status, held in session.execute(
            owned(select(Video.status, func.count(Video.id)), Video, owner).group_by(Video.status)
        ).all()
    }
    return {
        "counts": counts,
        # "added" means it reached the playlist at some point; this is what is
        # actually in there now, after pruning and watched-removals.
        "in_playlist": session.scalar(
            select(func.count(func.distinct(Placement.video_pk)))
            .join(Video, Video.id == Placement.video_pk)
            .where(Placement.playlist_item_id.is_not(None), belongs_to(Video, owner))
        )
        or 0,
        "watched_count": watched_service.count_watched(session, owner),
        "removable_count": watched_service.count_removable(session, owner),
        "enabled_channels": session.scalar(
            owned(select(func.count(Channel.id)), Channel, owner).where(Channel.enabled.is_(True))
        )
        or 0,
    }


def matching_channels(channels: Sequence[Channel], query: str) -> list[Channel]:
    """Every word must appear somewhere, in any order — partial words count."""
    terms = query.lower().split()
    if not terms:
        return list(channels)
    return [
        channel
        for channel in channels
        if all(
            term
            in " ".join(filter(None, [channel.title, channel.handle, channel.channel_id])).lower()
            for term in terms
        )
    ]


def matching_feeds(playlists: Sequence[Playlist], query: str) -> list[Playlist]:
    """The feeds whose title has every word of `query` in it."""
    terms = query.lower().split()
    if not terms:
        return list(playlists)
    return [p for p in playlists if all(term in (p.title or "").lower() for term in terms)]


def channel_list_context(
    session: Session,
    feed: str = "",
    tracking: bool = False,
    query: str = "",
    *,
    owner: OwnerId = None,
) -> Context:
    """Everything the Configuration page draws: sources, feeds, counts and filters."""
    def counts_by_channel(*conditions: ColumnElement[bool]) -> dict[int, int]:
        """How many items meet `conditions`, per source."""
        return {
            channel_pk: held
            for channel_pk, held in session.execute(
                select(Video.channel_pk, func.count(Video.id))
                .where(*conditions)
                .group_by(Video.channel_pk)
            ).all()
        }

    channels = channel_service.list_channels(session, owner)
    playlists = playlist_service.list_playlists(session, owner)
    counts_by_feed = {p.id: sum(1 for c in channels if p in c.playlists) for p in playlists}
    unassigned = sum(1 for c in channels if not c.playlists)

    if feed == "none":
        channels = [c for c in channels if not c.playlists]
    elif feed.isdigit():
        wanted = int(feed)
        channels = [c for c in channels if any(p.id == wanted for p in c.playlists)]
    else:
        feed = ""

    # Each word has to appear somewhere, in any order: "greene daniel" finds
    # "Daniel Greene", and a partial word still matches.
    terms = query.lower().split()
    if terms:
        def matches(channel: Channel) -> bool:
            """Whether every search word is in the source's title, handle or id."""
            haystack = " ".join(
                filter(None, [channel.title, channel.handle, channel.channel_id])
            ).lower()
            return all(term in haystack for term in terms)

        channels = [c for c in channels if matches(c)]

    return {
        "channels": channels,
        "tracking": tracking,
        "query": query,
        "all_feeds": playlists,
        "backfill_choices": channel_service.BACKFILL_CHOICES,
        "feed": feed,
        "feed_playlists": playlists,
        "counts_by_feed": counts_by_feed,
        "unassigned_count": unassigned,
        "total_channels": session.scalar(owned(select(func.count(Channel.id)), Channel, owner)) or 0,
        "pending_by_channel": counts_by_channel(Video.status == "pending"),
        "added_by_channel": {
            channel_pk: held
            for channel_pk, held in session.execute(
                select(Video.channel_pk, func.count(func.distinct(Placement.video_pk)))
                .join(Placement, Placement.video_pk == Video.id)
                .where(Placement.playlist_item_id.is_not(None))
                .group_by(Video.channel_pk)
            ).all()
        },
    }


_ACCOUNT_PLAYLIST_TTL = 120.0


_account_playlists_cache: dict[str, Any] = {"at": 0.0, "items": [], "error": None}


def _account_playlists(
    session: Session, *, refresh: bool = False, owner: OwnerId = None
) -> tuple[list[PlaylistInfo], str | None]:
    """The playlists on the connected account, cached for a couple of minutes."""
    # One cache for the whole process, not per account — see Known Issues.
    now = time.monotonic()
    fresh = now - _account_playlists_cache["at"] < _ACCOUNT_PLAYLIST_TTL
    if fresh and not refresh:
        return _account_playlists_cache["items"], _account_playlists_cache["error"]

    items: list[PlaylistInfo] = []
    error: str | None = None
    with outgoing.client() as http:
        client = build_client(session, http, owner)
        if client.has_write_access:
            try:
                items = client.my_playlists()
            except PublishError as exc:
                error = str(exc)
    _account_playlists_cache.update({"at": now, "items": items, "error": error})
    return items, error


def forget_account_playlists() -> None:
    """Drop the cached list of the account's YouTube playlists."""
    _account_playlists_cache["at"] = 0.0


def playlist_context(
    session: Session, creating: bool = False, *, owner: OwnerId = None
) -> Context:
    """Everything the targets panel needs, including the account's own lists."""
    state = connection_state(session, owner)
    available: list[PlaylistInfo] = []
    error: str | None = None
    if state["connected"]:
        available, error = _account_playlists(session, owner=owner)
    known = {p.playlist_id for p in state["playlists"]}
    return {
        "state": state,
        "targets": state["playlists"],
        "counts": state["playlist_counts"],
        "available": [p for p in available if p.playlist_id not in known],
        "playlist_error": error,
        "all_channels": channel_service.list_channels(session, owner),
        "creating": creating,
    }


def connection_state(session: Session, owner: OwnerId = None) -> Context:
    """The sign-in feeds are published through, and the feeds themselves.

    About the plugin that publishes, whichever that is: what its service is
    called, whether the admin has given it an OAuth client, and whether this
    account has signed in.
    """
    plugin = publishing_plugin()
    connect = plugin.connect if plugin is not None else None
    token = connections.publisher_token(session, owner) if connect else None
    return {
        # Which plugin, and what its service is called, for every sentence
        # that has to name them: "Connect your Google account".
        "plugin_id": plugin.id if plugin is not None else "",
        "publisher": plugin.title if plugin is not None else "",
        "service": connect.name if connect is not None else "",
        "can_connect": connect is not None,
        "connected": token is not None,
        "account": token.account_title if token else None,
        "needs_reconnect": bool(token and token.refresh_error),
        "reconnect_reason": token.refresh_error if token else None,
        "has_client": bool(plugin and connections.has_client_credentials(plugin)),
        "playlists": playlist_service.list_playlists(session, owner),
        "playlist_counts": playlist_service.item_counts(session, owner),
        "has_targets": bool(
            session.scalar(
                owned(select(func.count(Playlist.id)), Playlist, owner).where(
                    Playlist.enabled.is_(True)
                )
            )
        ),
    }


def channel_list_response(
    request: Request,
    *,
    ok: str | None = None,
    err: str | None = None,
    feed: str = "",
    tracking: bool = False,
    back: str = "",
    query: str = "",
) -> Response:
    """Every channel mutation answers with the whole list, freshly counted."""
    if back:
        # A channel's own page posts plainly and returns to itself.
        return redirect(back, ok=ok, err=err)
    # The canvas is the only view of this now, and it reloads itself.
    return redirect("/channels", ok=ok, err=err)


def feed_window_words(pieces: list[GraphNode]) -> list[str]:
    """What the pieces under a feed say about when it can be read.

    The Timer is a modifier rather than a line of its own: it says how long a
    Reset's window lasts, so it is read into the Reset's sentence and only
    speaks for itself when there is no Reset to speak for.
    """
    resets = [one for one in pieces if one.kind == "reset"]
    timers = [one for one in pieces if one.kind == "timer"]
    window = (
        max(1, timers[0].duration_minutes or graph_service.DEFAULT_DURATION_MINUTES)
        if timers
        else graph_service.DEFAULT_DURATION_MINUTES
    )
    said = [
        f"{graph_service.piece_words(one)} once you start reading" for one in timers[:1]
    ]
    said += [graph_service.piece_words(one, window) for one in resets]
    # Last, because it is a condition on the rest rather than another way in.
    said += [
        graph_service.piece_words(one)
        for one in pieces
        if one.kind == "alive" and graph_service.piece_words(one) != "any time of day"
    ]
    return said
