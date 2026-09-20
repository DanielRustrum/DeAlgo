"""What a plugin may ask for beyond the table it starts with.

A plugin begins with nothing: pure Lua, no clock, no network, no way to leave
a mark. Everything past that is asked for by name and granted by a person,
and what is granted is simply what gets put in its environment — a plugin
without the network permission does not find a locked door, it finds no door.

The vocabulary is closed and lives here. A plugin says which of these it
wants and why it wants them; it cannot invent one, because a permission
nobody has written down is a permission nobody can reason about.

Each capability is built fresh per plugin, so one cannot reach another's, and
each carries its own ceiling. The point is not that a plugin is trusted once
granted — it is that the worst it can do with a grant is bounded and said out
loud beforehand.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)

#: Most a plugin may fetch in one request. A feed is tens of kilobytes; a
#: plugin pulling megabytes is doing something it did not ask permission for.
MOST_BYTES = 2 * 1024 * 1024

#: How many requests one plugin may make per call into it. A plugin resolving
#: a handle needs one; a plugin walking a site needs a different design.
MOST_REQUESTS = 4


@dataclass(frozen=True)
class Permission:
    """One thing a plugin can ask for."""

    name: str
    label: str
    #: What granting it actually allows, said plainly enough that somebody
    #: who does not write Lua can decide.
    means: str
    #: Why it is worth pausing over. Empty for the ones that are not.
    caution: str = ""


KNOWN: tuple[Permission, ...] = (
    Permission(
        name="network",
        label="Make network requests",
        means=(
            "Fetch web addresses of its own choosing while it runs. Requests go "
            "through De-Algo, so they wait when a host asks them to and are "
            "capped in size and number."
        ),
        caution=(
            "This is the one worth thinking about. A plugin that can fetch can "
            "also send — anything it has been shown could leave this machine."
        ),
    ),
    Permission(
        name="clock",
        label="Read the time",
        means="Ask what the time is now, so it can judge how old something is.",
    ),
    Permission(
        name="read",
        label="See what you are watching",
        means=(
            "Read the shape of the account it is working for: which sources "
            "are watched, which feeds exist, what is tagged what. Never what "
            "you have read or watched, and never another account's."
        ),
    ),
    Permission(
        name="manage",
        label="Change what you are watching",
        means=(
            "Add a source, tag one, or switch one off — for the account it is "
            "working for. Anything it adds arrives paused, so it can suggest "
            "and cannot start fetching."
        ),
        caution=(
            "It can rearrange a setup you built. Nothing is deleted, but "
            "things can appear and be switched off."
        ),
    ),
    Permission(
        name="account",
        label="Act as your connected account",
        means=(
            "Make requests to the service your connected account belongs to — "
            "reading your playlists, adding to them, looking up channels. "
            "De-Algo signs and sends them and charges the day's allowance; "
            "the plugin never sees the credential, and nothing is signed for "
            "any address but that service's own."
        ),
        caution=(
            "It acts as you there. Anything the account can do, a plugin with "
            "this can do — including changing playlists."
        ),
    ),
    Permission(
        name="log",
        label="Write to the log",
        means=(
            "Leave lines in De-Algo's own log, which is how a plugin explains "
            "itself when it is not doing what you expected."
        ),
    ),
)

BY_NAME = {permission.name: permission for permission in KNOWN}


def describe(name: str) -> Permission:
    """A permission by name, falling back rather than failing: a plugin that
    asks for something this version does not know still has to draw."""
    known = BY_NAME.get(name)
    if known is not None:
        return known
    return Permission(
        name=name,
        label=name,
        means="This version of De-Algo does not know what that is, so it is refused.",
        caution="Nothing is granted for a permission nobody here understands.",
    )


def capabilities(
    plugin: str,
    granted: frozenset[str],
    http: Callable[[], httpx.Client] | None = None,
    lua: Any = None,
    wants: tuple[tuple[str, str], ...] = (),
) -> dict[str, object]:
    """What to put in a plugin's world, given what it has been granted.

    Absent rather than refusing: a plugin without the network permission finds
    no `net` at all. That is the honest shape — there is nothing to probe, and
    an author testing `if net then` gets the right answer.

    ``dealgo`` is the exception. It is always there, because a plugin needs
    somewhere to ask what version it is talking to, and every question on it
    that touches an account's data answers nothing until somebody has been
    granted the permission for it. One object with parts that stay shut is
    kinder to write against than an object that might not exist.
    """
    from .site import Site

    given: dict[str, object] = {}
    if "clock" in granted:
        given["clock"] = _Clock()
    if "log" in granted:
        given["log"] = _Log(plugin)
    if "network" in granted:
        given["net"] = _Net(plugin, http)
    if "account" in granted and lua is not None:
        from .account import Account

        given["account"] = Account(plugin, lua)
    if lua is not None:
        given["dealgo"] = Site(
            plugin,
            lua,
            reading="read" in granted,
            managing="manage" in granted,
            # Its own manifest, so it can read back what it asked for and
            # what it was given without asking permission to.
            wants=wants,
            granted=granted,
        )
    return given


class _Clock:
    """The time, and nothing else about the machine."""

    #: What a plugin may reach on this. Anything not named here is
    #: unreachable, which is what keeps `__class__` — and the whole
    #: machine behind it — out of a plugin's hands.
    LUA_OFFERS = frozenset({"now"})

    def now(self) -> float:
        """Seconds since the epoch, UTC. A number, because a plugin has no
        date type and comparing two numbers is what it actually wants."""
        return dt.datetime.now(dt.timezone.utc).timestamp()


class _Log:
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


class _Net:
    """Fetching, through the host rather than around it.

    Every request goes out the way De-Algo's own do: the same client, the same
    user agent, and the same `patience` — so a plugin cannot spend a host's
    rate-limit budget behind the back of the thing that tracks it.
    """

    #: What a plugin may reach on this. Anything not named here is
    #: unreachable, which is what keeps `__class__` — and the whole
    #: machine behind it — out of a plugin's hands.
    LUA_OFFERS = frozenset({"get"})

    def __init__(self, plugin: str, http: Callable[[], httpx.Client] | None):
        self._plugin = plugin
        self._http = http
        self._made = 0

    def get(self, url: object) -> Any:
        """Fetch a page and hand back its text, or nothing if it could not be.

        Nothing rather than an error: a plugin is a filter, and a filter that
        throws because a site was down is a filter that stops a sync.
        """
        from ..sources import patience

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
                response = client.get(address)
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


def _short(message: object) -> str:
    """A plugin's own words, bounded. A log line is not a place to put a feed."""
    said = str(message)
    return said if len(said) <= 500 else said[:500] + "…"
