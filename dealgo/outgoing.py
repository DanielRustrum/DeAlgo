"""Every request Pamphlets makes to the outside world starts with this client.

One recipe — who we say we are, how long we wait, whether we follow a
redirect — so a feed, a newsletter's home page, a plugin's fetch and a call to
YouTube all leave the same way. Called through the module (`outgoing.client()`)
so a test can stand in for the network in one place.
"""

from __future__ import annotations

import httpx

USER_AGENT = "Pamphlets/0.1 (personal feed builder)"
TIMEOUT = 30.0


def client() -> httpx.Client:
    """A fresh client, to be used in a `with` block and closed after."""
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
