"""Answering a request: a page, a fragment, or a redirect — for whoever is signed in."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..config import CONFIG
from ..db import get_settings, session_scope
from ..models import (
    Channel,
    Playlist,
    SyncRun,
    channel_playlist,
)
from ..services import connections
from ..services import sync as sync_service
from ..services import watched as watched_service
from ..services.scope import OwnerId, owned
from ..services.theming import store as themes
from .notices import plugin_notices
from .templates import ASSET_VERSION, TEMPLATES, Context


def newest_run_id() -> int:
    """The id of the latest run, so the page can tell when another finishes."""
    with session_scope() as session:
        return session.scalar(select(func.max(SyncRun.id))) or 0


def owner_of(request: Request) -> OwnerId:
    """Whose data this request is about.

    None is the implicit owner — which is everyone, while sign-in is off. With
    accounts on it is the signed-in one, and never anybody else's: there is no
    route that reads another account's channels or feeds.
    """
    identity = getattr(request.state, "identity", None)
    return identity.user_pk if identity else None


def render(request: Request, template: str, context: Context) -> HTMLResponse:
    """A full page, with what every page shows: version, flash messages, run state."""
    identity = getattr(request.state, "identity", None)
    context = {
        # Somebody's own look once they are signed in; the stock one before,
        # since a sign-in page belongs to nobody yet.
        "theme": themes.page(owner_of(request))
        if identity or not CONFIG.auth_enabled else themes.STOCK,
        # Nothing to say to somebody who has not signed in yet.
        "plugin_notices": plugin_notices(owner_of(request), bool(identity and identity.is_admin))
        if identity or not CONFIG.auth_enabled else [],
        "version": __version__,
        "asset_version": ASSET_VERSION,
        "ok_message": request.query_params.get("ok"),
        "error_message": request.query_params.get("err"),
        "sync_running": sync_service.is_running(),
        "last_run_id": newest_run_id(),
        "identity": identity,
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
    # Who is asking, as a full page would have it: a piece of a page that
    # depends on the account (its sign-in, its pictures) must not quietly
    # answer for the implicit owner instead.
    body = TEMPLATES.get_template(template).render(
        {"request": request, "identity": getattr(request.state, "identity", None), **context}
    )
    if ok or err:
        body += TEMPLATES.get_template("_flash.html").render(
            {"request": request, "ok_message": ok, "error_message": err, "oob": True}
        )
    return HTMLResponse(body, headers=headers)


def is_htmx(request: Request) -> bool:
    """Whether htmx sent this request, so a fragment is wanted rather than a page."""
    return request.headers.get("hx-request") == "true"


def redirect(path: str, *, ok: str | None = None, err: str | None = None) -> RedirectResponse:
    """A 303 to `path`, carrying a flash message as `?ok=` or `?err=`.

    A `#place` on the path stays at the end, where it belongs: written after
    it, the message would be part of the fragment and never reach the server.
    """
    params = {k: v for k, v in (("ok", ok), ("err", err)) if v}
    path, hash_, fragment = path.partition("#")
    url = f"{path}?{urlencode(params)}" if params else path
    url += hash_ + fragment
    return RedirectResponse(url, status_code=303)
