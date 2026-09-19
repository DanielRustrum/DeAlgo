"""Reading a feed, whichever of the two shapes it is written in.

RSS 2.0 and Atom are different enough to need separate readers and similar
enough that one set of fields covers both. Everything here is parsing: nothing
knows what a Reddit post or a YouTube video is, only what a feed entry is.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse
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
_IMG_RE = re.compile(r"""<img\b[^>]*?\bsrc=["']([^"']+)["']""", re.I)
# A picture is not always in an <img>. Reddit writes an image post as a link
# to the file, and that link is the full-size one — the <img> and the
# media:thumbnail beside it are both crops a few hundred pixels wide.
_HREF_RE = re.compile(r"""<a\b[^>]*?\bhref=["']([^"']+)["']""", re.I)
_WIDTH_RE = re.compile(r"[?&]width=(\d+)")
_IMAGE_FILE_RE = re.compile(r"\.(?:png|jpe?g|gif|webp|avif)$", re.I)
# Hosts that serve nothing but images, for the addresses that carry no
# extension to go on.
_IMAGE_HOSTS = (
    "preview.redd.it",
    "external-preview.redd.it",
    "i.redd.it",
    "i.imgur.com",
)


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
    #: Every picture the entry carries, in the order it carried them. Reddit
    #: puts them in the post's own HTML; a plain blog often does too.
    images: list[str] = field(default_factory=list)


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
                summary=_summary(node, ("description", "content:encoded"), _images(node)),
                thumbnail_url=_thumbnail(node),
                images=_images(node),
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
                summary=_summary(node, ("atom:summary", "atom:content"), _images(node)),
                thumbnail_url=_thumbnail(node),
                images=_images(node),
            )
        )
    return Feed(title=_clean(root.findtext("atom:title", namespaces=_NS) or ""), items=items)


def _summary(
    node: ElementTree.Element, wanted: tuple[str, ...], pictures: list[str] | None = None
) -> str | None:
    """The entry's own words, with the markup taken out.

    Kept as text rather than as HTML: it is shown in a card, and a feed is not
    a place to accept markup from.
    """
    for name in wanted:
        found = node.findtext(name, namespaces=_NS)
        if found and found.strip():
            words = _clean(html.unescape(_TAG_RE.sub(" ", found)))
            return _without_addresses(words, pictures)[:2000] or None
    return None


def _without_addresses(words: str, pictures: list[str] | None) -> str:
    """Take the picture's address out of the words.

    Reddit writes an image post as a link whose visible text is the address
    itself, so stripping the markup leaves a line of URL above the writing.
    The picture is shown as a picture; its address is not the post.
    """
    if not pictures:
        return words
    wanted = set(pictures)
    kept = [piece for piece in words.split(" ") if piece not in wanted]
    return " ".join(kept).strip()


def _thumbnail(node: ElementTree.Element) -> str | None:
    """The best picture to lead with.

    "Best" is "biggest it offered", because a feed's declared thumbnail is
    often a 140px crop while the same picture sits in the entry's own HTML at
    640. The card is sized for a video still, and a 140px image in it looks
    like a mistake.

    The URL is used exactly as given. Reddit signs its preview addresses over
    the size parameters, so asking for a bigger one by editing the query only
    earns a 403.
    """
    offered = [url for url in _declared(node) + _in_words(node) if url]
    if not offered:
        return None
    return max(offered, key=_declared_width)


def _declared(node: ElementTree.Element) -> list[str]:
    """Pictures the feed names as pictures, rather than ones in its prose."""
    found: list[str] = []
    for name in ("media:thumbnail", "media:content"):
        for element in node.findall(name, _NS):
            url = element.get("url")
            if url and (element.get("type") or "image/").startswith("image/"):
                found.append(url)
    enclosure = node.find("enclosure")
    if enclosure is not None and (enclosure.get("type") or "").startswith("image/"):
        url = enclosure.get("url")
        if url:
            found.append(url)
    return found


def _in_words(node: ElementTree.Element) -> list[str]:
    """Pictures inside the entry's own HTML, which is where Reddit puts them."""
    found: list[str] = []
    for name in ("description", "content:encoded", "atom:summary", "atom:content"):
        body = node.findtext(name, namespaces=_NS)
        if not body:
            continue
        # The HTML arrives escaped inside the XML, so it is text to us until
        # it is unescaped — the parser has already done that by this point.
        # The HTML is escaped inside the XML, so one unescape gets us the
        # markup and its entities survive into the attributes. A Reddit
        # preview address is signed over its query, so an "&amp;" left in it
        # is not a cosmetic difference — it is a URL that will be refused.
        found.extend(html.unescape(match.group(1)) for match in _IMG_RE.finditer(body))
        found.extend(
            url
            for url in (html.unescape(m.group(1)) for m in _HREF_RE.finditer(body))
            if _is_a_picture(url)
        )
    return found


def _is_a_picture(url: str) -> bool:
    """Whether a link points at an image rather than at another page.

    By the file it names, or by a host that serves nothing else — Reddit's
    preview addresses carry the extension before the query, and its [link]
    and [comments] anchors point at neither.
    """
    parsed = urlparse(url)
    if _IMAGE_FILE_RE.search(parsed.path):
        return True
    return (parsed.hostname or "").lower() in _IMAGE_HOSTS


def _declared_width(url: str) -> int:
    """What the address says it is, for picking between two of the same thing.

    Only a hint: an address that does not say is treated as ordinary rather
    than as huge, so a named size always beats an unnamed one.
    """
    found = _WIDTH_RE.search(url)
    return int(found.group(1)) if found else 1


def _images(node: ElementTree.Element) -> list[str]:
    """Every picture the entry carries, in order and without repeats.

    The lead picture first where it is one of them, so opening an item shows
    the same image the card did rather than starting somewhere else.
    """
    seen: list[str] = []
    for url in _in_words(node) + _declared(node):
        if url and url not in seen:
            seen.append(url)
    lead = _thumbnail(node)
    if lead in seen:
        seen.remove(lead)
        seen.insert(0, lead)
    return seen[:20]


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
