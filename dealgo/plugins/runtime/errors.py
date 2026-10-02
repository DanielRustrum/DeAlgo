"""What goes wrong in a plugin, said the way its author would want it."""

from __future__ import annotations


class PluginError(RuntimeError):
    """Something a plugin did wrong, said the way its author would want it."""


class PluginStopped(PluginError):
    """It ran too long, or asked for too much memory, and was stopped."""


def complaint(exc: BaseException) -> str:
    """What Lua said, without the parts only Lua cares about.

    A Lua error carries a stack traceback and repeats the chunk name it was
    given. Neither helps the person reading the plugin list; the line number
    and the message do.
    """
    said = str(exc).split("stack traceback:")[0].strip()
    # Lua writes "@name:12: message"; the name is already on the row.
    _, _, after = said.partition(":")
    return (after.strip() or said) if said.count(":") >= 2 else said
