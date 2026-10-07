"""The Feed page's shelf: every feed as a tile, favourites first, in your order.

A feed's place here is the account's own arrangement and nothing else. The
order feeds are *filled* in when quota is short is `priority`, set on each
feed's settings; this is only where it sits when you go looking for it.

Favourites come first, then everything else, each in the order the account
put them in (`shelf_position`). Other sorts — by name, by what is waiting,
by what arrived last — are views of the same shelf and change nothing.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Placement, Playlist, Video, utcnow
from ..graph import consumption, window_state
from ..scope import OwnerId, owned
from .listing import list_playlists

#: The ways the shelf can be sorted, and what each is called on the page.
SORTS: dict[str, str] = {
    "mine": "My order",
    "name": "Name",
    "waiting": "Most waiting",
    "recent": "Latest arrivals",
}

#: How many of a feed's latest items its tile shows.
PREVIEWS = 4

#: Where a feed can be moved to, from its tile while arranging.
MOVES = ("first", "earlier", "later", "last")


@dataclass
class Preview:
    """One square of a tile's mosaic: a picture, or the opening words."""

    picture: str | None
    words: str


@dataclass
class Tile:
    """One feed as the shelf shows it."""

    playlist: Playlist
    waiting: int = 0
    total: int = 0
    latest: dt.datetime | None = None
    previews: list[Preview] = field(default_factory=list)
    #: Shut by a window on its second input, and when it opens again.
    shut: bool = False
    opens_at: dt.datetime | None = None


def _counts(
    session: Session, ids: list[int]
) -> tuple[dict[int, int], dict[int, int], dict[int, dt.datetime]]:
    """How many each feed holds, how many of those are unwatched, and when the last arrived."""
    held = Placement.playlist_item_id.is_not(None)
    totals: dict[int, int] = {}
    latest: dict[int, dt.datetime] = {}
    for pk, count, last in session.execute(
        select(Placement.playlist_pk, func.count(Placement.id), func.max(Placement.added_at))
        .where(Placement.playlist_pk.in_(ids), held)
        .group_by(Placement.playlist_pk)
    ):
        totals[pk] = count
        if last is not None:
            latest[pk] = last
    # Built by hand: dict() takes a result for a mapping, since it has keys().
    waiting = {
        pk: count
        for pk, count in session.execute(
            select(Placement.playlist_pk, func.count(Placement.id))
            .join(Video, Video.id == Placement.video_pk)
            .where(Placement.playlist_pk.in_(ids), held, Video.watched_at.is_(None))
            .group_by(Placement.playlist_pk)
        )
    }
    return totals, waiting, latest


def _previews(session: Session, playlist: Playlist) -> list[Preview]:
    """The newest few unwatched items in a feed, as its tile shows them."""
    videos = session.scalars(
        select(Video)
        .join(Placement, Placement.video_pk == Video.id)
        .where(
            Placement.playlist_pk == playlist.id,
            Placement.playlist_item_id.is_not(None),
            Video.watched_at.is_(None),
        )
        .order_by(Video.published_at.desc(), Video.id.desc())
        .limit(PREVIEWS)
    )
    return [
        Preview(picture=next(iter(video.pictures), None), words=video.title or video.body or "")
        for video in videos
    ]


def shelf(
    session: Session,
    owner: OwnerId = None,
    *,
    sort: str = "mine",
    query: str = "",
    tag: str = "",
) -> tuple[list[Tile], list[Tile]]:
    """The account's feeds as tiles: its favourites, then everything else.

    `query` matches names and tags as the old search did; `tag` keeps only
    feeds wearing that tag.
    """
    playlists = list_playlists(session, owner)
    terms = query.lower().split()
    if terms:
        playlists = [p for p in playlists if all(term in p.searchable for term in terms)]
    if tag:
        playlists = [p for p in playlists if tag in p.tag_list]

    ids = [p.id for p in playlists]
    totals, waiting, latest = _counts(session, ids) if ids else ({}, {}, {})
    windows = consumption(session, owner)
    now = utcnow()

    tiles = [
        _tile(session, playlist, totals, waiting, latest, windows.get(playlist.id, []), now)
        for playlist in playlists
    ]

    tiles.sort(key=_sort_key(sort))
    favourites = [t for t in tiles if t.playlist.favorite]
    rest = [t for t in tiles if not t.playlist.favorite]
    return favourites, rest


def tile_for(session: Session, playlist: Playlist, owner: OwnerId = None) -> Tile:
    """One feed's tile, as the shelf would show it — for a pamphlet to show."""
    totals, waiting, latest = _counts(session, [playlist.id])
    windows = consumption(session, owner)
    return _tile(session, playlist, totals, waiting, latest, windows.get(playlist.id, []), utcnow())


def _tile(
    session: Session,
    playlist: Playlist,
    totals: dict[int, int],
    waiting: dict[int, int],
    latest: dict[int, dt.datetime],
    pieces: list[Any],
    now: dt.datetime,
) -> Tile:
    tile = Tile(
        playlist=playlist,
        waiting=waiting.get(playlist.id, 0),
        total=totals.get(playlist.id, 0),
        latest=latest.get(playlist.id),
        previews=_previews(session, playlist),
    )
    if pieces:
        state = window_state(pieces, now)
        tile.shut = not state.open
        tile.opens_at = state.opens_at
    return tile


def _sort_key(sort: str) -> Callable[[Tile], tuple[Any, ...]]:
    """How tiles are ordered for one of `SORTS`. Ties fall back to your order."""
    def mine(tile: Tile) -> tuple[int, int]:
        return tile.playlist.shelf_position, tile.playlist.id

    if sort == "name":
        return lambda tile: (tile.playlist.title.lower(), mine(tile))
    if sort == "waiting":
        return lambda tile: (-tile.waiting, mine(tile))
    if sort == "recent":
        # Never filled sorts last rather than first.
        return lambda tile: (
            -(tile.latest.timestamp() if tile.latest else 0.0), mine(tile)
        )
    return mine


def _in_order(session: Session, owner: OwnerId, favorite: bool) -> list[Playlist]:
    """One part of the shelf — favourites, or the rest — in the account's order."""
    return list(
        session.scalars(
            owned(select(Playlist), Playlist, owner)
            .where(Playlist.favorite.is_(favorite))
            .order_by(Playlist.shelf_position.asc(), Playlist.id.asc())
        )
    )


def _renumber(feeds: list[Playlist]) -> None:
    for position, playlist in enumerate(feeds):
        playlist.shelf_position = position


def set_favorite(
    session: Session, playlist: Playlist, favorite: bool, owner: OwnerId = None
) -> None:
    """Star a feed, or take its star away. It goes to the end of where it lands."""
    if playlist.favorite == favorite:
        return
    landing = _in_order(session, owner, favorite)
    playlist.favorite = favorite
    _renumber(landing + [playlist])
    session.flush()


def arrange(session: Session, owner: OwnerId, order: list[int]) -> None:
    """Put the feeds in the order given, each within its own part of the shelf.

    Ids not given keep their place after those that are, and ids that are not
    this account's are ignored, so a stale page cannot lose a feed or move
    somebody else's.
    """
    for favorite in (True, False):
        feeds = _in_order(session, owner, favorite)
        by_id = {p.id: p for p in feeds}
        given = [by_id[pk] for pk in order if pk in by_id]
        seen = {p.id for p in given}
        _renumber(given + [p for p in feeds if p.id not in seen])
    session.flush()


def move(session: Session, owner: OwnerId, playlist: Playlist, where: str) -> None:
    """Move a feed first, last, or one place either way, within its part of the shelf."""
    feeds = _in_order(session, owner, playlist.favorite)
    at = next((i for i, p in enumerate(feeds) if p.id == playlist.id), None)
    if at is None or where not in MOVES:
        return
    feeds.pop(at)
    to = {"first": 0, "earlier": max(at - 1, 0), "later": at + 1, "last": len(feeds)}[where]
    feeds.insert(to, playlist)
    _renumber(feeds)
    session.flush()


def all_tags(session: Session, owner: OwnerId = None) -> list[str]:
    """Every tag the account's feeds wear, for the shelf's tag filter."""
    tags = {tag for p in list_playlists(session, owner) for tag in p.tag_list}
    return sorted(tags, key=str.lower)
