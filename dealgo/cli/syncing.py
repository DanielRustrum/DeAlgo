"""`dealgo sync`: one pass for every account, then exit."""

from __future__ import annotations

import argparse

from ..db import init_db, session_scope
from ..services.sync import (
    SyncResult,
    owners_with_channels,
    run_for_everyone,
    run_sync,
)
from .logs import configure_logging


def _owners() -> list[int | None]:
    with session_scope() as session:
        return owners_with_channels(session)


def _combined(results: list[SyncResult]) -> SyncResult:
    """One line for a run that covered several accounts."""
    total = SyncResult(ok=all(one.ok for one in results))
    for one in results:
        total.channels_checked += one.channels_checked
        total.channels_waiting += one.channels_waiting
        total.discovered += one.discovered
        total.added += one.added
        total.skipped += one.skipped
        total.failed += one.failed
        total.pruned += one.pruned
        total.quota_spent += one.quota_spent
    return total


def cmd_sync(args: argparse.Namespace) -> int:
    configure_logging()
    init_db()
    # The command line belongs to no account in particular, so it syncs every
    # one that has channels — each with its own credentials and quota.
    if getattr(args, "force", False):
        results = [run_sync(trigger="cli", force=True, owner=owner)
                   for owner in _owners()]
    else:
        results = run_for_everyone(trigger="cli")
    result = results[0] if len(results) == 1 else _combined(results)
    print(
        f"channels={result.channels_checked} waiting={result.channels_waiting} "
        f"new={result.discovered} added={result.added} "
        f"skipped={result.skipped} failed={result.failed} pruned={result.pruned} "
        f"quota={result.quota_spent}"
    )
    if result.message:
        print(result.message)
    return 0 if result.ok else 1
