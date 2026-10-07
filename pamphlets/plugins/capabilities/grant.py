"""Building a plugin's world from what it was granted."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

import httpx

from .account import Account
from .clock import Clock
from .log import Log
from .net import Net
from .site import Site

if TYPE_CHECKING:
    from ..registry.plugin import Plugin


def granted_to(
    plugin: str,
    granted: frozenset[str],
    http: Callable[[], httpx.Client] | None = None,
    lua: Any = None,
    wants: tuple[tuple[str, str], ...] = (),
    declared: Plugin | None = None,
) -> dict[str, object]:
    """What to put in a plugin's world, given what it has been granted.

    Absent rather than refusing: a plugin without the network permission finds
    no `net` at all. That is the honest shape — there is nothing to probe, and
    an author testing `if net then` gets the right answer.

    ``pamphlets`` is the exception. It is always there, because a plugin needs
    somewhere to ask what version it is talking to, and every question on it
    that touches an account's data answers nothing until somebody has been
    granted the permission for it. One object with parts that stay shut is
    kinder to write against than an object that might not exist.
    """
    given: dict[str, object] = {}
    if "clock" in granted:
        given["clock"] = Clock()
    if "log" in granted:
        given["log"] = Log(plugin)
    if "network" in granted:
        given["net"] = Net(plugin, http, lua)
    if "account" in granted and lua is not None:
        given["account"] = Account(plugin, lua, declared)
    if lua is not None:
        given["pamphlets"] = Site(
            plugin,
            lua,
            reading="read" in granted,
            managing="manage" in granted,
            # Its own manifest, so it can read back what it asked for and
            # what it was given without asking permission to.
            wants=wants,
            granted=granted,
        )
        # The name it had before the app was called Pamphlets, so a plugin
        # written then keeps working: the same object, under both.
        given["dealgo"] = given["pamphlets"]
    return given
