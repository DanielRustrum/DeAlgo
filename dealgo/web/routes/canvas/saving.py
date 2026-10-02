"""Saving what a box's panel says, and what follows from it."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .... import outgoing, sources
from ....db import session_scope
from ....models import (
    Channel,
    GraphNode,
    Playlist,
)
from ....plugins import registry
from ....services import channels as channel_service
from ....services import graph as graph_service
from ....services.scope import OwnerId, owned
from ...responses import owner_of

if TYPE_CHECKING:
    pass
from .facts import orders
from .payload import graph_payload

router = APIRouter()


@router.post("/graph/nodes/{node_pk}")
async def graph_save_node(
    request: Request,
    node_pk: int,
    label: str = Form(""),
    handle: str = Form(""),
    source_pk: str = Form(""),
    backfill: str = Form(""),
    # An unticked checkbox is not submitted at all, so "off" and "this form
    # never showed the switch" arrive looking identical. This marker is what
    # tells them apart: only a form that says it carried the switches may
    # turn any of them off. One marker for every kind of box, because every
    # kind of box has the same switch on it.
    box_form: str = Form(""),
    active: str = Form(""),
    max_items: str = Form(""),
    feed_max_per_run: str = Form(""),
    takes_videos: str = Form(""),
    takes_shorts: str = Form(""),
    takes_live: str = Form(""),
    takes_posts: str = Form(""),
    mirror_url: str = Form(""),
    every_minutes: str = Form(""),
    cron: str = Form(""),
    every_unit: str = Form(""),
    duration_minutes: str = Form(""),
    sort_by: str = Form(""),
    sort_dir: str = Form(""),
    # What a condition piece is set to. One pair rather than a parameter per
    # rule: a piece carries exactly one value, and which column it lands in
    # is the piece's kind rather than the form's business.
    value: str = Form(""),
    value_unit: str = Form(""),
    repository: str = Form(""),
    takes_how_many: str = Form(""),
    alive_from: str = Form(""),
    alive_to: str = Form(""),
    marks: str = Form(""),
) -> JSONResponse:
    """Save what a box says about itself.

    One route for every kind, because the canvas has one way to open a box and
    one Save in it. What each kind carries differs; what they share is a name.
    """
    owner = owner_of(request)
    with session_scope() as session:
        node = session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
        )
        if node is None:
            return JSONResponse({"error": "That node is not here."}, status_code=404)

        answer = _point_source(session, node, source_pk, handle, backfill, owner)
        if answer is not None:
            return answer

        graph_service.rename(session, node.id, label, owner)

        if box_form == "1":
            _switch(session, node, on=active == "1", owner=owner)

        if node.kind == "feed" and node.playlist is not None and box_form == "1":
            _save_feed(node.playlist, max_items=max_items, max_per_run=feed_max_per_run)
        elif node.kind == "source" and node.channel is not None and box_form == "1":
            answer = _save_channel(
                session,
                node.channel,
                takes={
                    "videos": takes_videos, "shorts": takes_shorts,
                    "live": takes_live, "posts": takes_posts,
                },
                mirror_url=mirror_url,
            )
            if answer is not None:
                return answer
        elif node.kind == "tag":
            node.marks = graph_service.tag_name(marks) or None
        elif node.kind in graph_service.CONDITION_KINDS:
            answer = _save_condition(
                node, value=value, unit=value_unit, sort_by=sort_by, sort_dir=sort_dir
            )
            if answer is not None:
                return answer
        elif node.kind == graph_service.RULE:
            await _save_plugin_box(request, node)
            # A plugin's ordering carries which end comes first, the same way
            # the app's own Order piece does.
            if orders(node):
                node.sort_dir = "asc" if sort_dir == "asc" else "desc"
        elif node.kind in graph_service.AUGMENTATIONS:
            answer = _save_piece(
                node, alive_from=alive_from, alive_to=alive_to,
                duration_minutes=duration_minutes, every_unit=every_unit, cron=cron,
            )
            if answer is not None:
                return answer
        elif node.kind in ("deposit", "withdraw"):
            _save_store(node, repository=repository, takes_how_many=takes_how_many)
        elif node.kind == "trigger":
            answer = _save_trigger(node, every_minutes, every_unit, cron, duration_minutes)
            if answer is not None:
                return answer

        session.flush()
        return JSONResponse(graph_payload(session, owner))


def _point_source(
    session: Session, node: GraphNode, source_pk: str, handle: str, backfill: str, owner: OwnerId
) -> JSONResponse | None:
    """Point a source box at a source: one already watched, or a new one typed in."""
    if node.kind != "source":
        return None
    if source_pk.strip().isdigit():
        # Pointed at something already watched, rather than told again.
        return _attach_watched(session, node, int(source_pk), owner)
    if handle.strip():
        return _attach_channel(session, node, handle.strip(), backfill, owner)
    return None


def _save_piece(
    node: GraphNode,
    *,
    alive_from: str,
    alive_to: str,
    duration_minutes: str,
    every_unit: str,
    cron: str,
) -> JSONResponse | None:
    """An Alive's hours, a Timer's length, or a Reset's schedule."""
    if node.kind == "alive":
        begins = graph_service.clock_time(alive_from)
        ends = graph_service.clock_time(alive_to)
        if (alive_from.strip() and not begins) or (alive_to.strip() and not ends):
            return JSONResponse(
                {"error": "Write the times as HH:MM, on a 24-hour clock."},
                status_code=400,
            )
        node.alive_from, node.alive_to = begins or None, ends or None
    elif node.kind == "timer":
        wanted = duration_minutes.strip()
        node.duration_minutes = (
            graph_service.every_minutes_from(int(wanted), every_unit or "minutes")
            if wanted.isdigit() and int(wanted) > 0
            else None
        )
    else:
        try:
            graph_service.cron_trigger(cron.strip() or graph_service.DEFAULT_CRON)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        node.cron = cron.strip() or graph_service.DEFAULT_CRON
    return None


def _save_store(node: GraphNode, *, repository: str, takes_how_many: str) -> None:
    """Which repository a Deposit or Withdraw box is an end of, and how much a pull takes."""
    # The name is what joins the two ends. Filed the way the walk files it,
    # so a name typed two ways is still one repository.
    node.repository = graph_service.store_name(repository) or None
    if node.kind == "withdraw":
        wanted = takes_how_many.strip()
        # Empty, or nothing that reads as a number, means everything waiting
        # — which is what the field says it means and the least surprising
        # answer to an unreadable one.
        node.takes = int(wanted) if wanted.isdigit() and int(wanted) > 0 else None


def _attach_channel(
    session: Session, node: GraphNode, wanted: str, backfill: str, owner: OwnerId
) -> JSONResponse | None:
    """Tell an empty channel box which channel it is. None means it worked."""
    if node.channel is not None:
        return None  # already named; the rename below is all that was meant

    # A channel already being watched is attached rather than refused: two
    # nodes for one channel is a way of wiring it down two paths that filter
    # differently, and is worth being able to draw.
    already = _channel_already_here(session, wanted, owner)
    if already is not None:
        graph_service.attach_channel(session, node, already, owner)
        return None

    with outgoing.client() as http:
        try:
            # Within the kind this box was dragged out as, so what is typed
            # is read the way somebody typing into that box meant it: "python"
            # in a Subreddit box is r/python and nothing else.
            channel = channel_service.add_source(
                session,
                wanted,
                http,
                backfill_days=channel_service.parse_backfill(backfill),
                within=node.source_kind or "",
                owner=owner,
            )
        except channel_service.ChannelError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    graph_service.attach_channel(session, node, channel, owner)
    return None


def _switch(
    session: Session, node: GraphNode, *, on: bool, owner: OwnerId = None
) -> None:
    """Turn a box on or off, and the thing behind it where that is the same.

    The box's own switch, always. Whether it also reaches the channel or the
    playlist is the rule a rename lives by: a box speaks for the thing behind
    it only while it is the only box for it. Two boxes that switched each
    other off would be one box in two places, which is the opposite of why
    you drew the second.

    Switching one *on* always reaches it, however many boxes there are. That
    is the plain reading: a box switched on for a channel nobody is watching
    would sit there doing nothing, and there is nowhere else to say you want
    it back.
    """
    node.enabled = on
    if not (on or graph_service.stands_alone(session, node, owner)):
        return
    if node.kind == "source" and node.channel is not None:
        node.channel.enabled = on
    elif node.kind == "feed" and node.playlist is not None:
        node.playlist.enabled = on


def _save_feed(playlist: Playlist, *, max_items: str, max_per_run: str) -> None:
    """How much this feed takes.

    Both limits count from zero meaning no limit, so an unreadable answer
    becomes no limit rather than a limit of nothing — which would quietly stop
    the feed filling at all.
    """
    for name, raw in (("max_items", max_items), ("max_per_run", max_per_run)):
        wanted = raw.strip()
        setattr(playlist, name, int(wanted) if wanted.isdigit() else 0)


def _save_channel(
    session: Session,
    channel: Channel,
    *,
    takes: dict[str, str],
    mirror_url: str = "",
) -> JSONResponse | None:
    """What kinds the channel takes.

    Not what it filters: narrowing by title or length is a filter box's job,
    and offering it here as well would be two places to look for one answer.

    Through the same services the channel's own page uses, not by setting the
    columns: turning something back on brings back what was skipped for that
    reason, and writing ``skip_shorts = False`` here would quietly lose that.
    Each is only called when the answer actually changed, so saving the box
    without touching a switch requeues nothing.

    Only reached for a form that said it carried these fields, so an unticked
    box here really does mean off.
    """
    switches = (
        ("videos", channel.skip_videos, channel_service.set_videos),
        ("shorts", channel.skip_shorts, channel_service.set_shorts),
        ("live", channel.skip_live, channel_service.set_live),
        ("posts", channel.skip_posts, channel_service.set_posts),
    )
    for name, skipping, apply in switches:
        wanted = takes[name] == "1"
        if wanted is skipping:  # it was off and is wanted on, or the reverse
            apply(session, channel, include=wanted)

    wanted_mirror = mirror_url.strip()
    if wanted_mirror and not wanted_mirror.lower().startswith(("http://", "https://")):
        return JSONResponse(
            {"error": "A mirror is a web address — it should start with https://."},
            status_code=400,
        )
    channel.mirror_url = wanted_mirror or None

    session.flush()
    return None


def _attach_watched(
    session: Session, node: GraphNode, channel_pk: int, owner: OwnerId
) -> JSONResponse | None:
    """Point an empty channel node at a source already being watched."""
    if node.channel is not None:
        return None
    channel = session.scalar(
        owned(select(Channel), Channel, owner).where(Channel.id == channel_pk)
    )
    if channel is None:
        return JSONResponse({"error": "That source is not here."}, status_code=400)
    graph_service.attach_channel(session, node, channel, owner)
    return None


def _channel_already_here(session: Session, wanted: str, owner: OwnerId) -> Channel | None:
    """A channel this account already watches, by whatever was typed.

    Matched without asking YouTube: an id or a handle already on record is
    enough, and a lookup would cost a request to tell us what we know.
    """
    typed = wanted.strip()
    found = session.scalar(
        owned(select(Channel), Channel, owner).where(
            or_(
                Channel.channel_id == typed,
                func.lower(Channel.handle) == typed.lower(),
                func.lower(Channel.title) == typed.lower(),
            )
        )
    )
    if found is not None:
        return found

    # A source elsewhere is filed under the short name its kind reduces to, so
    # a pasted URL and the r/ name that means the same thing find one row. A
    # YouTube handle is the exception: nothing here can turn one into a
    # channel id, so there is no key to look up and the caller resolves it.
    try:
        said = sources.resolve(typed)
    except sources.UnknownSource:
        return None
    if said.needs_host:
        return None
    key = said.key
    return session.scalar(
        owned(select(Channel), Channel, owner).where(Channel.channel_id == key)
    )


async def _save_plugin_box(request: Request, node: GraphNode) -> None:
    """Keep whatever a plugin augmentation's own fields were set to.

    Read straight off the form rather than through named parameters, because
    the host does not know the names: they are the plugin's to declare, and a
    parameter per field is not something a plugin can ask for.

    Only fields the plugin still declares are kept. A box whose plugin has
    dropped a field should not carry it for ever in a column nobody reads.
    """
    box = registry.current().augmentation(node.plugin_ref or "")
    if box is None:
        return  # its plugin is off; there is nothing to save it against

    sent = await request.form()
    kept: dict[str, str] = {}
    for one in box.fields:
        value = sent.get(f"plugin_{one.name}")
        kept[one.name] = str(value).strip() if isinstance(value, str) else one.default
    node.plugin_settings = json.dumps(kept) if kept else None


def _save_trigger(
    node: GraphNode, every_minutes: str, every_unit: str, cron: str, duration: str
) -> JSONResponse | None:
    wanted_window = duration.strip()
    if wanted_window.isdigit() and int(wanted_window) > 0:
        node.duration_minutes = int(wanted_window)
    elif wanted_window != "":
        node.duration_minutes = graph_service.DEFAULT_DURATION_MINUTES

    if node.trigger_kind == "schedule":
        try:
            node.cron = graph_service.check_cron(cron)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return None
    wanted = every_minutes.strip()
    # The number is in whatever unit was chosen beside it; minutes is what is
    # stored, and what an older form with no unit at all meant. Zero is a real
    # answer — "every run there is" — rather than a missing one, so it is kept
    # instead of being replaced by the default.
    if wanted.isdigit():
        node.every_minutes = graph_service.every_minutes_from(
            int(wanted), every_unit or "minutes"
        )
    else:
        node.every_minutes = graph_service.DEFAULT_EVERY_MINUTES
    return None


def _save_condition(
    node: GraphNode, *, value: str, unit: str, sort_by: str, sort_dir: str
) -> JSONResponse | None:
    """What one condition piece was told, into the column that rule lives in.

    A blank is stored as NULL rather than as zero or false: an empty
    condition narrows nothing and leaves the answer to the channel, which is
    the whole difference between a condition and a second copy of the
    channel's settings.
    """
    spec = graph_service.condition(node.kind)
    if spec is None:
        return None

    if spec.field == "order":
        try:
            node.sort_by = graph_service.check_sort_key(
                sort_by or graph_service.DEFAULT_SORT_BY
            )
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        node.sort_dir = "asc" if sort_dir == "asc" else "desc"
        return None

    said = value.strip()
    if spec.field == "text":
        # A tag is filed the way every other tag is filed, so one typed two
        # ways still matches the Tag box that put it on.
        kept = graph_service.tag_name(said) if node.kind == "carrying" else said
        setattr(node, spec.column, kept or None)
        return None

    if not (said.isdigit() and int(said) > 0):
        setattr(node, spec.column, None)
        return None
    if spec.field == "duration":
        setattr(node, spec.column, graph_service.seconds_from(int(said), unit))
    else:
        setattr(node, spec.column, int(said))
    return None
