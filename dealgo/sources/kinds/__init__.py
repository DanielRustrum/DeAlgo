"""What a reference turns out to be, asked of the plugins that know.

This used to hold a regex per site. It holds none now: every kind of
somewhere — YouTube, Reddit, Bluesky, Substack — is a plugin, and this asks
them in turn. What is left here is the part that cannot be a plugin:

* **RSS**, the floor. Anything with no plugin to claim it is taken at its
  word as the address of a feed, which is what it most often is. It is not a
  peer of the others; it is what they are all built on.
* **Newsletter**, which is the floor said the way somebody thinks of it. A
  newsletter is known by where it lives rather than by where its feed is, and
  every platform puts that feed somewhere slightly different — so this one
  kind resolves to a site and has its feed found by reading it. Not a plugin
  because it belongs to no service: Substack, Ghost, beehiiv and a WordPress
  with an email list are all the same answer to "which newsletter".
* **the vocabulary** — ``Resolved``, ``SourceKind``, ``UnknownSource`` — so
  the rest of the app talks about sources without knowing a plugin exists.

Nothing here makes a request. A plugin says where a feed is by the shape of
what was typed; reading it is the host's business, and so are rate limits —
which is why a Newsletter resolves with no feed address at all and says so,
rather than fetching one from in here.
"""

from __future__ import annotations

from .addresses import feed_url, home_url, item_url, suggest_mirror
from .resolving import resolve
from .vocabulary import NEWSLETTER, RSS, Resolved, SourceKind, UnknownSource, all_kinds, describe

__all__ = [
    "NEWSLETTER",
    "RSS",
    "Resolved",
    "SourceKind",
    "UnknownSource",
    "all_kinds",
    "describe",
    "feed_url",
    "home_url",
    "item_url",
    "resolve",
    "suggest_mirror",
]
