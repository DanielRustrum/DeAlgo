"""Reading RSS 2.0 and RSS 1.0 (RDF)."""

from __future__ import annotations

from xml.etree import ElementTree

from .entries import Feed, Item
from .pictures import images_in, thumbnail_of
from .text import NAMESPACES, clean_text, parse_date, summary_of


def read_rss(root: ElementTree.Element) -> Feed:
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
                title=clean_text(node.findtext("title") or ""),
                link=link,
                published_at=parse_date(node.findtext("pubDate") or node.findtext("dc:date", namespaces=NAMESPACES)),
                summary=summary_of(node, ("description", "content:encoded"), images_in(node)),
                thumbnail_url=thumbnail_of(node),
                images=images_in(node),
            )
        )
    return Feed(title=clean_text(channel.findtext("title") or ""), items=items)
