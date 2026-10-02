"""Answering a request: a page, a fragment, or a redirect — for whoever is signed in."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..config import CONFIG
from ..db import get_settings, get_token, session_scope
from ..models import (
    Channel,
    Playlist,
    SyncRun,
    channel_playlist,
)
from ..services import sync as sync_service
from ..services import watched as watched_service
from ..services.scope import OwnerId, owned
from .templates import ASSET_VERSION, TEMPLATES

if TYPE_CHECKING:
    from .templates import Context


def newest_run_id() -> int:
    with session_scope() as session:
        return session.scalar(select(func.max(SyncRun.id))) or 0


def tour_progress(session: Session, owner: OwnerId = None) -> Context:
    """What the tour can already tick off, so it guides rather than lectures."""
    feeds = list(session.scalars(owned(select(Playlist), Playlist, owner)))
    return {
        "has_feed": bool(feeds),
        "has_youtube_feed": any(not feed.is_generic for feed in feeds),
        "has_channel": bool(session.scalar(owned(select(func.count(Channel.id)), Channel, owner))),
        "linked": bool(
            session.scalar(
                select(func.count()).select_from(channel_playlist)
            )
        ),
        "connected": get_token(session, owner) is not None,
        "synced": bool(session.scalar(owned(select(func.count(SyncRun.id)), SyncRun, owner))),
        "watched_any": watched_service.count_watched(session, owner) > 0,
    }


def notices() -> Context:
    """Which standing notices this instance still wants to see.

    One read for all of them, since every page render asks. Each is stored as
    "hide", so an unticked checkbox — which sends nothing at all — means show.
    """
    with session_scope() as session:
        settings = get_settings(session)
        return {
            "show_tour": not settings.hide_tour,
            "show_open_notice": not settings.hide_open_notice,
            "show_connect_notice": not settings.hide_connect_notice,
        }


def owner_of(request: Request) -> OwnerId:
    """Whose data this request is about.

    None is the implicit owner — which is everyone, while sign-in is off. With
    accounts on it is the signed-in one, and never anybody else's: there is no
    route that reads another account's channels or feeds.
    """
    identity = getattr(request.state, "identity", None)
    return identity.user_pk if identity else None


def render(request: Request, template: str, context: Context) -> HTMLResponse:
    context = {
        "version": __version__,
        "asset_version": ASSET_VERSION,
        "ok_message": request.query_params.get("ok"),
        "error_message": request.query_params.get("err"),
        "sync_running": sync_service.is_running(),
        "last_run_id": newest_run_id(),
        **notices(),
        "identity": getattr(request.state, "identity", None),
        "auth_enabled": CONFIG.auth_enabled,
        "weak_admin_password": CONFIG.admin_password_weak,
        **context,
    }
    return TEMPLATES.TemplateResponse(request, template, context)


def fragment(
    request: Request,
    template: str,
    context: Context,
    *,
    ok: str | None = None,
    err: str | None = None,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    """Render one piece of a page, with the flash area swapped out of band."""
    body = TEMPLATES.get_template(template).render({"request": request, **context})
    if ok or err:
        body += TEMPLATES.get_template("_flash.html").render(
            {"request": request, "ok_message": ok, "error_message": err, "oob": True}
        )
    return HTMLResponse(body, headers=headers)


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def redirect(path: str, *, ok: str | None = None, err: str | None = None) -> RedirectResponse:
    params = {k: v for k, v in (("ok", ok), ("err", err)) if v}
    url = f"{path}?{urlencode(params)}" if params else path
    return RedirectResponse(url, status_code=303)
