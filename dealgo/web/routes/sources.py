"""One source's page, and removing it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ...db import get_settings, session_scope
from ...models import (
    Channel,
    Placement,
    Video,
)
from ...services import channels as channel_service
from ...services import playlists as playlist_service
from ...services.scope import owned
from ..responses import owner_of, redirect, render

if TYPE_CHECKING:
    pass
from ..contexts import channel_list_response, matching_feeds

router = APIRouter()


@router.get("/channels/{channel_id}", response_class=HTMLResponse)
def channel_detail(request: Request, channel_id: int, q: str = "") -> Response:
    owner = owner_of(request)
    with session_scope() as session:
        channel = session.scalar(
            owned(select(Channel), Channel, owner)
            .options(selectinload(Channel.playlists))
            .where(Channel.id == channel_id)
        )
        if channel is None:
            return redirect("/channels", err="That channel is no longer being watched.")
        videos = list(
            session.scalars(
                owned(select(Video), Video, owner)
                .options(
                    selectinload(Video.channel),
                    selectinload(Video.placements).selectinload(Placement.playlist),
                )
                .where(Video.channel_pk == channel_id)
                .order_by(Video.published_at.desc())
                .limit(50)
            )
        )
        context = {
            "channel": channel,
            "videos": videos,
            "settings": get_settings(session, owner),
            "all_playlists": matching_feeds(playlist_service.list_playlists(session, owner), q),
            "query": q,
                "channel_playlist_pks": {p.id for p in channel.playlists},
            "placed": session.scalar(
                select(func.count(func.distinct(Placement.video_pk)))
                .join(Video, Video.id == Placement.video_pk)
                .where(Video.channel_pk == channel_id, Placement.playlist_item_id.is_not(None))
            )
            or 0,
            "pending": session.scalar(
                select(func.count(Video.id)).where(
                    Video.channel_pk == channel_id, Video.status == "pending"
                )
            )
            or 0,
        }
    return render(request, "channel_detail.html", context)


@router.post("/channels/{channel_id}/delete")
def remove_channel(request: Request, channel_id: int, feed: str = Form("")) -> Response:
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            return channel_list_response(request, err="That channel is no longer being watched.", feed=feed)
        title = channel.title
        channel_service.delete_channel(session, channel)
    return channel_list_response(request, ok=f"Stopped watching {title}.", feed=feed)
