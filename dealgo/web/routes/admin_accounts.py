"""The admin's Accounts page: who can sign in, their passwords and sessions."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from ...config import CONFIG
from ...db import session_scope
from ...models import (
    User,
)
from ...services import accounts
from ..responses import redirect, render

router = APIRouter()


@router.get("/admin/accounts", response_class=HTMLResponse)
def accounts_page(request: Request) -> HTMLResponse:
    """Every account, and adding one. Says what would turn accounts on when they are off."""
    with session_scope() as session:
        users = accounts.list_users(session) if CONFIG.auth_enabled else []
        context = {
            "users": users,
            "admin_user": CONFIG.admin_user,
            "session_days": CONFIG.session_days,
            "min_password": accounts.MIN_PASSWORD_LENGTH,
        }
        return render(request, "accounts.html", context)


@router.post("/admin/accounts")
def add_account(
    request: Request, username: str = Form(""), password: str = Form("")
) -> Response:
    """Create a member account from the form."""
    with session_scope() as session:
        try:
            accounts.create_user(session, username, password)
        except accounts.AccountError as exc:
            return redirect("/admin/accounts", err=str(exc))
    return redirect("/admin/accounts", ok=f"Account {username.strip().lower()} created.")


@router.post("/admin/accounts/{user_pk}/password")
def reset_account_password(request: Request, user_pk: int, password: str = Form("")) -> Response:
    """Set a member's password. The admin's own comes from the environment."""
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin/accounts", err="That account no longer exists.")
        if user.is_admin:
            return redirect(
                "/admin",
                err="The admin password comes from DEALGO_ADMIN_PASSWORD; change it there.",
            )
        try:
            accounts.set_password(session, user, password)
        except accounts.AccountError as exc:
            return redirect("/admin/accounts", err=str(exc))
        name = user.username
    return redirect("/admin/accounts", ok=f"New password set for {name}. Their other sessions ended.")


@router.post("/admin/accounts/{user_pk}/enabled")
def set_account_enabled(request: Request, user_pk: int) -> Response:
    """Switch a member account off (signing it out everywhere) or back on."""
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin/accounts", err="That account no longer exists.")
        if user.is_admin:
            return redirect("/admin/accounts", err="The admin account cannot switch itself off.")
        accounts.set_enabled(session, user, enabled=not user.enabled)
        name, now_on = user.username, user.enabled
    word = "can sign in again" if now_on else "is switched off, and signed out everywhere"
    return redirect("/admin/accounts", ok=f"{name} {word}.")


@router.post("/admin/accounts/{user_pk}/delete")
def remove_account(request: Request, user_pk: int) -> Response:
    """Delete a member account and everything it owns."""
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin/accounts", err="That account no longer exists.")
        name = user.username
        try:
            accounts.delete_user(session, user)
        except accounts.AccountError as exc:
            return redirect("/admin/accounts", err=str(exc))
    return redirect("/admin/accounts", ok=f"Account {name} deleted.")


@router.post("/admin/accounts/{user_pk}/sessions")
def end_account_sessions(request: Request, user_pk: int) -> Response:
    """Sign one account out of every browser."""
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin/accounts", err="That account no longer exists.")
        accounts.revoke_all(session, user)
        name = user.username
    return redirect("/admin/accounts", ok=f"{name} has been signed out everywhere.")


@router.post("/admin/sessions/prune")
def prune_sessions(request: Request) -> Response:
    """Delete every expired sign-in session."""
    with session_scope() as session:
        cleared = accounts.clear_expired(session)
    return redirect("/admin/accounts", ok=f"Cleared {cleared} expired session(s).")
