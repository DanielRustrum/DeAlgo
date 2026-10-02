"""Adding and editing the sources this account watches.

Called channels throughout because that is what they were when there was only
YouTube, and renaming a table is a worse idea than a name that has grown.
"""

from __future__ import annotations

from .adding import BACKFILL_CHOICES, add_source, parse_backfill
from .listing import ChannelError, delete_channel, list_channels
from .switches import POST_REASON, set_live, set_posts, set_shorts, set_videos

__all__ = [
    "BACKFILL_CHOICES",
    "ChannelError",
    "POST_REASON",
    "add_source",
    "delete_channel",
    "list_channels",
    "parse_backfill",
    "set_live",
    "set_posts",
    "set_shorts",
    "set_videos",
]
