"""Running a plugin's Lua, and keeping it where it is put.

A plugin is somebody else's code running inside this process, so the question
is not "what can it do" but "what is it handed". It is handed a table, and
that table is the whole of its world: no ``io``, no ``os``, no ``require``,
no ``load``, and no way to reach the Python objects behind the functions it
is given.

A capability it is granted arrives as a Python object, and Lua can ask a
Python object for any attribute it likes — including ``__class__``, and from
there ``__globals__``, ``__builtins__``, ``__import__`` and the whole machine.
So every attribute goes through ``only_what_is_offered``: a capability lists
what it offers and nothing else is reachable, reading or writing. Without that
one function, granting any permission at all would be granting everything.

Three ceilings, because a plugin does not have to be hostile to hang a sync:

* **memory** — a table that grows for ever stops at a few megabytes;
* **instructions** — a loop that never ends stops after a few hundred
  thousand steps, through a debug hook the plugin cannot reach to remove;
* **no network** — the host fetches, so rate limits and patience stay in the
  one place that knows about them.

Nothing here knows what a source or a node is. It loads a file, calls a
function, and turns what comes back into Python. What those functions mean is
``registry``'s business.
"""

from __future__ import annotations

from .errors import PluginError, PluginStopped
from .sandbox import Sandbox, load

__all__ = [
    "load",
    "PluginError",
    "PluginStopped",
    "Sandbox",
]
