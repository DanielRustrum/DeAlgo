"""Command line entry point.

``dealgo`` (no arguments) serves the web GUI; the subcommands exist so the same
container can be driven headlessly from cron or a shell.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import httpx

from . import __version__
from .config import CONFIG
from .db import get_settings, init_db, session_scope
from .services import channels as channel_service
from .services import backup as backup_service
from .services import playlists as playlist_service
from .services import quota as quota_service
from .services import watched as watched_service
from .services.sync import HTTP_TIMEOUT, USER_AGENT, run_sync
from .models import Video
from sqlalchemy import select


def _configure_logging() -> None:
    logging.basicConfig(
        level=CONFIG.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "dealgo.web.app:app",
        host=args.host,
        port=args.port,
        log_level=CONFIG.log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    _configure_logging()
    init_db()
    result = run_sync(trigger="cli", force=getattr(args, "force", False))
    print(
        f"channels={result.channels_checked} waiting={result.channels_waiting} "
        f"new={result.discovered} added={result.added} "
        f"skipped={result.skipped} failed={result.failed} pruned={result.pruned} "
        f"quota={result.quota_spent}"
    )
    if result.message:
        print(result.message)
    return 0 if result.ok else 1


def cmd_add(args: argparse.Namespace) -> int:
    _configure_logging()
    init_db()
    with session_scope() as session:
        with httpx.Client(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as http:
            try:
                channel = channel_service.add_channel(session, args.reference, http)
            except channel_service.ChannelError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            print(f"watching {channel.title} ({channel.channel_id})")
    return 0


def cmd_watched(args: argparse.Namespace) -> int:
    """Mark videos watched by video id or URL, so they can be removed later."""
    _configure_logging()
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
    _configure_logging()
    init_db()
    result = watched_service.remove_watched(trigger="cli")
    print(f"removed={result.removed} already-gone={result.missing} failed={result.failed}")
    if result.message:
        print(result.message)
    return 0 if result.ok else 1


def cmd_export(args: argparse.Namespace) -> int:
    """The same JSON the Settings page downloads, for scripted backups."""
    init_db()
    with session_scope() as session:
        data = backup_service.build_export(session)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        counts = data["counts"]
        print(f"wrote {args.output}: {counts['feeds']} feed(s), {counts['channels']} channel(s)")
    else:
        print(text)
    return 0


def cmd_channels(_args: argparse.Namespace) -> int:
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


def cmd_status(_args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        settings = get_settings(session)
        print(f"De-Algo {__version__}")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dealgo", description="A YouTube feed that is yours, not the algorithm's.")
    parser.add_argument("--version", action="version", version=f"dealgo {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the web GUI (default)")
    serve.add_argument("--host", default=CONFIG.host)
    serve.add_argument("--port", type=int, default=CONFIG.port)
    serve.set_defaults(func=cmd_serve)

    sync = sub.add_parser("sync", help="run a single sync pass and exit")
    sync.add_argument(
        "--force",
        action="store_true",
        help="poll every channel, ignoring each channel's minimum gap",
    )
    sync.set_defaults(func=cmd_sync)

    add = sub.add_parser("add", help="watch a channel")
    add.add_argument("reference", help="channel URL, @handle, or UC… id")
    add.set_defaults(func=cmd_add)

    export = sub.add_parser("export", help="write a JSON backup of the setup")
    export.add_argument("-o", "--output", help="file to write (default: stdout)")
    export.set_defaults(func=cmd_export)

    watched = sub.add_parser("watched", help="mark videos as watched")
    watched.add_argument("videos", nargs="+", help="video ids or watch URLs")
    watched.set_defaults(func=cmd_watched)

    remove_watched = sub.add_parser(
        "remove-watched", help="remove watched videos from the playlist"
    )
    remove_watched.set_defaults(func=cmd_remove_watched)

    channels = sub.add_parser("channels", help="list watched channels")
    channels.set_defaults(func=cmd_channels)

    status = sub.add_parser("status", help="show configuration")
    status.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args = parser.parse_args(["serve"])
    exit_code: int = args.func(args)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
