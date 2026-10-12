"""Every request Pamphlets makes to the outside world starts with this client.

One recipe — who we say we are, how long we wait, whether we follow a
redirect — so a feed, a newsletter's home page, a plugin's fetch and a call to
YouTube all leave the same way. Called through the module (`outgoing.client()`)
so a test can stand in for the network in one place.

Certificates are checked against the usual public authorities and, when
`PAMPHLETS_EXTRA_CA` names a PEM file, against those in it as well: a forge
on a home network signed by its own authority — where plugins may be kept —
is then trusted, and nothing else changes. Never switched off.
"""

from __future__ import annotations

import os
import ssl
from functools import lru_cache

import certifi
import httpx

USER_AGENT = "Pamphlets/0.1 (personal feed builder)"
TIMEOUT = 30.0


@lru_cache(maxsize=4)
def _trusting(extra: str) -> ssl.SSLContext | bool:
    """The public authorities, and those in `extra` too when it names one."""
    if not extra:
        return True
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cafile=extra)
    return context


def client() -> httpx.Client:
    """A fresh client, to be used in a `with` block and closed after."""
    return httpx.Client(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True,
        verify=_trusting(os.environ.get("PAMPHLETS_EXTRA_CA", "").strip()),
    )
