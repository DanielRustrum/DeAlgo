"""The admin's tab: accounts, sessions, and moving the whole instance."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from ...config import CONFIG
from ...db import session_scope
from ...models import (
    User,
)
from ...plugins import registry
from ...services import accounts, migration
from ..responses import redirect, render
from ..templates import Context

log = logging.getLogger(__name__)

router = APIRouter()


def _admin_context(session: Session) -> Context:
    """What the Admin page shows: the accounts, their limits, and the plugin counts."""
    return {
        "users": accounts.list_users(session),
        "admin_user": CONFIG.admin_user,
        "session_days": CONFIG.session_days,
        "min_password": accounts.MIN_PASSWORD_LENGTH,
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
            {
                "users": [],
                "admin_user": "",
                "session_days": CONFIG.session_days,
                "min_password": accounts.MIN_PASSWORD_LENGTH,
                "min_passphrase": migration.MIN_PASSPHRASE,
                **_plugin_tally(),
            },
        )
    with session_scope() as session:
        context = _admin_context(session)
    return render(request, "admin.html", context)


@router.post("/admin/accounts")
def add_account(
    request: Request, username: str = Form(""), password: str = Form("")
) -> Response:
    """Create a member account from the form."""
    with session_scope() as session:
        try:
            accounts.create_user(session, username, password)
        except accounts.AccountError as exc:
            return redirect("/admin", err=str(exc))
    return redirect("/admin", ok=f"Account {username.strip().lower()} created.")


@router.post("/admin/accounts/{user_pk}/password")
def reset_account_password(request: Request, user_pk: int, password: str = Form("")) -> Response:
    """Set a member's password. The admin's own comes from the environment."""
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin", err="That account no longer exists.")
        if user.is_admin:
            return redirect(
                "/admin",
                err="The admin password comes from DEALGO_ADMIN_PASSWORD; change it there.",
            )
        try:
            accounts.set_password(session, user, password)
        except accounts.AccountError as exc:
            return redirect("/admin", err=str(exc))
        name = user.username
    return redirect("/admin", ok=f"New password set for {name}. Their other sessions ended.")


@router.post("/admin/accounts/{user_pk}/enabled")
def set_account_enabled(request: Request, user_pk: int) -> Response:
    """Switch a member account off (signing it out everywhere) or back on."""
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin", err="That account no longer exists.")
        if user.is_admin:
            return redirect("/admin", err="The admin account cannot switch itself off.")
        accounts.set_enabled(session, user, enabled=not user.enabled)
        name, now_on = user.username, user.enabled
    word = "can sign in again" if now_on else "is switched off, and signed out everywhere"
    return redirect("/admin", ok=f"{name} {word}.")


@router.post("/admin/accounts/{user_pk}/delete")
def remove_account(request: Request, user_pk: int) -> Response:
    """Delete a member account and everything it owns."""
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin", err="That account no longer exists.")
        name = user.username
        try:
            accounts.delete_user(session, user)
        except accounts.AccountError as exc:
            return redirect("/admin", err=str(exc))
    return redirect("/admin", ok=f"Account {name} deleted.")


@router.post("/admin/accounts/{user_pk}/sessions")
def end_account_sessions(request: Request, user_pk: int) -> Response:
    """Sign one account out of every browser."""
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin", err="That account no longer exists.")
        accounts.revoke_all(session, user)
        name = user.username
    return redirect("/admin", ok=f"{name} has been signed out everywhere.")


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


@router.post("/admin/sessions/prune")
def prune_sessions(request: Request) -> Response:
    """Delete every expired sign-in session."""
    with session_scope() as session:
        cleared = accounts.clear_expired(session)
    return redirect("/admin", ok=f"Cleared {cleared} expired session(s).")
