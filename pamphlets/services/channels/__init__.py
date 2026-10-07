"""Adding and editing the sources this account watches.

Called channels throughout because that is what they were when there was only
YouTube, and renaming a table is a worse idea than a name that has grown.
"""

from __future__ import annotations

from .adding import BACKFILL_CHOICES, add_source, parse_backfill
from .listing import ChannelError, delete_channel, list_channels
from .switches import default_left_out, set_take

__all__ = [
    "add_source",
    "BACKFILL_CHOICES",
    "ChannelError",
    "delete_channel",
    "list_channels",
    "parse_backfill",
    "default_left_out",
    "set_take",
]
