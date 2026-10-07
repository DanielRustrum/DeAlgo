"""Command line entry point: `pamphlets`, or `python -m pamphlets`.

`pamphlets` with no arguments serves the web GUI; the subcommands, in pamphlets/cli,
exist so the same container can be driven headlessly from cron or a shell.
"""

from __future__ import annotations

from .cli import build_parser


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run the command; `serve` when none is given."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args = parser.parse_args(["serve"])
    exit_code: int = args.func(args)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
