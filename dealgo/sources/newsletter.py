"""Finding a newsletter's feed when all you have is where it lives.

A newsletter is a publication you know by name — platformer.news, not
platformer.news/feed. Substack, Ghost, beehiiv, Buttondown and WordPress all
publish a feed and all put it somewhere slightly different, so rather than
making somebody find out which of those theirs runs on, this asks the site.

Two ways, the site's own answer first:

* **The page says so.** Anything that publishes a feed usually declares it in
  its head, as ``<link rel="alternate" type="application/rss+xml">``. One
  request, and it is the site's answer rather than a guess at it.
* **The usual places.** A site that declares nothing may still serve one at a
  path everything uses. Tried in turn, and each confirmed by being read — a
  page of HTML at /feed is not a feed, and plenty of sites answer 200 to
  anything.

This is the half that makes requests, which is why it is here and not in
``kinds``: what a reference *is* is worked out from its spelling, and where
its feed lives is worked out by asking.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx

from . import patience, syndication

#: What a site's own head has to say to count as declaring a feed.
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")

#: Where to look when it declares nothing. In the order they are worth
#: trying: the two that nearly everything uses, then the ones a particular
#: generator prefers. Substack and beehiiv serve /feed, Ghost serves /rss,
#: Hugo writes /index.xml, and WordPress answers both /feed and /feed/.
USUAL_PLACES = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml")

#: The paths worth trying on the other of www and the bare domain. Fewer,
#: because by then two things are being guessed at once.
ALSO_TRIED = ("/feed", "/rss", "/feed.xml")

#: How many addresses are worth reading before giving up. Each is a request
#: to somebody else's server, and a site that has not answered by the tenth
#: is not hiding its feed, it has not got one.
MOST_TRIED = 10

#: How much of a page to read looking for its head. A declaration is in the
#: head or it is nowhere, and a page that buries one a megabyte down is not
#: one this should be holding in memory to find out.
ENOUGH_PAGE = 512 * 1024


@dataclass(frozen=True)
class Found:
    """A newsletter's feed, and what the feed calls itself."""

    feed_url: str
    title: str


class _Heads(HTMLParser):
    """Every feed a page's head declares, in the order it declares them.

    A parser rather than a regular expression: a `<link>` may carry its
    attributes in any order, quoted three ways, and the thing being read is
    somebody else's markup rather than something this app wrote.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[str] = []
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            # Past the head. Anything below it is a link on the page rather
            # than the page saying what it publishes.
            self.done = True
            return
        if tag != "link" or self.done:
            return
        said = {name: (value or "") for name, value in attrs}
        rels = said.get("rel", "").lower().split()
        if "alternate" not in rels:
            return
        if said.get("type", "").lower().split(";")[0].strip() not in FEED_TYPES:
            return
        href = said.get("href", "").strip()
        if href:
            self.found.append(href)


def declared(html_text: str, base: str) -> list[str]:
    """The feeds a page says it publishes, as addresses that can be read."""
    reader = _Heads()
    try:
        reader.feed(html_text[:ENOUGH_PAGE])
    except (AssertionError, ValueError):  # pragma: no cover - malformed markup
        return []
    seen: list[str] = []
    for href in reader.found:
        whole = urljoin(base, href)
        if whole not in seen:
            seen.append(whole)
    return seen


def sibling(site: str) -> str:
    """The same site on the other of www and the bare domain.

    Worth asking because plenty of places serve their page on one and their
    feed only on the other — a Substack answers at the bare domain and 404s
    on its own /feed there, while www serves both. And a site that declares
    a feed is not necessarily right about where it is: astralcodexten.com
    names a /feed that is not there.
    """
    parts = urlparse(site)
    host = (parts.hostname or "").lower()
    if not host:
        return ""
    other = host[4:] if host.startswith("www.") else f"www.{host}"
    if other.count(".") < 1:
        return ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme or 'https'}://{other}{port}/"


def candidates(site: str, html_text: str = "") -> list[str]:
    """Every address worth reading for this site, best first.

    The site's own declaration beats a guess, the usual places beat guessing
    at the host as well, and a guess already made is not worth making twice.
    """
    found = declared(html_text, site) if html_text else []
    also = sibling(site)
    for base, paths in ((site, USUAL_PLACES), (also, ALSO_TRIED if also else ())):
        for path in paths:
            whole = urljoin(base, path)
            if whole not in found:
                found.append(whole)
    return found[:MOST_TRIED]


def site_url(typed: str) -> str:
    """What was typed, as the address of a site.

    Forgiving about how it is written and strict about what comes out: a
    newsletter is named by where it lives, and "platformer.news",
    "www.platformer.news" and "https://platformer.news/archive" are all the
    same answer to "which newsletter".
    """
    said = (typed or "").strip()
    if not said:
        return ""
    whole = said if "://" in said else f"https://{said.lstrip('/')}"
    parts = urlparse(whole)
    host = (parts.hostname or "").lower()
    # Something with no dot in it is a word, not a site. Guessing ".com" from
    # one would watch whatever happens to be there rather than what was meant.
    if not host or "." not in host:
        return ""
    # One spelling, so typing it two ways does not watch it twice. Anything
    # that serves only on www redirects to it, and the client follows.
    if host.startswith("www.") and host.count(".") > 1:
        host = host[4:]
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme or 'https'}://{host}{port}/"


def find(site: str, client: httpx.Client) -> Found | None:
    """The feed this newsletter publishes, or None if it publishes none.

    None rather than a raise: "that site has no feed" is an ordinary answer
    to give somebody who has just typed a name, not a failure of this app.
    """
    page, landed = _read(site, client)
    # From where the page actually came from, which a redirect may have moved:
    # what a site declares is relative to where it answered, not to what was
    # typed into the box.
    for address in candidates(landed or site, page):
        feed = _feed_at(address, client)
        if feed is not None:
            return Found(feed_url=address, title=feed.title)
    return None


def _read(url: str, client: httpx.Client) -> tuple[str, str]:
    """A site's front page and where it turned out to live.

    "" for both if it will not give one up: a site that refuses its own page
    may still serve a feed at one of the usual places, so this answers with
    nothing rather than stopping.
    """
    try:
        patience.hold(url)
        response = client.get(url, headers={"Accept": "text/html, */*"})
        patience.note(response)
        response.raise_for_status()
    except (httpx.HTTPError, patience.RateLimited):
        return "", ""
    landed = str(getattr(response, "url", "") or url)
    if "html" not in response.headers.get("content-type", "").lower():
        return "", landed
    return response.text, landed


def _feed_at(url: str, client: httpx.Client) -> syndication.Feed | None:
    """Whether there is a feed at this address, settled by reading it."""
    try:
        return syndication.fetch(url, client)
    except (httpx.HTTPError, ElementTree.ParseError, patience.RateLimited):
        return None
