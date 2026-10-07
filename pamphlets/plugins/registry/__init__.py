"""What plugins there are, what each one offers, and what went wrong.

A plugin is a folder of its own — ``<id>/plugin.lua`` — in the shipped
plugins folder or in the data folder's. This reads them all on start, judges
what each returned, and keeps the ones that make sense — with a note against
the ones that do not, because a plugin that quietly fails to load is worse
than one that says why. Its id is its folder's name, never anything its file
says about itself.

Nothing is thrown away on a bad plugin. A file that will not parse, or comes
back without the fields it needs, becomes a row on the Admin page saying so;
the rest of the app carries on with the plugins that did load.

Held in memory and rebuilt on demand rather than stored: the folder is the
truth, and a registry that could disagree with it would be a second place to
look when something is missing.
"""

from __future__ import annotations

from ..runtime import PluginError
from .current import current, forget, reload
from .decisions import origins, paused_ids, set_granted, set_origin, set_paused
from .offers import Registry
from .reading import judge, read
from . import storage
from .storage import (
    PLAIN,
    STAGING,
    discard,
    home_of,
    inside,
    keep,
    settle,
    stage,
    take_staged,
)

__all__ = [
    "current",
    "discard",
    "forget",
    "home_of",
    "inside",
    "judge",
    "keep",
    "origins",
    "paused_ids",
    "PLAIN",
    "PluginError",
    "read",
    "Registry",
    "reload",
    "set_granted",
    "set_origin",
    "set_paused",
    "settle",
    "stage",
    "STAGING",
    "storage",
    "take_staged",
]
