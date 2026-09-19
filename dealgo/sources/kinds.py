"""The kinds of source, and how a reference becomes a feed.

Each kind answers three questions: does this look like one of mine, where is
its feed, and where does an item from it live. Nothing else varies — polling,
filtering and routing are the same whatever the answer.

Adding a kind is adding an entry here. That is the point of the shape: the
rest of the app asks the registry rather than knowing the list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


class UnknownSource(ValueError):
    """What was typed does not look like anything this knows how to poll."""


@dataclass(frozen=True)
class Resolved:
    """What a reference turned out to be."""

    kind: str
    #: What identifies it within its kind — a subreddit's name, a handle, a
    #: URL. Stored as the channel's id, and unique per account.
    key: str
    feed_url: str
    title: str


@dataclass(frozen=True)
class SourceKind:
    name: str
    label: str
    #: What to type, said the way somebody would say it.
    example: str
    #: Only YouTube videos can be put into a YouTube playlist. Everything else
    #: can only fill a feed that lives inside De-Algo.
    playlistable: bool = False


KINDS: tuple[SourceKind, ...] = (
    SourceKind("youtube", "YouTube", "@handle, a channel URL, or a UC… id", playlistable=True),
    SourceKind("reddit", "Reddit", "r/python, or a subreddit URL"),
    SourceKind("bluesky", "Bluesky", "@name.bsky.social, or a profile URL"),
    SourceKind("substack", "Substack", "name.substack.com"),
    SourceKind("rss", "RSS", "the address of any feed"),
)

_SUBREDDIT = re.compile(r"^/?r/([A-Za-z0-9_]{2,30})/?$")
_BLUESKY_HANDLE = re.compile(r"^@?([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)$")
_YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")


def describe(kind: str) -> SourceKind:
    """What a kind is called, falling back rather than failing: a row stored
    by a later version should still draw on an earlier one."""
    for known in KINDS:
        if known.name == kind:
            return known
    return SourceKind(kind, kind.title(), "")


def resolve(reference: str) -> Resolved:
    """Work out what somebody has typed, without asking anybody.

    Nothing here makes a request: a subreddit, a Bluesky handle and a feed
    address all say where their feed is by their shape alone. YouTube is the
    exception and is resolved by its own service, which may need an API key to
    turn a handle into a channel id — so it is recognised here and sent there.
    """
    typed = (reference or "").strip()
    if not typed:
        raise UnknownSource("Give it something to watch.")

    subreddit = _SUBREDDIT.match(typed)
    if subreddit:
        return _reddit(subreddit.group(1))

    if "://" in typed or typed.startswith("www."):
        return _from_url(typed if "://" in typed else f"https://{typed}")

    # A bare host, which is how a Substack is usually written down.
    if typed.endswith(".substack.com"):
        return _substack(typed)

    handle = _BLUESKY_HANDLE.match(typed)
    if handle and (typed.endswith(".bsky.social") or typed.count(".") >= 1):
        return _bluesky(handle.group(1))

    raise UnknownSource(
        f"“{typed}” is not something this knows how to follow. Try r/name, a "
        "Bluesky handle, or the address of a feed."
    )


def _from_url(url: str) -> Resolved:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")

    if host in _YOUTUBE_HOSTS:
        # Left to the YouTube service: a handle needs an API call to become a
        # channel id, and that is its business rather than this file's.
        raise _IsYouTube(url)

    if host.endswith("reddit.com"):
        found = re.match(r"^/r/([A-Za-z0-9_]{2,30})", path)
        if found:
            return _reddit(found.group(1))

    if host.endswith("bsky.app"):
        found = re.match(r"^/profile/([^/]+)", path)
        if found:
            return _bluesky(found.group(1))

    if host.endswith(".substack.com"):
        return _substack(host)

    # Anything else is taken at its word: the address of a feed, or of a page
    # that is one. Whether it parses is settled by reading it, not by guessing
    # from the address.
    return Resolved(kind="rss", key=url, feed_url=url, title=host or url)


class _IsYouTube(UnknownSource):
    """Recognised as YouTube, which resolves its own references.

    An ``UnknownSource`` because that is true from here: this file does not
    know how to follow it, and callers reach YouTube by asking
    ``looks_like_youtube`` first. One that forgot gets an error it already
    catches rather than one escaping to the top.
    """

    def __init__(self, url: str):
        super().__init__(f"{url} is a YouTube address; that kind resolves its own.")
        self.url = url


def looks_like_youtube(reference: str) -> bool:
    """Whether this is YouTube's to resolve rather than ours."""
    typed = (reference or "").strip()
    if not typed:
        return False
    if re.match(r"^UC[\w-]{22}$", typed):
        return True
    if typed.startswith("@") and "." not in typed:
        return True  # a bare @handle is YouTube's shape; a dotted one is Bluesky's
    host = (urlparse(typed if "://" in typed else f"https://{typed}").hostname or "").lower()
    return host in _YOUTUBE_HOSTS


def _reddit(name: str) -> Resolved:
    return Resolved(
        kind="reddit",
        key=f"r/{name}",
        feed_url=f"https://www.reddit.com/r/{name}/.rss",
        title=f"r/{name}",
    )


def _bluesky(handle: str) -> Resolved:
    return Resolved(
        kind="bluesky",
        key=f"@{handle}",
        feed_url=f"https://bsky.app/profile/{handle}/rss",
        title=f"@{handle}",
    )


def _substack(host: str) -> Resolved:
    name = host.split(".")[0]
    return Resolved(
        kind="substack",
        key=host,
        feed_url=f"https://{host}/feed",
        title=name.replace("-", " ").title(),
    )


# Where somebody else publishes the same feeds, for the hosts that ration us.
# Open RSS is a nonprofit that generates feeds for sites which do not, and is
# the usual answer for Reddit. Offered as a suggestion only: it is a service
# we do not run, and whether to lean on it is the reader's call.
OPEN_RSS = "https://openrss.org"


def suggest_mirror(kind: str, key: str) -> str | None:
    """A mirror worth trying for this source, where one is known.

    Only for the kinds that actually ration a reader. A suggestion nobody
    needs is a field somebody has to think about for no reason.
    """
    name = (key or "").strip()
    if kind == "reddit" and name.startswith("r/"):
        return f"{OPEN_RSS}/reddit.com/{name}"
    return None


def item_url(kind: str, key: str, link: str | None) -> str | None:
    """Where an item lives. The link the feed gave, which every kind but
    YouTube supplies; YouTube items are addressed by their video id and are
    built elsewhere."""
    return link
