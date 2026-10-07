"""Augmentations: slotting a piece under a box, and finding the chain under one."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    GraphNode,
)
from ..scope import OwnerId
from .conditions import CONDITIONS, RULE
from .leaflets import LEAFLET_KINDS, SIDES, side_of
from .errors import GraphError
from .reading import nodes
from .vocabulary import AUGMENTATIONS, BOX_NAMES

#: Which boxes each augmentation may be slotted under. An Alive under a
#: Filter would be a piece nobody ever reads, so it is refused at the drop
#: rather than discovered later by a box that quietly does nothing.
#:
#: This is the one answer: the palette prints it on every row, the canvas
#: lights up the boxes it names while a piece is dragged, and `attach`
#: refuses anything else. Three places saying different things is how you
#: end up able to drop something where it will never be read.
PIECE_HOSTS: dict[str, tuple[str, ...]] = {
    # A Timer is an amount of time and means something different in each:
    # a sitting, how long you get with one item, how long an item stays.
    "timer": ("feed", "decay", "expire"),
    # The other three are about reading a feed, and only a feed reads them.
    "reset": ("feed",),
    "alive": ("feed",),
    # And a Lock is about a Decay's Timer being one you cannot pause.
    "lock": ("decay",),
    # After watching starts an Expire's Timer when the item is watched.
    "after-watch": ("expire",),
    **{one.kind: (one.under,) for one in CONDITIONS},
    # A leaflet is a block of a Pamphlet's page, and means nothing anywhere else.
    **{kind: ("pamphlet",) for kind in LEAFLET_KINDS},
}


def hosts_for(kind: str, ref: str = "") -> tuple[str, ...]:
    """Which boxes an augmentation of this kind may be slotted under.

    A plugin's is asked of the plugin rather than read off the table: what
    it goes under is the plugin's to declare, and a Filter and a Sort ask
    different enough questions that one answering either would do nothing
    under the other.

    Empty where there is nothing to say — this is not an augmentation, or it
    is one whose plugin is switched off. An empty answer is not a refusal:
    see `attach`, which takes it as "no opinion" rather than "nowhere".
    """
    if kind != RULE:
        return PIECE_HOSTS.get(kind, ())
    from ...plugins import registry

    found = registry.current().augmentation(ref)
    # Its plugin is switched off or gone. It narrows nothing while that is
    # true, and refusing to move it as well would be twice the punishment
    # for something that is not the canvas's fault.
    return () if found is None else (found.under,)


def host_boxes(kind: str, ref: str = "") -> list[dict[str, str]]:
    """Where one goes, as the boxes themselves: their kind and their name.

    Named rather than described, because a list of names is what the reader
    is actually going to look for in the palette — and because two of them
    read no worse than one, where a sentence has to choose between "or" and
    "and" for something that is neither.
    """
    return [
        {"kind": one, "label": BOX_NAMES.get(one, one.title())}
        for one in hosts_for(kind, ref)
    ]


def piece_hosts(piece: GraphNode) -> tuple[str, ...] | None:
    """Which boxes this particular piece may be slotted under.

    None means nothing is known about where it goes, which is not the same
    as nowhere: a piece whose plugin is switched off would otherwise be
    unmovable as well as inert.
    """
    found = hosts_for(piece.kind, piece.plugin_ref or "")
    return found or None


def attach(
    session: Session, piece: GraphNode, host: GraphNode, owner: OwnerId = None,
    side: str = "below",
) -> GraphNode:
    """Slot an augmentation under a box, or under another one.

    Refused where it would make no sense, said at the moment of the drop
    rather than discovered later by a piece that quietly does nothing.

    A leaflet can also go `side="beside"` another leaflet, which starts the
    next column of its pamphlet's page. Every other piece only hangs below.
    """
    if piece.kind not in AUGMENTATIONS:
        raise GraphError(f"A {piece.kind} box is not an augmentation.")
    if piece.id == host.id:
        raise GraphError("A piece cannot be slotted under itself.")
    if host.kind == "group":
        raise GraphError("A group is a background, not something to slot into.")

    # Where this kind of piece is allowed to end up. A chain belongs to the
    # box at the top of it, so what matters is that box and not whatever the
    # piece was dropped directly onto.
    wanted = piece_hosts(piece)
    if wanted is not None:
        landing = host if host.kind not in AUGMENTATIONS else host_of(nodes(session, owner), host)
        if landing is None or landing.kind not in wanted:
            named = " or a ".join(one.capitalize() for one in wanted)
            raise GraphError(f"{piece.title} goes under a {named} box.")

    leaflet = piece.kind in LEAFLET_KINDS
    if leaflet:
        side = side if side in SIDES else "below"
        if side == "beside" and host.kind not in LEAFLET_KINDS:
            raise GraphError("A leaflet goes beside another leaflet, or below the Pamphlet box.")

    # No rings. Walking up from the host must not arrive back at the piece.
    seen = {piece.id}
    walk: GraphNode | None = host
    while walk is not None:
        if walk.id in seen:
            raise GraphError("That would slot a piece under itself.")
        seen.add(walk.id)
        walk = session.get(GraphNode, walk.attached_to) if walk.attached_to else None

    if not leaflet:
        piece.attached_to = host.id
        session.flush()
        return piece

    # A leaflet moved from elsewhere leaves a closed-up gap behind it.
    if piece.attached_to is not None:
        close_up(session, piece)
    # An edge holds one leaflet. Whatever already hung there hangs on from
    # the new one instead, so dropping a leaflet between two puts it between
    # them rather than beside the one that was there.
    taken = _hanging(session, host.id, side, but=piece.id)
    piece.attached_to = host.id
    piece.attached_side = side
    session.flush()
    if taken is not None:
        end = piece
        while (further := _hanging(session, end.id, side, but=taken.id)) is not None:
            end = further
        taken.attached_to = end.id
        session.flush()
    return piece


def _hanging(session: Session, host_pk: int, side: str, *, but: int = 0) -> GraphNode | None:
    """The leaflet hanging from one edge of a box or leaflet, if any."""
    for one in session.scalars(
        select(GraphNode).where(GraphNode.attached_to == host_pk).order_by(GraphNode.id)
    ):
        if one.id != but and one.kind in LEAFLET_KINDS and side_of(one) == side:
            return one
    return None


def detach(session: Session, piece: GraphNode) -> bool:
    """Take a piece out of whatever it was slotted under.

    What was under it closes up behind it. Taking the middle piece out of a
    chain is taking one piece out, not breaking the chain in half: everything
    below it would otherwise be hanging off a piece that is slotted into
    nothing, which is to say doing nothing at all.
    """
    if piece.attached_to is None:
        return False
    close_up(session, piece)
    piece.attached_to = None
    piece.attached_side = None
    session.flush()
    return True


def close_up(session: Session, piece: GraphNode) -> None:
    """Move whatever is under a piece up to whatever the piece was under.

    Said in one place because both ways of taking a piece out of a chain —
    unslotting it and deleting it — have to do it, and a chain that healed
    one way and not the other would be worse than one that never healed.
    """
    hanging = list(session.scalars(
        select(GraphNode).where(GraphNode.attached_to == piece.id).order_by(GraphNode.id)
    ))
    if piece.kind in LEAFLET_KINDS:
        _close_up_leaflet(session, piece, hanging)
        return
    for below in hanging:
        below.attached_to = piece.attached_to
    session.flush()


def _close_up_leaflet(session: Session, piece: GraphNode, hanging: list[GraphNode]) -> None:
    """A leaflet's gap, closed the way its page would close it.

    What was below it moves up into its place; what was beside it stays
    beside, now beside what moved up. With nothing below, what was beside it
    moves across into its place instead.
    """
    below = [one for one in hanging if side_of(one) == "below"]
    beside = [one for one in hanging if side_of(one) == "beside"]
    order = below + beside
    if not order:
        return
    first = order[0]
    first.attached_to = piece.attached_to
    first.attached_side = piece.attached_side if piece.attached_to is not None else None
    session.flush()
    # Anything else that hung from it goes beside the end of the row the
    # first one now heads, so nothing is left hanging from a gap.
    for one in order[1:]:
        end = first
        while (further := _hanging(session, end.id, "beside", but=one.id)) is not None:
            end = further
        one.attached_to = end.id
        one.attached_side = "beside"
        session.flush()


def pieces_under(all_nodes: list[GraphNode], host_pk: int) -> list[GraphNode]:
    """Every augmentation in the chain under one box, nearest first.

    A chain rather than a list: a piece may be slotted under another, and all
    of them belong to the box at the top. Nearest first because that is the
    order they are read in — the one closest to the box has the last word,
    the same rule a filter nearest a feed lives by.
    """
    below: dict[int, list[GraphNode]] = {}
    for node in all_nodes:
        if node.kind in AUGMENTATIONS and node.attached_to is not None:
            below.setdefault(node.attached_to, []).append(node)

    found: list[GraphNode] = []
    queue = list(below.get(host_pk, []))
    seen: set[int] = set()
    while queue:
        piece = queue.pop(0)
        if piece.id in seen:
            continue  # a ring somebody built before this refused to make one
        seen.add(piece.id)
        found.append(piece)
        queue.extend(below.get(piece.id, []))
    return found


def host_of(all_nodes: list[GraphNode], piece: GraphNode) -> GraphNode | None:
    """The box at the top of a piece's chain, which is what it changes."""
    by_id = {node.id: node for node in all_nodes}
    seen: set[int] = {piece.id}
    walk = by_id.get(piece.attached_to) if piece.attached_to else None
    while walk is not None and walk.kind in AUGMENTATIONS:
        if walk.id in seen:
            return None
        seen.add(walk.id)
        walk = by_id.get(walk.attached_to) if walk.attached_to else None
    return walk


def pieces_of(session: Session, owner: OwnerId = None) -> Any:
    """A way to ask what is slotted under a box, read once for a whole run.

    Handed to the `stamped_*` readers rather than each of them walking the
    canvas again: a fill pass asks about the same boxes once per item.
    """
    all_nodes = nodes(session, owner)
    return lambda node: pieces_under(all_nodes, node.id)
