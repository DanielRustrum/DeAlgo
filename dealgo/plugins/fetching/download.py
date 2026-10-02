"""Fetching a plugin: download the archive, then hand it to be vetted."""

from __future__ import annotations

import io

import httpx

from ..runtime import PluginError
from .addresses import USUAL_REFS, archives, repository_name
from .archive import Fetched, unpack

#: How much of an archive is worth downloading. A plugin is a Lua file and
#: whatever small things sit beside it; anything approaching this is not one.
MOST_ARCHIVE_BYTES = 2 * 1024 * 1024


def fetch(url: str, client: httpx.Client, *, ref: str = "") -> Fetched:
    """Take a plugin out of a repository, or say why it could not be.

    Nothing is written and nothing is loaded: this hands back the text, and
    what happens to it is the same as for a file somebody uploaded.
    """
    tried: list[str] = []
    for address, wanted in archives(url, ref):
        body = _download(address, client)
        if body is None:
            tried.append(address)
            continue
        return unpack(body, origin=url, ref=wanted, named=repository_name(url))
    said = "that branch" if ref else " or ".join(USUAL_REFS)
    raise PluginError(
        f"Nothing to download there. Checked {said}; is the repository public?"
    )


def _download(url: str, client: httpx.Client) -> bytes | None:
    """An archive, or None where there is not one there.

    Read in pieces and stopped the moment it is too big, rather than asked
    for whole and measured afterwards: what a server says its length is, is
    somebody else's claim about it.
    """
    try:
        with client.stream("GET", url, headers={"Accept": "application/gzip, */*"}) as answer:
            if answer.status_code != 200:
                return None
            # Count what actually arrives, and stop as soon as it is too much.
            held = io.BytesIO()
            for piece in answer.iter_bytes():
                held.write(piece)
                if held.tell() > MOST_ARCHIVE_BYTES:
                    raise PluginError(
                        "That download is far too big to be a plugin "
                        f"(more than {MOST_ARCHIVE_BYTES // 1024} KB)."
                    )
            return held.getvalue()
    except httpx.HTTPError as exc:
        raise PluginError(f"Could not reach that repository: {exc}") from exc
