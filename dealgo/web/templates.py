"""The templates, and the filters and globals they are given."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from .. import __version__, sources
from ..db import get_token, session_scope
from ..models import (
    GENERIC_PLAYLIST_PREFIX,
    Playlist,
)
from ..services import graph as graph_service
from ..services.filters import format_duration
from ..services.scope import OwnerId, owned

BASE_DIR = Path(__file__).parent


TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _asset_version() -> str:
    """Newest mtime across the static files, so a rebuild busts browser caches.

    Without this a redeploy keeps serving the stylesheet the browser already
    has, and a fixed layout still looks broken until someone hard-reloads.
    """
    static = BASE_DIR / "static"
    try:
        newest = max(path.stat().st_mtime for path in static.iterdir() if path.is_file())
    except (OSError, ValueError):  # pragma: no cover - no static dir at all
        return __version__
    return f"{int(newest):x}"


ASSET_VERSION = _asset_version()


def ago(value: dt.datetime | None) -> str:
    """How long ago, said plainly: "3 hours ago"; a date past 30 days."""
    if value is None:
        return "never"
    delta = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - value.replace(tzinfo=None)
    seconds = int(delta.total_seconds())
    if seconds < 0:
        seconds = abs(seconds)
        suffix = "from now"
    else:
        suffix = "ago"
    for limit, unit, size in ((60, "second", 1), (3600, "minute", 60), (86400, "hour", 3600)):
        if seconds < limit:
            count = max(1, seconds // size)
            return f"{count} {unit}{'s' if count != 1 else ''} {suffix}"
    days = seconds // 86400
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} {suffix}"
    return value.strftime("%d %b %Y")


def until(value: dt.datetime | None) -> str:
    """How long until something, said the way a person would say it.

    The mirror of `ago`, and it stops at the same place: past thirty days the
    count stops meaning anything and the date says it better. Something whose
    moment has passed but which is still on the page is going at the end of
    the next run, which is what "any moment" means.
    """
    if value is None:
        return ""
    seconds = int(
        (
            value.replace(tzinfo=None)
            - dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        ).total_seconds()
    )
    if seconds <= 60:
        return "any moment"

    # Rounded to the nearest, and the unit chosen from the rounded number
    # rather than the raw one. Counting down, "in 23 hours" for something a
    # day away is the kind of accuracy nobody asked for: a whole day short
    # of the hour still reads as a day.
    for size, unit, over in ((60, "minute", 60), (3600, "hour", 24), (86400, "day", 30)):
        count = round(seconds / size)
        if count < over:
            return f"in {max(1, count)} {unit}{'s' if count != 1 else ''}"
    return "on " + value.strftime("%d %b %Y")


def spell(seconds: int | None) -> str:
    """A stretch of seconds, said the way somebody would say it.

    Focus counts in seconds and a Decay box is set in minutes, so both land
    here: "45s" and "3 min" rather than one of them in the other's units.
    """
    if not seconds:
        return ""
    if seconds < 60:
        return f"{seconds}s"
    minutes = round(seconds / 60)
    return f"{minutes} min"


def stamp(value: dt.datetime | None) -> str:
    """A time as `YYYY-MM-DD HH:MM UTC`; a dash when there is none."""
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "—"


def clock(value: dt.datetime | None) -> str:
    """Just the time of day, for lines that are all from the same run."""
    return value.strftime("%H:%M:%S") if value else "—"


TEMPLATES.env.globals["source_label"] = lambda kind: sources.describe(kind).label
TEMPLATES.env.globals["source_colour"] = lambda kind: sources.describe(kind).colour


# Whether a palette row is for an augmentation — something that slots under a
# box rather than sitting on a path. A global rather than an argument at each
# call site, because then the palette and the canvas answer it from the same
# list instead of the template carrying a second copy of it.
TEMPLATES.env.globals["is_augmentation"] = (
    lambda kind: kind in graph_service.AUGMENTATIONS
)


# And which boxes it goes under, for the row to say so: once as a sentence
# under the description, once as the list the canvas lights up while it is
# being dragged. Both from the table the drop itself is checked against.
TEMPLATES.env.globals["host_boxes"] = (
    lambda kind, ref="": graph_service.host_boxes(kind, ref)
)


TEMPLATES.env.globals["host_kinds"] = (
    lambda kind, ref="": ",".join(graph_service.hosts_for(kind, ref))
)


TEMPLATES.env.filters["ago"] = ago


TEMPLATES.env.filters["until"] = until


TEMPLATES.env.filters["spell"] = spell


TEMPLATES.env.filters["stamp"] = stamp


TEMPLATES.env.filters["clock"] = clock


# What a template is handed. Jinja takes anything, so this says only that the
# keys are names — the value types are the templates' business.
Context = dict[str, Any]


TEMPLATES.env.filters["duration"] = format_duration


# Bound late: the function is defined further down, and the template calls it
# with the owner the page belongs to.
TEMPLATES.env.globals["youtube_offline"] = lambda owner=None: youtube_offline(owner)


def youtube_offline(owner: OwnerId = None) -> Context | None:
    """The state where Google is not available: no usable account, but feeds
    that point at a YouTube playlist.

    Registered as a template global rather than threaded through every context,
    because the htmx fragments render outside `render()` and need it too.
    """
    with session_scope() as session:
        token = get_token(session, owner)
        if token is not None and not token.refresh_error:
            return None
        feeds = session.scalar(
            owned(select(func.count(Playlist.id)), Playlist, owner).where(
                Playlist.enabled.is_(True),
                Playlist.playlist_id.not_like(f"{GENERIC_PLAYLIST_PREFIX}%"),
            )
        )
        if not feeds:
            return None
        return {"feeds": feeds, "stale": token is not None}
