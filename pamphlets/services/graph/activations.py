"""Activation triggers, and the Activate boxes that set them off.

An **Activation** is a trigger on no clock: it starts the flow it is wired to
— the sources and Withdraw boxes it signals, as any trigger does — only when
something sets it off. It says what it takes: a list of **parameters**, each
with a default.

An **Activate** box ends a path, as a feed or a Deposit does. It names one
Activation, anywhere in the account — in another canvas too, which is how
one flow starts another — and what to fill each of its parameters with:
words, or `{{ fields }}` of what reaches it (the first item to, and the data
wired into its `{ }` port as `{{ data… }}`), or both.

Once per run, an Activate box that anything reached sets its Activation off
with the values filled in. The flow it starts reads them as
`{{ params.name }}` — in a REST API source's address and header, a Text box's
instructions — and they come out of the Activation's own `{ }` port as one
row, for a Format box, a Transform, a Text box or a chart.

A chain of them goes five deep at most, so a ring of flows that set each
other off stops rather than running for ever. An Activation in a frozen
canvas, or switched off, is not set off.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Collection
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Channel, GraphNode, Video, utcnow
from ..scope import OwnerId, owned
from .errors import GraphError
from .reading import nodes

#: How many activations deep a chain goes: one flow setting off another,
#: setting off another…
MOST_DEPTH = 5

#: What a parameter may be called: what `{{ params.name }}` can name.
NAME = re.compile(r"^[a-z_][a-z0-9_]{0,39}$")

#: How many parameters an Activation takes, at most.
MOST_PARAMS = 20


def is_activation(node: GraphNode | None) -> bool:
    return node is not None and node.kind == "trigger" and node.trigger_kind == "activation"


def _said(node: GraphNode) -> dict[str, Any]:
    try:
        said = json.loads(node.activation or "{}")
    except ValueError:
        return {}
    return said if isinstance(said, dict) else {}


# -- an Activation's parameters ------------------------------------------------


def params(node: GraphNode) -> list[dict[str, str]]:
    """The parameters an Activation takes, in order: each a name and a default."""
    found = []
    for one in _said(node).get("params") or []:
        if isinstance(one, dict) and isinstance(one.get("name"), str) and NAME.match(one["name"]):
            found.append({"name": one["name"], "default": str(one.get("default") or "")})
    return found


def defaults(node: GraphNode) -> dict[str, str]:
    return {one["name"]: one["default"] for one in params(node)}


def last(node: GraphNode) -> dict[str, str]:
    """The values it was last set off with — its defaults, until it has been."""
    said = _said(node).get("last")
    values = defaults(node)
    if isinstance(said, dict):
        values.update({name: str(value) for name, value in said.items() if name in values})
    return values


def set_params(node: GraphNode, names: list[str], given_defaults: list[str]) -> None:
    """Say what an Activation takes. Blank names are dropped; a name it cannot
    be read by, or the same name twice, is refused."""
    if not is_activation(node):
        raise GraphError("Only an Activation trigger takes parameters.")
    found: list[dict[str, str]] = []
    for name, default in zip(names, given_defaults + [""] * len(names)):
        name = name.strip().lower()
        if not name:
            continue
        if not NAME.match(name):
            raise GraphError(
                f"“{name}” cannot be a parameter's name: letters, digits and _, starting with a letter."
            )
        if any(one["name"] == name for one in found):
            raise GraphError(f"There are two parameters called “{name}”.")
        found.append({"name": name, "default": default.strip()[:500]})
    if len(found) > MOST_PARAMS:
        raise GraphError(f"An Activation takes {MOST_PARAMS} parameters at most.")
    said = _said(node)
    said["params"] = found
    node.activation = json.dumps(said)


def set_off(node: GraphNode, values: dict[str, str], by: int | None = None) -> dict[str, str]:
    """Keep what an Activation is being set off with, when, and by which
    Activate box (None by hand): its parameters only, a missing one taking
    its default. Answers the values."""
    kept = defaults(node)
    kept.update({name: str(value)[:2000] for name, value in values.items() if name in kept})
    said = _said(node)
    said["last"] = kept
    said["by"] = by
    node.activation = json.dumps(said)
    node.last_fired_at = utcnow()
    return kept


def as_row(node: GraphNode) -> list[dict[str, str]]:
    """What comes out of an Activation's `{ }` port: its values, as one row."""
    return [last(node)]


# -- an Activate box -----------------------------------------------------------


def target_of(session: Session, box: GraphNode) -> GraphNode | None:
    """The Activation an Activate box sets off, if it names one that is there."""
    pk = _said(box).get("target")
    if not isinstance(pk, int):
        return None
    found = session.get(GraphNode, pk)
    if not is_activation(found) or found is None or found.owner_pk != box.owner_pk:
        return None
    return found


def values_of(box: GraphNode) -> dict[str, str]:
    """What an Activate box fills each parameter with, as written."""
    said = _said(box).get("values")
    return {str(k): str(v) for k, v in said.items()} if isinstance(said, dict) else {}


def set_activate(session: Session, box: GraphNode, target: int | None, values: dict[str, str]) -> None:
    """Say which Activation an Activate box sets off, and with what."""
    if box.kind != "activate":
        raise GraphError("Only an Activate box sets an Activation off.")
    if target is not None:
        found = session.get(GraphNode, target)
        if not is_activation(found) or found is None or found.owner_pk != box.owner_pk:
            raise GraphError("That is not an Activation trigger of yours.")
    said = _said(box)
    said["target"] = target
    said["values"] = {name: value.strip()[:2000] for name, value in values.items()}
    box.activation = json.dumps(said)


def choices(session: Session, owner: OwnerId = None) -> list[dict[str, Any]]:
    """Every Activation an Activate box could set off, in any canvas: its
    name, where it is, and the parameters it takes."""
    every = nodes(session, owner)
    by_id = {node.id: node for node in every}
    found = []
    for node in every:
        if not is_activation(node):
            continue
        where: list[str] = []
        inside = node.inside_pk
        while inside is not None and len(where) < 6:
            holder = by_id.get(inside)
            if holder is None:
                break
            where.insert(0, holder.title)
            inside = holder.inside_pk
        found.append({
            "id": node.id,
            "title": node.title,
            "where": " › ".join(where),
            "params": [one["name"] for one in params(node)],
        })
    return found


def fill_values(box: GraphNode, item: dict[str, Any] | None, data: Any, passed: dict[str, str]) -> dict[str, str]:
    """An Activate box's values, filled: each `{{ field }}` from the first item
    to reach it, `{{ data… }}` from what is wired into its `{ }` port, and
    `{{ params… }}` from the Activation that started its own flow, if one did."""
    from .templating import fill

    context: dict[str, Any] = {**(item or {}), "data": data, "params": passed}
    return {name: fill(template, context) for name, template in values_of(box).items()}


# -- what a run does -----------------------------------------------------------


def _item_row(video: Video) -> dict[str, Any]:
    """An item as an Activate box's fields read it."""
    return {
        "title": video.title or "",
        "link": video.link or "",
        "words": video.body or "",
        "kind": video.kind,
        "source": video.channel.title if video.channel else "",
        "published": video.published_at.isoformat() if video.published_at else "",
        "duration": video.duration_sec or 0,
        "tags": ", ".join(video.tag_list),
    }


def reached(
    session: Session, owner: OwnerId, since: dt.datetime, sources: Collection[int] | None = None,
) -> dict[int, Video]:
    """The Activate boxes something reached in a run begun at `since`, each
    with the first item that did: items that arrived in the run, from a
    source box down a path that lets them through to it. `sources` narrows
    it to paths from those boxes, as the run itself was narrowed."""
    from ...db import get_settings
    from ..sync.deciding import decide
    from .routes import routes_to_activate

    settings = get_settings(session, owner)
    found: dict[int, Video] = {}
    arrived: dict[int, list[Video]] = {}
    for path in routes_to_activate(session, owner):
        box = path.finish
        if box is None or box.id in found:
            continue
        if sources is not None and (path.source is None or path.source.id not in sources):
            continue
        if path.channel.id not in arrived:
            arrived[path.channel.id] = list(session.scalars(
                owned(select(Video), Video, owner)
                .where(Video.channel_pk == path.channel.id, Video.discovered_at >= since)
                .order_by(Video.published_at.desc(), Video.id.desc())
            ))
        for video in arrived[path.channel.id]:
            if decide(video, path, None, settings).accept:
                found[box.id] = video
                break
    return found


def fire_reached(
    session: Session, owner: OwnerId, since: dt.datetime, sources: Collection[int] | None,
    say: Any = None,
) -> list[int]:
    """Set off the Activation of every Activate box something reached in this
    run, once each, with its values filled in. Answers the Activations set
    off, for their flows to run."""
    from .formatting import data_into

    fired: list[int] = []
    for box_pk, video in reached(session, owner, since, sources).items():
        box = session.get(GraphNode, box_pk)
        if box is None or not box.enabled:
            continue
        target = target_of(session, box)
        if target is None or not target.enabled or target.id in fired:
            continue
        values = fill_values(box, _item_row(video), data_into(session, box, owner), params_for(session, box, owner))
        kept = set_off(target, values, by=box.id)
        fired.append(target.id)
        if say is not None:
            shown = ", ".join(f"{k} = “{v}”" for k, v in kept.items()) or "no parameters"
            say.write(f"{box.title} set off {target.title} ({shown})", about=video.title or None)
    session.flush()
    return fired


def what_it_starts(session: Session, node: GraphNode, owner: OwnerId) -> tuple[list[int], list[int], list[int]]:
    """What an Activation's flow is: the channels to poll, the source boxes
    whose paths to fill, and the Withdraw boxes to pull."""
    from .triggers import wired_channels, wired_sources, wired_withdrawals

    channels = [
        pk for pk in wired_channels(session, node, owner)
        if (channel := session.get(Channel, pk)) is not None and channel.enabled
    ]
    return channels, wired_sources(session, node, owner), [one.id for one in wired_withdrawals(session, node, owner)]


# -- Return boxes: what an activated flow sends back -------------------------


def set_by(node: GraphNode) -> int | None:
    """The Activate box that last set an Activation off; None if by hand."""
    by = _said(node).get("by")
    return by if isinstance(by, int) else None


def returned(box: GraphNode) -> Any:
    """What an Activate box's Activation sent back last, through its flow's
    Return box: what comes out of its `{ }` port. None until something has."""
    return _said(box).get("returned")


def returned_at(box: GraphNode) -> str | None:
    when = _said(box).get("returned_at")
    return when if isinstance(when, str) else None


def send_back(session: Session, owner: OwnerId, activation: int, say: Any = None) -> int:
    """At the end of a flow an Activation started: what reached each Return
    box in it, sent back to the Activate box that set it off. Data wired into
    a Return box goes back as it is; items, as rows. Answers how many went."""
    from .formatting import data_into, incoming, items_into

    node = session.get(GraphNode, activation)
    if not is_activation(node) or node is None:
        return 0
    caller = session.get(GraphNode, set_by(node) or -1)
    if caller is None or caller.kind != "activate":
        return 0
    sent = 0
    for box in nodes(session, owner):
        if box.kind != "return" or not box.enabled or activation not in started_by(session, box, owner):
            continue
        value: Any = (
            data_into(session, box, owner) if incoming(session, box, owner, "data")
            else items_into(session, box, owner)
        )
        said = _said(caller)
        said["returned"] = value
        said["returned_at"] = utcnow().isoformat()
        said["returned_by"] = box.id
        caller.activation = json.dumps(said, default=str)
        sent += 1
        if say is not None:
            say.write(f"{box.title} sent back to {caller.title}")
    session.flush()
    return sent


# -- {{ params }} in the flow an Activation starts -----------------------------


def started_by(session: Session, node: GraphNode, owner: OwnerId = None) -> list[int]:
    """The Activations whose flow a box is in, nearest first."""
    from .reading import edges

    into: dict[int, list[int]] = {}
    for edge in edges(session, owner, every=True):
        into.setdefault(edge.target_pk, []).append(edge.source_pk)
    found: list[int] = []
    seen: set[int] = set()
    waiting = [node.id]
    while waiting:
        at = waiting.pop(0)
        if at in seen:
            continue
        seen.add(at)
        holder = session.get(GraphNode, at)
        if is_activation(holder):
            found.append(at)
            continue
        waiting.extend(into.get(at, []))
    return found


def params_for(session: Session, node: GraphNode, owner: OwnerId = None) -> dict[str, str]:
    """The values `{{ params… }}` reads in a box: those of the Activation(s)
    whose flow it is in — found by walking back along the wires it is on to
    the triggers at their start. The nearest one's win a name both have."""
    from .reading import edges

    into: dict[int, list[int]] = {}
    for edge in edges(session, owner, every=True):
        into.setdefault(edge.target_pk, []).append(edge.source_pk)
    values: dict[str, str] = {}
    seen: set[int] = set()
    waiting = [node.id]
    while waiting:
        at = waiting.pop(0)
        if at in seen:
            continue
        seen.add(at)
        holder = session.get(GraphNode, at)
        if is_activation(holder) and holder is not None:
            for name, value in last(holder).items():
                values.setdefault(name, value)
            continue
        waiting.extend(into.get(at, []))
    return values


def params_for_channel(session: Session, channel: Channel) -> dict[str, str]:
    """What `{{ params… }}` reads in a source's own settings — its REST API
    address and header: the values of the Activations wired to its boxes."""
    values: dict[str, str] = {}
    boxes = session.scalars(select(GraphNode).where(GraphNode.kind == "source", GraphNode.channel_pk == channel.id))
    for box in boxes:
        for name, value in params_for(session, box, box.owner_pk).items():
            values.setdefault(name, value)
    return values
