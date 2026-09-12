"""Managing the set of playlists De-Algo keeps filled."""

from __future__ import annotations

from uuid import uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import GENERIC_PLAYLIST_PREFIX, Channel, Placement, Playlist
from .scope import OwnerId, belongs_to, owned
from ..youtube.api import YouTubeAPIError
from . import ordering
from .auth import build_client
from collections.abc import Mapping


class PlaylistError(RuntimeError):
    pass


def list_playlists(session: Session, owner: OwnerId = None) -> list[Playlist]:
    return list(
        session.scalars(
            owned(select(Playlist), Playlist, owner)
            .options(selectinload(Playlist.channels))
            .order_by(Playlist.priority.asc(), Playlist.id.asc())
        )
    )


def enabled_playlists(session: Session, owner: OwnerId = None) -> list[Playlist]:
    return list(
        session.scalars(
            owned(select(Playlist), Playlist, owner)
            .where(Playlist.enabled.is_(True))
            .order_by(Playlist.priority, Playlist.id)
        )
    )


def item_counts(session: Session, owner: OwnerId = None) -> dict[int, int]:
    """How many videos each playlist currently holds, as De-Algo sees it."""
    return {
        playlist_pk: held
        for playlist_pk, held in session.execute(
            select(Placement.playlist_pk, func.count(Placement.id))
            .join(Playlist, Playlist.id == Placement.playlist_pk)
            .where(Placement.playlist_item_id.is_not(None), belongs_to(Playlist, owner))
            .group_by(Placement.playlist_pk)
        ).all()
    }


def add_existing(
    session: Session, playlist_id: str, http: httpx.Client, owner: OwnerId = None
) -> Playlist:
    """Start feeding a playlist that already exists on the account."""
    playlist_id = (playlist_id or "").strip()
    if not playlist_id:
        raise PlaylistError("Choose a playlist.")
    if session.scalar(
        owned(select(Playlist), Playlist, owner).where(Playlist.playlist_id == playlist_id)
    ):
        raise PlaylistError("That playlist is already a target.")

    client = build_client(session, http, owner)
    if not client.has_write_access:
        raise PlaylistError("Connect a Google account first.")
    try:
        info = client.get_playlist(playlist_id)
    except YouTubeAPIError as exc:
        raise PlaylistError(f"YouTube API error: {exc}") from exc
    if info is None:
        raise PlaylistError("That playlist could not be found on your account.")
    return _store(session, info.playlist_id, info.title, owner)


PRIVACY_CHOICES = ("private", "unlisted", "public")


def create_generic(session: Session, title: str, owner: OwnerId = None) -> Playlist:
    """A generic feed: no YouTube playlist behind it, so no quota and no account."""
    title = (title or "").strip()
    if not title:
        raise PlaylistError("Give the feed a name.")
    return _store(session, f"{GENERIC_PLAYLIST_PREFIX}{uuid4().hex[:16]}", title, owner)


def create(
    session: Session,
    title: str,
    http: httpx.Client,
    *,
    privacy: str = "private",
    owner: OwnerId = None,
) -> Playlist:
    title = (title or "").strip()
    if not title:
        raise PlaylistError("Give the new playlist a name.")
    if privacy not in PRIVACY_CHOICES:
        privacy = "private"

    client = build_client(session, http, owner)
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
    return _store(session, info.playlist_id, info.title, owner)


def set_up_feed(
    session: Session,
    http: httpx.Client,
    *,
    source: str,
    title: str = "",
    privacy: str = "private",
    playlist_id: str = "",
    channel_pks: list[int] | None = None,
    owner: OwnerId = None,
) -> tuple[Playlist, int]:
    """Create or adopt a playlist and link the channels that will fill it."""
    if source == "existing":
        playlist = add_existing(session, playlist_id, http, owner)
    elif source == "generic":
        playlist = create_generic(session, title, owner)
    else:
        playlist = create(session, title, http, privacy=privacy, owner=owner)

    linked = 0
    for channel_pk in channel_pks or []:
        try:
            set_membership(session, playlist, channel_pk, include=True)
            linked += 1
        except PlaylistError:
            continue  # a channel removed between opening the dialog and saving
    return playlist, linked


def _store(
    session: Session, playlist_id: str, title: str, owner: OwnerId = None
) -> Playlist:
    playlist = Playlist(playlist_id=playlist_id, title=title or playlist_id, owner_pk=owner)
    session.add(playlist)
    session.flush()
    ordering.append(session, playlist)
    return playlist


def rename(session: Session, playlist: Playlist, title: str, http: httpx.Client) -> bool:
    """Retitle a feed, and the playlist behind it where there is one.

    Returns True if YouTube was updated too. A generic feed has nothing to
    update; for the rest, the local name still changes even when the call
    cannot be made, so the two only drift when YouTube refuses.
    """
    title = (title or "").strip()
    if not title:
        raise PlaylistError("Give the feed a name.")
    if title == playlist.title:
        return False

    playlist.title = title
    session.flush()

    if playlist.is_generic:
        return False

    from . import quota
    from ..youtube.api import QUOTA_COST_INSERT

    client = build_client(session, http, playlist.owner_pk)
    if not client.has_write_access:
        raise PlaylistError(
            f"Renamed here, but not on YouTube: no account is connected."
        )
    if not quota.can_afford(session, QUOTA_COST_INSERT, use_reserve=True):
        raise PlaylistError(
            "Renamed here, but not on YouTube: the daily API quota is spent."
        )
    try:
        client.rename_playlist(playlist.playlist_id, title)
    except YouTubeAPIError as exc:
        if exc.is_quota_error:
            quota.mark_exhausted(session)
        raise PlaylistError(f"Renamed here, but YouTube refused: {exc}") from exc
    return True


def set_enabled(session: Session, playlist: Playlist, *, enabled: bool) -> None:
    """Whether De-Algo keeps filling this feed. Nothing already in it moves."""
    playlist.enabled = enabled
    session.flush()


def set_tags(session: Session, playlist: Playlist, raw: str) -> list[str]:
    """Normalise free-form tags: comma separated, lowercase, deduped.

    Kept as plain text rather than a table — they are labels for searching,
    not entities anything else refers to.
    """
    seen: list[str] = []
    for piece in (raw or "").replace("\n", ",").split(","):
        tag = " ".join(piece.split()).lower()[:40]
        if tag and tag not in seen:
            seen.append(tag)
    playlist.tags = ", ".join(seen[:20]) or None
    session.flush()
    return seen


VIEW_ORDERS = ("oldest", "newest")
VIEW_SHOWS = ("unwatched", "all")


def set_view(session: Session, playlist: Playlist, *, order: str = "", show: str = "") -> None:
    """How this one feed is laid out on the watch page."""
    if order in VIEW_ORDERS:
        playlist.view_order = order
    if show in VIEW_SHOWS:
        playlist.view_show = show
    session.flush()


def unlink(session: Session, playlist: Playlist) -> str:
    """Cut a feed loose from its YouTube playlist, keeping the feed itself.

    Everything De-Algo holds stays — the name, channels, limits, fill order and
    the videos already in it — but nothing is written to YouTube again. The
    playlist over there is left exactly as it is, videos and all.

    Returns the YouTube id it was detached from.
    """
    if playlist.is_generic:
        raise PlaylistError(f"{playlist.title!r} has no YouTube playlist to unlink.")

    was = playlist.playlist_id
    playlist.playlist_id = f"{GENERIC_PLAYLIST_PREFIX}{uuid4().hex[:16]}"
    session.flush()

    # Those item ids point at rows in a playlist De-Algo no longer manages, so
    # restate them as this feed's own rather than leaving stale references.
    for placement in session.scalars(
        select(Placement).where(
            Placement.playlist_pk == playlist.id, Placement.playlist_item_id.is_not(None)
        )
    ):
        placement.playlist_item_id = f"generic-{playlist.id}-{placement.video_pk}"
    session.flush()
    return was


def update(session: Session, playlist: Playlist, form: Mapping[str, str]) -> Playlist:
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
