"""`pamphlets watched` and `pamphlets remove-watched`."""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from ..db import init_db, session_scope
from ..models import Video
from ..services import watched as watched_service
from .logs import configure_logging


def cmd_watched(args: argparse.Namespace) -> int:
    """Mark videos watched by video id or URL, so they can be removed later."""
    configure_logging()
    init_db()
    wanted = {ref.rsplit("/", 1)[-1].split("v=")[-1].split("&")[0] for ref in args.videos}
    with session_scope() as session:
        videos = list(session.scalars(select(Video).where(Video.video_id.in_(wanted))))
        found = {v.video_id for v in videos}
        changed = watched_service.mark_watched(session, [v.id for v in videos])
        for missing in sorted(wanted - found):
            print(f"not tracked: {missing}", file=sys.stderr)
    print(f"marked {changed} video(s) watched")
    return 0 if found else 1


def cmd_remove_watched(_args: argparse.Namespace) -> int:
    """`pamphlets remove-watched`: take watched items out of their feeds."""
    configure_logging()
    init_db()
    result = watched_service.remove_watched(trigger="cli")
    print(f"removed={result.removed} already-gone={result.missing} failed={result.failed}")
    if result.message:
        print(result.message)
    return 0 if result.ok else 1
