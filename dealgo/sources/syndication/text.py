"""The words and dates inside a feed entry, cleaned of markup."""

from __future__ import annotations

import datetime as dt
import html
import re
from xml.etree import ElementTree

NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


# Timestamps arrive in two standards and several dialects of each.
_RFC_822 = "%a, %d %b %Y %H:%M:%S %z"


_TAG_RE = re.compile(r"<[^>]+>")


# A picture is not always in an <img>. Reddit writes an image post as a link
# to the file, and that link is the full-size one — the <img> and the
# media:thumbnail beside it are both crops a few hundred pixels wide.
HREF_RE = re.compile(r"""<a\b[^>]*?\bhref=["']([^"']+)["']""", re.I)


def plain_tag(tag: str) -> str:
    """An element's name without the namespace it was declared in."""
    return tag.rsplit("}", 1)[-1]


def summary_of(
    node: ElementTree.Element, wanted: tuple[str, ...], pictures: list[str] | None = None
) -> str | None:
    """The entry's own words, with the markup taken out.

    Kept as text rather than as HTML: it is shown in a card, and a feed is not
    a place to accept markup from.
    """
    for name in wanted:
        found = node.findtext(name, namespaces=NAMESPACES)
        if found and found.strip():
            words = clean_text(html.unescape(_TAG_RE.sub(" ", found)))
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


def clean_text(raw: str) -> str:
    """Text with its runs of whitespace squeezed to single spaces."""
    return " ".join(raw.split())


def parse_date(raw: str | None) -> dt.datetime | None:
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
