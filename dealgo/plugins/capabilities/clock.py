"""`clock`: the time, for a plugin granted it."""

from __future__ import annotations

import datetime as dt


class Clock:
    """The time, and nothing else about the machine."""

    #: What a plugin may reach on this. Anything not named here is
    #: unreachable, which is what keeps `__class__` — and the whole
    #: machine behind it — out of a plugin's hands.
    LUA_OFFERS = frozenset({"now"})

    def now(self) -> float:
        """Seconds since the epoch, UTC. A number, because a plugin has no
        date type and comparing two numbers is what it actually wants."""
        return dt.datetime.now(dt.timezone.utc).timestamp()
