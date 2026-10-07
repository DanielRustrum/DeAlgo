"""The Configuration page: the canvas, its palette, and the stats above it."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...db import session_scope
from ...plugins import registry
from ...services import graph as graph_service
from ..contexts import channel_list_context, connection_state, playlist_context, stats_context
from ..responses import owner_of, render
from ..templates import Context

router = APIRouter()


@router.get("/channels", response_class=HTMLResponse)
def channels_page(
    request: Request, feed: str = "", new: str = "", track: str = "", q: str = ""
) -> HTMLResponse:
    """The Configuration page: the canvas, its palette, and the counts above it."""
    owner = owner_of(request)
    with session_scope() as session:
        context = {
            **channel_list_context(session, feed, tracking=track == "1", query=q, owner=owner),
            **playlist_context(session, creating=new == "1", owner=owner),
            # What there is, and what is stopping it working. Both used to be
            # on a page of their own; this is the page that can act on either.
            **stats_context(session, owner),
            "state": connection_state(session, owner),
            "plugin_nodes": _palette_plugins(),
        }
    return render(request, "channels.html", context)


def _palette_plugins() -> list[Context]:
    """What the plugins put in the palette, grouped by the plugin offering it.

    A plugin's source box comes first in its own group, because that is the
    box somebody is looking for: there is no generic Channel box any more,
    and the way to watch a subreddit is to drag out the Subreddit box.

    In the order the registry read them, so the palette is the same on every
    visit. A plugin offering nothing is left out entirely rather than shown
    as an empty heading, which would be a question about nothing.
    """
    found = registry.current()
    grouped: dict[str, list[Context]] = {}
    for kind in found.source_kinds():
        grouped.setdefault(kind.plugin, []).append(
            {
                "palette": "source",
                "ref": kind.kind,
                "label": kind.noun or kind.label,
                "blurb": kind.blurb or f"One {kind.label} source.",
                "swatch": "source",
                "colour": kind.colour,
            }
        )
    # One condition piece per thing a plugin knows how to ask. A plugin has no
    # box of its own: it widens what the app's Filter box can be told, rather
    # than standing a second kind of Filter beside it.
    for node in found.augmentations():
        grouped.setdefault(node.plugin, []).append(
            {
                "palette": graph_service.RULE,
                "ref": node.ref,
                "label": node.label,
                "blurb": node.blurb,
                "swatch": graph_service.RULE,
            }
        )
    return [{"plugin": plugin, "nodes": nodes} for plugin, nodes in grouped.items()]
