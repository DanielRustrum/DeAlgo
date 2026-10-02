"""Managing the set of playlists De-Algo keeps filled.
"""

from __future__ import annotations

from .creating import create_generic, set_up_feed
from .editing import remove, rename, set_enabled, set_tags, set_view, unlink, update
from .listing import PlaylistError, item_counts, list_playlists
from .membership import set_membership

__all__ = [
    "PlaylistError",
    "create_generic",
    "item_counts",
    "list_playlists",
    "remove",
    "rename",
    "set_enabled",
    "set_membership",
    "set_tags",
    "set_up_feed",
    "set_view",
    "unlink",
    "update",
]
