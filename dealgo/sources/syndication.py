"""Reading a feed, whichever of the two shapes it is written in.

RSS 2.0 and Atom are different enough to need separate readers and similar
enough that one set of fields covers both. Everything here is parsing: nothing
knows what a Reddit post or a YouTube video is, only what a feed entry is.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree

import httpx

from . import patience

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

# Timestamps arrive in two standards and several dialects of each.
_RFC_822 = "%a, %d %b %Y %H:%M:%S %z"
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Item:
    """One entry, said the same way whatever the feed was written in."""

    #: Stable for this entry, for as long as the feed keeps saying it. The
    #: entry's own id where it has one, its link where it does not.
    guid: str
    title: str
    link: str | None
    published_at: dt.datetime | None
    summary: str | None = None
    thumbnail_url: str | None = None


@dataclass(frozen=True)
class Feed:
    title: str
    items: list[Item] = field(default_factory=list)


def fetch(url: str, client: httpx.Client) -> Feed:
    # Asked before the request rather than after the refusal: a host that has
    # told us its budget is spent will only refuse us again, and being refused
    # is what deepens a block.
    patience.hold(url)
    response = client.get(url, headers={"Accept": "application/rss+xml, application/atom+xml, */*"})
    patience.note(response)
    response.raise_for_status()
    return parse(response.text)


def parse(xml_text: str) -> Feed:
    """Read a feed, newest first, whichever shape it is."""
    root = ElementTree.fromstring(xml_text)
    tag = _plain(root.tag)

    feed = _read_rss(root) if tag == "rss" or root.find("channel") is not None else _read_atom(root)
    return Feed(
        title=feed.title,
        items=sorted(
            feed.items,
            key=lambda item: item.published_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            reverse=True,
        ),
    )


def _plain(tag: str) -> str:
    """An element's name without the namespace it was declared in."""
    return tag.rsplit("}", 1)[-1]


def _read_rss(root: ElementTree.Element) -> Feed:
    channel = root.find("channel")
    if channel is None:
        return Feed(title="")

    items: list[Item] = []
    for node in channel.findall("item"):
        link = (node.findtext("link") or "").strip() or None
        guid = (node.findtext("guid") or "").strip() or link
        if not guid:
            continue
        items.append(
            Item(
                guid=guid,
                title=_clean(node.findtext("title") or ""),
                link=link,
                published_at=_stamp(node.findtext("pubDate") or node.findtext("dc:date", namespaces=_NS)),
                summary=_summary(node, ("description", "content:encoded")),
                thumbnail_url=_thumbnail(node),
            )
        )
    return Feed(title=_clean(channel.findtext("title") or ""), items=items)


def _read_atom(root: ElementTree.Element) -> Feed:
    items: list[Item] = []
    for node in root.findall("atom:entry", _NS):
        link = None
        for anchor in node.findall("atom:link", _NS):
            if anchor.get("rel") in (None, "alternate"):
                link = anchor.get("href")
                break
        guid = (node.findtext("atom:id", namespaces=_NS) or "").strip() or link
        if not guid:
            continue
        items.append(
            Item(
                guid=guid,
                title=_clean(node.findtext("atom:title", namespaces=_NS) or ""),
                link=link,
                published_at=_stamp(
                    node.findtext("atom:published", namespaces=_NS)
                    or node.findtext("atom:updated", namespaces=_NS)
                ),
                summary=_summary(node, ("atom:summary", "atom:content")),
                thumbnail_url=_thumbnail(node),
            )
        )
    return Feed(title=_clean(root.findtext("atom:title", namespaces=_NS) or ""), items=items)


def _summary(node: ElementTree.Element, wanted: tuple[str, ...]) -> str | None:
    """The entry's own words, with the markup taken out.

    Kept as text rather than as HTML: it is shown in a card, and a feed is not
    a place to accept markup from.
    """
    for name in wanted:
        found = node.findtext(name, namespaces=_NS)
        if found and found.strip():
            return _clean(_TAG_RE.sub(" ", found))[:2000]
    return None


def _thumbnail(node: ElementTree.Element) -> str | None:
    for name in ("media:thumbnail", "media:content"):
        found = node.find(name, _NS)
        if found is not None and found.get("url"):
            return found.get("url")
    enclosure = node.find("enclosure")
    if enclosure is not None and (enclosure.get("type") or "").startswith("image/"):
        return enclosure.get("url")
    return None


def _clean(raw: str) -> str:
    return " ".join(raw.split())


def _stamp(raw: str | None) -> dt.datetime | None:
    """A published time in whichever of the standards it was written in."""
    if not raw:
        return None
    text = raw.strip()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = dt.datetime.strptime(text, _RFC_822)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)
