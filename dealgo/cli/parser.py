"""The command line's grammar."""

from __future__ import annotations

import argparse

from .. import __version__
from ..config import CONFIG
from .backups import cmd_export
from .serving import cmd_serve
from .sources import cmd_add, cmd_channels
from .status import cmd_status
from .syncing import cmd_sync
from .watching import cmd_remove_watched, cmd_watched


def build_parser() -> argparse.ArgumentParser:
    """The command line: one subcommand per `cmd_*` function."""
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
    add.add_argument(
        "reference",
        help="a YouTube @handle, URL or UC… id; an r/community; a Bluesky handle; or a feed address",
    )
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
