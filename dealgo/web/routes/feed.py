"""The Feed tab: a shelf of every feed as a tile, and each feed on its own page.

The shelf (`/feed`) is for finding a feed: favourites first, then the rest in
the account's own order, with search, a tag filter and other sorts. A feed's
own page (`/feed/<id>`) is for reading it: its items, laid out the way that
feed asks, and what can be done with it.
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ...db import session_scope
from ...models import (
    GraphNode,
    Placement,
    Playlist,
    Video,
    utcnow,
)
from ...services import graph as graph_service
from ...services import playlists as playlist_service
from ...services import watched as watched_service
from ...services.playlists import shelf as shelf_service
from ...services.scope import OwnerId, owned
from ..contexts import feed_window_words
from ..responses import fragment, is_htmx, owner_of, redirect, render
from ..templates import Context

router = APIRouter()


# -- the shelf ------------------------------------------------------------------


def _shelf_context(
    session: Session,
    owner: OwnerId,
    *,
    sort: str = "mine",
    query: str = "",
    tag: str = "",
    arrange: bool = False,
) -> Context:
    """Every feed as a tile, favourites first, filtered and sorted as asked.

    Arranging is only done in the account's own order: dragging a tile while
    the shelf is sorted by name would move it somewhere other than where it
    lands.
    """
    sort = sort if sort in shelf_service.SORTS else "mine"
    if arrange:
        sort, query, tag = "mine", "", ""
    favourites, rest = shelf_service.shelf(session, owner, sort=sort, query=query, tag=tag)
    return {
        "favourites": favourites,
        "rest": rest,
        "sort": sort,
        "sorts": shelf_service.SORTS,
        "query": query,
        "tag": tag,
        "tags": shelf_service.all_tags(session, owner),
        "arrange": arrange,
        # Carried by every form on the shelf, so an action keeps the view.
        "shelf_query": urlencode(
            {"sort": sort, "q": query, "tag": tag, "arrange": "1" if arrange else ""}
        ),
    }


@router.get("/feed", response_class=HTMLResponse)
def feed_page(
    request: Request,
    playlist: str = "",
    q: str = "",
    sort: str = "mine",
    tag: str = "",
    arrange: str = "",
) -> Response:
    """The shelf. An old link to one feed (`?playlist=`) goes to its own page."""
    if playlist.isdigit():
        return redirect(f"/feed/{playlist}")
    owner = owner_of(request)
    with session_scope() as session:
        context = _shelf_context(
            session, owner, sort=sort, query=q, tag=tag, arrange=arrange == "1"
        )
    return render(request, "feed.html", context)


@router.get("/partials/feed", response_class=HTMLResponse)
def partial_shelf(
    request: Request, q: str = "", sort: str = "mine", tag: str = "", arrange: str = ""
) -> HTMLResponse:
    """The shelf again: after a search, a sort, or a sync landing."""
    owner = owner_of(request)
    with session_scope() as session:
        context = _shelf_context(
            session, owner, sort=sort, query=q, tag=tag, arrange=arrange == "1"
        )
    return fragment(request, "_feed_shelf.html", context)


def _owned_feed(session: Session, owner: OwnerId, playlist_pk: int) -> Playlist | None:
    """One of this account's feeds, or None: nobody reaches another's."""
    return session.scalar(
        owned(select(Playlist), Playlist, owner).where(Playlist.id == playlist_pk)
    )


def _shelf_answer(
    request: Request, owner: OwnerId, sort: str, q: str, tag: str, arrange: str,
    *, ok: str | None = None, err: str | None = None,
) -> Response:
    """After an action on the shelf: the shelf again, or the page, as it was viewed."""
    if is_htmx(request):
        with session_scope() as session:
            context = _shelf_context(
                session, owner, sort=sort, query=q, tag=tag, arrange=arrange == "1"
            )
        return fragment(request, "_feed_shelf.html", context, ok=ok, err=err)
    query = urlencode({k: v for k, v in (("sort", sort), ("q", q), ("tag", tag),
                                          ("arrange", arrange)) if v and v != "mine"})
    return redirect("/feed" + (f"?{query}" if query else ""), ok=ok, err=err)


@router.post("/feeds/{playlist_pk}/favorite")
def favorite_feed(
    request: Request,
    playlist_pk: int,
    on: str = Form("1"),
    back: str = Form("shelf"),
    sort: str = Form("mine"),
    q: str = Form(""),
    tag: str = Form(""),
    arrange: str = Form(""),
) -> Response:
    """Star a feed so it sits at the top of the shelf, or unstar it."""
    owner = owner_of(request)
    with session_scope() as session:
        target = _owned_feed(session, owner, playlist_pk)
        if target is None:
            return redirect("/feed", err="That feed is not here.")
        shelf_service.set_favorite(session, target, on == "1", owner)
        title = target.title
    said = f"“{title}” is a favourite." if on == "1" else f"“{title}” is no longer a favourite."
    if back == "feed":
        # From the feed's own page: only its star changes.
        if is_htmx(request):
            with session_scope() as session:
                again = _owned_feed(session, owner, playlist_pk)
                return fragment(request, "_feed_star.html", {"playlist": again, "back": "feed"})
        return redirect(f"/feed/{playlist_pk}", ok=said)
    return _shelf_answer(request, owner, sort, q, tag, arrange)


@router.post("/feeds/{playlist_pk}/move")
def move_feed(
    request: Request,
    playlist_pk: int,
    where: str = Form(...),
    sort: str = Form("mine"),
    q: str = Form(""),
    tag: str = Form(""),
    arrange: str = Form("1"),
) -> Response:
    """Move a feed first, last, or one place along — the keyboard's way to arrange."""
    owner = owner_of(request)
    with session_scope() as session:
        target = _owned_feed(session, owner, playlist_pk)
        if target is None:
            return redirect("/feed", err="That feed is not here.")
        shelf_service.move(session, owner, target, where)
    return _shelf_answer(request, owner, sort, q, tag, arrange)


@router.post("/feed/arrange")
def arrange_feeds(
    request: Request,
    order: str = Form(""),
    sort: str = Form("mine"),
    q: str = Form(""),
    tag: str = Form(""),
    arrange: str = Form("1"),
) -> Response:
    """The order the tiles were dragged into, as feed ids."""
    owner = owner_of(request)
    ids = [int(part) for part in order.split(",") if part.strip().isdigit()]
    with session_scope() as session:
        shelf_service.arrange(session, owner, ids)
    return _shelf_answer(request, owner, sort, q, tag, arrange)


# -- one feed ---------------------------------------------------------------------


def _feed_view_context(
    session: Session, target: Playlist, owner: OwnerId, *, sitting: bool
) -> Context:
    """One feed's page: what is in it, laid out the way it asks, or why it is shut.

    ``sitting`` says whether somebody actually came to the feed. A pulse on a
    feed's second input gives a stretch of reading that starts when you sit
    down, so arriving is what starts it — and a background refresh must not,
    or a sync landing overnight would spend the day's reading before anyone
    was awake to do it.
    """
    windows = graph_service.consumption(session, owner)
    section = _section(
        session, target, owner, windows.get(target.id, []), now=utcnow(), sitting=sitting
    )
    return {"section": section, "playlist": target}


def _section(
    session: Session,
    target: Playlist,
    owner: OwnerId,
    opens: list[GraphNode],
    *,
    now: dt.datetime,
    sitting: bool,
) -> Context:
    """One feed's items, or why it is shut."""
    # A feed with a Reset slotted under it is only read while that window is
    # open. Shown as shut rather than hidden: a feed that vanished would read
    # as a feed that had gone.
    if opens:
        state = graph_service.window_state(opens, now)
        if not state.open:
            return {
                "playlist": target,
                "videos": [],
                "total": 0,
                "shut": feed_window_words(opens),
                "opens_at": state.opens_at,
                "expiring": {},
            }
        if sitting:
            graph_service.begin_sitting(session, state, now)
    return {
        "playlist": target,
        "videos": _shown(session, target, owner),
        "total": _held(session, target),
        "shut": [],
        "opens_at": None,
        "expiring": _expiring(session, target),
    }


def _shown(session: Session, target: Playlist, owner: OwnerId) -> list[Video]:
    """What the feed shows, in the order it asks for."""
    statement = (
        owned(select(Video), Video, owner)
        .join(Placement, Placement.video_pk == Video.id)
        .options(selectinload(Video.channel))
        .where(Placement.playlist_pk == target.id, Placement.playlist_item_id.is_not(None))
    )
    if target.view_show != "all":
        statement = statement.where(Video.watched_at.is_(None))
    direction = (
        Video.published_at.desc() if target.view_order == "newest"
        else Video.published_at.asc()
    )
    return list(session.scalars(statement.order_by(direction, Video.id.asc())))


def _held(session: Session, target: Playlist) -> int:
    """How many the feed holds, watched or not."""
    return (
        session.scalar(
            select(func.count(Placement.id)).where(
                Placement.playlist_pk == target.id, Placement.playlist_item_id.is_not(None)
            )
        )
        or 0
    )


def _expiring(session: Session, target: Playlist) -> dict[int, dt.datetime]:
    """When an Expire box takes each item out of *this* feed.

    Per feed rather than per item: the same video in two feeds may have two
    different answers, and the one that matters here is this one's.
    """
    return {
        video_pk: when
        for video_pk, when in session.execute(
            select(Placement.video_pk, Placement.expires_at).where(
                Placement.playlist_pk == target.id,
                Placement.expires_at.is_not(None),
                Placement.removed_at.is_(None),
            )
        )
    }


@router.get("/feed/{playlist_pk}", response_class=HTMLResponse)
def one_feed_page(request: Request, playlist_pk: int) -> Response:
    """A feed's own page. Opening it starts a reading window's sitting."""
    owner = owner_of(request)
    with session_scope() as session:
        target = _owned_feed(session, owner, playlist_pk)
        if target is None:
            return redirect("/feed", err="That feed is not here.")
        context = _feed_view_context(session, target, owner, sitting=True)
        return render(request, "feed_view.html", context)


@router.get("/partials/feed/{playlist_pk}", response_class=HTMLResponse)
def partial_one_feed(request: Request, playlist_pk: int) -> HTMLResponse:
    """A feed's items again after a sync landed. Not a sitting: nobody arrived,
    the page they were already on caught up."""
    owner = owner_of(request)
    with session_scope() as session:
        target = _owned_feed(session, owner, playlist_pk)
        if target is None:
            return HTMLResponse("", status_code=404)
        context = _feed_view_context(session, target, owner, sitting=False)
        return fragment(request, "_feed_section.html", context)


@router.post("/feeds/{playlist_pk}/view")
def set_feed_view(
    request: Request,
    playlist_pk: int,
    order: str = Form(""),
    show: str = Form(""),
) -> Response:
    """Each feed is laid out its own way, and remembers it."""
    owner = owner_of(request)
    with session_scope() as session:
        target = _owned_feed(session, owner, playlist_pk)
        if target is None:
            return redirect("/feed", err="That feed is no longer a target.")
        playlist_service.set_view(session, target, order=order, show=show)
        if is_htmx(request):
            # Changing how a feed is laid out is somebody looking at it.
            context = _feed_view_context(session, target, owner, sitting=True)
            return fragment(request, "_feed_section.html", context)
    return redirect(f"/feed/{playlist_pk}")


@router.post("/feeds/{playlist_pk}/clear")
def clear_feed(request: Request, playlist_pk: int) -> Response:
    """Empty one feed, from the button on its page."""
    owner = owner_of(request)
    result = watched_service.clear_feed(playlist_pk, owner)
    ok, err = (result.message, None) if result.ok else (None, result.message)
    if is_htmx(request):
        with session_scope() as session:
            target = _owned_feed(session, owner, playlist_pk)
            if target is not None:
                context = _feed_view_context(session, target, owner, sitting=False)
                return fragment(request, "_feed_section.html", context, ok=ok, err=err)
    return redirect(f"/feed/{playlist_pk}", ok=ok, err=err)
