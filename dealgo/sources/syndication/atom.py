"""Reading Atom."""

from __future__ import annotations

from xml.etree import ElementTree

from .entries import Feed, Item
from .pictures import images_in, thumbnail_of
from .text import NAMESPACES, clean_text, parse_date, summary_of


def read_atom(root: ElementTree.Element) -> Feed:
    """An Atom document's entries, as items."""
    items: list[Item] = []
    for node in root.findall("atom:entry", NAMESPACES):
        link = None
        for anchor in node.findall("atom:link", NAMESPACES):
            if anchor.get("rel") in (None, "alternate"):
                link = anchor.get("href")
                break
        guid = (node.findtext("atom:id", namespaces=NAMESPACES) or "").strip() or link
        if not guid:
            continue
        items.append(
            Item(
                guid=guid,
                title=clean_text(node.findtext("atom:title", namespaces=NAMESPACES) or ""),
                link=link,
                published_at=parse_date(
                    node.findtext("atom:published", namespaces=NAMESPACES)
                    or node.findtext("atom:updated", namespaces=NAMESPACES)
                ),
                summary=summary_of(node, ("atom:summary", "atom:content"), images_in(node)),
                thumbnail_url=thumbnail_of(node),
                images=images_in(node),
            )
        )
    return Feed(title=clean_text(root.findtext("atom:title", namespaces=NAMESPACES) or ""), items=items)
