"""The admin's tab: where accounts and plugins are managed, and moving the whole instance.

Accounts have a page of their own (admin_accounts.py), as plugins do (plugins.py).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from ...config import CONFIG
from ...db import session_scope
from ...plugins import registry
from ...services import accounts, migration
from ..responses import redirect, render
from ..templates import Context

log = logging.getLogger(__name__)

router = APIRouter()


def _admin_context(session: Session) -> Context:
    """What the Admin page shows: enough about accounts and plugins to point
    at their pages, and what moving the instance needs."""
    users = accounts.list_users(session)
    return {
        "account_count": len(users),
        "accounts_off": sum(1 for user in users if not user.enabled),
        "min_passphrase": migration.MIN_PASSPHRASE,
        **_plugin_tally(),
    }


def _plugin_tally() -> Context:
    """Enough about the plugins for the Admin page to point at them, and to
    say when one is not loading rather than leaving it to be noticed."""
    found = registry.current()
    return {"plugin_count": len(found.working), "plugin_trouble": len(found.broken)}


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request) -> HTMLResponse:
    """The Admin page, or what would turn accounts on when they are off."""
    # Reachable by address even with accounts switched off, where an empty
    # list of them would explain nothing. Say what would turn it on instead.
    if not CONFIG.auth_enabled:
        return render(
            request,
            "admin.html",
            {"account_count": 0, "accounts_off": 0,
             "min_passphrase": migration.MIN_PASSPHRASE, **_plugin_tally()},
        )
    with session_scope() as session:
        context = _admin_context(session)
    return render(request, "admin.html", context)


@router.post("/admin/backup")
def download_site_backup(request: Request, passphrase: str = Form("")) -> Response:
    """The whole instance, encrypted, for standing it up somewhere else.

    A POST rather than a link, because it needs the passphrase — and because a
    file holding every account's credentials should not be one click from a
    bookmark.
    """
    try:
        migration.check_passphrase(passphrase)
        with session_scope() as session:
            blob = migration.build_site_export(session, passphrase)
    except migration.MigrationError as exc:
        return redirect("/admin", err=str(exc))

    return Response(
        blob,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{migration.filename()}"'},
    )


@router.post("/admin/restore")
def restore_site_backup(
    request: Request, passphrase: str = Form(""), backup_file: UploadFile = File(...)
) -> Response:
    """Stand up the accounts in an uploaded, encrypted migration file."""
    blob = backup_file.file.read()
    if not blob:
        return redirect("/admin", err="Choose a site backup to load.")
    try:
        with session_scope() as session:
            summary = migration.restore_site(session, blob, passphrase)
    except migration.MigrationError as exc:
        return redirect("/admin", err=str(exc))
    except Exception as exc:  # a file that opened but did not make sense
        log.exception("site restore failed")
        return redirect("/admin", err=f"That backup opened but could not be applied: {exc}")

    message = (
        f"Restored {summary.accounts} new account(s), {summary.feeds} feed(s) and "
        f"{summary.channels} channel(s)."
    )
    if summary.notes:
        message += " " + " ".join(summary.notes)
    return redirect("/admin", ok=message)
