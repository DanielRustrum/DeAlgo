"""Which plugins' boxes a canvas offers.

A Canvas node can say which installed plugins' boxes may be used inside it —
their sources and the conditions they add. Its palette then shows only
those, and a box of any other plugin is refused there: dropped in, pasted
in, or moved in by a cut. Left unsaid, every plugin is offered.

A canvas inside it offers no more than the canvases around it: what one
leaves out, nothing inside it can take back. Boxes already inside when a
plugin is left out stay where they are, and run.

The app's own boxes — feeds, filters, triggers, feed addresses, newsletters,
REST APIs — are not a plugin's, and are offered everywhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import CURRENT_INSIDE, Channel, GraphNode
from ..scope import OwnerId, owned
from ...plugins import registry
from .conditions import RULE
from .errors import GraphError


@dataclass(frozen=True)
class Offered:
    """One working plugin, and the boxes it puts in the palette."""

    id: str
    title: str
    kinds: frozenset[str]
    refs: frozenset[str]


def offered() -> list[Offered]:
    """The working plugins that put anything in the palette, in the order
    the registry read them."""
    found = []
    for plugin in registry.current().working:
        kinds = frozenset(kind.kind for kind in plugin.sources)
        refs = frozenset(one.ref for one in plugin.augments)
        if kinds or refs:
            found.append(Offered(plugin.id, plugin.title, kinds, refs))
    return found


def plugin_of(*, source_kind: str = "", ref: str = "") -> Offered | None:
    """The plugin a source kind or a condition's ref is from, if a plugin's."""
    for plugin in offered():
        if (source_kind and source_kind in plugin.kinds) or (ref and ref in plugin.refs):
            return plugin
    return None


def plugin_of_node(node: GraphNode) -> Offered | None:
    """The plugin a box is from: a source of one of its kinds, or one of its
    conditions. None for the app's own boxes."""
    if node.kind == "source":
        kind = node.channel.source_kind if node.channel is not None else node.source_kind
        return plugin_of(source_kind=kind or "")
    if node.kind == RULE:
        return plugin_of(ref=node.plugin_ref or "")
    return None


def own(node: GraphNode) -> set[str] | None:
    """The plugins a canvas itself says to offer; None for every one."""
    if not node.plugins:
        return None
    try:
        said = json.loads(node.plugins)
    except ValueError:
        return None
    return {str(one) for one in said} if isinstance(said, list) else None


def allowed_in(session: Session, inside: int | None) -> set[str] | None:
    """The plugins whose boxes may be used in a canvas: what it and every
    canvas around it allow. None where every plugin is."""
    allowed: set[str] | None = None
    seen: set[int] = set()
    while inside is not None and inside not in seen and len(seen) <= 6:
        seen.add(inside)
        holder = session.get(GraphNode, inside)
        if holder is None:
            break
        says = own(holder)
        if says is not None:
            allowed = says if allowed is None else allowed & says
        inside = holder.inside_pk
    return allowed


def check(session: Session, inside: int | None, plugin: Offered | None) -> None:
    """Refuse a plugin's box in a canvas that does not offer it."""
    if plugin is None:
        return
    allowed = allowed_in(session, inside)
    if allowed is not None and plugin.id not in allowed:
        raise GraphError(f"{plugin.title}'s boxes are not offered in this canvas: its Plugins tab says which are.")


def check_here(session: Session, *, source_kind: str = "", ref: str = "") -> None:
    """Refuse a plugin's box in the canvas boxes are being made in."""
    check(session, CURRENT_INSIDE.get(), plugin_of(source_kind=source_kind, ref=ref))


def check_entries(
    session: Session, inside: int | None, entries: list[Any], owner: OwnerId = None,
) -> None:
    """Refuse a copy or a file before any of it is made, if a box in it is a
    plugin's this canvas does not offer — rather than making half of it."""
    if allowed_in(session, inside) is None:
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == RULE:
            check(session, inside, plugin_of(ref=str(entry.get("plugin_ref") or "")))
        elif entry.get("kind") == "source":
            check(session, inside, plugin_of(source_kind=_entry_kind(session, entry, owner)))


def _entry_kind(session: Session, entry: dict[str, Any], owner: OwnerId) -> str:
    """Which kind of source a copied or filed source box is."""
    channel = None
    if isinstance(entry.get("channel_pk"), int):
        channel = session.scalar(owned(select(Channel), Channel, owner).where(Channel.id == entry["channel_pk"]))
    if channel is None and entry.get("channel_id"):
        channel = session.scalar(
            owned(select(Channel), Channel, owner).where(Channel.channel_id == str(entry["channel_id"]))
        )
    if channel is not None:
        return channel.source_kind or ""
    return str(entry.get("source_kind") or "")


def set_allowed(node: GraphNode, plugin_ids: list[str] | None) -> None:
    """Say which plugins a canvas offers — None, or every working plugin,
    for all of them, including any installed later."""
    if node.kind != "canvas":
        raise GraphError("Only a Canvas box says which plugins it offers.")
    if plugin_ids is None:
        node.plugins = None
        return
    working = {plugin.id for plugin in offered()}
    wanted = sorted({one for one in plugin_ids if one in working})
    node.plugins = None if set(wanted) == working else json.dumps(wanted)
