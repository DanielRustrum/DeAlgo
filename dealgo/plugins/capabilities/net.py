"""`net`: reading the web, for a plugin granted it.

The host makes every request. A plugin says where, and gets back what came:
never the client itself, and never more than its ceilings allow in one call.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)


#: Most a plugin may fetch in one request. A feed is tens of kilobytes; a
#: plugin pulling megabytes is doing something it did not ask permission for.
MOST_BYTES = 2 * 1024 * 1024


#: How many requests one plugin may make per call into it. A plugin resolving
#: a handle needs one; a plugin walking a site needs a different design.
MOST_REQUESTS = 4


class Net:
    """Fetching, through the host rather than around it.

    Every request goes out the way De-Algo's own do: the same client, the same
    user agent, and the same `patience` — so a plugin cannot spend a host's
    rate-limit budget behind the back of the thing that tracks it.
    """

    #: What a plugin may reach on this. Anything not named here is
    #: unreachable, which is what keeps `__class__` — and the whole
    #: machine behind it — out of a plugin's hands.
    LUA_OFFERS = frozenset({"get", "embedded", "find"})

    def __init__(self, plugin: str, http: Callable[[], httpx.Client] | None, lua: Any = None):
        self._plugin = plugin
        self._http = http
        self._lua = lua
        self._made = 0

    def embedded(self, text: object, name: object, key: object) -> Any:
        """Every value under `key` inside the JSON a page assigns to `name`.

        A page with no feed keeps its content in a blob its own scripts read,
        and pulling that out is a parser's job — the same argument that keeps
        the XML reader here rather than in Lua. What is a plugin's is saying
        which variable and which key, which is all this asks for.

        Only the matches cross over, not the blob. One of these pages is a
        megabyte, and a megabyte of JSON as Lua tables would not fit in the
        memory a plugin is allowed.
        """
        from ...sources import embedded as reading

        document = reading.script_object(str(text or ""), str(name or ""))
        if document is None:
            return None
        return self._list(reading.find(document, str(key or "")))

    def find(self, thing: object, key: object) -> Any:
        """The same search, over something already in hand.

        For the second look inside a match — a post's attachment, say. Those
        are small by the time they get here, which is why this one takes a
        table and the other does not.
        """
        from ...sources import embedded as reading

        return self._list(reading.find(_plain(thing), str(key or "")))

    def afresh(self) -> None:
        """A new call, a new allowance. The limit is on what one call may do,
        not on what a plugin may do before it is next restarted."""
        self._made = 0

    def _list(self, found: list[Any]) -> Any:
        """A list of decoded values as Lua tables, all the way down.

        A nested dictionary handed over as a Python object is one a plugin
        cannot index, and what comes out of a page is nested by nature.
        """
        made = self._lua.table() if self._lua is not None else None
        if made is None:  # pragma: no cover - only without a runtime to build in
            return None
        for index, value in enumerate(found, start=1):
            made[index] = self._table(value)
        return made

    def _table(self, value: object) -> Any:
        if isinstance(value, dict):
            made = self._lua.table()
            for key, inner in value.items():
                made[str(key)] = self._table(inner)
            return made
        if isinstance(value, list):
            made = self._lua.table()
            for index, inner in enumerate(value, start=1):
                made[index] = self._table(inner)
            return made
        return value

    def get(self, url: object, headers: object = None) -> Any:
        """Fetch a page and hand back its text, or nothing if it could not be.

        Nothing rather than an error: a plugin is a filter, and a filter that
        throws because a site was down is a filter that stops a sync.
        """
        from ...sources import patience

        address = str(url or "")
        if not address.startswith(("http://", "https://")):
            log.warning("plugin %s asked for %r, which is not a web address", self._plugin, address)
            return None
        self._made += 1
        if self._made > MOST_REQUESTS:
            log.warning("plugin %s asked for more than %d requests", self._plugin, MOST_REQUESTS)
            return None
        if self._http is None:  # pragma: no cover - only when nothing set one up
            return None

        try:
            patience.hold(address)
            with self._http() as client:
                response = client.get(address, headers=_polite(headers))
            patience.note(response)
            response.raise_for_status()
        except patience.RateLimited as held:
            log.info("plugin %s is waiting on %s: %s", self._plugin, held.host, held)
            return None
        except Exception as exc:
            log.warning("plugin %s could not fetch %s: %s", self._plugin, address, exc)
            return None

        body = response.content[: MOST_BYTES + 1]
        if len(body) > MOST_BYTES:
            log.warning("plugin %s asked for something too large: %s", self._plugin, address)
            return None
        try:
            return body.decode(response.encoding or "utf-8", errors="replace")
        except (LookupError, UnicodeDecodeError):  # pragma: no cover - a strange encoding
            return body.decode("utf-8", errors="replace")


#: The headers a plugin may set on its own request. Everything that carries
#: authority — a cookie, an authorization, a host — is the host's to set and
#: not a plugin's to forge.
ASKABLE_HEADERS = frozenset({"user-agent", "accept", "accept-language", "referer"})


def _polite(headers: object) -> dict[str, str] | None:
    """What a plugin asked to send, less anything it has no business sending.

    A site that serves a consent wall to anything without a browser's user
    agent is a real problem for a plugin that has to read a page, so this is
    worth allowing. A `Cookie` is not.
    """
    given = _plain(headers)
    if not isinstance(given, dict):
        return None
    return {
        str(name): str(value)
        for name, value in given.items()
        if str(name).lower() in ASKABLE_HEADERS
    }


def _plain(value: object) -> object:
    """A Lua table as something Python can walk."""
    import lupa

    if lupa.lua_type(value) != "table":
        return value
    table: Any = value
    keys = list(table.keys())
    if keys and keys == list(range(1, len(keys) + 1)):
        return [_plain(table[key]) for key in keys]
    return {str(key): _plain(table[key]) for key in keys}
