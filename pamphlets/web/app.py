"""FastAPI application: the Pamphlets GUI.

Server-rendered HTML so the container ships with no build step and the UI works
in any browser, which is the only GUI that makes sense inside Docker.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .. import __version__, scheduler
from ..config import CONFIG
from ..db import init_db, session_scope
from ..services import accounts
from . import guard, routes
from .responses import is_htmx
from .templates import BASE_DIR

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start up — logging, database, scheduler — and shut the scheduler down after."""
    logging.basicConfig(
        level=CONFIG.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    init_db()
    scheduler.start()
    log.info("Pamphlets %s ready on %s", __version__, CONFIG.public_url)
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="Pamphlets", version=__version__, lifespan=lifespan)


# Starlette hands the next handler in untyped; naming the shape here keeps
# the middleware itself honest about what it returns.
Handler = Callable[[Request], Awaitable[Response]]


@app.middleware("http")
async def require_account(request: Request, call_next: Handler) -> Response:
    """Decide who this is, before any route runs.

    Middleware rather than a dependency on each route: there are sixty of
    them, and one that forgets its dependency is a hole nobody notices. Here
    the default is deny, and the exceptions are a list in guard.py.
    """
    path = request.url.path
    request.state.identity = None

    if not CONFIG.auth_enabled:
        # No admin configured: the app behaves as it did before there were
        # accounts, and says so on every page.
        return await call_next(request)

    token = request.cookies.get(accounts.SESSION_COOKIE) or request.cookies.get(
        accounts.OLD_SESSION_COOKIE
    )

    if guard.is_public(path):
        # Public means "no account required", not "do not look". The login
        # page has to know it is being read by someone already signed in, or
        # it offers the form again and looks as though signing in failed.
        # Skipped for assets, which would otherwise cost a query apiece.
        if token and not path.startswith("/static/"):
            request.state.identity = await run_in_threadpool(_identify, token)
        return await call_next(request)

    identity = await run_in_threadpool(_identify, token)

    if identity is None:
        return _ask_to_sign_in(request)
    if guard.needs_admin(path) and not identity.is_admin:
        return _refuse(request)

    request.state.identity = identity
    return await call_next(request)


def _identify(token: str | None) -> accounts.Identity | None:
    """Who a session cookie belongs to, or None if it is not a live session."""
    with session_scope() as session:
        user = accounts.identify(session, token)
        if user is None:
            return None
        return accounts.Identity(username=user.username, is_admin=user.is_admin, user_pk=user.id)


def _ask_to_sign_in(request: Request) -> Response:
    """Send them to the login page, and back here afterwards.

    An htmx request is answered with the header htmx understands: a plain
    redirect would be followed by the XHR and the login page swapped into
    whatever panel asked.
    """
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    destination = f"/login?next={quote(target, safe='/?=&')}"
    if is_htmx(request):
        return Response(status_code=401, headers={"HX-Redirect": destination})
    return RedirectResponse(destination, status_code=303)


def _refuse(request: Request) -> Response:
    """Turn a member away from an admin page."""
    message = "That part of Pamphlets belongs to the admin account."
    if is_htmx(request):
        return Response(message, status_code=403)
    return RedirectResponse(f"/?err={quote(message)}", status_code=303)


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
for router in routes.ROUTERS:
    app.include_router(router)
