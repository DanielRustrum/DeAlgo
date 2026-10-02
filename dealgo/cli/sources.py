"""`dealgo add` and `dealgo channels`: watching a source, and listing them."""

from __future__ import annotations

import argparse
import sys

from .. import outgoing
from ..db import init_db, session_scope
from ..services import channels as channel_service
from .logs import configure_logging


def cmd_add(args: argparse.Namespace) -> int:
    """`dealgo add REFERENCE`: watch a source. Exits 1 if it could not be added."""
    configure_logging()
    init_db()
    with session_scope() as session:
        with outgoing.client() as http:
            try:
                channel = channel_service.add_source(session, args.reference, http)
            except channel_service.ChannelError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            print(f"watching {channel.title} ({channel.channel_id})")
    return 0


def cmd_channels(_args: argparse.Namespace) -> int:
    """`dealgo channels`: list the watched sources and whether each is paused."""
    init_db()
    with session_scope() as session:
        rows = channel_service.list_channels(session)
        if not rows:
            print("no channels are being watched")
            return 0
        for channel in rows:
            state = "watching" if channel.enabled else "paused  "
            targets = ", ".join(p.title for p in channel.playlists) or "no playlist"
            print(f"{channel.priority + 1:>3}. {state}  {channel.title}  → {targets}")
    return 0
