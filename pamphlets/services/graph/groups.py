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
    add_activate,
    add_format,
    add_pamphlet,
    add_feed,
    add_filter,
    add_piece,
    add_sort,
    add_source,
    add_stamp,
    add_store,
    add_text_box,
    add_transform,
    add_trigger,
)
from .insides import add_canvas, add_relay
from . import comments, formatting, leaflets, looks
from .cron import check_cron
from .conditions import CONDITION_KINDS, DEFAULT_SORT_BY, RULE, condition, conditions_for
from .errors import GraphError
from .leaflets import LEAFLET_KINDS
from .pieces import attach
from .units import DEFAULT_CRON, DEFAULT_EVERY_MINUTES
from .reading import edges, nodes
from .vocabulary import AUGMENTATIONS, GROUP_LEAST, GROUP_SIZE, INPUT_KINDS, STAMPS
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

    # Keys last: a box keeps the key it was given, whether by an earlier
    # export or by the file it was loaded from, so the chain of copies of
    # one group all agree on which box is which.
    if not group.group_key:
        group.group_key = _new_key()
    for node in carried:
        if not node.group_key:
            node.group_key = _new_key()
    session.flush()

    packed, wires = pack_nodes(session, carried, group.x, group.y, owner)

    return {
        "pamphlets_group": GROUP_FORMAT,
        "id": group.group_key,
        "name": group.label or "Group",
        "width": group.width or GROUP_SIZE[0],
        "height": group.height or GROUP_SIZE[1],
        "nodes": packed,
        "wires": wires,
    }


def pack_nodes(
    session: Session, carried: list[GraphNode], left: int, top: int, owner: OwnerId = None,
) -> tuple[list[dict[str, Any]], list[list[Any]]]:
    """Boxes as they travel in a file or a copy: each one's settings, where it
    is from (`left`, `top`), what it is slotted under — and the wires between
    them, a path wire as a pair and any other kind saying what it carries."""
    refs = {node.id: index for index, node in enumerate(carried)}
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
            "x": node.x - left,
            "y": node.y - top,
            "label": node.label,
            "enabled": node.switched_on,
        }
        if node.attached_to is not None and node.attached_to in refs:
            # A piece travels as what it is slotted under, not as where it
            # happens to lie: the assembly is the thing being handed over.
            entry["under"] = refs[node.attached_to]
        if node.kind == "format":
            entry["format"] = formatting.settings(node)
        if node.kind == "comment":
            entry["comment"] = comments.settings(node)
            entry["width"], entry["height"] = node.width, node.height
        if node.kind == "text":
            from .. import writing

            entry["writing"] = writing.settings(node)
        if node.kind == "canvas" and node.frozen:
            entry["frozen"] = True
        if node.kind in INPUT_KINDS and node.form_field:
            # A form's field: what it is filed as, asked as, and must be.
            entry["form_field"] = json.loads(node.form_field)
        if node.kind in ("trigger", "activate") and node.activation:
            # An Activation's parameters; an Activate box's values, and the
            # Activation it sets off — by its place in this copy when it is
            # in it, since an id means nothing to an account loading a file.
            said = json.loads(node.activation)
            if node.kind == "activate":
                target = said.pop("target", None)
                if target in refs:
                    said["target_ref"] = refs[target]
                elif isinstance(target, int):
                    said["target_id"] = target
            entry["activation"] = said
        if node.kind == "canvas" and node.width:
            entry["width"], entry["height"] = node.width, node.height
        if node.kind == "canvas" and node.plugins:
            entry["plugins"] = json.loads(node.plugins)
        if node.kind in ("relay", "group"):
            entry["look"] = looks.look(node)
            if node.kind == "group":
                entry["width"], entry["height"] = node.width, node.height
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
            # Which kind of source, and where it is read from: a channel id
            # alone is a YouTube channel's, and every other kind would come
            # back as one.
            entry["source_kind"] = node.channel.source_kind
            if node.channel.source_url:
                entry["source_url"] = node.channel.source_url
            if node.channel.handle:
                entry["handle"] = node.channel.handle
        elif node.kind == "source":
            # Not told which source it is yet: it travels as the kind it was
            # dragged out as, to be told on arrival.
            entry["source_kind"] = node.source_kind or ""
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
            if node.tag_choices:
                entry["tag_choices"] = node.tag_choices
        elif node.kind == "aggregation":
            entry["aggregation"] = node.aggregation or ""
        elif node.kind in ("deposit", "withdraw"):
            entry["repository"] = node.repository or ""
            entry["takes"] = node.takes
        elif node.kind == "trigger":
            entry["trigger_kind"] = node.trigger_kind or "pulse"
            entry["every_minutes"] = node.every_minutes
            entry["cron"] = node.cron
        packed.append(entry)
    # A path wire drawn the usual way is a pair; any other kind says what it
    # carries, one drawn another way says how after that, one coloured says
    # which after that, and one bent by hand says how far, last.
    wires: list[list[Any]] = []
    for start, end, carries, route, colour, bend in _wires_within(session, carried, owner):
        if start not in refs or end not in refs:
            continue
        wire: list[Any] = [refs[start], refs[end]]
        if carries != "content" or route or colour or bend:
            wire.append(carries)
        if route or colour or bend:
            wire.append(route or "curve")
        if colour or bend:
            wire.append(colour or "default")
        if bend:
            wire.append(bend)
        wires.append(wire)
    return packed, wires


def _wires_within(
    session: Session, carried: list[GraphNode], owner: OwnerId
) -> list[tuple[int, int, str, str, str, float]]:
    """Every wire with both ends inside the group, and what it carries. A
    wire out of it is not the group's to give away."""
    held = {node.id for node in carried}
    return [
        (edge.source_pk, edge.target_pk, edge.carries, edge.route or "", edge.colour or "", edge.bend or 0.0)
        # As drawn: a relay travels as a relay, with its wires.
        for edge in edges(session, owner, every=True, raw=True)
        if edge.source_pk in held and edge.target_pk in held
    ]


def _check_file(payload: Any) -> dict[str, Any]:
    """A group file this version can read, or GraphError saying why not."""
    # A group file from before the app was called Pamphlets says so the old way.
    if not isinstance(payload, dict) or not ({"pamphlets_group", "de_algo_group"} & set(payload)):
        raise GraphError("That is not a Pamphlets group file.")
    version = payload.get("pamphlets_group", payload.get("de_algo_group"))
    if not isinstance(version, int) or version > GROUP_FORMAT:
        raise GraphError(
            f"That group is format {version}, and this version of Pamphlets reads {GROUP_FORMAT}."
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
    from .allowing import check_entries
    from .insides import current

    check_entries(session, current(session, owner), list(payload.get("nodes") or []), owner)

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
        node = unpack(session, entry, owner, at=(x + int(entry.get("x") or 0),
                                                  y + int(entry.get("y") or 0)))
        if node is not None:
            node.group_key = _key_of(entry)
            apply(session, node, entry, owner)
            made[int(entry.get("ref", -1))] = node
    session.flush()

    # Slotted in once every box exists, because a piece may be exported
    # before what it goes under. A piece that refuses to go where the file
    # says is left lying on the canvas rather than dropped.
    for entry in payload.get("nodes") or []:
        if isinstance(entry, dict):
            _slot(session, entry, made, owner)
    session.flush()

    slot_and_wire(session, payload, made, owner, slot=False)
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


def _point_activates(session: Session, payload: dict[str, Any], made: dict[int, GraphNode]) -> None:
    """Each Activate box made from a copy or a file, pointed at its Activation:
    the copy of it, when that came too; else the one it pointed at, if it is
    an Activation of this account's. Its values come with it either way."""
    from .activations import set_activate

    for entry in payload.get("nodes") or []:
        if not isinstance(entry, dict) or entry.get("kind") != "activate":
            continue
        box = made.get(int(entry.get("ref", -1)))
        said = entry.get("activation")
        if box is None or not isinstance(said, dict):
            continue
        target = None
        if isinstance(said.get("target_ref"), int) and said["target_ref"] in made:
            target = made[said["target_ref"]].id
        elif isinstance(said.get("target_id"), int):
            target = said["target_id"]
        given = said.get("values")
        values = {str(k): str(v) for k, v in given.items()} if isinstance(given, dict) else {}
        try:
            set_activate(session, box, target, values)
        except GraphError:
            set_activate(session, box, None, values)


def slot_and_wire(
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
    _point_activates(session, payload, made)
    # Round again while any go in: a wire out of a relay can only be drawn
    # once the wire into it is, and the file need not list that one first.
    waiting = [pair for pair in payload.get("wires") or [] if isinstance(pair, list) and 2 <= len(pair) <= 6]
    while waiting:
        refused = []
        for pair in waiting:
            start, end = made.get(pair[0]), made.get(pair[1])
            if start is None or end is None:
                continue
            carries = str(pair[2]) if len(pair) >= 3 else None
            try:
                edge = connect(session, start, end, owner, carries=carries)
                if edge is not None and len(pair) >= 4:
                    looks.set_route(edge, str(pair[3]))
                if edge is not None and len(pair) >= 5:
                    looks.set_colour(edge, str(pair[4]))
                if edge is not None and len(pair) == 6 and isinstance(pair[5], (int, float)):
                    looks.set_bend(edge, float(pair[5]))
            except GraphError:
                refused.append(pair)
        if len(refused) == len(waiting):
            break
        waiting = refused


def apply(session: Session, node: GraphNode, entry: dict[str, Any], owner: OwnerId) -> None:
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
    if kind in INPUT_KINDS and isinstance(entry.get("form_field"), dict):
        node.form_field = json.dumps(entry["form_field"], sort_keys=True)
    if kind == "canvas" and "frozen" in entry:
        node.frozen = entry["frozen"] is True
    if kind == "canvas" and isinstance(entry.get("plugins"), list):
        node.plugins = json.dumps([str(one) for one in entry["plugins"]])
    # How a relay or a group looks: which way it faces, its colour, folded.
    if kind in ("relay", "group") and isinstance(entry.get("look"), dict):
        said = {
            f"look_{key}": ("1" if value else "0") if isinstance(value, bool) else str(value)
            for key, value in entry["look"].items()
        }
        try:
            looks.save(node, said)
        except GraphError:
            pass  # a look this install does not have: as it was, then
    if kind in ("group", "canvas"):
        from .insides import CANVAS_LEAST

        least = GROUP_LEAST if kind == "group" else CANVAS_LEAST
        for side in ("width", "height"):
            if isinstance(entry.get(side), int):
                setattr(node, side, max(least[0 if side == "width" else 1], entry[side]))
    if kind == "text" and isinstance(entry.get("writing"), dict):
        from .. import writing

        try:
            writing.save(node, {f"writing_{key}": str(value) for key, value in entry["writing"].items()})
        except writing.WritingError:
            pass
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
        if kind == "tag" and isinstance(entry.get("tag_choices"), str):
            node.tag_choices = entry["tag_choices"] or None
    elif kind == "aggregation" and isinstance(entry.get("aggregation"), str):
        node.aggregation = entry["aggregation"] or None
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
        # Only what belongs to its kind, as making one keeps it: a pulse its
        # gap, a schedule its time. One the file leaves out keeps the default.
        wanted = entry.get("trigger_kind")
        node.trigger_kind = wanted if wanted in ("schedule", "activation") else "pulse"
        every, cron = entry.get("every_minutes"), entry.get("cron")
        if node.trigger_kind == "activation":
            # On no clock: what it takes is all there is to it.
            node.every_minutes = node.cron = None
            given = entry.get("activation")
            if isinstance(given, dict):
                node.activation = json.dumps({"params": given.get("params") or []})
        elif node.trigger_kind == "pulse":
            node.cron = None
            if isinstance(every, int) and every > 0:
                node.every_minutes = every
            node.every_minutes = node.every_minutes or DEFAULT_EVERY_MINUTES
        else:
            node.every_minutes = None
            if isinstance(cron, str) and cron.strip():
                try:
                    node.cron = check_cron(cron)
                except GraphError:
                    pass  # a time this cannot read: the default, as made
            node.cron = node.cron or DEFAULT_CRON


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
            node = unpack(session, entry, owner, at=(
                group.x + int(entry.get("x") or 0), group.y + int(entry.get("y") or 0)))
            if node is None:
                continue
            node.group_key = key
            result.added += 1
        else:
            result.updated += 1
        apply(session, node, entry, owner)
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
    slot_and_wire(session, payload, made, owner)

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


def unpack(
    session: Session, entry: dict[str, Any], owner: OwnerId, *, at: tuple[int, int]
) -> GraphNode | None:
    """One node out of a group file."""
    kind = entry.get("kind")
    if kind == leaflets.OLD_CHART:
        # A file from before each chart had its own leaflet: the chart it drew.
        found = entry.get("leaflet")
        said: dict[str, Any] = found if isinstance(found, dict) else {}
        kind, style = leaflets.current_kind(kind, said)
        entry["kind"] = kind
        entry["leaflet"] = {**{k: v for k, v in said.items() if k != "kind"}, **style}
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

    if kind == "group":
        # Only in a copy: a group's own file is the group, not one of its boxes.
        return add_group(
            session, owner, label=label, x=x, y=y,
            width=int(entry.get("width") or GROUP_SIZE[0]), height=int(entry.get("height") or GROUP_SIZE[1]),
        )

    if kind == "format":
        return add_format(session, owner, label=label, x=x, y=y)

    if kind == "comment":
        written = entry.get("comment")
        words: dict[str, Any] = written if isinstance(written, dict) else {}
        made = comments.add_comment(session, owner, text=str(words.get("text") or ""), x=x, y=y)
        try:
            comments.save(made, {"comment_colour": str(words.get("colour") or "paper")})
        except GraphError:
            pass  # a colour this install does not have: paper, then
        for side in ("width", "height"):
            if isinstance(entry.get(side), int):
                setattr(made, side, max(comments.LEAST[0 if side == "width" else 1], entry[side]))
        return made

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

    if kind == "transform":
        return add_transform(session, owner, label=label, x=x, y=y)

    if kind == "text":
        return add_text_box(session, owner, label=label, x=x, y=y)

    if kind == "relay":
        return add_relay(session, owner, x=x, y=y)

    if kind == "canvas":
        # Made in the canvas being worked in, as everything else is.
        return add_canvas(session, owner, label=label, x=x, y=y)

    if kind == "activate":
        return add_activate(session, owner, label=label, x=x, y=y)

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
            # A file from before kinds were written down is YouTube's: the
            # only kind group files were made of then.
            source_kind=str(entry.get("source_kind") or "youtube")[:12],
            source_url=str(entry["source_url"]) if entry.get("source_url") else None,
            handle=str(entry["handle"])[:255] if entry.get("handle") else None,
        )
        session.add(channel)
        session.flush()
        ordering.append(session, channel)
    return channel


def _unpack_source(
    session: Session, entry: dict[str, Any], owner: OwnerId, *, at: tuple[int, int]
) -> GraphNode | None:
    """A source box from a group file, watching its channel by id."""
    x, y = at
    channel = _channel_for(session, entry, owner)
    if channel is None:
        # An empty box — dragged out, never told which source — comes as one.
        if entry.get("channel_id"):
            return None
        return add_source(session, owner, source_kind=str(entry.get("source_kind") or ""), x=x, y=y)
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
        # Only in its own canvas: one inside a Canvas node at the same spot
        # is somewhere else altogether.
        and node.inside_pk == group.inside_pk
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
    if group is None or group.kind not in ("group", "comment", "canvas") or group.locked:
        return False
    # A comment or a canvas is resized as a group is, down to a size of its own.
    from .insides import CANVAS_LEAST

    least = comments.LEAST if group.kind == "comment" else CANVAS_LEAST if group.kind == "canvas" else GROUP_LEAST
    group.width = max(least[0], int(width))
    group.height = max(least[1], int(height))
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
