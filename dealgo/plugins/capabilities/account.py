"""Sending as the connected account, without handing over the credential.

The plugin knows the service. It knows which endpoint answers what, what the
JSON looks like coming back, and what each call costs against the day's
allowance — all of which is YouTube's business, not De-Algo's.

What it does not know, and must never learn, is the token. So it does not
make the request: it says what request to make, and the host makes it. The
host attaches the credential, charges the quota, and refuses to sign anything
addressed anywhere but the host the account came from.

That last part is the whole reason this is safe to grant. A capability that
signed a request to any address would be a capability that leaks the token to
the first address a plugin chose. The hosts are the plugin's own `connect.hosts`
— declared in its file, checked when it loads, and shown to the admin — and the
token is the one its own service issued, so the most a plugin can do is send
its own service's token to its own service.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from ... import outgoing
from ...services.scope import OwnerId
from ..runtime.values import to_lua, to_python
from .owner import whose

if TYPE_CHECKING:
    from ..registry.plugin import Plugin

log = logging.getLogger(__name__)

#: What one call may cost, whatever the plugin says. A quota unit is real
#: money to somebody, and a plugin that miscounts should not be able to spend
#: a day's allowance in one request.
MOST_COST = 100

#: What one call may send and receive. A playlist page is a few kilobytes.
MOST_BYTES = 4 * 1024 * 1024

#: How many signed calls one plugin may make per call into it. Filling a
#: playlist is done one item at a time by the host, not in a loop in here.
MOST_CALLS = 30


class Account:
    """What a plugin is handed as `account`.

    Bound to no owner of its own: like everything else a plugin reaches, it
    answers about whoever's work the host says is in hand, and refuses
    outside any such moment.
    """

    #: What a plugin may reach on this. Anything not named here is
    #: unreachable, which is what keeps `__class__` — and the whole
    #: machine behind it — out of a plugin's hands.
    LUA_OFFERS = frozenset({"connected", "send"})

    def __init__(self, plugin: str, lua: Any, declared: Plugin | None = None):
        """The `account` capability for one plugin, with no calls made yet.

        `declared` is the plugin itself, whose `connect` says which service
        and which hosts. Read when a request is made, not now: the file has
        not run yet, so nothing is declared.
        """
        self._plugin = plugin
        self._lua = lua
        self._declared = declared
        self._made = 0

    def afresh(self) -> None:
        """A new call, a new allowance. Filling a playlist is many calls into
        this plugin, and a budget that ran out for good after thirty would
        stop a sync partway through and never start again."""
        self._made = 0

    def connected(self) -> bool:
        """Whether there is a credential to send with at all.

        Worth asking before building a request: a plugin that knows there is
        no account can do the half of its job that needs none, rather than
        failing at the send.
        """
        owner = self._owner()
        declared = self._declared
        if owner is False or declared is None or declared.connect is None:
            return False
        try:
            from ...db import session_scope
            from ...services.connections import api_key, get_token

            with session_scope() as session:
                return bool(get_token(session, owner, declared.id) or api_key(declared))
        except Exception as exc:  # pragma: no cover - a database having a bad day
            log.warning("plugin %s could not check for an account: %s", self._plugin, exc)
            return False

    def send(self, method: object, url: object, body: object = None, cost: object = 1) -> Any:
        """Make one signed request and hand back what came, as a table.

        Nothing rather than an error when it fails, for the same reason
        everything else a plugin touches answers that way: a filter that
        throws because a service was down is a filter that stops a sync. What
        went wrong goes to the log, where somebody can read it.
        """
        owner = self._owner()
        if owner is False:
            return None

        # Refuse anything but a plain method to the account's own host, and more than the per-call
        # budget.
        address = str(url or "")
        how = str(method or "GET").upper()
        connect = self._declared.connect if self._declared is not None else None
        if connect is None:
            log.warning("plugin %s has no `connect`, so nothing to send as", self._plugin)
            return None
        if not connect.signs(address):
            log.warning(
                "plugin %s asked to sign a request to %r, which is not the account's host",
                self._plugin,
                address,
            )
            return None
        if how not in ("GET", "POST", "PUT", "DELETE"):
            log.warning("plugin %s asked for method %r", self._plugin, how)
            return None

        self._made += 1
        if self._made > MOST_CALLS:
            log.warning("plugin %s made more than %d signed calls", self._plugin, MOST_CALLS)
            return None

        return self._go(owner, how, address, body, _charge(cost))

    # -- the plumbing ------------------------------------------------------

    def _owner(self) -> Any:
        """Whose account, or False when there is nobody in hand."""
        owner, acting = whose()
        if not acting:
            log.info("plugin %s asked to send with no account in hand", self._plugin)
            return False
        return owner

    def _go(self, owner: OwnerId, how: str, url: str, body: object, cost: int) -> Any:
        """Sign, send and charge one request for `owner`; the answer as Lua tables."""
        from ...db import session_scope
        from ...services.connections import api_key, valid_access_token
        from ...services.quota import mark_exhausted, meter

        declared = self._declared
        if declared is None or declared.connect is None:  # pragma: no cover - checked in send
            return None
        try:
            with session_scope() as session, outgoing.client() as http:
                token = valid_access_token(session, http, owner, declared)
                key = api_key(declared) if not token else None
                if not token and not key:
                    log.info("plugin %s has no account to send as", self._plugin)
                    return None

                headers = {"Authorization": f"Bearer {token}"} if token else {}
                params = {} if token else {"key": key}
                sending = to_python(body)
                response = http.request(
                    how, url, params=params, json=sending, headers=headers
                )

                # Charged whatever the answer, because a service that rations
                # charges for the requests it refuses too — the only free call
                # is one turned away for having no allowance left.
                spent = meter(session, declared.id)
                payload = _read(response)
                why = self._refusal(payload)
                allowance = declared.connect.allowance
                if allowance is not None and allowance.exhausted and why == allowance.exhausted:
                    # The service says the day is spent. Believe it over the
                    # count, so nothing else is tried until it resets.
                    mark_exhausted(session, declared.id)
                else:
                    spent(cost)

            if response.status_code >= 400:
                log.warning(
                    "plugin %s: %s %s answered %d (%s)",
                    self._plugin, how, _tidy(url), response.status_code,
                    why or "no reason given",
                )
                return None
        except Exception as exc:
            log.warning("plugin %s could not send: %s", self._plugin, exc)
            return None

        return to_lua(self._lua, payload)

    def _refusal(self, payload: dict[str, Any]) -> str | None:
        """Why the service said no, in the plugin's words, where it says.

        The plugin's own `connect.refusal` reads it, since how a service
        spells a refusal is the service's business. One that throws, or has
        no such function, gives no reason.
        """
        declared = self._declared
        reader = declared.connect._refusal if declared and declared.connect else None
        if reader is None or not payload:
            return None
        try:
            said = reader(to_lua(self._lua, payload))
        except Exception as exc:
            log.warning("plugin %s could not read a refusal: %s", self._plugin, exc)
            return None
        return str(said) if said else None

def _charge(cost: object) -> int:
    """What to take off the day's allowance, bounded.

    The plugin says, because the cost of a YouTube call is YouTube's own
    table and nobody here should be keeping a second copy of it. But a plugin
    that miscounts — or lies — must not be able to spend the day in one call,
    and must not be able to spend nothing.
    """
    try:
        asked = int(float(str(cost)))
    except (TypeError, ValueError):
        return 1
    return max(1, min(asked, MOST_COST))


def _read(response: httpx.Response) -> dict[str, Any]:
    """A response's JSON as a dict, or `{}` when it is empty, too big, or not JSON."""
    if response.status_code == 204:
        return {}
    if len(response.content) > MOST_BYTES:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {"items": payload}


def _tidy(url: str) -> str:
    """An address without its query, for the log. A query can carry a key."""
    return url.split("?", 1)[0]
