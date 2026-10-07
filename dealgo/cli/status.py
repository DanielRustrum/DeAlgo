"""`dealgo status`: what this instance is configured with."""

from __future__ import annotations

import argparse

from .. import __version__
from ..config import CONFIG
from ..db import get_settings, init_db, session_scope
from ..services import playlists as playlist_service
from ..services import quota as quota_service


def cmd_status(_args: argparse.Namespace) -> int:
    """`dealgo status`: print the configuration, feeds and today's quota."""
    init_db()
    with session_scope() as session:
        settings = get_settings(session)
        print(f"Pamphlets {__version__}")
        print(f"database:  {CONFIG.database_url}")
        targets = playlist_service.list_playlists(session)
        if targets:
            counts = playlist_service.item_counts(session)
            for playlist in targets:
                state = "" if playlist.enabled else " (paused)"
                print(
                    f"playlist:  {playlist.title}{state} — {counts.get(playlist.id, 0)} videos, "
                    f"{len(playlist.channels)} channel(s)"
                )
        else:
            print("playlist:  none set")
        print(f"auto sync: {'every %d min' % settings.poll_interval_minutes if settings.auto_sync else 'off'}")
        quota_state = quota_service.state(session)
        note = " (exhausted)" if quota_state.exhausted else ""
        print(
            f"quota:     {quota_state.used}/{quota_state.budget} units used{note}, "
            f"resets {quota_service.describe_reset()}"
        )
    return 0
