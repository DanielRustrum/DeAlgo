"""Applying a backup, matching what is already here by the services' own ids."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_settings
from ...models import Channel, Placement, Playlist, Video
from ..scope import OwnerId, owned
from .export import FORMAT_VERSION


class RestoreError(RuntimeError):
    pass


@dataclass
class RestoreSummary:
    feeds: int = 0
    channels: int = 0
    videos: int = 0
    placements: int = 0
    skipped: list[str] = field(default_factory=list)

    def describe(self) -> str:
        parts = [
            f"{self.feeds} feed{'s' if self.feeds != 1 else ''}",
            f"{self.channels} channel{'s' if self.channels != 1 else ''}",
        ]
        if self.videos:  # only an older file carries these
            parts.append(f"{self.videos} video{'s' if self.videos != 1 else ''}")
        return "Restored " + ", ".join(parts) + "."


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
    if not isinstance(payload, dict) or "de_algo_backup" not in payload:
        raise RestoreError("That is not a De-Algo backup file.")
    version = payload.get("de_algo_backup")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise RestoreError(
            f"This backup is format {version}, but this version of De-Algo reads {FORMAT_VERSION}."
        )

    summary = RestoreSummary()
    from ...services import ordering  # local import: ordering imports models only

    settings = get_settings(session)
    for key, value in (payload.get("settings") or {}).items():
        if hasattr(settings, key) and key not in ("id", "updated_at"):
            setattr(settings, key, value)

    for key, value in (payload.get("credentials") or {}).items():
        if key in ("client_id", "client_secret", "api_key") and value:
            setattr(settings, key, value)

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

    channels: dict[str, Channel] = {}
    simple = (
        "title", "handle", "enabled", "priority", "min_pull_minutes", "max_per_run",
        "skip_videos", "skip_shorts", "skip_live", "title_include", "title_exclude",
        "min_duration_sec", "max_duration_sec",
    )
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
        for key in simple:
            if key in entry:
                setattr(channel, key, entry[key])
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

    for entry in payload.get("videos") or []:
        video_id = entry.get("video_id")
        channel = channels.get(entry.get("channel_id"))
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
        video.is_short = bool(entry.get("is_short"))
        video.status = entry.get("status") or "pending"
        video.reason = entry.get("reason")
        video.watched_at = _parse_stamp(entry.get("watched_at"))
        summary.videos += 1

        for slot in entry.get("placements") or []:
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
        session.flush()

    return summary
