"""Making, editing and removing feeds, and the YouTube playlists behind them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ... import outgoing
from ...db import session_scope
from ...models import (
    Channel,
    Placement,
    Playlist,
    Video,
)
from ...services import channels as channel_service
from ...services import playlists as playlist_service
from ...services.scope import owned
from ..responses import owner_of, redirect, render

if TYPE_CHECKING:
    pass
from ..contexts import connection_state, forget_account_playlists, matching_channels

router = APIRouter()


def _playlists_response(
    request: Request,
    *,
    ok: str | None = None,
    err: str | None = None,
    creating: bool = False,
    back: str = "",
) -> Response:
    owner = owner_of(request)
    if back:
        # The detail page posts plainly and returns to itself.
        return redirect(back, ok=ok, err=err)
    return redirect("/channels", ok=ok, err=err)


@router.post("/settings/feeds/new")
def create_feed(
    request: Request,
    source: str = Form("new"),
    new_title: str = Form(""),
    generic_title: str = Form(""),
    privacy: str = Form("private"),
    playlist_id: str = Form(""),
    channels: list[int] = Form(default=[]),
) -> Response:
    """Set up a feed in one step: the playlist, then what fills it."""
    owner = owner_of(request)
    with session_scope() as session, outgoing.client() as http:
        try:
            playlist, linked = playlist_service.set_up_feed(
                session,
                http,
                source=source,
                title=generic_title if source == "generic" else new_title,
                privacy=privacy,
                playlist_id=playlist_id,
                channel_pks=channels,
                owner=owner,
            )
        except playlist_service.PlaylistError as exc:
            return redirect("/settings", err=str(exc))
        title = playlist.title

    forget_account_playlists()
    message = f"Now feeding {title!r}. It is on the Configuration canvas."
    if linked:
        message += f" {linked} channel{'s' if linked != 1 else ''} linked."
    return redirect("/settings", ok=message)


@router.post("/settings/playlists/{playlist_pk}")
def save_playlist(
    request: Request,
    playlist_pk: int,
    max_items: str = Form("0"),
    max_per_run: str = Form("0"),
    back: str = Form(""),
) -> Response:
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That playlist is no longer a target.", back=back)
        try:
            playlist_service.update(
                session,
                playlist,
                {"max_items": max_items, "max_per_run": max_per_run},
            )
        except playlist_service.PlaylistError as exc:
            return _playlists_response(request, err=str(exc), back=back)
        title = playlist.title
    return _playlists_response(request, ok=f"Saved {title!r}.", back=back)


@router.get("/feeds/{playlist_pk}", response_class=HTMLResponse)
def feed_detail(request: Request, playlist_pk: int, rename: str = "", q: str = "") -> Response:
    """Everything about one feed, off the list that only needs to be scannable."""
    owner = owner_of(request)
    with session_scope() as session:
        playlist = session.scalar(
            owned(select(Playlist), Playlist, owner)
            .options(selectinload(Playlist.channels))
            .where(Playlist.id == playlist_pk)
        )
        if playlist is None:
            return redirect("/channels", err="That feed is no longer a target.")

        videos = list(
            session.scalars(
                owned(select(Video), Video, owner)
                .join(Placement, Placement.video_pk == Video.id)
                .options(
                    selectinload(Video.channel),
                    selectinload(Video.placements).selectinload(Placement.playlist),
                )
                .where(Placement.playlist_pk == playlist_pk, Placement.playlist_item_id.is_not(None))
                .order_by(Video.published_at.desc())
                .limit(50)
            )
        )
        order = [p.id for p in playlist_service.list_playlists(session, owner)]
        context = {
            "playlist": playlist,
            "videos": videos,
            "held": playlist_service.item_counts(session, owner).get(playlist_pk, 0),
            "all_channels": matching_channels(channel_service.list_channels(session, owner), q),
            "query": q,
            "position": order.index(playlist_pk) + 1 if playlist_pk in order else None,
            "total_feeds": len(order),
            "renaming": playlist_pk if rename == "1" else None,
            "state": connection_state(session, owner),
        }
    return render(request, "feed_detail.html", context)


@router.post("/settings/playlists/{playlist_pk}/tags")
def set_playlist_tags(request: Request, playlist_pk: int, tags: str = Form(""), back: str = Form("")) -> Response:
    """Free-form labels, searchable on the Feed page."""
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That feed is no longer a target.", back=back)
        applied = playlist_service.set_tags(session, playlist, tags)
        title = playlist.title

    message = (
        f"{title} tagged {', '.join(applied)}." if applied else f"Cleared the tags on {title}."
    )
    return _playlists_response(request, ok=message, back=back)


@router.post("/settings/playlists/{playlist_pk}/filling")
def toggle_playlist_filling(request: Request, playlist_pk: int, back: str = Form("")) -> Response:
    """Pause or resume a feed without disturbing what is already in it."""
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That feed is no longer a target.", back=back)
        playlist_service.set_enabled(session, playlist, enabled=not playlist.enabled)
        title, filling = playlist.title, playlist.enabled

    message = (
        f"Filling {title} again." if filling
        else f"Paused {title}. Nothing already in it is removed."
    )
    return _playlists_response(request, ok=message, back=back)


@router.post("/settings/playlists/{playlist_pk}/rename")
def rename_playlist(
    request: Request, playlist_pk: int, title: str = Form(""), back: str = Form("")
) -> Response:
    """Retitle a feed, and the playlist behind it where there is one."""
    with session_scope() as session, outgoing.client() as http:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That feed is no longer a target.", back=back)
        try:
            on_youtube = playlist_service.rename(session, playlist, title, http)
        except playlist_service.PlaylistError as exc:
            # The local rename may well have gone through; say so either way.
            return _playlists_response(request, err=str(exc), back=back)
        new_title = playlist.title

    forget_account_playlists()
    message = f"Renamed to {new_title!r}."
    if on_youtube:
        message += " The YouTube playlist was renamed too."
    return _playlists_response(request, ok=message, back=back)


@router.post("/settings/playlists/{playlist_pk}/unlink")
def unlink_playlist(request: Request, playlist_pk: int, back: str = Form("")) -> Response:
    """Keep the feed, drop the YouTube playlist behind it."""
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That feed is no longer a target.", back=back)
        try:
            playlist_service.unlink(session, playlist)
        except playlist_service.PlaylistError as exc:
            return _playlists_response(request, err=str(exc), back=back)
        title = playlist.title

    forget_account_playlists()
    return _playlists_response(
        request,
        ok=f"{title} is now a generic feed. Its YouTube playlist and videos are untouched.",
        back=back,
    )


@router.post("/settings/playlists/{playlist_pk}/delete")
def delete_playlist(request: Request, playlist_pk: int, back: str = Form("")) -> Response:
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That playlist is no longer a target.", back=back)
        title = playlist.title
        playlist_service.remove(session, playlist)
    forget_account_playlists()
    return _playlists_response(request, ok=f"Stopped feeding {title!r}. The playlist itself is untouched on YouTube."
    , back=back)


@router.post("/settings/playlists/{playlist_pk}/channels")
def set_feed_membership(
    request: Request,
    playlist_pk: int,
    channel_id: int = Form(...),
    include: str = Form("1"),
    back: str = Form(""),
) -> Response:
    """Add or remove one channel from one feed, straight from the feed row."""
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That feed is no longer a target.", back=back)
        try:
            title = playlist_service.set_membership(
                session, playlist, channel_id, include=include == "1"
            )
        except playlist_service.PlaylistError as exc:
            return _playlists_response(request, err=str(exc), back=back)
        feed_title = playlist.title
        channel = session.get(Channel, channel_id)
        resumed = include == "1" and channel is not None and channel.enabled
        stranded = include != "1" and channel is not None and channel.awaiting_feed

    verb = "now feeds" if include == "1" else "no longer feeds"
    message = f"{title} {verb} {feed_title}."
    if resumed and include == "1":
        message += " It was waiting for a feed, so watching has started."
    elif stranded:
        message += " It feeds nothing now, so it is paused until you link one."
    return _playlists_response(request, ok=message, back=back)
