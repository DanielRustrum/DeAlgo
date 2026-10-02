"""The way in: the front door and the tour."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ...db import session_scope
from ..responses import owner_of, redirect, render, tour_progress

if TYPE_CHECKING:
    pass

router = APIRouter()


@router.get("/")
def front_door(request: Request) -> RedirectResponse:
    """Straight to the feed.

    There was a dashboard here: counts, a list of feeds, a status block and
    what had turned up lately. Every part of it was a second view of
    something with a page of its own, and it sat in front of the thing the
    app is for. The counts moved to Configuration, which is the page that
    can act on them; the rest was already somewhere.
    """
    return redirect("/feed")


@router.get("/tour", response_class=HTMLResponse)
def tour(request: Request, step: int = 1) -> HTMLResponse:
    """A guided walk from an empty install to a daily habit."""
    owner = owner_of(request)
    with session_scope() as session:
        progress = tour_progress(session, owner)
        context = {"progress": progress, "step": step}
    return render(request, "tour.html", context)
