"""The sync engine: poll feeds, filter, and push new uploads into the playlist.

One run is a single pass over every enabled channel. It is deliberately
restartable — every decision is written to the database as it is made, so a
crash mid-run costs at most the videos still in flight, and nothing is ever
added twice.
"""

from __future__ import annotations

from .deciding import decide, plugin_refusal, plugin_settings
from .filing import MAX_INSERT_ATTEMPTS
from .lock import Busy, is_running, playlist_lock
from .ordering import ordering_value
from .pictures import repair_stored_pictures, repair_stored_pictures_now
from .progress import RunProgress, claim, note, note_placed, note_polled, progress
from .reasons import TOO_OLD, WRONG_KIND_OF_FEED
from .repositories import waiting_in
from .result import SyncResult
from .run import owners_with_channels, run_for_everyone, run_sync
from .withdrawing import withdraw_now

__all__ = [
    "Busy",
    "MAX_INSERT_ATTEMPTS",
    "RunProgress",
    "SyncResult",
    "TOO_OLD",
    "WRONG_KIND_OF_FEED",
    "decide",
    "note",
    "note_placed",
    "note_polled",
    "plugin_refusal",
    "plugin_settings",
    "claim",
    "is_running",
    "ordering_value",
    "owners_with_channels",
    "playlist_lock",
    "progress",
    "repair_stored_pictures",
    "repair_stored_pictures_now",
    "run_for_everyone",
    "run_sync",
    "waiting_in",
    "withdraw_now",
]
