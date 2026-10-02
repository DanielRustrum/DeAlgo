"""Pictures that were filed in an item's words, moved to where they belong."""

from __future__ import annotations

import html
import json
import logging

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...db import session_scope
from ...models import (
    Video,
)
from ...sources import syndication

log = logging.getLogger(__name__)


def repair_stored_pictures(session: Session) -> int:
    """Take the pictures out of items that were stored before we looked.

    Every item from a feed elsewhere was filed by a version that threw the
    markup away without reading it for pictures — so the address survived as
    words, which is why it was showing up as the first line of the post.

    It cannot be fixed by polling again: a feed lists its most recent couple
    of dozen items and no more, and most of what is in hand has long since
    fallen off the end of it. But nothing needs fetching. The address is in
    the text, and this reads it back out.

    Run once, at startup. `images` is written even when nothing is found, so
    a row that has been looked at is never looked at again — "we checked, it
    has none" is an answer worth recording.
    """
    # Anything never looked at, and anything still showing its workings: a
    # body that kept its escapes, or one that still leads with the address of
    # its own picture. All three converge after one pass, because the repair
    # removes exactly what selects them.
    waiting = list(
        session.scalars(
            select(Video).where(
                Video.kind == "link",
                or_(
                    Video.images.is_(None),
                    Video.body.like("%&amp;%"),
                    Video.body.like("%&#%"),
                    Video.body.like("http%"),
                ),
            )
        )
    )
    if not waiting:
        return 0

    repaired = 0
    for video in waiting:
        pictures = syndication.pictures_in(video.body or "")
        # Never throws away pictures a reading already found: this one looks
        # only at the words, and a feed names pictures the words do not.
        if pictures or video.images is None:
            video.images = json.dumps(pictures or video.image_list)
        # Tidied either way: a body stored before the words were unescaped
        # carries its "&#32;" into every reading of it, picture or no picture.
        video.body = _words_without(video.body or "", pictures) or None
        if not pictures:
            continue

        biggest = max(pictures, key=syndication.declared_width)
        if not video.thumbnail_url or syndication.declared_width(
            video.thumbnail_url
        ) < syndication.declared_width(biggest):
            video.thumbnail_url = biggest
        repaired += 1

    session.flush()
    log.info("read pictures back out of %d stored items", repaired)
    return repaired


def repair_stored_pictures_now() -> int:
    """The repair over a session of its own, for a caller that has none open.

    `init_db` already holds one and passes it in; everybody else just wants
    it done.
    """
    with session_scope() as session:
        return repair_stored_pictures(session)


def _words_without(body: str, pictures: list[str]) -> str:
    """The post's words, unescaped, with the pictures' addresses taken out.

    Splitting on whitespace and rejoining is what closes the gaps an escape
    leaves behind: "&#32;" unescapes to a space beside the ones already there.
    """
    wanted = set(pictures)
    kept = [word for word in html.unescape(body).split() if word not in wanted]
    return " ".join(kept).strip()
