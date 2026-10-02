"""Finding the pictures an entry carries: declared, enclosed, or in its words."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse
from xml.etree import ElementTree

from .text import HREF_RE, NAMESPACES

_IMG_RE = re.compile(r"""<img\b[^>]*?\bsrc=["']([^"']+)["']""", re.I)


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


def thumbnail_of(node: ElementTree.Element) -> str | None:
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
    return max(offered, key=declared_width)


def _declared(node: ElementTree.Element) -> list[str]:
    """Pictures the feed names as pictures, rather than ones in its prose."""
    found: list[str] = []
    for name in ("media:thumbnail", "media:content"):
        # Anywhere inside the entry, not only directly under it. YouTube
        # wraps its thumbnail in a <media:group>, and a reader that only
        # looked one level down found nothing at all there.
        for element in node.findall(f".//{name}", NAMESPACES):
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
        body = node.findtext(name, namespaces=NAMESPACES)
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
            for url in (html.unescape(m.group(1)) for m in HREF_RE.finditer(body))
            if _is_a_picture(url)
        )
    return found


def pictures_in(words: str) -> list[str]:
    """Picture addresses sitting loose in a piece of plain text.

    For entries already stored, whose markup was thrown away before anything
    knew to look for a picture in it — the address survived as text, which is
    exactly why it was showing up as the first line of the post. Reading it
    back out of there needs no network and reaches items the feed has long
    since stopped listing.
    """
    found: list[str] = []
    for token in html.unescape(words or "").split():
        if token.startswith(("http://", "https://")) and _is_a_picture(token):
            if token not in found:
                found.append(token)
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


def declared_width(url: str) -> int:
    """What the address says it is, for picking between two of the same thing.

    Only a hint: an address that does not say is treated as ordinary rather
    than as huge, so a named size always beats an unnamed one.
    """
    found = _WIDTH_RE.search(url)
    return int(found.group(1)) if found else 1


def images_in(node: ElementTree.Element) -> list[str]:
    """Every picture the entry carries, in order and without repeats.

    The lead picture first where it is one of them, so opening an item shows
    the same image the card did rather than starting somewhere else.
    """
    seen: list[str] = []
    for url in _in_words(node) + _declared(node):
        if url and url not in seen:
            seen.append(url)
    lead = thumbnail_of(node)
    if lead in seen:
        seen.remove(lead)
        seen.insert(0, lead)
    return seen[:20]
