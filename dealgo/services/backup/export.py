"""One account's setup as portable JSON."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ... import __version__
from ...db import get_settings
from ...models import Channel, Playlist
from ..scope import OwnerId, owned

# Bumped if the shape changes in a way a reader would need to know about.
FORMAT_VERSION = 1


def _stamp(value: dt.datetime | None) -> str | None:
    """Naive UTC in the database becomes an explicit UTC instant on the way out."""
    if value is None:
        return None
    return value.replace(tzinfo=dt.timezone.utc).isoformat()


def filename(now: dt.datetime | None = None) -> str:
    """The download's name: `de-algo-backup-YYYY-MM-DD.json`."""
    moment = now or dt.datetime.now(dt.timezone.utc)
    return f"de-algo-backup-{moment:%Y-%m-%d}.json"


def build_export(session: Session, owner: OwnerId = None) -> dict[str, Any]:
    """The setup: settings, feeds, channels, and which feeds each channel fills."""
    settings = get_settings(session)

    exported: dict[str, Any] = {
        "de_algo_backup": FORMAT_VERSION,
        "app_version": __version__,
        "exported_at": _stamp(dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)),
        "settings": {
            "auto_sync": settings.auto_sync,
            "poll_interval_minutes": settings.poll_interval_minutes,
            "initial_backfill": settings.initial_backfill,
            "shorts_max_seconds": settings.shorts_max_seconds,
        },
    }

    playlists = list(
        session.scalars(
            owned(select(Playlist), Playlist, owner)
            .options(selectinload(Playlist.channels))
            .order_by(Playlist.priority, Playlist.id)
        )
    )
    exported["feeds"] = [
        {
            "playlist_id": playlist.playlist_id,
            "title": playlist.title,
            "enabled": playlist.enabled,
            "priority": playlist.priority,
            "max_items": playlist.max_items,
            "max_per_run": playlist.max_per_run,
            "channels": sorted(channel.channel_id for channel in playlist.channels),
        }
        for playlist in playlists
    ]

    channels = list(
        session.scalars(
            owned(select(Channel), Channel, owner)
            .options(selectinload(Channel.playlists))
            .order_by(Channel.priority, Channel.id)
        )
    )
    exported["channels"] = [
        {
            "channel_id": channel.channel_id,
            "title": channel.title,
            "handle": channel.handle,
            "enabled": channel.enabled,
            "priority": channel.priority,
            "min_pull_minutes": channel.min_pull_minutes,
            "max_per_run": channel.max_per_run,
            "skip_videos": channel.skip_videos,
            "skip_shorts": channel.skip_shorts,
            "skip_live": channel.skip_live,
            "title_include": channel.title_include,
            "title_exclude": channel.title_exclude,
            "min_duration_sec": channel.min_duration_sec,
            "max_duration_sec": channel.max_duration_sec,
            "added_at": _stamp(channel.added_at),
            "last_checked_at": _stamp(channel.last_checked_at),
            "feeds": sorted(playlist.playlist_id for playlist in channel.playlists),
        }
        for channel in channels
    ]

    exported["counts"] = {
        "feeds": len(exported["feeds"]),
        "channels": len(exported["channels"]),
    }
    return exported
