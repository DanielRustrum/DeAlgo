"""The Configuration canvas: what is wired to what.

The graph is the truth about routing. A video leaves a source node, follows
wires, and lands in every feed node it can reach — narrowed on the way by any
filter node it passes through.

Three rules make it comprehensible:

* **A channel's own filters are the default.** They apply on every path out of
  that channel, exactly as they did before there was a graph.
* **A filter node overrides, it does not replace.** Anything it leaves unset
  stays whatever the channel said. So a channel can take long videos
  everywhere except down one particular wire, without its settings being
  duplicated.
* **A box says on the canvas what it does.** A Filter narrows by the condition
  pieces slotted under it, one piece per condition, and a Sort orders by the
  Order piece under it. The rules sat in the boxes' own popovers once, which
  meant a canvas of boxes all reading "Filter" and no way to tell them apart
  without opening each one. A condition that is a fact about one service —
  whether a video is a Short — is declared by the plugin that knows what
  those words mean, and slots under the same Filter as the app's own.

Existing setups are turned into a graph the first time one is asked for, so
nobody has to build theirs again.

Every wire is a ``GraphEdge``, and an edge belongs to the box it was drawn
from. A source's used to be stored against its *channel* instead, which meant
two boxes for one channel could not be told apart: wiring either drew a wire
from both, and unwiring either unwired both. A second box is a second box.

``channel.playlists`` — what the feed page, the backup and the sync engine
read — is a view of those wires, worked out again whenever they change. One
writer, so the two cannot disagree.
"""

from __future__ import annotations

from .adding import (
    add_feed,
    add_filter,
    add_format,
    add_text_box,
    add_transform,
    add_pamphlet,
    add_piece,
    add_sort,
    add_source,
    add_stamp,
    add_store,
    add_trigger,
    attach_channel,
)
from .canvas import TRIGGER_COLUMN, TRIGGER_GAP, load
from .conditions import CONDITION_KINDS, DEFAULT_SORT_BY, RULE, SORT_KEYS, check_sort_key, condition
from .cron import check_cron, cron_trigger
from .editing import move, remove, rename, stands_alone
from .errors import GraphError
from .groups import (
    GroupUpdate,
    add_group,
    export_group,
    import_group,
    inside,
    lock,
    move_group,
    resize,
    update_group,
)
from .names import store_name, tag_name, tag_names
from . import formatting, leaflets
from .leaflets import LEAFLET_KINDS
from .pieces import attach, detach, host_boxes, host_of, hosts_for, pieces_of, pieces_under
from .reading import channels_of, edges, nodes
from .report import Judged, filter_report
from .routes import Route, paths_from, routes
from .stamps import stamped_after_watch, stamped_life, stamped_locked, stamped_seconds, stamped_tags
from .trial import Trial, try_it
from .triggers import (
    When,
    due_withdrawals,
    polling_plan,
    pulse_targets,
    wired_sources,
    wired_withdrawals,
)
from .units import (
    DEFAULT_CRON,
    DEFAULT_DURATION_MINUTES,
    DEFAULT_EVERY_MINUTES,
    EVERY_UNITS,
    LENGTH_UNITS,
    clock_time,
    every_minutes_from,
    every_words,
    seconds_from,
    split_every,
    split_length,
)
from .vocabulary import AUGMENTATIONS, BOX_NAMES, GROUP_SIZE, SLOTTED, STAMPS, TRIGGER_KINDS
from .windows import begin_sitting, consumption, is_open, window_state
from .wiring import connect, disconnect, only_data, wires
from .words import condition_words, piece_note, piece_words, stamp_words, window_words

__all__ = [
    "add_feed",
    "add_filter",
    "add_group",
    "add_format",
    "add_text_box",
    "add_transform",
    "only_data",
    "add_pamphlet",
    "add_piece",
    "add_sort",
    "add_source",
    "add_stamp",
    "add_store",
    "add_trigger",
    "attach",
    "formatting",
    "leaflets",
    "LEAFLET_KINDS",
    "attach_channel",
    "AUGMENTATIONS",
    "begin_sitting",
    "BOX_NAMES",
    "channels_of",
    "check_cron",
    "check_sort_key",
    "clock_time",
    "condition",
    "CONDITION_KINDS",
    "condition_words",
    "connect",
    "consumption",
    "cron_trigger",
    "DEFAULT_CRON",
    "DEFAULT_DURATION_MINUTES",
    "DEFAULT_EVERY_MINUTES",
    "DEFAULT_SORT_BY",
    "detach",
    "disconnect",
    "due_withdrawals",
    "edges",
    "every_minutes_from",
    "EVERY_UNITS",
    "every_words",
    "export_group",
    "filter_report",
    "GraphError",
    "GROUP_SIZE",
    "host_boxes",
    "host_of",
    "hosts_for",
    "import_group",
    "inside",
    "is_open",
    "Judged",
    "LENGTH_UNITS",
    "load",
    "move",
    "GroupUpdate",
    "lock",
    "update_group",
    "move_group",
    "nodes",
    "paths_from",
    "piece_note",
    "piece_words",
    "pieces_of",
    "pieces_under",
    "polling_plan",
    "pulse_targets",
    "remove",
    "rename",
    "resize",
    "Route",
    "routes",
    "RULE",
    "seconds_from",
    "SLOTTED",
    "SORT_KEYS",
    "split_every",
    "split_length",
    "stamp_words",
    "stamped_after_watch",
    "stamped_life",
    "stamped_locked",
    "stamped_seconds",
    "stamped_tags",
    "STAMPS",
    "stands_alone",
    "store_name",
    "tag_name",
    "tag_names",
    "Trial",
    "TRIGGER_COLUMN",
    "TRIGGER_GAP",
    "TRIGGER_KINDS",
    "try_it",
    "When",
    "window_state",
    "window_words",
    "wired_sources",
    "wired_withdrawals",
    "wires",
]
