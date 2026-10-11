"""How layout boxes and wires look: drawing only, never read by a run.

* A **Relay** takes its wire in on one side and gives it out on another —
  any two of its four, chosen on a drawing of it — and has a colour.
* A **group** has a colour — the theme's own, as a comment's are — and can
  be folded up to its name, hiding what it surrounds; a lock holds where it
  is, not whether it is folded.
* A **wire** is drawn as a curve, a straight line, square elbows, or a path
  found round the boxes in its way.

Kept as JSON on the box (`GraphNode.look`) and a word on the wire
(`GraphEdge.route`), read and written only here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ...models import GraphEdge, GraphNode
from .comments import COLOURS
from .errors import GraphError

#: A relay's four sides, any of which can take its wire in or give it out.
SIDES = ("left", "top", "right", "bottom")

#: How a relay that faced a way, before its sides were chosen one by one,
#: takes in and gives out.
FACES: dict[str, tuple[str, str]] = {
    "right": ("left", "right"), "left": ("right", "left"),
    "down": ("top", "bottom"), "up": ("bottom", "top"),
}

#: The colours a relay or a wire can be: the theme's own. "default" is the
#: colour of what a wire carries, and a relay's quiet grey.
LINE_COLOURS: tuple[tuple[str, str], ...] = (
    ("default", "Default"), ("accent", "Accent"), ("sage", "Sage"), ("ochre", "Ochre"),
    ("sky", "Sky"), ("pink", "Pink"), ("plum", "Plum"), ("slate", "Slate"),
)

#: How a wire is drawn.
ROUTES: tuple[tuple[str, str], ...] = (
    ("curve", "Curve"),
    ("straight", "Straight"),
    ("square", "Square"),
    ("astar", "Around boxes"),
)


def look(node: GraphNode) -> dict[str, Any]:
    """What a box's look is set to: the defaults for its kind, and its own."""
    try:
        stored: Any = json.loads(node.look or "{}")
    except ValueError:
        stored = {}
    stored = stored if isinstance(stored, dict) else {}
    if node.kind == "relay":
        sides = FACES.get(str(stored.get("faces") or "right"), ("left", "right"))
        taken = str(stored.get("in") or sides[0])
        given = str(stored.get("out") or sides[1])
        if taken not in SIDES or given not in SIDES or taken == given:
            taken, given = "left", "right"
        colour = str(stored.get("colour") or "default")
        return {"in": taken, "out": given, "colour": colour if colour in dict(LINE_COLOURS) else "default"}
    if node.kind == "group":
        colour = str(stored.get("colour") or "paper")
        return {
            "colour": colour if colour in dict(COLOURS) else "paper",
            "collapsed": bool(stored.get("collapsed")),
        }
    return {}


def save(node: GraphNode, form: Mapping[str, str]) -> None:
    """Set a box's look from `look_in`, `look_out`, `look_colour` and
    `look_collapsed`; one left out is left as it was. (`look_faces`, from
    before a relay's sides were chosen one by one, still sets both.)"""
    said = look(node)
    if not said:
        return
    if node.kind == "relay":
        faces = form.get("look_faces")
        if faces is not None:
            if faces not in FACES:
                raise GraphError("A relay faces left, right, up or down.")
            said["in"], said["out"] = FACES[faces]
        for end in ("in", "out"):
            side = form.get(f"look_{end}")
            if side is not None:
                if side not in SIDES:
                    raise GraphError("A relay's sides are left, top, right and bottom.")
                said[end] = side
        if said["in"] == said["out"]:
            raise GraphError("A relay takes in on one side and gives out on another.")
    colour = form.get("look_colour")
    if colour is not None and "colour" in said:
        allowed = LINE_COLOURS if node.kind == "relay" else COLOURS
        if colour not in dict(allowed):
            raise GraphError("That is not one of the theme's colours.")
        said["colour"] = colour
    collapsed = form.get("look_collapsed")
    if collapsed is not None and "collapsed" in said:
        said["collapsed"] = collapsed == "1"
    node.look = json.dumps(said, sort_keys=True)


def route_of(edge: GraphEdge) -> str:
    return edge.route if edge.route in dict(ROUTES) else "curve"


def set_route(edge: GraphEdge, route: str) -> None:
    """Draw a wire another way."""
    if route not in dict(ROUTES):
        raise GraphError("A wire is drawn as a curve, straight, square, or round the boxes.")
    edge.route = None if route == "curve" else route


def colour_of(edge: GraphEdge) -> str:
    return edge.colour if edge.colour in dict(LINE_COLOURS) else "default"


def set_colour(edge: GraphEdge, colour: str) -> None:
    """Colour a wire one of the theme's colours, or back to its own."""
    if colour not in dict(LINE_COLOURS):
        raise GraphError("That is not one of the theme's colours.")
    edge.colour = None if colour == "default" else colour
