"""Groups: a background for boxes, and a way to hand a piece of setup to somebody else."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    Channel,
    GraphEdge,
    GraphNode,
    utcnow,
)
from .. import ordering
from ..scope import OwnerId, owned
from .adding import (
    add_format,
    add_pamphlet,
    add_feed,
    add_filter,
    add_piece,
    add_sort,
    add_source,
    add_stamp,
    add_store,
    add_trigger,
)
from . import formatting, leaflets
from .conditions import CONDITION_KINDS, DEFAULT_SORT_BY, RULE, condition, conditions_for
from .errors import GraphError
from .leaflets import LEAFLET_KINDS
from .pieces import attach
from .reading import edges, nodes
from .vocabulary import AUGMENTATIONS, GROUP_LEAST, GROUP_SIZE, STAMPS
from .wiring import connect, refresh_membership

# Bumped if the shape changes in a way a reader would need to know about.
# 2 carries augmentations, each with an `under` naming what it is slotted
# into. A format-1 file has none, and its filter rules are unpacked into
# conditions on the way in, so one exported before this still loads.
# 3 gives the file an `id` and each node a `key`, which last from one export
# of a group to the next, so a newer copy can update what an older one made.
GROUP_FORMAT = 3


def _new_key() -> str:
    return uuid.uuid4().hex[:16]


def _key_of(entry: dict[str, Any]) -> str:
    """A node's key in a file. One from before keys is known by its place."""
    key = entry.get("key")
    return str(key) if key else f"ref-{entry.get('ref', '')}"


def _file_id(payload: dict[str, Any]) -> str:
    """A file's id. One from before ids is known by its name."""
    said = payload.get("id")
    return str(said) if said else f"name:{payload.get('name') or 'Group'}"


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

    # Keys last: a box keeps the key it was given, whether by an earlier
    # export or by the file it was loaded from, so the chain of copies of
    # one group all agree on which box is which.
    if not group.group_key:
        group.group_key = _new_key()
    for node in carried:
        if not node.group_key:
            node.group_key = _new_key()
    session.flush()

    # A leaflet showing a feed in the group travels pointing at that feed's
    # box, since a feed's id means nothing to the account loading the file.
    feed_refs = {
        node.playlist_pk: refs[node.id] for node in carried
        if node.kind == "feed" and node.playlist_pk is not None
    }

    packed: list[dict[str, Any]] = []
    for node in carried:
        entry: dict[str, Any] = {
            "ref": refs[node.id],
            "key": node.group_key,
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
        if node.kind == "format":
            entry["format"] = formatting.settings(node)
        if node.kind in LEAFLET_KINDS:
            entry["side"] = leaflets.side_of(node)
            shown = leaflets.settings(node)
            feed = shown.pop("feed", None)
            if feed in feed_refs:
                entry["feed_ref"] = feed_refs[feed]
            entry["leaflet"] = shown
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
        "id": group.group_key,
        "name": group.label or "Group",
        "width": group.width or GROUP_SIZE[0],
        "height": group.height or GROUP_SIZE[1],
        "nodes": packed,
        # A path wire is a pair; any other kind says what it carries.
        "wires": [
            [refs[start], refs[end]] if carries == "content" else [refs[start], refs[end], carries]
            for start, end, carries in _wires_within(session, carried, owner)
            if start in refs and end in refs
        ],
    }


def _wires_within(
    session: Session, carried: list[GraphNode], owner: OwnerId
) -> list[tuple[int, int, str]]:
    """Every wire with both ends inside the group, and what it carries. A
    wire out of it is not the group's to give away."""
    held = {node.id for node in carried}
    return [
        (edge.source_pk, edge.target_pk, edge.carries)
        for edge in edges(session, owner, every=True)
        if edge.source_pk in held and edge.target_pk in held
    ]


def _check_file(payload: Any) -> dict[str, Any]:
    """A group file this version can read, or GraphError saying why not."""
    if not isinstance(payload, dict) or "de_algo_group" not in payload:
        raise GraphError("That is not a De-Algo group file.")
    version = payload.get("de_algo_group")
    if not isinstance(version, int) or version > GROUP_FORMAT:
        raise GraphError(
            f"That group is format {version}, and this version of De-Algo reads {GROUP_FORMAT}."
        )
    return payload


def import_group(
    session: Session,
    payload: Any,
    owner: OwnerId = None,
    *,
    x: int = 40,
    y: int = 40,
    file_name: str = "",
) -> GraphNode:
    """Load a group somebody else exported, beside whatever is already here.

    Channels are matched by their YouTube id and made if they are missing;
    feeds are always made, as feeds of this account's own. Nothing existing is
    changed: loading somebody's setup adds theirs, it does not replace yours.

    The group remembers the file — its id, each box's key, the file's name —
    so a newer copy of it can update this group later (`update_group`).
    """
    payload = _check_file(payload)

    group = add_group(
        session,
        owner,
        label=str(payload.get("name") or "Group"),
        x=x,
        y=y,
        width=int(payload.get("width") or GROUP_SIZE[0]),
        height=int(payload.get("height") or GROUP_SIZE[1]),
    )
    group.group_key = _file_id(payload)
    group.imported_from = (file_name or "")[:255] or None
    group.imported_at = utcnow()

    made: dict[int, GraphNode] = {}
    for entry in payload.get("nodes") or []:
        if not isinstance(entry, dict):
            continue
        node = _unpack(session, entry, owner, at=(x + int(entry.get("x") or 0),
                                                  y + int(entry.get("y") or 0)))
        if node is not None:
            node.group_key = _key_of(entry)
            _apply(session, node, entry, owner)
            made[int(entry.get("ref", -1))] = node
    session.flush()

    # Slotted in once every box exists, because a piece may be exported
    # before what it goes under. A piece that refuses to go where the file
    # says is left lying on the canvas rather than dropped.
    for entry in payload.get("nodes") or []:
        if isinstance(entry, dict):
            _slot(session, entry, made, owner)
    session.flush()

    _slot_and_wire(session, payload, made, owner, slot=False)
    return group


def _slot(
    session: Session, entry: dict[str, Any], made: dict[int, GraphNode], owner: OwnerId
) -> None:
    """Slot one piece where the file says, and point a leaflet at its feed.

    Refused slots leave the piece lying on the canvas rather than dropped.
    """
    piece = made.get(int(entry.get("ref", -1)))
    if piece is None:
        return
    if piece.kind in LEAFLET_KINDS and "feed_ref" in entry:
        feed = made.get(int(entry.get("feed_ref", -1)))
        if feed is not None and feed.playlist_pk is not None:
            shown = leaflets.settings(piece)
            shown["feed"] = feed.playlist_pk
            piece.leaflet = json.dumps(shown, sort_keys=True)
    if "under" not in entry:
        return
    host = made.get(int(entry.get("under", -1)))
    if host is None or (piece.attached_to == host.id and piece.kind not in LEAFLET_KINDS):
        return
    try:
        attach(session, piece, host, owner, side=str(entry.get("side") or "below"))
    except GraphError:
        return


def _slot_and_wire(
    session: Session,
    payload: dict[str, Any],
    made: dict[int, GraphNode],
    owner: OwnerId,
    *,
    slot: bool = True,
) -> None:
    """Slot each piece under what the file says, then draw the file's wires.

    Pieces are slotted once every box exists, because a piece may be exported
    before what it goes under. A piece that refuses to go where the file says
    is left lying on the canvas rather than dropped; a wire that makes no
    sense here is left out, not fatal.
    """
    if slot:
        for entry in payload.get("nodes") or []:
            if isinstance(entry, dict):
                _slot(session, entry, made, owner)
        session.flush()
    for pair in payload.get("wires") or []:
        if not isinstance(pair, list) or len(pair) not in (2, 3):
            continue
        start, end = made.get(pair[0]), made.get(pair[1])
        if start is None or end is None:
            continue
        carries = str(pair[2]) if len(pair) == 3 else None
        try:
            connect(session, start, end, owner, carries=carries)
        except GraphError:
            continue


def _apply(session: Session, node: GraphNode, entry: dict[str, Any], owner: OwnerId) -> None:
    """Write what a file says about one box onto it: its name, whether it is
    on, and the settings of its kind. The same for a box just made from the
    file and one the file is updating, so the two cannot come out different.
    """
    if entry.get("label") not in (None, "") and node.kind not in ("source", "feed"):
        node.label = str(entry["label"])
    if "enabled" in entry and node.kind not in ("source", "feed"):
        # A source or feed is switched through its channel or playlist.
        node.enabled = bool(entry["enabled"])
    kind = node.kind
    if kind == "source":
        channel_id = entry.get("channel_id")
        if channel_id and (node.channel is None or node.channel.channel_id != channel_id):
            was = node.channel
            found = _channel_for(session, entry, owner)
            if found is not None:
                node.channel = found
                session.flush()
                refresh_membership(session, found, owner)
                if was is not None:
                    refresh_membership(session, was, owner)
    elif kind == "feed":
        title = str(entry.get("title") or "")
        if title and node.playlist is not None and node.playlist.title != title:
            node.playlist.title = title
    elif kind in CONDITION_KINDS:
        spec = condition(kind)
        if spec is not None and entry.get("value") not in (None, ""):
            setattr(node, spec.column, entry.get("value"))
        if "sort_dir" in entry:
            node.sort_dir = str(entry.get("sort_dir") or "desc")
    elif kind == RULE:
        node.plugin_ref = str(entry.get("plugin_ref") or "") or node.plugin_ref
        node.plugin_settings = str(entry.get("plugin_settings") or "") or None
    elif kind == "timer":
        node.duration_minutes = entry.get("duration_minutes")
    elif kind == "reset":
        node.cron = str(entry.get("cron") or "") or None
    elif kind == "alive":
        node.alive_from = str(entry.get("alive_from") or "") or None
        node.alive_to = str(entry.get("alive_to") or "") or None
    elif kind in STAMPS:
        node.marks = str(entry.get("marks") or "")
    elif kind == "format" and isinstance(entry.get("format"), dict):
        try:
            formatting.save(node, {f"format_{k}": str(v) for k, v in entry["format"].items()})
        except GraphError:
            pass  # a file saying something this box cannot do: left as it was
    elif kind in LEAFLET_KINDS and isinstance(entry.get("leaflet"), dict):
        # What it shows, but its feed: that is put back once the feed's box
        # exists, by `_slot`.
        shown = leaflets.settings(node)
        feed = shown.get("feed")
        for key, value in entry["leaflet"].items():
            if key in shown and key != "feed" and (value is None or isinstance(value, (str, int))):
                shown[key] = value
        shown["feed"] = feed
        node.leaflet = json.dumps(shown, sort_keys=True)
    elif kind in ("deposit", "withdraw"):
        node.repository = str(entry.get("repository") or "")
        node.takes = entry.get("takes")
    elif kind == "trigger":
        node.trigger_kind = str(entry.get("trigger_kind") or "pulse")
        node.every_minutes = entry.get("every_minutes")
        node.cron = entry.get("cron")


@dataclass
class GroupUpdate:
    """What updating a group from its file did, to say back."""

    updated: int = 0
    added: int = 0
    removed: int = 0
    #: Feeds whose boxes the file no longer has, kept with their items.
    kept_feeds: list[str] = field(default_factory=list)

    def describe(self, name: str) -> str:
        parts = []
        if self.updated:
            parts.append(f"{self.updated} updated")
        if self.added:
            parts.append(f"{self.added} added")
        if self.removed:
            parts.append(f"{self.removed} removed")
        said = f"“{name}” is up to date with its file" + (f": {', '.join(parts)}." if parts else ".")
        if self.kept_feeds:
            said += (
                " The file no longer has " + ", ".join(f"“{t}”" for t in self.kept_feeds)
                + "; " + ("that feed is" if len(self.kept_feeds) == 1 else "those feeds are")
                + " kept, with everything in them, on the Feed tab."
            )
        return said


def update_group(
    session: Session,
    group_pk: int,
    payload: Any,
    owner: OwnerId = None,
    *,
    file_name: str = "",
) -> GroupUpdate:
    """Bring a loaded group up to date with a newer copy of the file it came from.

    Each box the group was loaded with is found by its key. One the file
    still has is updated in place, so its history, channel and feed are
    kept; one it adds is made; one it no longer has is taken away. Boxes the
    account added to the group itself have no key, and are left alone.

    Taking away is careful: a source box goes but its channel stays if
    anything else draws it, and a feed box goes but its feed and every item
    in it stay — an update must not delete what somebody has been reading.
    Where each box sits is left as the account arranged it; only new boxes
    are placed where the file puts them.

    Wires between the group's own boxes are drawn again from the file. Wires
    to boxes outside the group are kept, as long as both ends still are.
    """
    payload = _check_file(payload)
    group = session.scalar(
        owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == group_pk)
    )
    if group is None or group.kind != "group":
        raise GraphError("That node is not a group.")
    if not group.group_key:
        raise GraphError(
            "This group was not loaded from a file, so there is nothing to update it from."
        )
    if _file_id(payload) != group.group_key:
        raise GraphError(
            f"That file is a different group (“{payload.get('name') or 'Group'}”), not the one "
            "this was loaded from. Use Load a group to add it as a new one."
        )

    result = GroupUpdate()
    carried = inside(session, group, owner)
    keyed = {node.group_key: node for node in carried if node.group_key}

    # Wires among the group's own keyed boxes are the file's, and are
    # redrawn from it; anything touching a box of the account's own stays.
    keyed_ids = {node.id for node in keyed.values()}
    for edge in session.scalars(
        owned(select(GraphEdge), GraphEdge, owner).where(
            GraphEdge.source_pk.in_(keyed_ids), GraphEdge.target_pk.in_(keyed_ids)
        )
    ):
        session.delete(edge)
    session.flush()

    made: dict[int, GraphNode] = {}
    seen: set[str] = set()
    for entry in payload.get("nodes") or []:
        if not isinstance(entry, dict):
            continue
        key = _key_of(entry)
        seen.add(key)
        node = keyed.get(key)
        if node is not None and node.kind != entry.get("kind"):
            # The same place in the file now holds something else: the old
            # box goes, and the new one is made below.
            _take_away(session, node, owner, result)
            node = None
            keyed.pop(key, None)
        if node is None:
            node = _unpack(session, entry, owner, at=(
                group.x + int(entry.get("x") or 0), group.y + int(entry.get("y") or 0)))
            if node is None:
                continue
            node.group_key = key
            result.added += 1
        else:
            result.updated += 1
        _apply(session, node, entry, owner)
        made[int(entry.get("ref", -1))] = node
    session.flush()

    for key, node in keyed.items():
        if key not in seen:
            _take_away(session, node, owner, result)
    session.flush()

    # Pieces go back under what the file says, from the top of each chain.
    for node in made.values():
        if node.kind in AUGMENTATIONS and node.attached_to is not None:
            node.attached_to = None
            node.attached_side = None
    session.flush()
    _slot_and_wire(session, payload, made, owner)

    group.label = str(payload.get("name") or group.label or "Group")
    group.width = max(group.width or GROUP_SIZE[0], int(payload.get("width") or 0))
    group.height = max(group.height or GROUP_SIZE[1], int(payload.get("height") or 0))
    if file_name:
        group.imported_from = file_name[:255]
    group.imported_at = utcnow()
    session.flush()
    return result


def _take_away(session: Session, node: GraphNode, owner: OwnerId, result: GroupUpdate) -> None:
    """A box the file no longer has. Its feed or channel stays; see update_group."""
    from .editing import remove
    from .pieces import close_up, pieces_under

    if node.kind in ("source", "feed"):
        if node.kind == "feed" and node.playlist is not None:
            result.kept_feeds.append(node.playlist.title)
        channel = node.channel
        for piece in pieces_under(nodes(session, owner), node.id):
            if not piece.group_key:
                # A piece the account slotted on itself goes back on the canvas.
                close_up(session, piece)
                piece.attached_to = None
            else:
                session.delete(piece)
        session.delete(node)
        session.flush()
        if channel is not None:
            refresh_membership(session, channel, owner)
    else:
        remove(session, node.id, owner)
    result.removed += 1


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

    if kind == "pamphlet":
        return add_pamphlet(session, owner, label=label, x=x, y=y)

    if kind == "format":
        return add_format(session, owner, label=label, x=x, y=y)

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


def _channel_for(session: Session, entry: dict[str, Any], owner: OwnerId) -> Channel | None:
    """The channel a file's source box watches, by id: this account's, or made."""
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
    return channel


def _unpack_source(
    session: Session, entry: dict[str, Any], owner: OwnerId, *, at: tuple[int, int]
) -> GraphNode | None:
    """A source box from a group file, watching its channel by id."""
    channel = _channel_for(session, entry, owner)
    if channel is None:
        return None
    x, y = at
    return add_source(session, owner, channel=channel, x=x, y=y)


def _unpack_filter(
    session: Session, entry: dict[str, Any], owner: OwnerId, *, at: tuple[int, int]
) -> GraphNode:
    """A Filter box from a group file, with its conditions as pieces."""
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
    """A condition piece from a group file, with its value."""
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
    if group.locked:
        raise GraphError("That group is locked in place. Unlock it to move it.")

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
    """Resize a group box, no smaller than `GROUP_LEAST`. False if it is not a group."""
    group = session.scalar(
        owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
    )
    if group is None or group.kind != "group" or group.locked:
        return False
    group.width = max(GROUP_LEAST[0], int(width))
    group.height = max(GROUP_LEAST[1], int(height))
    session.flush()
    return True


def lock(session: Session, node_pk: int, locked: bool, owner: OwnerId = None) -> bool:
    """Hold a group where it is, or let it go. False if it is not a group."""
    group = session.scalar(
        owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
    )
    if group is None or group.kind != "group":
        return False
    group.locked = locked
    session.flush()
    return True
