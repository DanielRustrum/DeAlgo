"""What a plugin is handed: one object per permission it was granted.

A plugin begins with nothing: pure Lua, no clock, no network, no way to leave
a mark. What it is granted is simply what gets put in its environment — a
plugin without the network permission does not find a locked door, it finds
no door.

Each capability is built fresh per plugin, so one cannot reach another's, and
each carries its own ceiling. The point is not that a plugin is trusted once
granted — it is that the worst it can do with a grant is bounded and said out
loud beforehand.
"""

from __future__ import annotations

from .account import Account
from .clock import Clock
from .grant import granted_to
from .log import Log
from .net import Net
from .owner import acting_for, whose
from .settings import PluginSettings
from .site import Site

__all__ = [
    "Account",
    "acting_for",
    "Clock",
    "granted_to",
    "Log",
    "Net",
    "PluginSettings",
    "Site",
    "whose",
]
