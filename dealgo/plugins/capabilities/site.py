"""The `dealgo` object: how a plugin reaches the rest of the app.

What a plugin *returns* is configuration — what it is called, what kinds of
source it reads, what boxes it puts in the palette, what it is asking to be
allowed. Nothing in that table does anything. Everything a plugin *does* to
the site goes through this object, which it is handed rather than importing,
and only if somebody granted it.

The hard part is not the functions. It is whose data they are about.

De-Algo keeps one account's channels, feeds and settings apart from another's,
and a plugin is install-wide: one file, loaded once, used by everybody. So
this object has no account of its own and answers nothing until the host says
whose work is in hand. During a sync for one account, `dealgo.sources()` is
that account's sources and no other's; outside any such moment it is empty
and every change is refused.

That is enforced here rather than left to each function to remember, because
a missed owner filter is a data leak and "remember to pass the owner" is the
kind of rule that gets missed once.
"""

from __future__ import annotations

import logging
from typing import Any

from ..runtime.values import to_lua
from .owner import whose
from .site_queries import feeds_of, pause_source, sources_of, watch_source

log = logging.getLogger(__name__)


#: Most rows one call may hand back. A plugin wanting the shape of a setup
#: needs tens; a plugin wanting thousands is reading a database it was given
#: no permission to read.
MOST_ROWS = 500


class Site:
    """What a plugin is handed as `dealgo`.

    Built per plugin, so one cannot reach another's, and given the Lua runtime
    so that what it answers with are real Lua tables — a list a plugin cannot
    walk with `ipairs` is not an answer.
    """

    #: What a plugin may reach on this. Anything not named here is
    #: unreachable, which is what keeps `__class__` — and the whole
    #: machine behind it — out of a plugin's hands.
    LUA_OFFERS = frozenset({"version", "permissions", "sources", "feeds", "pause", "watch"})

    def __init__(
        self,
        plugin: str,
        lua: Any,
        *,
        reading: bool,
        managing: bool,
        wants: tuple[tuple[str, str], ...] = (),
        granted: frozenset[str] = frozenset(),
    ):
        self._plugin = plugin
        self._lua = lua
        self._reading = reading
        self._managing = managing
        self._wants = wants
        self._granted = granted

    # -- what it is --------------------------------------------------------

    @property
    def version(self) -> str:
        """De-Algo's version. Needs no permission: it is on every page.

        Worth having so a plugin can tell an older host from a newer one and
        do less rather than fail — which is the only way a plugin outlives
        the version it was written against.
        """
        from ... import __version__

        return str(__version__)

    def permissions(self) -> Any:
        """Everything this plugin asked for, and how it went.

        Its own manifest read back, so it needs no permission of its own —
        there is nothing here a plugin did not already write down.

        The point is the `granted` field. A plugin that asked for the network
        and did not get it can say so, or quietly do the lesser thing, rather
        than failing at the moment it reaches for something that is not
        there. Testing `if net then` answers whether it has one; this answers
        what it asked for and why, which is what it needs to explain itself.
        """
        rows = [
            {
                "name": name,
                "label": permissions_for(name).label,
                "why": why,
                "granted": name in self._granted,
                # False for one this version of De-Algo has no name for. It
                # was asked for and can never be granted, and a plugin should
                # be able to tell that apart from a plain refusal.
                "known": name in _known_names(),
            }
            for name, why in self._wants
        ]
        return self._rows(rows)

    # -- reading -----------------------------------------------------------

    def sources(self) -> Any:
        """The sources this account watches.

        Their shape, not their history: a key, a name, a kind, and whether
        it is on. Enough to decide something about a setup; nothing about
        what anybody has read.
        """
        if not self._may("read", self._reading):
            return self._empty()
        rows = self._look(sources_of)
        return self._rows(rows)

    def feeds(self) -> Any:
        """The feeds this account keeps, and how much is in each."""
        if not self._may("read", self._reading):
            return self._empty()
        rows = self._look(feeds_of)
        return self._rows(rows)

    # -- changing ----------------------------------------------------------

    def pause(self, key: object, on: object) -> bool:
        """Switch a source on or off."""
        if not self._may("manage", self._managing):
            return False
        wanted = on is not False
        return bool(self._change(lambda s, o: pause_source(s, o, str(key or ""), wanted)))

    def watch(self, reference: object) -> Any:
        """Start watching somewhere, the way the Sources page would.

        Answers the key it was filed under, or nothing if it could not be
        read. Added paused, as everything added is: a plugin may decide
        something is worth following and does not get to decide it is worth
        fetching.
        """
        if not self._may("manage", self._managing):
            return None
        return self._change(lambda s, o: watch_source(s, o, str(reference or "")))

    # -- the plumbing ------------------------------------------------------

    def _may(self, what: str, granted: bool) -> bool:
        if not granted:
            log.warning("plugin %s tried to %s without being allowed to", self._plugin, what)
            return False
        _, acting = whose()
        if not acting:
            # Not an error: a plugin may be asked something outside any run,
            # and the honest answer then is that there is nobody to answer
            # about rather than somebody picked arbitrarily.
            log.info("plugin %s asked to %s with no account in hand", self._plugin, what)
            return False
        return True

    def _look(self, run: Any) -> list[dict[str, object]]:
        from ...db import session_scope

        owner, _ = whose()
        try:
            with session_scope() as session:
                return list(run(session, owner))[:MOST_ROWS]
        except Exception as exc:  # pragma: no cover - a database having a bad day
            log.warning("plugin %s could not read: %s", self._plugin, exc)
            return []

    def _change(self, run: Any) -> object:
        from ...db import session_scope

        owner, _ = whose()
        try:
            with session_scope() as session:
                return run(session, owner)
        except Exception as exc:
            log.warning("plugin %s could not change anything: %s", self._plugin, exc)
            return None

    def _rows(self, rows: list[dict[str, object]]) -> Any:
        """Python dictionaries as Lua tables, one-based, walkable."""
        return to_lua(self._lua, rows)

    def _empty(self) -> Any:
        return self._lua.table()


def permissions_for(name: str) -> Any:
    from .. import permissions

    return permissions.describe(name)


def _known_names() -> frozenset[str]:
    from .. import permissions

    return frozenset(permissions.BY_NAME)
