"""Managing the set of playlists De-Algo keeps filled."""

from __future__ import annotations

from uuid import uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import GENERIC_PLAYLIST_PREFIX, Channel, Placement, Playlist
from ..youtube.api import YouTubeAPIError
from . import ordering
from .auth import build_client


class PlaylistError(RuntimeError):
    pass


def list_playlists(session: Session) -> list[Playlist]:
    return list(
        session.scalars(
            select(Playlist)
            .options(selectinload(Playlist.channels))
            .order_by(Playlist.priority.asc(), Playlist.id.asc())
        )
    )


def enabled_playlists(session: Session) -> list[Playlist]:
    return list(
        session.scalars(
            select(Playlist).where(Playlist.enabled.is_(True)).order_by(Playlist.priority, Playlist.id)
        )
    )


def item_counts(session: Session) -> dict[int, int]:
    """How many videos each playlist currently holds, as De-Algo sees it."""
    return dict(
        session.execute(
            select(Placement.playlist_pk, func.count(Placement.id))
            .where(Placement.playlist_item_id.is_not(None))
            .group_by(Placement.playlist_pk)
        ).all()
    )


def add_existing(session: Session, playlist_id: str, http: httpx.Client) -> Playlist:
    """Start feeding a playlist that already exists on the account."""
    playlist_id = (playlist_id or "").strip()
    if not playlist_id:
        raise PlaylistError("Choose a playlist.")
    if session.scalar(select(Playlist).where(Playlist.playlist_id == playlist_id)):
        raise PlaylistError("That playlist is already a target.")

    client = build_client(session, http)
    if not client.has_write_access:
        raise PlaylistError("Connect a Google account first.")
    try:
        info = client.get_playlist(playlist_id)
    except YouTubeAPIError as exc:
        raise PlaylistError(f"YouTube API error: {exc}") from exc
    if info is None:
        raise PlaylistError("That playlist could not be found on your account.")
    return _store(session, info.playlist_id, info.title)


PRIVACY_CHOICES = ("private", "unlisted", "public")


def create_generic(session: Session, title: str) -> Playlist:
    """A generic feed: no YouTube playlist behind it, so no quota and no account."""
    title = (title or "").strip()
    if not title:
        raise PlaylistError("Give the feed a name.")
    return _store(session, f"{GENERIC_PLAYLIST_PREFIX}{uuid4().hex[:16]}", title)


def create(session: Session, title: str, http: httpx.Client, *, privacy: str = "private") -> Playlist:
    title = (title or "").strip()
    if not title:
        raise PlaylistError("Give the new playlist a name.")
    if privacy not in PRIVACY_CHOICES:
        privacy = "private"

    client = build_client(session, http)
    if not client.has_write_access:
        raise PlaylistError("Connect a Google account first.")
    try:
        info = client.create_playlist(
            title,
            description="Built by De-Algo from the channels you chose.",
            privacy=privacy,
        )
    except YouTubeAPIError as exc:
        raise PlaylistError(f"YouTube API error: {exc}") from exc
    return _store(session, info.playlist_id, info.title)


def set_up_feed(
    session: Session,
    http: httpx.Client,
    *,
    source: str,
    title: str = "",
    privacy: str = "private",
    playlist_id: str = "",
    channel_pks: list[int] | None = None,
) -> tuple[Playlist, int]:
    """Create or adopt a playlist and link the channels that will fill it."""
    if source == "existing":
        playlist = add_existing(session, playlist_id, http)
    elif source == "generic":
        playlist = create_generic(session, title)
    else:
        playlist = create(session, title, http, privacy=privacy)

    linked = 0
    for channel_pk in channel_pks or []:
        try:
            set_membership(session, playlist, channel_pk, include=True)
            linked += 1
        except PlaylistError:
            continue  # a channel removed between opening the dialog and saving
    return playlist, linked


def _store(session: Session, playlist_id: str, title: str) -> Playlist:
    playlist = Playlist(playlist_id=playlist_id, title=title or playlist_id)
    session.add(playlist)
    session.flush()
    ordering.append(session, playlist)
    return playlist


def update(session: Session, playlist: Playlist, form: dict) -> Playlist:
    def as_count(key: str, label: str) -> int:
        raw = (form.get(key) or "").strip()
        if not raw:
            return 0
        try:
            return max(0, int(raw))
        except ValueError as exc:
            raise PlaylistError(f"{label} must be a whole number.") from exc

    playlist.max_items = as_count("max_items", "Max size")
    playlist.max_per_run = as_count("max_per_run", "Max added per sync")
    playlist.enabled = bool(form.get("enabled"))
    session.flush()
    return playlist


def remove(session: Session, playlist: Playlist) -> None:
    """Stop feeding a playlist. The playlist itself is left alone on YouTube."""
    session.delete(playlist)


def follow_feed_links(session: Session, channel: Channel, before: int) -> None:
    """Pause a channel with nowhere to send videos; resume it when it gains a feed.

    Only the transitions are acted on — gaining the first feed, or losing the
    last. A channel paused by hand while it had feeds stays paused when another
    is added, because that pause was a decision rather than a missing setup.
    """
    after = len(channel.playlists)
    if before == 0 and after > 0:
        channel.enabled = True
    elif before > 0 and after == 0:
        channel.enabled = False
    session.flush()


def set_membership(session: Session, playlist: Playlist, channel_id: int, *, include: bool) -> str:
    """Add or remove one channel from one feed. Returns the channel's title."""
    channel = session.get(Channel, channel_id)
    if channel is None:
        raise PlaylistError("That channel is no longer being watched.")

    before = len(channel.playlists)
    if include and channel not in playlist.channels:
        playlist.channels.append(channel)
    elif not include and channel in playlist.channels:
        playlist.channels.remove(channel)
    session.flush()
    follow_feed_links(session, channel, before)
    return channel.title


def set_channel_targets(session: Session, channel: Channel, playlist_pks: list[int]) -> None:
    before = len(channel.playlists)
    wanted = set(playlist_pks)
    channel.playlists = (
        list(session.scalars(select(Playlist).where(Playlist.id.in_(wanted)))) if wanted else []
    )
    session.flush()
    follow_feed_links(session, channel, before)
