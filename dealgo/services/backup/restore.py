"""Applying a backup, matching what is already here by the services' own ids."""

from __future__ import annotations

import base64
import binascii
import json

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_settings
from ...models import Channel, Placement, Playlist, Video
from ..scope import OwnerId, owned
from ..theming import store as themes
from ..theming import images as theme_images
from ..theming.theme import ThemeError, parse as parse_theme
from .export import FORMAT_VERSION


class RestoreError(RuntimeError):
    """The file is not a backup this version can read."""

    pass


@dataclass
class RestoreSummary:
    """What a restore made or updated, counted."""

    feeds: int = 0
    channels: int = 0
    videos: int = 0
    placements: int = 0
    skipped: list[str] = field(default_factory=list)
    #: Whether the file carried a theme and it was used; None when it had none.
    theme: bool | None = None
    #: Theme pictures in the file that did not pass the checks an upload does.
    pictures_refused: list[str] = field(default_factory=list)

    def describe(self) -> str:
        """The summary as one sentence for the person who restored it."""
        parts = [
            f"{self.feeds} feed{'s' if self.feeds != 1 else ''}",
            f"{self.channels} channel{'s' if self.channels != 1 else ''}",
        ]
        if self.videos:  # only an older file carries these
            parts.append(f"{self.videos} video{'s' if self.videos != 1 else ''}")
        sentence = "Restored " + ", ".join(parts)
        if self.theme:
            sentence += ", and your theme"
        elif self.theme is False:
            sentence += ". The theme in the file could not be used"
        sentence += "."
        if self.pictures_refused:
            sentence += (
                " Left out the " + " and ".join(self.pictures_refused)
                + " picture" + ("s" if len(self.pictures_refused) > 1 else "")
                + ", which did not pass the checks an upload does."
            )
        return sentence


def _parse_stamp(value: str | None) -> dt.datetime | None:
    """ISO instants come back as the naive UTC the database stores."""
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def restore(session: Session, payload: Any, owner: OwnerId = None) -> RestoreSummary:
    """Apply a backup, matching existing rows by their YouTube ids.

    The file is the source of truth: anything it names is created or updated to
    match. Nothing is deleted, so restoring onto a live install adds to it
    rather than replacing it — and the OAuth grant is never touched, because a
    backup never carries one.
    """
    _check(payload)
    summary = RestoreSummary()
    _restore_settings(session, payload)
    playlists = _restore_feeds(session, payload, owner, summary)
    channels = _restore_channels(session, payload, owner, playlists, summary)
    _restore_videos(session, payload, owner, channels, playlists, summary)
    _restore_theme(session, payload, owner, summary)
    return summary


def _check(payload: Any) -> None:
    """Raise `RestoreError` unless this is a backup of a format this version reads."""
    if not isinstance(payload, dict) or "de_algo_backup" not in payload:
        raise RestoreError("That is not a De-Algo backup file.")
    version = payload.get("de_algo_backup")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise RestoreError(
            f"This backup is format {version}, but this version of De-Algo reads {FORMAT_VERSION}."
        )


def _restore_settings(session: Session, payload: dict[str, Any]) -> None:
    """Lay the file's settings over the stored ones.

    Writes the implicit owner's settings whatever account restores — see Known Issues.
    """
    settings = get_settings(session)
    for key, value in (payload.get("settings") or {}).items():
        if hasattr(settings, key) and key not in ("id", "updated_at"):
            setattr(settings, key, value)


def _restore_theme(
    session: Session, payload: dict[str, Any], owner: OwnerId, summary: RestoreSummary
) -> None:
    """The file's theme and pictures, when it has them, checked like any import.

    One that does not read is left out rather than failing the restore: the
    feeds and channels are what a backup is for.
    """
    # Its pictures are checked as hard as an upload: a backup is only a file.
    for slot, entry in (payload.get("theme_pictures") or {}).items():
        if slot not in theme_images.ALL_SLOTS or not isinstance(entry, dict):
            continue
        try:
            raw = base64.b64decode(str(entry.get("data", "")), validate=True)
            themes.put_picture(session, owner, slot, theme_images.accept_for(slot, raw))
        except (binascii.Error, theme_images.ImageError):
            summary.pictures_refused.append(theme_images.ALL_SLOTS[slot].lower())
    if "theme" not in payload:
        return
    try:
        theme = parse_theme(payload["theme"])
    except ThemeError:
        summary.theme = False
        return
    themes.write(session, owner, theme)
    summary.theme = True


def _restore_feeds(
    session: Session, payload: dict[str, Any], owner: OwnerId, summary: RestoreSummary
) -> dict[str, Playlist]:
    """Every feed the file names, made or brought up to date, by playlist id."""
    from ...services import ordering  # local import: ordering imports models only

    playlists: dict[str, Playlist] = {}
    for entry in payload.get("feeds") or []:
        playlist_id = entry.get("playlist_id")
        if not playlist_id:
            continue
        playlist = session.scalar(
            owned(select(Playlist), Playlist, owner).where(Playlist.playlist_id == playlist_id)
        )
        if playlist is None:
            playlist = Playlist(owner_pk=owner, playlist_id=playlist_id, title=entry.get("title") or playlist_id)
            session.add(playlist)
            session.flush()
            ordering.append(session, playlist)
        playlist.title = entry.get("title") or playlist.title
        playlist.enabled = bool(entry.get("enabled", True))
        playlist.priority = int(entry.get("priority") or 0)
        playlist.max_items = int(entry.get("max_items") or 0)
        playlist.max_per_run = int(entry.get("max_per_run") or 0)
        playlists[playlist_id] = playlist
        summary.feeds += 1
    session.flush()
    return playlists


#: The source fields a backup carries as they are.
_CHANNEL_FIELDS = (
    "title", "handle", "enabled", "priority", "min_pull_minutes", "max_per_run",
    "title_include", "title_exclude",
    "min_duration_sec", "max_duration_sec",
)


def _left_out(entry: dict[str, Any]) -> list[str] | None:
    """Which kinds of content a source leaves out, as the file says.

    Files from before plugins declared them carried YouTube's three switches
    as `skip_*`; those names are the kinds' own, so they read across. None
    when the file says nothing, which leaves the source as it is.
    """
    given = entry.get("left_out")
    if isinstance(given, list):
        return sorted(str(one) for one in given)
    old = [name for name in ("videos", "shorts", "live", "posts") if entry.get(f"skip_{name}")]
    if any(f"skip_{name}" in entry for name in ("videos", "shorts", "live", "posts")):
        return old
    return None


def _restore_channels(
    session: Session,
    payload: dict[str, Any],
    owner: OwnerId,
    playlists: dict[str, Playlist],
    summary: RestoreSummary,
) -> dict[str, Channel]:
    """Every source the file names, and the feeds it fills, by channel id."""
    channels: dict[str, Channel] = {}
    for entry in payload.get("channels") or []:
        channel_id = entry.get("channel_id")
        if not channel_id:
            continue
        channel = session.scalar(
            owned(select(Channel), Channel, owner).where(Channel.channel_id == channel_id)
        )
        if channel is None:
            channel = Channel(owner_pk=owner, channel_id=channel_id, title=entry.get("title") or channel_id)
            session.add(channel)
            session.flush()
        for key in _CHANNEL_FIELDS:
            if key in entry:
                setattr(channel, key, entry[key])
        left_out = _left_out(entry)
        if left_out is not None:
            channel.left_out = json.dumps(left_out)
        # Only trust a last-checked time when the file also carries the videos
        # that check found. Without them the channel would look up to date and
        # its whole feed would count as new, dumping fifteen uploads at once;
        # left unset it is treated as never checked, so the backfill limit
        # applies as it does for a freshly added channel.
        channel.last_checked_at = (
            _parse_stamp(entry.get("last_checked_at")) if payload.get("videos") else None
        )
        channel.playlists = [
            playlists[pid] for pid in (entry.get("feeds") or []) if pid in playlists
        ]
        channels[channel_id] = channel
        summary.channels += 1
    session.flush()
    return channels


def _restore_videos(
    session: Session,
    payload: dict[str, Any],
    owner: OwnerId,
    channels: dict[str, Channel],
    playlists: dict[str, Playlist],
    summary: RestoreSummary,
) -> None:
    """The items an older file carries, and where each was placed."""
    for entry in payload.get("videos") or []:
        video_id = entry.get("video_id")
        channel = channels.get(entry.get("channel_id"))
        # An item whose source is not in the file has nowhere to belong; it is reported, not
        # restored.
        if not video_id or channel is None:
            if video_id:
                summary.skipped.append(video_id)
            continue

        video = session.scalar(
            owned(select(Video), Video, owner).where(Video.video_id == video_id)
        )
        if video is None:
            video = Video(owner_pk=owner, video_id=video_id, channel_pk=channel.id)
            session.add(video)
            session.flush()
        video.channel_pk = channel.id
        video.title = entry.get("title") or video.title
        video.published_at = _parse_stamp(entry.get("published_at"))
        video.duration_sec = entry.get("duration_sec")
        # Older files said whether an item was a Short; that is a hint now.
        video.hint = entry.get("hint") or ("shorts" if entry.get("is_short") else None)
        video.status = entry.get("status") or "pending"
        video.reason = entry.get("reason")
        video.watched_at = _parse_stamp(entry.get("watched_at"))
        summary.videos += 1

        _restore_placements(session, video, entry.get("placements") or [], playlists, summary)
        session.flush()


def _restore_placements(
    session: Session,
    video: Video,
    slots: list[Any],
    playlists: dict[str, Playlist],
    summary: RestoreSummary,
) -> None:
    """Where an older file says an item was placed, matched by playlist id."""
    for slot in slots:
        playlist = playlists.get(slot.get("playlist_id"))
        if playlist is None:
            continue
        placement = session.scalar(
            select(Placement).where(
                Placement.video_pk == video.id, Placement.playlist_pk == playlist.id
            )
        )
        if placement is None:
            placement = Placement(video_pk=video.id, playlist_pk=playlist.id)
            session.add(placement)
        placement.playlist_item_id = slot.get("playlist_item_id")
        placement.added_at = _parse_stamp(slot.get("added_at"))
        placement.removed_at = _parse_stamp(slot.get("removed_at"))
        summary.placements += 1
