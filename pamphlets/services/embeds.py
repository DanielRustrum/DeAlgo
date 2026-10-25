"""A video's address, as something a page can play.

YouTube and Vimeo give a player of their own to put in a frame: YouTube's
from youtube-nocookie.com, as Focus mode's is, so watching on a pamphlet sets
no cookie until play is pressed. A file — .mp4, .webm, .ogg — plays in the
browser's own player. Anything else is a link to where it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

#: A YouTube video's id: eleven of these.
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
#: Files a browser plays by itself.
FILES = (".mp4", ".webm", ".ogg", ".ogv", ".mov", ".m4v")


@dataclass(frozen=True)
class Embed:
    """How a page shows one video."""

    #: "youtube" or "vimeo" for a frame, "file" for the browser's player,
    #: "link" for neither, "" for no video at all.
    kind: str
    #: What goes in the frame or the player; the address itself for a link.
    src: str
    #: Where the video lives, for the link under it.
    page: str


def youtube_id(url: str) -> str:
    """A YouTube video's id from any of the ways its address is written, or ""."""
    parts = urlparse(url)
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    found = ""
    if host == "youtu.be":
        found = parts.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com", "music.youtube.com"):
        if parts.path == "/watch":
            found = (parse_qs(parts.query).get("v") or [""])[0]
        else:
            bits = [one for one in parts.path.split("/") if one]
            if len(bits) >= 2 and bits[0] in ("embed", "shorts", "live", "v"):
                found = bits[1]
    return found if YOUTUBE_ID.match(found) else ""


def embed_for(url: str) -> Embed:
    """How to show the video at `url`."""
    url = (url or "").strip()
    if not url:
        return Embed("", "", "")
    found = youtube_id(url)
    if found:
        return Embed("youtube", f"https://www.youtube-nocookie.com/embed/{found}?rel=0", url)
    parts = urlparse(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    if host in ("vimeo.com", "player.vimeo.com"):
        number = next((one for one in parts.path.split("/") if one.isdigit()), "")
        if number:
            return Embed("vimeo", f"https://player.vimeo.com/video/{number}", url)
    if parts.path.lower().endswith(FILES):
        return Embed("file", url, url)
    return Embed("link", url, url)
