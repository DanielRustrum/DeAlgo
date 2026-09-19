"""Channel polling via YouTube's per-channel Atom feed.

The feed is free — it costs no API quota and needs no credentials — and carries
the last ~15 uploads of a channel, which is everything De-Algo needs to notice
new videos. The Data API is only used for the things the feed cannot do:
resolving a handle to a channel id, reading durations, and writing playlists.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Iterable
from xml.etree import ElementTree

import httpx

from ..sources import patience

FEED_URL = "https://www.youtube.com/feeds/videos.xml"

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")


@dataclass(frozen=True)
class FeedEntry:
    video_id: str
    title: str
    published_at: dt.datetime | None
    thumbnail_url: str | None
    # The feed links Shorts as /shorts/<id>, which is the only way to spot one
    # without spending API quota.
    is_short: bool = False
    # What kind of item this is, and where it lives, for the sources that are
    # not YouTube. This reader only ever produces videos; the general one
    # fills these in.
    kind: str = "video"
    link: str | None = None
    summary: str | None = None


@dataclass(frozen=True)
class FeedResult:
    channel_id: str
    channel_title: str
    entries: list[FeedEntry]


def _parse_timestamp(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def normalize_channel_id(raw: str) -> str:
    """The feed's own ``<yt:channelId>`` omits the ``UC`` prefix; entries keep it."""
    value = (raw or "").strip()
    if value and not value.startswith("UC"):
        return "UC" + value
    return value


def parse_feed(xml_text: str) -> FeedResult:
    """Parse a channel Atom feed into entries, newest first."""
    root = ElementTree.fromstring(xml_text)
    channel_id = normalize_channel_id(root.findtext("yt:channelId", namespaces=_NS) or "")
    channel_title = (root.findtext("atom:title", namespaces=_NS) or "").strip()

    entries: list[FeedEntry] = []
    for node in root.findall("atom:entry", _NS):
        video_id = (node.findtext("yt:videoId", namespaces=_NS) or "").strip()
        if not video_id:
            continue
        group = node.find("media:group", _NS)
        thumb = None
        if group is not None:
            thumb_node = group.find("media:thumbnail", _NS)
            if thumb_node is not None:
                thumb = thumb_node.get("url")

        is_short = False
        for link in node.findall("atom:link", _NS):
            if link.get("rel") == "alternate" and "/shorts/" in (link.get("href") or ""):
                is_short = True

        entries.append(
            FeedEntry(
                video_id=video_id,
                title=(node.findtext("atom:title", namespaces=_NS) or "").strip(),
                published_at=_parse_timestamp(node.findtext("atom:published", namespaces=_NS)),
                thumbnail_url=thumb,
                is_short=is_short,
            )
        )

    entries.sort(key=lambda e: e.published_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    return FeedResult(channel_id=channel_id, channel_title=channel_title, entries=entries)


def fetch_feed(channel_id: str, client: httpx.Client) -> FeedResult:
    # YouTube has never asked us to wait, but the courtesy costs nothing and
    # the day it starts asking is not the day to begin listening.
    patience.hold(FEED_URL)
    response = client.get(FEED_URL, params={"channel_id": channel_id})
    patience.note(response)
    response.raise_for_status()
    return parse_feed(response.text)


def newest_first(entries: Iterable[FeedEntry]) -> list[FeedEntry]:
    return sorted(
        entries,
        key=lambda e: e.published_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
        reverse=True,
    )
