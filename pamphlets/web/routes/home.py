"""The way in: the front door."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ..responses import redirect

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

