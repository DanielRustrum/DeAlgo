"""How long each host has asked us to wait before asking it again.

A host that says "your budget is spent, come back in 36 seconds" is doing us
a favour: reading it is the difference between waiting a minute and being
blocked for an hour. Reddit says exactly that, and says it on the *successful*
response — so a reader that listens never makes the request that gets refused.

Kept in memory, per host, deliberately:

* it is worth nothing after a restart — a fresh process has spent no budget;
* a wrong answer costs one early request, not a lost item;
* and it must be read on every poll, which is no place for a database.

It is advice, not a lock. Nothing here stops a caller that wants to ask
anyway; ``hold`` is the caller saying it would rather wait than be refused.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import threading
import time
from urllib.parse import urlparse

import httpx


class RateLimited(Exception):
    """This host asked us to wait, and the wait is not up yet.

    Carries how long is left so the person watching can be told something
    more useful than "it did not work".
    """

    def __init__(self, host: str, seconds: float):
        super().__init__(f"{host} asked us to wait {round(seconds)}s")
        self.host = host
        self.seconds = seconds


# Host -> the monotonic moment it may be asked again.
_until: dict[str, float] = {}
_lock = threading.Lock()

# Never wait longer than this on one host's say-so. A header that asks for a
# day is either a misreading on our part or a host we should not be polling
# on a schedule at all, and either way an hour is long enough to be polite.
MOST_WE_WAIT = 3600.0


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def wait_for(url: str) -> float:
    """Seconds still to wait before asking this host. Zero when it is free."""
    host = host_of(url)
    if not host:
        return 0.0
    with _lock:
        ready = _until.get(host)
    if ready is None:
        return 0.0
    left = ready - time.monotonic()
    return left if left > 0 else 0.0


def hold(url: str) -> None:
    """Refuse to ask a host that is still inside the wait it asked for."""
    left = wait_for(url)
    if left > 0:
        raise RateLimited(host_of(url), left)


def rest(url: str, seconds: float) -> None:
    """Leave this host alone for a while. The longest wait in hand wins, so a
    second opinion can extend a wait but never cut one short."""
    host = host_of(url)
    if not host or seconds <= 0:
        return
    ready = time.monotonic() + min(seconds, MOST_WE_WAIT)
    with _lock:
        _until[host] = max(_until.get(host, 0.0), ready)


def note(response: httpx.Response) -> None:
    """Read whatever this response says about how often we may ask.

    Called on every response, not only the refusals: the whole point is that
    a host which tells us on a *success* that nothing is left lets us skip the
    request that would have been refused.
    """
    url = str(response.url)
    after = _retry_after(response.headers.get("retry-after"))
    if after is not None:
        rest(url, after)
        return

    remaining = _number(response.headers.get("x-ratelimit-remaining"))
    if remaining is None or remaining > 0:
        return
    reset = _reset(response.headers.get("x-ratelimit-reset"))
    if reset is not None:
        rest(url, reset)


def forget() -> None:
    """Drop every wait. For tests, and for a person who has waited enough."""
    with _lock:
        _until.clear()


def _number(raw: str | None) -> float | None:
    try:
        return float((raw or "").strip())
    except ValueError:
        return None


def _retry_after(raw: str | None) -> float | None:
    """``Retry-After`` is either a count of seconds or an HTTP date."""
    if not raw:
        return None
    seconds = _number(raw)
    if seconds is not None:
        return max(0.0, seconds)
    try:
        when = email.utils.parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return max(0.0, (when - dt.datetime.now(dt.timezone.utc)).total_seconds())


def _reset(raw: str | None) -> float | None:
    """``x-ratelimit-reset`` is seconds to wait for some hosts and a moment in
    time for others. Told apart by size: nobody asks for a wait of a million
    seconds, and no epoch timestamp is that small."""
    value = _number(raw)
    if value is None or value < 0:
        return None
    if value > 1_000_000:
        return max(0.0, value - dt.datetime.now(dt.timezone.utc).timestamp())
    return value
