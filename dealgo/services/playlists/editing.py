"""Renaming, switching, tagging, showing, unlinking and removing a feed."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import GENERIC_PLAYLIST_PREFIX, Placement, Playlist
from ...plugins.publisher import PublishError
from ..auth import build_client
from .listing import PlaylistError


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

    from ...plugins.publisher import cost_of
    from .. import quota

    client = build_client(session, http, playlist.owner_pk)
    if not client.has_write_access:
        raise PlaylistError(
            "Renamed here, but not on YouTube: no account is connected."
        )
    if not quota.can_afford(session, cost_of("add"), use_reserve=True):
        raise PlaylistError(
            "Renamed here, but not on YouTube: the daily API quota is spent."
        )
    try:
        client.rename_playlist(playlist.playlist_id, title)
    except PublishError as exc:
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
