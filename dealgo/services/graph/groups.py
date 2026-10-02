"""Groups: a background for boxes, and a way to hand a piece of setup to somebody else."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    Channel,
    GraphNode,
)
from .. import ordering
from ..scope import OwnerId, owned
from .adding import (
    add_feed,
    add_filter,
    add_piece,
    add_sort,
    add_source,
    add_stamp,
    add_store,
    add_trigger,
)
from .conditions import CONDITION_KINDS, DEFAULT_SORT_BY, RULE, condition, conditions_for
from .errors import GraphError
from .pieces import attach
from .reading import nodes
from .vocabulary import AUGMENTATIONS, GROUP_LEAST, GROUP_SIZE, STAMPS
from .wiring import connect, wires

# Bumped if the shape changes in a way a reader would need to know about.
# 2 carries augmentations, each with an `under` naming what it is slotted
# into. A format-1 file has none, and its filter rules are unpacked into
# conditions on the way in, so one exported before this still loads.
GROUP_FORMAT = 2


def export_group(session: Session, node_pk: int, owner: OwnerId = None) -> dict[str, Any]:
    """A group as a piece of setup somebody else can load.

    Positions are relative to the group's own corner, so it lands wherever it
    is dropped rather than on top of whatever is already at those coordinates.
    Channels travel as their YouTube ids, which mean the same thing on any
    machine; feeds travel as names, because a playlist id belongs to whoever
    owns the playlist and would be nobody else's to write to.
    """
    group = session.scalar(
        owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
    )
    if group is None or group.kind != "group":
        raise GraphError("That node is not a group.")

    carried = inside(session, group, owner)
    refs = {node.id: index for index, node in enumerate(carried)}

    packed: list[dict[str, Any]] = []
    for node in carried:
        entry: dict[str, Any] = {
            "ref": refs[node.id],
            "kind": node.kind,
            "x": node.x - group.x,
            "y": node.y - group.y,
            "label": node.label,
            "enabled": node.enabled,
        }
        if node.attached_to is not None and node.attached_to in refs:
            # A piece travels as what it is slotted under, not as where it
            # happens to lie: the assembly is the thing being handed over.
            entry["under"] = refs[node.attached_to]
        if node.kind == "source" and node.channel is not None:
            entry["channel_id"] = node.channel.channel_id
            entry["title"] = node.channel.title
        elif node.kind == "feed" and node.playlist is not None:
            entry["title"] = node.playlist.title
        elif node.kind in CONDITION_KINDS:
            # A condition carries one value, in the column that rule lives
            # in. Written under its own name so the file reads as what it is.
            spec = condition(node.kind)
            if spec is not None:
                entry["value"] = getattr(node, spec.column, None)
            entry["sort_dir"] = node.sort_dir or "desc"
        elif node.kind == RULE:
            entry["plugin_ref"] = node.plugin_ref or ""
            entry["plugin_settings"] = node.plugin_settings or ""
        elif node.kind == "timer":
            entry["duration_minutes"] = node.duration_minutes
        elif node.kind == "reset":
            entry["cron"] = node.cron
        elif node.kind == "alive":
            entry["alive_from"] = node.alive_from or ""
            entry["alive_to"] = node.alive_to or ""
        elif node.kind == "tag":
            entry["marks"] = node.marks or ""
        elif node.kind in ("deposit", "withdraw"):
            entry["repository"] = node.repository or ""
            entry["takes"] = node.takes
        elif node.kind == "trigger":
            entry["trigger_kind"] = node.trigger_kind or "pulse"
            entry["every_minutes"] = node.every_minutes
            entry["cron"] = node.cron
        packed.append(entry)

    return {
        "de_algo_group": GROUP_FORMAT,
        "name": group.label or "Group",
        "width": group.width or GROUP_SIZE[0],
        "height": group.height or GROUP_SIZE[1],
        "nodes": packed,
        "wires": [
            [refs[start], refs[end]]
            for start, end in _wires_within(session, carried, owner)
            if start in refs and end in refs
        ],
    }


def _wires_within(
    session: Session, carried: list[GraphNode], owner: OwnerId
) -> list[tuple[int, int]]:
    """Every wire with both ends inside the group. A wire out of it is not
    the group's to give away."""
    held = {node.id for node in carried}
    drawn: list[tuple[int, int]] = []
    for wire in wires(session, owner):
        start, end = int(wire["from"]), int(wire["to"])
        if start in held and end in held:
            drawn.append((start, end))
    return drawn


def import_group(
    session: Session,
    payload: Any,
    owner: OwnerId = None,
    *,
    x: int = 40,
    y: int = 40,
) -> GraphNode:
    """Load a group somebody else exported, beside whatever is already here.

    Channels are matched by their YouTube id and made if they are missing;
    feeds are always made, as feeds of this account's own. Nothing existing is
    changed: loading somebody's setup adds theirs, it does not replace yours.
    """
    if not isinstance(payload, dict) or "de_algo_group" not in payload:
        raise GraphError("That is not a De-Algo group file.")
    version = payload.get("de_algo_group")
    if not isinstance(version, int) or version > GROUP_FORMAT:
        raise GraphError(
            f"That group is format {version}, and this version of De-Algo reads {GROUP_FORMAT}."
        )

    group = add_group(
        session,
        owner,
        label=str(payload.get("name") or "Group"),
        x=x,
        y=y,
        width=int(payload.get("width") or GROUP_SIZE[0]),
        height=int(payload.get("height") or GROUP_SIZE[1]),
    )

    made: dict[int, GraphNode] = {}
    for entry in payload.get("nodes") or []:
        if not isinstance(entry, dict):
            continue
        node = _unpack(session, entry, owner, at=(x + int(entry.get("x") or 0),
                                                  y + int(entry.get("y") or 0)))
        if node is not None:
            made[int(entry.get("ref", -1))] = node
    session.flush()

    # Slotted in once every box exists, because a piece may be exported
    # before what it goes under. A piece that refuses to go where the file
    # says is left lying on the canvas rather than dropped.
    for entry in payload.get("nodes") or []:
        if not isinstance(entry, dict) or "under" not in entry:
            continue
        piece = made.get(int(entry.get("ref", -1)))
        host = made.get(int(entry.get("under", -1)))
        if piece is None or host is None:
            continue
        try:
            attach(session, piece, host, owner)
        except GraphError:
            continue
    session.flush()

    for pair in payload.get("wires") or []:
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        start, end = made.get(pair[0]), made.get(pair[1])
        if start is None or end is None:
            continue
        try:
            connect(session, start, end, owner)
        except GraphError:
            continue  # a wire that makes no sense here is dropped, not fatal
    return group


def _unpack(
    session: Session, entry: dict[str, Any], owner: OwnerId, *, at: tuple[int, int]
) -> GraphNode | None:
    """One node out of a group file."""
    kind = entry.get("kind")
    label = str(entry.get("label") or "")
    x, y = at

    if kind == "source":
        return _unpack_source(session, entry, owner, at=at)

    if kind == "feed":
        from .. import playlists as playlist_service

        playlist = playlist_service.create_generic(
            session, str(entry.get("title") or "Imported feed"), owner
        )
        return add_feed(session, playlist, owner, x=x, y=y)

    if kind == "filter":
        return _unpack_filter(session, entry, owner, at=at)

    if kind == "sort":
        node = add_sort(session, owner, label=label, x=x, y=y)
        if "sort_by" in entry:
            add_piece(
                session, owner, kind="order", host=node, x=x, y=y + 60,
                sort_by=str(entry.get("sort_by") or DEFAULT_SORT_BY),
                newest_first=str(entry.get("sort_dir") or "desc") == "desc",
            )
        return node

    if kind in CONDITION_KINDS:
        return _unpack_condition(session, entry, owner, kind=kind, at=at)

    if kind in AUGMENTATIONS:
        return add_piece(
            session, owner, kind=kind, x=x, y=y,
            duration_minutes=entry.get("duration_minutes"),
            cron=str(entry.get("cron") or "") or None,
            alive=(str(entry.get("alive_from") or ""), str(entry.get("alive_to") or "")),
            ref=str(entry.get("plugin_ref") or ""),
        )

    if kind in ("deposit", "withdraw"):
        return add_store(
            session, owner, kind=kind,
            repository=str(entry.get("repository") or ""),
            takes=entry.get("takes"), x=x, y=y,
        )

    if kind in STAMPS:
        return add_stamp(
            session, owner, kind=kind, marks=str(entry.get("marks") or ""), x=x, y=y
        )

    if kind == "trigger":
        return add_trigger(
            session,
            owner,
            trigger_kind=str(entry.get("trigger_kind") or "pulse"),
            label=label,
            every_minutes=entry.get("every_minutes"),
            cron=entry.get("cron"),
            x=x,
            y=y,
        )
    return None


def _unpack_source(
    session: Session, entry: dict[str, Any], owner: OwnerId, *, at: tuple[int, int]
) -> GraphNode | None:
    channel_id = entry.get("channel_id")
    if not channel_id:
        return None
    channel = session.scalar(
        owned(select(Channel), Channel, owner).where(Channel.channel_id == channel_id)
    )
    if channel is None:
        # Made from the file rather than looked up: a UC id is enough to
        # watch a channel, and asking YouTube would make loading a group
        # need credentials it has no other use for.
        channel = Channel(
            owner_pk=owner,
            channel_id=str(channel_id),
            title=str(entry.get("title") or channel_id),
            enabled=False,
        )
        session.add(channel)
        session.flush()
        ordering.append(session, channel)
    x, y = at
    return add_source(session, owner, channel=channel, x=x, y=y)


def _unpack_filter(
    session: Session, entry: dict[str, Any], owner: OwnerId, *, at: tuple[int, int]
) -> GraphNode:
    x, y = at
    node = add_filter(session, owner, label=str(entry.get("label") or "") or "Filter", x=x, y=y)
    # A format-1 file kept every rule on the box. They are pieces now, so
    # the file is unpacked into pieces — the same conversion the database
    # got, said once more for a file somebody exported before it.
    rules = entry.get("rules")
    if isinstance(rules, dict):
        under: GraphNode = node
        for spec in conditions_for("filter"):
            said = rules.get(spec.column)
            if said is None or said == "":
                continue
            under = add_piece(
                session, owner, kind=spec.kind, host=under, x=x, y=y + 60
            )
            setattr(under, spec.column, said)
    return node


def _unpack_condition(
    session: Session, entry: dict[str, Any], owner: OwnerId, *, kind: str, at: tuple[int, int]
) -> GraphNode:
    x, y = at
    piece = add_piece(
        session, owner, kind=kind, x=x, y=y,
        sort_by=str(entry.get("value") or DEFAULT_SORT_BY),
        newest_first=str(entry.get("sort_dir") or "desc") == "desc",
    )
    said = condition(kind)
    if said is not None and kind != "order" and entry.get("value") not in (None, ""):
        setattr(piece, said.column, entry.get("value"))
    return piece


def add_group(
    session: Session,
    owner: OwnerId = None,
    *,
    label: str = "",
    x: int = 40,
    y: int = 40,
    width: int = GROUP_SIZE[0],
    height: int = GROUP_SIZE[1],
) -> GraphNode:
    """A rectangle drawn behind the others. What it surrounds travels with it."""
    node = GraphNode(
        owner_pk=owner,
        kind="group",
        label=label,
        x=x,
        y=y,
        width=max(GROUP_LEAST[0], width),
        height=max(GROUP_LEAST[1], height),
    )
    session.add(node)
    session.flush()
    return node


def inside(session: Session, group: GraphNode, owner: OwnerId = None) -> list[GraphNode]:
    """What a group surrounds.

    Worked out from where things are rather than remembered, because that is
    how it is said: a node is in a group when the group is drawn around it,
    and dragging one out takes it out. Nothing is written when a node moves,
    so there is no membership to fall out of step with the drawing.

    A node counts as surrounded when its own corner is inside, which is the
    rule a reader applies at a glance and the one that survives a node being
    wider than it looks.
    """
    if group.kind != "group":
        return []
    right = group.x + (group.width or GROUP_SIZE[0])
    bottom = group.y + (group.height or GROUP_SIZE[1])
    return [
        node
        for node in nodes(session, owner)
        if node.id != group.id
        and node.kind != "group"  # a group inside a group would move twice
        and group.x <= node.x <= right
        and group.y <= node.y <= bottom
    ]


def move_group(
    session: Session, node_pk: int, x: int, y: int, owner: OwnerId = None
) -> list[GraphNode]:
    """Move a group, and everything it surrounds, by the same amount."""
    group = session.scalar(
        owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
    )
    if group is None or group.kind != "group":
        raise GraphError("That node is not a group.")

    carried = inside(session, group, owner)
    across, down = int(x) - group.x, int(y) - group.y
    group.x, group.y = int(x), int(y)
    for node in carried:
        node.x += across
        node.y += down
    session.flush()
    return carried


def resize(
    session: Session, node_pk: int, width: int, height: int, owner: OwnerId = None
) -> bool:
    group = session.scalar(
        owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
    )
    if group is None or group.kind != "group":
        return False
    group.width = max(GROUP_LEAST[0], int(width))
    group.height = max(GROUP_LEAST[1], int(height))
    session.flush()
    return True
