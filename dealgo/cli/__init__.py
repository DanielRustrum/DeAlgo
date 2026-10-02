"""The command line's commands, one module per subject.

`dealgo` with no arguments serves the web GUI; the subcommands exist so the
same container can be driven headlessly from cron or a shell.
"""

from __future__ import annotations

from .parser import build_parser

__all__ = [
    "build_parser",
]
