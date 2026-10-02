"""Reading a feed from an address or from text, and telling it from a page that is not one."""

from __future__ import annotations

import datetime as dt
from xml.etree import ElementTree

import httpx

from .. import patience
from .atom import read_atom
from .entries import Feed
from .rss import read_rss
from .text import plain_tag


def fetch(url: str, client: httpx.Client) -> Feed:
    # Asked before the request rather than after the refusal: a host that has
    # told us its budget is spent will only refuse us again, and being refused
    # is what deepens a block.
    patience.hold(url)
    response = client.get(url, headers={"Accept": "application/rss+xml, application/atom+xml, */*"})
    patience.note(response)
    response.raise_for_status()
    return parse(response.text)


#: What the outermost element of a feed is called. RSS 2.0 says `rss`, Atom
#: says `feed`, and RSS 1.0 wraps the whole thing in RDF.
FEED_ROOTS = ("rss", "feed", "rdf")


def parse(xml_text: str) -> Feed:
    """Read a feed, newest first, whichever shape it is.

    Refuses anything that is not one. A page of HTML is often well-formed
    XML, so parsing alone does not settle it — an ordinary web page would
    come back as a feed with no title and nothing in it, which reads exactly
    like a feed that has published nothing yet. Plenty of sites answer 200 to
    any address, so this is the difference between finding a feed and being
    told there is one.
    """
    root = ElementTree.fromstring(xml_text)
    tag = plain_tag(root.tag)
    if tag.lower() not in FEED_ROOTS and root.find("channel") is None:
        raise ElementTree.ParseError(f"the outermost element is <{tag}>, not a feed")

    feed = read_rss(root) if tag == "rss" or root.find("channel") is not None else read_atom(root)
    return Feed(
        title=feed.title,
        items=sorted(
            feed.items,
            key=lambda item: item.published_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            reverse=True,
        ),
    )
