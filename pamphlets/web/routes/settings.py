"""The Settings page, and backing up one account's setup."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ... import scheduler
from ...db import get_settings, session_scope
from ...services import backup as backup_service
from ...services.theming import images
from ...services.theming import store as themes
from ..responses import owner_of, redirect, render

if TYPE_CHECKING:
    pass
from ..contexts import connection_state, playlist_context
from .connections import connection_view
from .plugin_settings import user_settings_panels

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    """The Settings page: preferences, each plugin's own block, and backups."""
    owner = owner_of(request)
    with session_scope() as session:
        panels = user_settings_panels(owner)
        for panel in panels:
            # Its sign-in, where its service has one: connected or not, and
            # what is left of its allowance today.
            panel["connection"] = connection_view(session, owner, panel["plugin"])
        context = {
            "state": connection_state(session, owner),
            "settings": get_settings(session, owner),
            "next_run": scheduler.next_run_time(),
            # Feeds backed by a real YouTube playlist are made here: the
            # canvas makes the ones that live inside Pamphlets.
            **playlist_context(session, owner=owner),
            # What each switched-on plugin lets this account set for itself,
            # and its sign-in where it has one.
            "plugin_panels": panels,
        }
    return render(request, "settings.html", context)


@router.get("/settings/backup")
def download_backup(request: Request) -> Response:
    """The setup, as a JSON file the browser saves."""
    owner = owner_of(request)
    with session_scope() as session:
        data = backup_service.build_export(session, owner)
    body = json.dumps(data, indent=2, ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{backup_service.filename()}"',
            "Content-Length": str(len(body.encode("utf-8"))),
        },
    )


@router.post("/settings/restore")
def restore_backup(request: Request, backup_file: UploadFile = File(...)) -> RedirectResponse:
    """Load a backup file back in, matching rows by their YouTube ids."""
    owner = owner_of(request)
    raw = backup_file.file.read()
    if len(raw) > 32 * 1024 * 1024:
        return redirect("/settings", err="That file is too large to be a Pamphlets backup.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return redirect("/settings", err="That file is not readable JSON.")

    with session_scope() as session:
        try:
            summary = backup_service.restore(session, payload, owner)
        except backup_service.RestoreError as exc:
            return redirect("/settings", err=str(exc))
        message = summary.describe()
        if summary.skipped:
            message += f" {len(summary.skipped)} video(s) skipped: their channel was not in the file."

    scheduler.reschedule()
    # The restore may have brought a theme; pages read it from what is held.
    themes.drop_held()
    return redirect("/settings", ok=message)


@router.post("/settings/avatar")
def upload_avatar(request: Request, picture: UploadFile = File(...)) -> RedirectResponse:
    """The account's own picture, in place of its letter in the bar.

    Checked like a theme's pictures, and shown only to the account itself:
    accounts here are private, so nobody else has a page it would appear on.
    """
    raw = picture.file.read(images.MAX_RASTER + 1)
    try:
        kept = images.accept(raw)
    except images.ImageError as exc:
        return redirect("/settings#account", err=str(exc))
    with session_scope() as session:
        themes.put_picture(session, owner_of(request), "avatar", kept)
    themes.drop_held()
    return redirect("/settings#account", ok="Your account picture is in place.")


@router.post("/settings/avatar/remove")
def remove_avatar(request: Request) -> RedirectResponse:
    """Back to the letter."""
    with session_scope() as session:
        themes.put_picture(session, owner_of(request), "avatar", None)
    themes.drop_held()
    return redirect("/settings#account", ok="Your account picture is gone; the letter is back.")
