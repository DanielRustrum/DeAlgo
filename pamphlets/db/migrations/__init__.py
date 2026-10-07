"""Every change to the schema since the first release.

`create_all` only makes missing tables, so everything else an existing
database needs is done here, by hand, on every start. Each step looks at the
database first and does nothing if it is already done, so running them all
again is always safe. `startup.init_db` says the order, which matters.
"""

from __future__ import annotations

from .columns import add_missing_columns, drop_removed_columns
from .connections import youtube_becomes_a_plugin, youtube_takes_become_declared
from .feeds import migrate_single_playlist, rename_local_feed_prefix
from .edges import rebuild_edge_uniqueness, rest_sources_give_data, wires_say_what_they_carry
from .pieces import (
    after_watching_is_its_own_condition,
    feed_windows_become_pieces,
    leaflets_are_wired_to_their_feeds,
    plugin_boxes_become_pieces,
    rules_become_pieces,
)
from .uniqueness import rebuild_video_uniqueness, scope_uniqueness_to_owners
from .wires import retire_tag_nodes, wires_belong_to_boxes

__all__ = [
    "rebuild_edge_uniqueness",
    "rest_sources_give_data",
    "wires_say_what_they_carry",
    "after_watching_is_its_own_condition",
    "leaflets_are_wired_to_their_feeds",
    "add_missing_columns",
    "drop_removed_columns",
    "feed_windows_become_pieces",
    "migrate_single_playlist",
    "plugin_boxes_become_pieces",
    "rebuild_video_uniqueness",
    "rename_local_feed_prefix",
    "retire_tag_nodes",
    "rules_become_pieces",
    "scope_uniqueness_to_owners",
    "wires_belong_to_boxes",
    "youtube_becomes_a_plugin",
    "youtube_takes_become_declared",
]
