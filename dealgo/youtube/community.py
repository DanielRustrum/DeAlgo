"""Community posts, scraped from a channel's Posts tab.

There is no Data API for community posts — not in v3, not behind any scope —
so the only way to read them is the page a browser gets. That makes this the
one unofficial corner of De-Algo: it parses the `ytInitialData` blob YouTube
embeds in the HTML, and YouTube can change that shape without notice.

Everything here is therefore written to fail soft. A parse that finds nothing
returns nothing; it never raises into a sync, and a channel whose posts cannot
be read still has its videos collected as usual.

No credentials and no quota are involved, but a page is roughly 1 MB, so posts
are only fetched for channels that are set to take them.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx

from .payload import JsonDict

log = logging.getLogger(__name__)

POSTS_URL = "https://www.youtube.com/channel/{channel_id}/posts"

# Without a browser-shaped User-Agent YouTube serves a consent wall or the
# no-JavaScript page, neither of which carries ytInitialData.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_INITIAL_DATA = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S)

# "3 hours ago", "2 days ago", "1 month ago" — the only date a post carries.
_AGO = re.compile(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago")
_UNITS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,   # 30 days: close enough to sort by
    "year": 31536000,
}


@dataclass(frozen=True)
class Post:
    post_id: str
    text: str
    published_at: dt.datetime | None
    image_urls: list[str] = field(default_factory=list)
    # A post that shares one of the channel's videos, which is worth marking:
    # the video itself usually arrives through the Atom feed as well.
    shared_video_id: str | None = None

    @property
    def title(self) -> str:
        """A one-line stand-in, for the places that list posts beside videos."""
        first = self.text.strip().splitlines()[0] if self.text.strip() else ""
        if len(first) <= 80:
            return first or "(image post)"
        return first[:79].rsplit(" ", 1)[0] + "…"


def _walk(node: Any, key: str) -> Iterator[Any]:
    """Every value stored under `key`, however deep. The blob's shape shifts
    between layouts, so searching beats naming a path."""
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                yield value
            else:
                yield from _walk(value, key)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, key)


def _text_of(node: Any) -> str:
    """Flatten one of YouTube's run lists. Links carry their URL as the text
    only when it was short enough to display, so the run text is what a reader
    actually sees."""
    if not isinstance(node, dict):
        return ""
    if "simpleText" in node:
        return str(node["simpleText"])
    return "".join(str(run.get("text", "")) for run in node.get("runs", []) or [])


def _published(node: Any, now: dt.datetime) -> dt.datetime | None:
    """Posts carry "5 days ago" and nothing else, so the timestamp is derived.

    That is approximate by construction. It only has to be good enough to sort
    a feed, and posts arrive newest-first, which settles anything closer.
    """
    match = _AGO.search(_text_of(node))
    if not match:
        return None
    count, unit = int(match.group(1)), match.group(2)
    return now - dt.timedelta(seconds=count * _UNITS[unit])


def _largest(thumbnails: list[JsonDict]) -> str | None:
    if not thumbnails:
        return None
    best = max(thumbnails, key=lambda t: t.get("width", 0) or 0)
    return best.get("url")


def _images(attachment: JsonDict) -> list[str]:
    urls: list[str] = []
    for image in _walk(attachment, "backstageImageRenderer"):
        url = _largest(image.get("image", {}).get("thumbnails", []) or [])
        if url:
            urls.append(url)
    if not urls:
        # A single-image post keeps its thumbnails one level higher.
        for thumbs in _walk(attachment, "thumbnails"):
            url = _largest(thumbs if isinstance(thumbs, list) else [])
            if url and ("ggpht" in url or "ytimg" in url):
                urls.append(url)
                break
    return urls


def parse_posts(html: str, *, now: dt.datetime | None = None) -> list[Post]:
    """Pull the posts out of a Posts-tab page. Never raises on odd markup."""
    now = now or dt.datetime.now(dt.timezone.utc)
    match = _INITIAL_DATA.search(html)
    if not match:
        log.debug("no ytInitialData in the posts page")
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        log.debug("ytInitialData did not parse as JSON")
        return []

    posts: list[Post] = []
    seen: set[str] = set()
    for renderer in _walk(data, "backstagePostRenderer"):
        if not isinstance(renderer, dict):
            continue
        post_id = renderer.get("postId")
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)

        attachment = renderer.get("backstageAttachment") or {}
        shared = None
        for video in _walk(attachment, "videoRenderer"):
            shared = video.get("videoId")
            break

        posts.append(
            Post(
                post_id=str(post_id),
                text=_text_of(renderer.get("contentText")),
                published_at=_published(renderer.get("publishedTimeText"), now),
                image_urls=_images(attachment),
                shared_video_id=shared,
            )
        )
    return posts


def fetch_posts(channel_id: str, client: httpx.Client) -> list[Post]:
    """The channel's recent posts, or an empty list if they cannot be read."""
    try:
        response = client.get(
            POSTS_URL.format(channel_id=channel_id),
            headers=HEADERS,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.info("could not read posts for %s: %s", channel_id, exc)
        return []
    return parse_posts(response.text)
