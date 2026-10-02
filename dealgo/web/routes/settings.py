"""The Settings page, and backing up one account's setup."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ... import scheduler
from ...config import CONFIG
from ...db import get_settings, session_scope
from ...services import backup as backup_service
from ..responses import owner_of, redirect, render

if TYPE_CHECKING:
    pass
from ..contexts import connection_state, playlist_context, quota_context

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    """The Settings page: the Google connection, quota and backups."""
    owner = owner_of(request)
    with session_scope() as session:
        context = {
            **quota_context(session, owner),
            "state": connection_state(session, owner),
            "settings": get_settings(session, owner),
            "env_client_id": bool(CONFIG.client_id),
            "env_client_secret": bool(CONFIG.client_secret),
            "env_api_key": bool(CONFIG.api_key),
            "redirect_uri": CONFIG.redirect_uri,
            "next_run": scheduler.next_run_time(),
            # Feeds backed by a real YouTube playlist are made here: the
            # canvas makes the ones that live inside De-Algo.
            **playlist_context(session, owner=owner),
        }
    return render(request, "settings.html", context)


@router.post("/settings")
def save_settings(
    hide_tour: str = Form(""),
    hide_open_notice: str = Form(""),
    hide_connect_notice: str = Form(""),
    client_id: str = Form(""),
    client_secret: str = Form(""),
    api_key: str = Form(""),
) -> RedirectResponse:
    """What is left to set here, which is what the canvas cannot say.

    How often to poll, how far to reach back, what counts as a Short, how
    long a post is held, and what the day's quota is are all gone from this
    form. The first two are what a trigger box and a source box say; the
    rest keep the value they have. Not read from the form at all rather
    than read and defaulted: an absent field would otherwise reset the
    setting on every save, and an absent checkbox would switch polling off.
    """
    with session_scope() as session:
        settings = get_settings(session)
        settings.hide_tour = bool(hide_tour)
        settings.hide_open_notice = bool(hide_open_notice)
        settings.hide_connect_notice = bool(hide_connect_notice)
        settings.client_id = client_id.strip() or None
        settings.client_secret = client_secret.strip() or None
        settings.api_key = api_key.strip() or None
    scheduler.reschedule()
    return redirect("/settings", ok="Settings saved.")


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
        return redirect("/settings", err="That file is too large to be a De-Algo backup.")
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
    return redirect("/settings", ok=message)
