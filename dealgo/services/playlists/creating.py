"""Making a feed: one that lives here, or one backed by a playlist on the
publishing plugin's service."""

from __future__ import annotations

from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import GENERIC_PLAYLIST_PREFIX, Playlist
from ...plugins.publisher import PublishError, names
from .. import ordering
from ..connections import build_client
from ..scope import OwnerId, owned
from .listing import PlaylistError
from .membership import set_membership


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
        raise PlaylistError(f"Connect a {names().service} account first.")
    try:
        info = client.get_playlist(playlist_id)
    except PublishError as exc:
        raise PlaylistError(f"{names().publisher} refused: {exc}") from exc
    if info is None:
        raise PlaylistError("That playlist could not be found on your account.")
    return store_feed(session, info.playlist_id, info.title, owner)


PRIVACY_CHOICES = ("private", "unlisted", "public")


def create_generic(session: Session, title: str, owner: OwnerId = None) -> Playlist:
    """A generic feed: no playlist behind it, so no quota and no account."""
    title = (title or "").strip()
    if not title:
        raise PlaylistError("Give the feed a name.")
    return store_feed(session, f"{GENERIC_PLAYLIST_PREFIX}{uuid4().hex[:16]}", title, owner)


def create(
    session: Session,
    title: str,
    http: httpx.Client,
    *,
    privacy: str = "private",
    owner: OwnerId = None,
) -> Playlist:
    """Make a playlist on the connected account and a feed filling it."""
    title = (title or "").strip()
    if not title:
        raise PlaylistError("Give the new playlist a name.")
    if privacy not in PRIVACY_CHOICES:
        privacy = "private"

    client = build_client(session, http, owner)
    if not client.has_write_access:
        raise PlaylistError(f"Connect a {names().service} account first.")
    try:
        info = client.create_playlist(
            title,
            description="Built by Pamphlets from the channels you chose.",
            privacy=privacy,
        )
    except PublishError as exc:
        raise PlaylistError(f"{names().publisher} refused: {exc}") from exc
    return store_feed(session, info.playlist_id, info.title, owner)


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


def store_feed(
    session: Session, playlist_id: str, title: str, owner: OwnerId = None
) -> Playlist:
    """Save a feed for a playlist id, at the end of the fill order."""
    playlist = Playlist(playlist_id=playlist_id, title=title or playlist_id, owner_pk=owner)
    session.add(playlist)
    session.flush()
    ordering.append(session, playlist)
    return playlist
