"""The way in: the front door."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ...db import session_scope
from ..responses import owner_of, redirect
from .pamphlets import default_pamphlet, show_pamphlet

router = APIRouter()


@router.get("/")
def front_door(request: Request) -> Response:
    """The default pamphlet, at the bare address; with none chosen, the
    Pamphlets tab, to choose one or open another.

    Shown here rather than sent on to its own address, so the address the
    app opens at — and what an installed app opens — is the front page
    itself. The feed is a tab away.
    """
    owner = owner_of(request)
    with session_scope() as session:
        chosen = default_pamphlet(session, owner)
        if chosen is not None:
            return show_pamphlet(request, session, owner, chosen)
    return redirect("/pamphlets")
