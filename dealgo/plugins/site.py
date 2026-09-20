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

import contextlib
import logging
import threading
from collections.abc import Iterator
from typing import Any

from ..services.scope import OwnerId

log = logging.getLogger(__name__)

#: Most rows one call may hand back. A plugin wanting the shape of a setup
#: needs tens; a plugin wanting thousands is reading a database it was given
#: no permission to read.
MOST_ROWS = 500


class _Whose(threading.local):
    """Whose work is in hand, on this thread.

    Thread-local because a sync runs in one and a request in another, and the
    two must never borrow each other's answer.
    """

    owner: OwnerId = None
    acting: bool = False


_whose = _Whose()


@contextlib.contextmanager
def acting_for(owner: OwnerId) -> Iterator[None]:
    """Say whose work the plugins about to run are doing.

    Nested deliberately restores rather than clears: a run inside a run is not
    a thing here, but if it ever became one, the inner finishing must not
    leave the outer speaking for nobody.
    """
    was, acted = _whose.owner, _whose.acting
    _whose.owner, _whose.acting = owner, True
    try:
        yield
    finally:
        _whose.owner, _whose.acting = was, acted


def whose() -> tuple[OwnerId, bool]:
    return _whose.owner, _whose.acting


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
        from .. import __version__

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
        rows = self._look(lambda session, owner: _sources(session, owner))
        return self._rows(rows)

    def feeds(self) -> Any:
        """The feeds this account keeps, and how much is in each."""
        if not self._may("read", self._reading):
            return self._empty()
        rows = self._look(lambda session, owner: _feeds(session, owner))
        return self._rows(rows)

    # -- changing ----------------------------------------------------------

    def pause(self, key: object, on: object) -> bool:
        """Switch a source on or off."""
        if not self._may("manage", self._managing):
            return False
        wanted = on is not False
        return bool(self._change(lambda s, o: _pause(s, o, str(key or ""), wanted)))

    def watch(self, reference: object) -> Any:
        """Start watching somewhere, the way the Sources page would.

        Answers the key it was filed under, or nothing if it could not be
        read. Added paused, as everything added is: a plugin may decide
        something is worth following and does not get to decide it is worth
        fetching.
        """
        if not self._may("manage", self._managing):
            return None
        return self._change(lambda s, o: _watch(s, o, str(reference or "")))

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
        from ..db import session_scope

        owner, _ = whose()
        try:
            with session_scope() as session:
                return list(run(session, owner))[:MOST_ROWS]
        except Exception as exc:  # pragma: no cover - a database having a bad day
            log.warning("plugin %s could not read: %s", self._plugin, exc)
            return []

    def _change(self, run: Any) -> object:
        from ..db import session_scope

        owner, _ = whose()
        try:
            with session_scope() as session:
                return run(session, owner)
        except Exception as exc:
            log.warning("plugin %s could not change anything: %s", self._plugin, exc)
            return None

    def _rows(self, rows: list[dict[str, object]]) -> Any:
        """Python dictionaries as Lua tables, one-based, walkable."""
        table = self._lua.table()
        for index, row in enumerate(rows, start=1):
            made = self._lua.table()
            for name, value in row.items():
                made[name] = value
            table[index] = made
        return table

    def _empty(self) -> Any:
        return self._lua.table()


def permissions_for(name: str) -> Any:
    from . import permissions

    return permissions.describe(name)


def _known_names() -> frozenset[str]:
    from . import permissions

    return frozenset(permissions.BY_NAME)


# -- what each question actually asks --------------------------------------


def _sources(session: Any, owner: OwnerId) -> list[dict[str, object]]:
    from ..services import channels as channel_service

    return [
        {
            "key": channel.channel_id,
            "title": channel.title or channel.channel_id,
            "kind": channel.source_kind,
            "enabled": channel.enabled,
        }
        for channel in channel_service.list_channels(session, owner)
    ]


def _feeds(session: Any, owner: OwnerId) -> list[dict[str, object]]:
    from ..services import playlists as playlist_service

    return [
        {
            "title": playlist.title,
            "generic": playlist.is_generic,
            "enabled": playlist.enabled,
            "sources": len(playlist.channels),
        }
        for playlist in playlist_service.list_playlists(session, owner)
    ]


def _find(session: Any, owner: OwnerId, key: str) -> Any:
    from sqlalchemy import select

    from ..models import Channel
    from ..services.scope import owned

    if not key:
        return None
    return session.scalar(
        owned(select(Channel), Channel, owner).where(Channel.channel_id == key)
    )


def _pause(session: Any, owner: OwnerId, key: str, on: bool) -> bool:
    channel = _find(session, owner, key)
    if channel is None:
        return False
    channel.enabled = on
    session.flush()
    return True


def _watch(session: Any, owner: OwnerId, reference: str) -> str | None:
    from ..services import channels as channel_service
    from ..services import sync as sync_service

    if not reference:
        return None
    with sync_service.http_client() as http:
        try:
            channel = channel_service.add_source(session, reference, http, owner=owner)
        except channel_service.ChannelError as exc:
            log.info("a plugin could not watch %r: %s", reference, exc)
            return None
    return channel.channel_id
