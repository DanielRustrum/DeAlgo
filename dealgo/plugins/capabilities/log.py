"""`log`: lines in the app's own log, under the plugin's name."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class Log:
    """A way for a plugin to say what it is doing."""

    #: What a plugin may reach on this. Anything not named here is
    #: unreachable, which is what keeps `__class__` — and the whole
    #: machine behind it — out of a plugin's hands.
    LUA_OFFERS = frozenset({"info", "warn"})

    def __init__(self, plugin: str):
        self._plugin = plugin

    def info(self, message: object) -> None:
        log.info("plugin %s: %s", self._plugin, _short(message))

    def warn(self, message: object) -> None:
        log.warning("plugin %s: %s", self._plugin, _short(message))


def _short(message: object) -> str:
    """A plugin's own words, bounded. A log line is not a place to put a feed."""
    said = str(message)
    return said if len(said) <= 500 else said[:500] + "…"
