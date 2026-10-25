"""A video's address, as something a page can play.

Pamphlets knows no video service. An address one of the installed plugins
claims as one of its videos (`player.videos`) plays in that plugin's player
frame (plugins/registry/players.py). A file — .mp4, .webm, .ogg — plays in
the browser's own player. Anything else is a link to where it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

#: Files a browser plays by itself.
FILES = (".mp4", ".webm", ".ogg", ".ogv", ".mov", ".m4v")


@dataclass(frozen=True)
class Embed:
    """How a page shows one video."""

    #: "frame" for a plugin's player, "file" for the browser's player,
    #: "link" for neither, "" for no video at all.
    kind: str
    #: What goes in the frame or the player; the address itself for a link.
    src: str
    #: Where the video lives, for the link under it.
    page: str


def _origin() -> str:
    """Where Pamphlets is, for a player that asks: a page's own browser may
    know better, but a page drawn on the server has only this to say."""
    from ..config import CONFIG

    found = urlparse(CONFIG.public_url)
    return f"{found.scheme}://{found.netloc}"


def embed_for_item(source_kind: str, key: str, page: str) -> Embed:
    """How to show one item: in its source's player if its plugin gives one,
    else as its address would be."""
    from ..plugins import registry

    player = registry.current().player(source_kind)
    src = player.src(key, autoplay=False, origin=_origin()) if player is not None else ""
    return Embed("frame", src, page) if src else embed_for(page)


def embed_for(url: str) -> Embed:
    """How to show the video at `url`."""
    from ..plugins import registry

    url = (url or "").strip()
    if not url:
        return Embed("", "", "")
    parts = urlparse(url)
    if parts.scheme not in ("http", "https"):
        return Embed("", "", "")
    claimed = registry.current().video_at(url)
    if claimed is not None:
        player, key = claimed
        # Not started until it is pressed: a page of them must not all play.
        return Embed("frame", player.src(key, autoplay=False, origin=_origin()), url)
    if parts.path.lower().endswith(FILES):
        return Embed("file", url, url)
    return Embed("link", url, url)
