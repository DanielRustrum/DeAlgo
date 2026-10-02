"""Signing in and out."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from ...config import CONFIG
from ...db import session_scope
from ...services import accounts
from .. import guard
from ..responses import redirect, render

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

router = APIRouter()


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    """Http-only so no script can read it, Lax so it does not ride along with
    a cross-site form post, Secure wherever the connection can carry it."""
    response.set_cookie(
        accounts.SESSION_COOKIE,
        token,
        max_age=CONFIG.session_days * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "") -> Response:
    """The sign-in form, or onward if already signed in or sign-in is off."""
    if not CONFIG.auth_enabled:
        return redirect("/")
    if getattr(request.state, "identity", None) is not None:
        return redirect(guard.safe_next(next))
    return render(request, "login.html", {"next": guard.safe_next(next)})


@router.post("/login")
def sign_in(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
) -> Response:
    """Check the password and start a session; back to the form if it is wrong."""
    if not CONFIG.auth_enabled:
        return redirect("/")

    destination = guard.safe_next(next)
    with session_scope() as session:
        try:
            user = accounts.authenticate(session, username, password)
        except accounts.AccountError as exc:
            log.info("failed sign-in for %r", username.strip()[:64])
            return render(
                request,
                "login.html",
                {"next": destination, "username": username, "error_message": str(exc)},
            )
        token = accounts.start_session(
            session, user, agent=request.headers.get("user-agent", "")
        )

    response = redirect(destination, ok=f"Signed in as {username.strip().lower()}.")
    _set_session_cookie(response, request, token)
    return response


@router.post("/logout")
def sign_out(request: Request) -> Response:
    """End this browser's session."""
    with session_scope() as session:
        accounts.end_session(session, request.cookies.get(accounts.SESSION_COOKIE))
    response = redirect("/login", ok="Signed out.")
    response.delete_cookie(accounts.SESSION_COOKIE, path="/")
    return response


@router.get("/logout")
def sign_out_link(request: Request) -> Response:
    """So the menu can offer it as a plain link with no JavaScript."""
    return sign_out(request)
