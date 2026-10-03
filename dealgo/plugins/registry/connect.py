"""How a plugin signs somebody in to its service: what it declares, checked.

A plugin that writes back as a person — YouTube adding to a playlist — needs
that person's permission, which is an OAuth 2.0 sign-in. The plugin knows the
service: where to send the browser, where to trade the code, which scopes to
ask for, which hosts the token is for. The host does the sign-in itself and
keeps the token, so the plugin never sees it (capabilities/account.py signs
its requests). This is the plugin's half: a `connect` table, read and checked
here before anything is believed.

```lua
connect = {
  name = "Google",
  authorize = "https://accounts.google.com/o/oauth2/v2/auth",
  token = "https://oauth2.googleapis.com/token",
  revoke = "https://oauth2.googleapis.com/revoke",
  scopes = { "https://www.googleapis.com/auth/youtube" },
  params = { access_type = "offline", prompt = "consent" },
  hosts = { "googleapis.com" },
  client_id = "client_id", client_secret = "client_secret", api_key = "api_key",
  allowance = { daily = "daily_quota", reserve = "quota_reserve",
                timezone = "America/Los_Angeles", unit = "units", exhausted = "quotaExceeded" },
  refusal = function(answer) ... end,
  about = "…",
}
```
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..runtime import PluginError
from .settings import Settings

#: A host the token may be sent to: a plain DNS name, no scheme, port or path.
HOST = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")

#: How many hosts one plugin may name. The point is a short list.
MOST_HOSTS = 8


@dataclass(frozen=True)
class Allowance:
    """A daily budget the service enforces, and how to keep count of it.

    `daily` and `reserve` are app setting names or plain numbers; the host
    reads them through `amount`, so the admin can change them on the card.
    """

    daily: str = "0"
    reserve: str = "0"
    timezone: str = "UTC"
    #: What the service calls one of them: "units".
    unit: str = "units"
    #: The refusal reason that means the day's allowance is spent.
    exhausted: str = ""


@dataclass(frozen=True)
class Connect:
    """How a plugin's service signs somebody in, and what the token is for."""

    name: str
    authorize: str
    token: str
    revoke: str = ""
    scopes: tuple[str, ...] = ()
    #: Extra query parameters for the consent page.
    params: tuple[tuple[str, str], ...] = ()
    #: Where the token may be sent: these hosts and their subdomains, HTTPS only.
    hosts: tuple[str, ...] = ()
    #: The app settings holding the OAuth client, and an optional API key for
    #: reading without a sign-in.
    client_id: str = "client_id"
    client_secret: str = "client_secret"
    api_key: str = ""
    allowance: Allowance | None = None
    #: A few sentences for the plugin's block under Settings.
    about: str = ""
    #: The plugin's own function reading why the service refused a request.
    _refusal: Any = None

    def signs(self, url: str) -> bool:
        """Whether a URL is HTTPS to one of the hosts the token is for."""
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        host = (parsed.hostname or "").lower()
        return any(host == one or host.endswith("." + one) for one in self.hosts)


def connect_in(given: object, settings: Settings) -> Connect | None:
    """A plugin's `connect` table, checked; None when it has none."""
    if given is None:
        return None
    if not isinstance(given, dict):
        raise PluginError("`connect` has to be a table")

    name = str(given.get("name") or "").strip()
    if not name:
        raise PluginError("`connect` needs a `name`: what the account is called, like “Google”")
    authorize = _https(given, "authorize", required=True)
    token = _https(given, "token", required=True)
    revoke = _https(given, "revoke", required=False)

    hosts = _strings(given.get("hosts"), "hosts")
    if not hosts:
        raise PluginError("`connect.hosts` has to name the hosts the token is for")
    if len(hosts) > MOST_HOSTS:
        raise PluginError(f"`connect.hosts` may name at most {MOST_HOSTS} hosts")
    for host in hosts:
        if not HOST.fullmatch(host):
            raise PluginError(f"`connect.hosts`: “{host}” is not a plain host name")

    # The OAuth client lives in the plugin's own app settings, so the admin
    # sets it on the plugin's card. Each name must be one it declared.
    named = {one.name for one in settings.app}
    client_id = str(given.get("client_id") or "client_id")
    client_secret = str(given.get("client_secret") or "client_secret")
    api_key = str(given.get("api_key") or "")
    for field, setting in (("client_id", client_id), ("client_secret", client_secret),
                           ("api_key", api_key)):
        if setting and setting not in named:
            raise PluginError(
                f"`connect.{field}` names “{setting}”, which is not one of its `settings.app`"
            )

    refusal = given.get("refusal")
    if refusal is not None and not callable(refusal):
        raise PluginError("`connect.refusal` has to be a function")

    params = given.get("params") or {}
    if not isinstance(params, dict):
        raise PluginError("`connect.params` has to be a table of names and values")

    return Connect(
        name=name[:40],
        authorize=authorize,
        token=token,
        revoke=revoke,
        scopes=tuple(_strings(given.get("scopes"), "scopes")),
        params=tuple((str(k), str(v)) for k, v in params.items()),
        hosts=tuple(hosts),
        client_id=client_id,
        client_secret=client_secret,
        api_key=api_key,
        allowance=_allowance(given.get("allowance"), named),
        about=" ".join(str(given.get("about") or "").split())[:1200],
        _refusal=refusal,
    )


def _https(given: dict[str, Any], field: str, *, required: bool) -> str:
    """An HTTPS address from the table, checked."""
    value = str(given.get(field) or "").strip()
    if not value:
        if required:
            raise PluginError(f"`connect.{field}` is required")
        return ""
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PluginError(f"`connect.{field}` has to be an https:// address")
    return value


def _strings(given: object, field: str) -> list[str]:
    """A list of plain strings."""
    if given is None:
        return []
    if not isinstance(given, list):
        raise PluginError(f"`connect.{field}` has to be a list")
    return [str(one).strip().lower() if field == "hosts" else str(one).strip() for one in given]


def _allowance(given: object, named: set[str]) -> Allowance | None:
    """The daily budget, if the service has one."""
    if given is None:
        return None
    if not isinstance(given, dict):
        raise PluginError("`connect.allowance` has to be a table")

    def amount(field: str) -> str:
        value = given.get(field)
        if value is None:
            return "0"
        if isinstance(value, (int, float)):
            return str(int(value))
        if str(value) not in named:
            raise PluginError(
                f"`connect.allowance.{field}` has to be a number or one of its `settings.app`"
            )
        return str(value)

    zone = str(given.get("timezone") or "UTC")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise PluginError(f"`connect.allowance.timezone`: “{zone}” is not a time zone") from None
    return Allowance(
        daily=amount("daily"),
        reserve=amount("reserve"),
        timezone=zone,
        unit=str(given.get("unit") or "units")[:20],
        exhausted=str(given.get("exhausted") or ""),
    )
